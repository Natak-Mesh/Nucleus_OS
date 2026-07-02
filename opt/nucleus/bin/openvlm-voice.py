#!/usr/bin/env python3
"""
openvlm-voice.py - Mesh PTT voice daemon for Nucleus OS.

Transmits mic audio over the wlan1 802.11s mesh (UDP multicast) while the
OpenVLM PTT is held, and plays back received audio on the OpenVLM headset.
Audio is ADDITIVE: every source is jitter-buffered independently and mixed,
so simultaneous talkers are all heard.

Transport:
    - one multicast group per channel: 239.10.10.<channel>, UDP port 5555
    - multicast sent directly on wlan1 (IP_MULTICAST_IF = MESH_IP)
    - 802.11s handles multi-hop forwarding + dedup natively (no smcroute)
    - TTL = MESH_802_TTL from mesh.conf (default 8)

Codec (Phase 1): PCM S16_LE 16 kHz mono, 20 ms frames (640 B payload,
50 pkt/s, ~262 kbps while transmitting). Opus planned (codec byte in header).

Control socket (hook for web UI / channel switching):
    UDP 127.0.0.1:5556, text commands:
        STATUS        -> JSON status
        CHANNEL <n>   -> switch voice channel live
    e.g.  echo -n "CHANNEL 2" | nc -u -w1 127.0.0.1 5556

Config (/etc/nucleus/mesh.conf):
    VOICE_CHANNEL=1       startup channel
    VOICE_JITTER_MS=80    per-source RX buffer before playback starts
    VOICE_TX_GAIN=4       software mic gain (ComTac mics are low level)
    MESH_IP, MESH_802_TTL are also read.

Run as root (hidraw access). Designed to run via openvlm-voice.service.
Safe on nodes without an OpenVLM attached: waits for hardware in a loop.

See: docs/VoIP/openvlm_voice_plan.md
"""

import glob
import json
import os
import select
import socket
import struct
import subprocess
import sys
import threading
import time

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

MESH_CONF = "/etc/nucleus/mesh.conf"

VOICE_PORT = 5555
CONTROL_ADDR = ("127.0.0.1", 5556)
MCAST_BASE = "239.10.10."  # + channel number

MAGIC = b"NVOX"
VERSION = 1
CODEC_PCM16 = 0
# Header: magic(4s) version(B) codec(B) node_id(H) channel(B) flags(B) seq(I)
HDR_FORMAT = "<4sBBHBBI"
HDR_SIZE = struct.calcsize(HDR_FORMAT)  # 14

# Audio: 16 kHz mono S16_LE, 20 ms frames
RATE = 16000
FRAME_MS = 20
FRAME_SAMPLES = RATE * FRAME_MS // 1000        # 320
FRAME_BYTES = FRAME_SAMPLES * 2                # 640
SILENCE = b"\x00" * FRAME_BYTES

# Jitter buffer bounds
MAX_QUEUE_FRAMES = 25          # cap per-source backlog (500 ms), drop oldest
SOURCE_TIMEOUT = 1.0           # drop a source after this much silence (s)

# OpenVLM (CM108) PTT via HID GPIO
PTT_BYTE_INDEX = 1
PTT_PRESSED_MASK = 0x04
OPENVLM_USB_ID = "0D8C:0012"

LOG_LOCK = threading.Lock()


def log(msg):
    with LOG_LOCK:
        sys.stdout.write("[{}] {}\n".format(time.strftime("%H:%M:%S"), msg))
        sys.stdout.flush()


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

def load_config():
    """Parse KEY=value pairs from mesh.conf (shell-style, quotes stripped)."""
    cfg = {}
    try:
        with open(MESH_CONF) as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, _, val = line.partition("=")
                cfg[key.strip()] = val.strip().strip('"').strip("'")
    except OSError as e:
        log("WARNING: cannot read {}: {}".format(MESH_CONF, e))
    return cfg


# ---------------------------------------------------------------------------
# Hardware discovery (OpenVLM sound card + PTT hidraw)
# ---------------------------------------------------------------------------

def find_openvlm_card():
    """Locate the OpenVLM ALSA card number from /proc/asound/cards."""
    try:
        with open("/proc/asound/cards") as f:
            text = f.read()
    except OSError:
        return None
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or not stripped[0].isdigit():
            continue
        if "openvlm" in line.lower():
            return int(stripped.split()[0])
    return None


def find_openvlm_hidraw():
    """Locate the OpenVLM hidraw node by USB VID:PID, fallback /dev/hidraw0."""
    for node in sorted(glob.glob("/sys/class/hidraw/hidraw*")):
        uevent = os.path.join(node, "device", "uevent")
        try:
            with open(uevent) as f:
                text = f.read().upper()
        except OSError:
            continue
        if OPENVLM_USB_ID in text:
            return "/dev/" + os.path.basename(node)
    if os.path.exists("/dev/hidraw0"):
        return "/dev/hidraw0"
    return None


def set_mixer(card):
    """Max mic gain + AGC on, max playback volume. Best-effort."""
    for args in (["sset", "Mic", "100%", "cap"],
                 ["sset", "Auto Gain Control", "on"],
                 ["sset", "PCM", "100%"]):
        try:
            subprocess.run(["amixer", "-c", str(card)] + args,
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except FileNotFoundError:
            return


# ---------------------------------------------------------------------------
# DSP helpers (pure stdlib; audioop was removed in Python 3.13)
# ---------------------------------------------------------------------------

_FRAME_UNPACK = struct.Struct("<{}h".format(FRAME_SAMPLES))


def apply_gain(frame, gain):
    """Multiply S16 frame by gain with clipping. No-op for gain ~1."""
    if abs(gain - 1.0) < 0.01:
        return frame
    samples = _FRAME_UNPACK.unpack(frame)
    out = []
    for s in samples:
        v = int(s * gain)
        if v > 32767:
            v = 32767
        elif v < -32768:
            v = -32768
        out.append(v)
    return _FRAME_UNPACK.pack(*out)


def mix_frames(frames):
    """Additively mix S16 frames (sum + clamp). 1 frame passes through."""
    if len(frames) == 1:
        return frames[0]
    acc = [0] * FRAME_SAMPLES
    for f in frames:
        samples = _FRAME_UNPACK.unpack(f)
        for i in range(FRAME_SAMPLES):
            acc[i] += samples[i]
    out = []
    for v in acc:
        if v > 32767:
            v = 32767
        elif v < -32768:
            v = -32768
        out.append(v)
    return _FRAME_UNPACK.pack(*out)


# ---------------------------------------------------------------------------
# Per-source jitter buffer
# ---------------------------------------------------------------------------

class Source:
    """Jitter-buffered audio from one remote node."""

    def __init__(self, node_id, jitter_frames):
        self.node_id = node_id
        self.jitter_frames = jitter_frames
        self.queue = []          # list of frame bytes (FIFO)
        self.playing = False     # False = accumulating jitter buffer
        self.last_seen = time.monotonic()

    def push(self, frame):
        self.last_seen = time.monotonic()
        self.queue.append(frame)
        if len(self.queue) > MAX_QUEUE_FRAMES:
            # Bound latency: drop oldest backlog
            del self.queue[: len(self.queue) - self.jitter_frames]
        if not self.playing and len(self.queue) >= self.jitter_frames:
            self.playing = True

    def pop(self):
        """Return next frame to mix, or None if buffering/dry."""
        if not self.playing:
            return None
        if not self.queue:
            self.playing = False  # ran dry -> re-buffer
            return None
        return self.queue.pop(0)

    def expired(self, now):
        return (now - self.last_seen) > SOURCE_TIMEOUT and not self.queue


# ---------------------------------------------------------------------------
# Voice daemon
# ---------------------------------------------------------------------------

class VoiceDaemon:
    def __init__(self):
        cfg = load_config()
        self.mesh_ip = cfg.get("MESH_IP", "0.0.0.0")
        try:
            self.node_id = int(self.mesh_ip.split(".")[-1])
        except ValueError:
            self.node_id = 0
        self.channel = self._parse_int(cfg.get("VOICE_CHANNEL"), 1)
        self.ttl = self._parse_int(cfg.get("MESH_802_TTL"), 8)
        jitter_ms = self._parse_int(cfg.get("VOICE_JITTER_MS"), 80)
        self.jitter_frames = max(1, jitter_ms // FRAME_MS)
        self.tx_gain = self._parse_float(cfg.get("VOICE_TX_GAIN"), 4.0)

        self.ptt_pressed = False
        self.card = None
        self.sources = {}                 # node_id -> Source
        self.sources_lock = threading.Lock()
        self.channel_lock = threading.Lock()
        self.session_failed = threading.Event()  # trip -> restart hardware session
        self.tx_seq = 0

        self.rx_sock = None
        self.tx_sock = None

    @staticmethod
    def _parse_int(val, default):
        try:
            return int(val)
        except (TypeError, ValueError):
            return default

    @staticmethod
    def _parse_float(val, default):
        try:
            return float(val)
        except (TypeError, ValueError):
            return default

    # -- networking ---------------------------------------------------------

    def group_ip(self, channel=None):
        return MCAST_BASE + str(channel if channel is not None else self.channel)

    def open_sockets(self):
        # RX: bind the voice port, join current channel's group on the mesh IP.
        rx = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        rx.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        rx.bind(("", VOICE_PORT))
        self._join(rx, self.channel)
        self.rx_sock = rx

        # TX: egress via the mesh interface, TTL per mesh.conf, no loopback.
        tx = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        tx.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, self.ttl)
        tx.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_LOOP, 0)
        try:
            tx.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_IF,
                          socket.inet_aton(self.mesh_ip))
        except OSError as e:
            log("WARNING: IP_MULTICAST_IF({}) failed: {} "
                "(is wlan1/mesh up?)".format(self.mesh_ip, e))
        self.tx_sock = tx

    def _mreq(self, channel):
        return socket.inet_aton(self.group_ip(channel)) + socket.inet_aton(self.mesh_ip)

    def _join(self, sock, channel):
        try:
            sock.setsockopt(socket.IPPROTO_IP, socket.IP_ADD_MEMBERSHIP,
                            self._mreq(channel))
            log("joined {} on {}".format(self.group_ip(channel), self.mesh_ip))
        except OSError as e:
            log("WARNING: join {} failed: {}".format(self.group_ip(channel), e))

    def set_channel(self, new_channel):
        """Live channel switch: leave old multicast group, join new.
        Also works while waiting for hardware (sockets not open yet)."""
        if not 1 <= new_channel <= 254:
            return False
        with self.channel_lock:
            if new_channel == self.channel:
                return True
            old = self.channel
            if self.rx_sock is not None:
                try:
                    self.rx_sock.setsockopt(socket.IPPROTO_IP,
                                            socket.IP_DROP_MEMBERSHIP,
                                            self._mreq(old))
                except OSError:
                    pass
            self.channel = new_channel
            if self.rx_sock is not None:
                self._join(self.rx_sock, new_channel)
            with self.sources_lock:
                self.sources.clear()   # flush audio from the old channel
            log("channel {} -> {}".format(old, new_channel))
        return True

    # -- threads ------------------------------------------------------------

    def ptt_thread(self, hidraw_path):
        """Track PTT state from the CM108 HID GPIO."""
        try:
            fd = os.open(hidraw_path, os.O_RDONLY | os.O_NONBLOCK)
        except OSError as e:
            log("PTT: cannot open {}: {}".format(hidraw_path, e))
            self.session_failed.set()
            return
        log("PTT: watching {}".format(hidraw_path))
        try:
            while not self.session_failed.is_set():
                rlist, _, _ = select.select([fd], [], [], 0.25)
                if not rlist:
                    continue
                try:
                    report = os.read(fd, 64)
                except (BlockingIOError, OSError):
                    continue
                if not report:  # EOF: device unplugged
                    log("PTT: hidraw EOF (device removed?)")
                    self.session_failed.set()
                    break
                if len(report) > PTT_BYTE_INDEX:
                    pressed = (report[PTT_BYTE_INDEX] & PTT_PRESSED_MASK) != 0
                    if pressed != self.ptt_pressed:
                        self.ptt_pressed = pressed
                        log("PTT {}".format("PRESSED" if pressed else "RELEASED"))
        finally:
            os.close(fd)

    def tx_thread(self, alsa_device):
        """Continuously capture mic; send 20 ms frames while PTT is held.
        arecord's real-time delivery paces this loop."""
        cmd = ["arecord", "-D", alsa_device, "-f", "S16_LE", "-c", "1",
               "-r", str(RATE), "-t", "raw", "-q"]
        try:
            arec = subprocess.Popen(cmd, stdout=subprocess.PIPE,
                                    stderr=subprocess.DEVNULL)
        except FileNotFoundError:
            log("TX: arecord not found (install alsa-utils)")
            self.session_failed.set()
            return
        log("TX: capturing from {} ({} Hz mono)".format(alsa_device, RATE))
        buf = b""
        transmitting = False
        try:
            while not self.session_failed.is_set():
                chunk = arec.stdout.read(FRAME_BYTES - len(buf))
                if not chunk:
                    log("TX: arecord exited (device removed?)")
                    self.session_failed.set()
                    break
                buf += chunk
                if len(buf) < FRAME_BYTES:
                    continue
                frame, buf = buf[:FRAME_BYTES], buf[FRAME_BYTES:]

                if self.ptt_pressed:
                    if not transmitting:
                        transmitting = True
                        self.tx_seq = 0
                    frame = apply_gain(frame, self.tx_gain)
                    with self.channel_lock:
                        chan = self.channel
                        dest = (self.group_ip(chan), VOICE_PORT)
                    hdr = struct.pack(HDR_FORMAT, MAGIC, VERSION, CODEC_PCM16,
                                      self.node_id, chan, 0, self.tx_seq)
                    self.tx_seq += 1
                    try:
                        self.tx_sock.sendto(hdr + frame, dest)
                    except OSError as e:
                        log("TX: send failed: {}".format(e))
                else:
                    transmitting = False
        finally:
            try:
                arec.terminate()
            except Exception:
                pass

    def rx_thread(self):
        """Receive voice packets, demux into per-source jitter buffers."""
        log("RX: listening on *:{} group {}".format(VOICE_PORT, self.group_ip()))
        while not self.session_failed.is_set():
            rlist, _, _ = select.select([self.rx_sock], [], [], 0.25)
            if not rlist:
                continue
            try:
                data, _addr = self.rx_sock.recvfrom(2048)
            except OSError:
                continue
            if len(data) < HDR_SIZE + 2:
                continue
            magic, version, codec, node_id, channel, _flags, _seq = \
                struct.unpack(HDR_FORMAT, data[:HDR_SIZE])
            if magic != MAGIC or version != VERSION or codec != CODEC_PCM16:
                continue
            if node_id == self.node_id:       # our own packet
                continue
            if channel != self.channel:       # stale group / race
                continue
            payload = data[HDR_SIZE:]
            if len(payload) != FRAME_BYTES:
                continue
            with self.sources_lock:
                src = self.sources.get(node_id)
                if src is None:
                    src = Source(node_id, self.jitter_frames)
                    self.sources[node_id] = src
                    log("RX: new source node {}".format(node_id))
                src.push(payload)

    def mixer_loop(self, alsa_device):
        """Mix all active sources and write to aplay.
        aplay's blocking stdin paces this loop in real time."""
        cmd = ["aplay", "-D", alsa_device, "-f", "S16_LE", "-c", "1",
               "-r", str(RATE), "-t", "raw", "-q"]
        try:
            apl = subprocess.Popen(cmd, stdin=subprocess.PIPE,
                                   stderr=subprocess.DEVNULL)
        except FileNotFoundError:
            log("MIX: aplay not found (install alsa-utils)")
            self.session_failed.set()
            return
        log("MIX: playback on {} (jitter {} frames = {} ms)".format(
            alsa_device, self.jitter_frames, self.jitter_frames * FRAME_MS))
        try:
            while not self.session_failed.is_set():
                now = time.monotonic()
                frames = []
                with self.sources_lock:
                    for nid in list(self.sources):
                        src = self.sources[nid]
                        if src.expired(now):
                            log("RX: source node {} timed out".format(nid))
                            del self.sources[nid]
                            continue
                        f = src.pop()
                        if f is not None:
                            frames.append(f)
                out = mix_frames(frames) if frames else SILENCE
                try:
                    apl.stdin.write(out)
                    apl.stdin.flush()
                except (BrokenPipeError, OSError):
                    log("MIX: aplay exited (device removed?)")
                    self.session_failed.set()
                    break
        finally:
            try:
                apl.terminate()
            except Exception:
                pass

    def control_thread(self):
        """Local UDP control socket: STATUS / CHANNEL <n>. Web UI hook."""
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.bind(CONTROL_ADDR)
        sock.settimeout(0.5)
        log("CTL: control socket on {}:{}".format(*CONTROL_ADDR))
        while True:   # persists across hardware sessions
            try:
                data, addr = sock.recvfrom(256)
            except socket.timeout:
                continue
            except OSError:
                continue
            parts = data.decode(errors="replace").strip().split()
            reply = {"ok": False, "error": "unknown command"}
            if parts and parts[0].upper() == "STATUS":
                with self.sources_lock:
                    active = sorted(self.sources)
                reply = {"ok": True, "node_id": self.node_id,
                         "channel": self.channel, "group": self.group_ip(),
                         "ptt": self.ptt_pressed, "sources": active,
                         "card": self.card,
                         "hardware": self.card is not None}
            elif len(parts) == 2 and parts[0].upper() == "CHANNEL":
                try:
                    n = int(parts[1])
                except ValueError:
                    n = -1
                if self.set_channel(n):
                    reply = {"ok": True, "channel": self.channel}
                else:
                    reply = {"ok": False, "error": "bad channel (must be 1-254)"}
            try:
                sock.sendto(json.dumps(reply).encode(), addr)
            except OSError:
                pass

    # -- lifecycle ----------------------------------------------------------

    def wait_for_hardware(self):
        """Block until the OpenVLM card and hidraw node are both present."""
        announced = False
        while True:
            card = find_openvlm_card()
            hidraw = find_openvlm_hidraw()
            if card is not None and hidraw is not None:
                return card, hidraw
            if not announced:
                log("waiting for OpenVLM hardware (card={}, hidraw={})...".format(
                    card, hidraw))
                announced = True
            time.sleep(5)

    def run(self):
        log("openvlm-voice starting: node_id={} channel={} group={} ttl={} "
            "jitter={}ms gain=x{}".format(
                self.node_id, self.channel, self.group_ip(), self.ttl,
                self.jitter_frames * FRAME_MS, self.tx_gain))

        threading.Thread(target=self.control_thread, daemon=True).start()

        while True:
            card, hidraw = self.wait_for_hardware()
            self.card = card
            alsa_device = "plughw:{},0".format(card)
            log("hardware found: card {} ({}), ptt {}".format(
                card, alsa_device, hidraw))
            set_mixer(card)

            self.session_failed.clear()
            self.open_sockets()

            threads = [
                threading.Thread(target=self.ptt_thread, args=(hidraw,), daemon=True),
                threading.Thread(target=self.tx_thread, args=(alsa_device,), daemon=True),
                threading.Thread(target=self.rx_thread, daemon=True),
                threading.Thread(target=self.mixer_loop, args=(alsa_device,), daemon=True),
            ]
            for t in threads:
                t.start()

            # Wait for any component to trip the failure flag, then rebuild.
            self.session_failed.wait()
            log("session failed - restarting in 3s")
            for sock in (self.rx_sock, self.tx_sock):
                try:
                    sock.close()
                except Exception:
                    pass
            self.rx_sock = self.tx_sock = None
            self.card = None
            for t in threads:
                t.join(timeout=2)
            time.sleep(3)


def main():
    if os.geteuid() != 0:
        sys.exit("ERROR: must run as root (hidraw access). Try sudo.")
    VoiceDaemon().run()


if __name__ == "__main__":
    main()
