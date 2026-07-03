#!/usr/bin/env python3
"""
openvlm-voice.py - Mesh PTT voice daemon for Nucleus OS.

Real-time push-to-talk voice over the wlan1 802.11s mesh (UDP multicast).
Two independent PTT front-ends feed the *same* mesh transport, so a node with
a tactical headset on the OpenVLM USB card and a node with a phone on the web
page talk to each other transparently:

    1. HARDWARE PTT  - OpenVLM (CM108) mic/headset + HID GPIO PTT.
    2. SOFT PTT      - a phone/browser on the node's Wi-Fi AP, using the
                       node's /voice web page. The phone's own mic/speaker are
                       the handset; audio streams to/from this daemon over a
                       WebSocket (see WS server below).

ARCHITECTURE (the mesh side is INDEPENDENT of the OpenVLM):

    mesh wlan1  <--- TX sender ---+--- OpenVLM mic  (while hw PTT held)
    UDP mcast                     +--- phone mic    (while soft PTT held, WS)
    239.10.10.n
                --- RX + per-source jitter buffers --- mixer ---+--- OpenVLM
                                                                 |    playback
                                                                 +--- phone(s)
                                                                      via WS

The mixer is SELF-CLOCKED by a 20 ms monotonic timer (not by aplay), so it
runs whether or not an OpenVLM is attached, fanning each mixed 20 ms frame out
to every active playback sink (the OpenVLM `aplay` and/or connected phones).

Transport / packet format (unchanged, PCM S16_LE 16 kHz mono, 20 ms frames):
    magic(4s)="NVOX" version(B)=1 codec(B)=0 node_id(H) channel(B) flags(B) seq(I)
    + 640-byte payload.  50 pkt/s while transmitting.
Direct-message addressing is reserved for later (see FLAG_/channel notes).

Control socket (UDP 127.0.0.1:5556, text -> JSON):
    STATUS          -> node_id/channel/ptt/sources/card/hardware
    CHANNEL <n>     -> switch voice channel live (1-254)
    CHANNELS        -> named channel list + current channel

WebSocket server (127.0.0.1:5557, dependency-free RFC6455):
    nginx proxies wss://<host>/voice-ws -> here. The /voice page connects here.
    client->server text  : {"type":"ptt","down":bool} / {"type":"channel","n":N}
                           / {"type":"hello"} / {"type":"status"}
    client->server binary: raw S16_LE 16 kHz 20 ms frames (640 B) while soft PTT held
    server->client text  : {"type":"status", ...} (channels, sources, ptt, ...)
    server->client binary: mixed RX audio frames (640 B), continuous

Config (/etc/nucleus/mesh.conf):
    VOICE_CHANNEL=1                 startup channel
    VOICE_CHANNELS="1:Command,..."  named channel list (number:label, comma-sep)
    VOICE_JITTER_MS=80              per-source RX buffer before playback starts
    VOICE_TX_GAIN=4                 software mic gain for the OpenVLM path
    MESH_IP, MESH_802_TTL are also read.

Run as root (hidraw access). Designed to run via openvlm-voice.service.
Safe on nodes WITHOUT an OpenVLM: the mesh + WS (phone) paths run regardless;
the OpenVLM front-end attaches/detaches with the USB device.

See: docs/VoIP/mesh_voice.md
"""

import base64
import glob
import hashlib
import json
import os
import queue
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
WS_ADDR = ("127.0.0.1", 5557)
MCAST_BASE = "239.10.10."  # + channel number

MAGIC = b"NVOX"
VERSION = 1
CODEC_PCM16 = 0
# Header: magic(4s) version(B) codec(B) node_id(H) channel(B) flags(B) seq(I)
HDR_FORMAT = "<4sBBHBBI"
HDR_SIZE = struct.calcsize(HDR_FORMAT)  # 14
# flags byte reserved for future direct-messaging (e.g. FLAG_DIRECT + target id).

# Audio: 16 kHz mono S16_LE, 20 ms frames
RATE = 16000
FRAME_MS = 20
FRAME_SEC = FRAME_MS / 1000.0
FRAME_SAMPLES = RATE * FRAME_MS // 1000        # 320
FRAME_BYTES = FRAME_SAMPLES * 2                # 640
SILENCE = b"\x00" * FRAME_BYTES

# Jitter buffer bounds
MAX_QUEUE_FRAMES = 25          # cap per-source backlog (500 ms), drop oldest
SOURCE_TIMEOUT = 1.0           # drop a source after this much silence (s)

# Playback sink queue bounds (frames). Kept small to bound latency; drop oldest.
SINK_QUEUE_FRAMES = 12

# OpenVLM (CM108) PTT via HID GPIO
PTT_BYTE_INDEX = 1
PTT_PRESSED_MASK = 0x04
OPENVLM_USB_ID = "0D8C:0012"

# WebSocket
WS_GUID = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"
WS_OP_CONT = 0x0
WS_OP_TEXT = 0x1
WS_OP_BIN = 0x2
WS_OP_CLOSE = 0x8
WS_OP_PING = 0x9
WS_OP_PONG = 0xA

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


def parse_channels(spec, default_channel):
    """Parse VOICE_CHANNELS="1:Command,2:Squad" -> [(1,'Command'),(2,'Squad')].

    Falls back to a single entry for the default channel if spec is empty/bad.
    """
    result = []
    seen = set()
    if spec:
        for item in spec.split(","):
            item = item.strip()
            if not item:
                continue
            num_str, _, label = item.partition(":")
            try:
                num = int(num_str.strip())
            except ValueError:
                continue
            if not 1 <= num <= 254 or num in seen:
                continue
            label = label.strip() or "Channel {}".format(num)
            result.append((num, label))
            seen.add(num)
    if not result:
        result = [(default_channel, "Channel {}".format(default_channel))]
    return result


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
# Playback sink: OpenVLM aplay (fed via a queue so the mixer never blocks)
# ---------------------------------------------------------------------------

class AplaySink:
    """Wraps an `aplay` process; the mixer write()s frames into a bounded queue
    and a writer thread blocking-writes them to aplay's stdin."""

    def __init__(self, device):
        self.device = device
        self.q = queue.Queue(maxsize=SINK_QUEUE_FRAMES)
        self.failed = threading.Event()
        cmd = ["aplay", "-D", device, "-f", "S16_LE", "-c", "1",
               "-r", str(RATE), "-t", "raw", "-q"]
        self.proc = subprocess.Popen(cmd, stdin=subprocess.PIPE,
                                     stderr=subprocess.DEVNULL)
        self.thread = threading.Thread(target=self._writer, daemon=True)
        self.thread.start()
        log("MIX: OpenVLM playback sink on {}".format(device))

    def write(self, frame):
        try:
            self.q.put_nowait(frame)
        except queue.Full:
            # Drop oldest to bound latency, then enqueue newest.
            try:
                self.q.get_nowait()
                self.q.put_nowait(frame)
            except (queue.Empty, queue.Full):
                pass

    def _writer(self):
        while not self.failed.is_set():
            try:
                frame = self.q.get(timeout=0.5)
            except queue.Empty:
                continue
            try:
                self.proc.stdin.write(frame)
                self.proc.stdin.flush()
            except (BrokenPipeError, OSError):
                log("MIX: aplay exited (device removed?)")
                self.failed.set()
                break

    def close(self):
        self.failed.set()
        try:
            self.proc.terminate()
        except Exception:
            pass


# ---------------------------------------------------------------------------
# Minimal RFC6455 WebSocket connection (dependency-free)
# ---------------------------------------------------------------------------

def _recv_exact(sock, n):
    """Read exactly n bytes; return None on EOF/error."""
    buf = bytearray()
    while len(buf) < n:
        try:
            chunk = sock.recv(n - len(buf))
        except OSError:
            return None
        if not chunk:
            return None
        buf.extend(chunk)
    return bytes(buf)


class WSConnection:
    """One accepted WebSocket connection. Handles the handshake, decodes
    inbound frames, and encodes outbound frames. Thread-safe send()."""

    def __init__(self, sock):
        self.sock = sock
        self.send_lock = threading.Lock()
        self.closed = False
        self._frag_op = None
        self._frag_buf = bytearray()

    def handshake(self):
        """Read the HTTP upgrade request and reply 101. Returns True on success."""
        self.sock.settimeout(5)
        data = b""
        while b"\r\n\r\n" not in data:
            try:
                chunk = self.sock.recv(1024)
            except OSError:
                return False
            if not chunk:
                return False
            data += chunk
            if len(data) > 8192:
                return False
        headers = {}
        for line in data.split(b"\r\n")[1:]:
            if b":" in line:
                k, _, v = line.partition(b":")
                headers[k.strip().lower()] = v.strip()
        key = headers.get(b"sec-websocket-key")
        if not key:
            return False
        accept = base64.b64encode(
            hashlib.sha1(key + WS_GUID.encode()).digest()).decode()
        resp = (
            "HTTP/1.1 101 Switching Protocols\r\n"
            "Upgrade: websocket\r\n"
            "Connection: Upgrade\r\n"
            "Sec-WebSocket-Accept: {}\r\n\r\n".format(accept)
        )
        try:
            self.sock.sendall(resp.encode())
        except OSError:
            return False
        self.sock.settimeout(None)
        return True

    def recv(self):
        """Return (opcode, payload) for one *message* (reassembled), or None."""
        while True:
            hdr = _recv_exact(self.sock, 2)
            if hdr is None:
                return None
            b1, b2 = hdr[0], hdr[1]
            fin = b1 & 0x80
            opcode = b1 & 0x0F
            masked = b2 & 0x80
            length = b2 & 0x7F
            if length == 126:
                ext = _recv_exact(self.sock, 2)
                if ext is None:
                    return None
                length = struct.unpack(">H", ext)[0]
            elif length == 127:
                ext = _recv_exact(self.sock, 8)
                if ext is None:
                    return None
                length = struct.unpack(">Q", ext)[0]
            if length > 1 << 20:      # 1 MB sanity cap
                return None
            mask = b""
            if masked:
                mask = _recv_exact(self.sock, 4)
                if mask is None:
                    return None
            payload = _recv_exact(self.sock, length) if length else b""
            if length and payload is None:
                return None
            if masked and payload:
                payload = bytes(payload[i] ^ mask[i & 3]
                                for i in range(len(payload)))

            if opcode == WS_OP_CLOSE:
                return (WS_OP_CLOSE, b"")
            if opcode == WS_OP_PING:
                self.send(WS_OP_PONG, payload)
                continue
            if opcode == WS_OP_PONG:
                continue
            if opcode == WS_OP_CONT:
                self._frag_buf.extend(payload)
                if fin:
                    op = self._frag_op or WS_OP_BIN
                    out = bytes(self._frag_buf)
                    self._frag_op = None
                    self._frag_buf = bytearray()
                    return (op, out)
                continue
            # data frame (text/binary)
            if not fin:
                self._frag_op = opcode
                self._frag_buf = bytearray(payload)
                continue
            return (opcode, payload)

    def send(self, opcode, data):
        if self.closed:
            return False
        length = len(data)
        header = bytearray()
        header.append(0x80 | opcode)
        if length < 126:
            header.append(length)
        elif length < 65536:
            header.append(126)
            header += struct.pack(">H", length)
        else:
            header.append(127)
            header += struct.pack(">Q", length)
        with self.send_lock:
            if self.closed:
                return False
            try:
                self.sock.sendall(bytes(header) + data)
                return True
            except OSError:
                self.closed = True
                return False

    def send_text(self, text):
        return self.send(WS_OP_TEXT, text.encode())

    def send_binary(self, data):
        return self.send(WS_OP_BIN, data)

    def close(self):
        if self.closed:
            return
        self.closed = True
        try:
            self.sock.sendall(bytes([0x80 | WS_OP_CLOSE, 0]))
        except OSError:
            pass
        try:
            self.sock.close()
        except OSError:
            pass


class WSClient:
    """A connected phone/browser: soft-PTT flag + outbound audio queue."""

    def __init__(self, conn, daemon):
        self.conn = conn
        self.daemon = daemon
        self.ptt = False
        self.audioq = queue.Queue(maxsize=SINK_QUEUE_FRAMES)
        self.alive = True
        self.writer = threading.Thread(target=self._writer_loop, daemon=True)

    # -- playback sink interface (called by the mixer) --
    def write(self, frame):
        try:
            self.audioq.put_nowait(frame)
        except queue.Full:
            try:
                self.audioq.get_nowait()
                self.audioq.put_nowait(frame)
            except (queue.Empty, queue.Full):
                pass

    def _writer_loop(self):
        while self.alive:
            try:
                frame = self.audioq.get(timeout=0.5)
            except queue.Empty:
                continue
            if not self.conn.send_binary(frame):
                self.alive = False
                break

    def send_status(self, status):
        self.conn.send_text(json.dumps(status))

    def run(self):
        self.writer.start()
        self.daemon.add_ws_client(self)
        self.send_status(self.daemon.build_status())
        try:
            while self.alive:
                msg = self.conn.recv()
                if msg is None:
                    break
                opcode, payload = msg
                if opcode == WS_OP_CLOSE:
                    break
                elif opcode == WS_OP_BIN:
                    # Uplink mic audio: transmit only while soft PTT held.
                    if self.ptt and len(payload) == FRAME_BYTES:
                        self.daemon.transmit_frame(payload)
                elif opcode == WS_OP_TEXT:
                    self._handle_text(payload)
        finally:
            self.alive = False
            self.daemon.remove_ws_client(self)
            self.conn.close()

    def _handle_text(self, payload):
        try:
            msg = json.loads(payload.decode())
        except (ValueError, UnicodeDecodeError):
            return
        mtype = msg.get("type")
        if mtype == "ptt":
            self.ptt = bool(msg.get("down"))
        elif mtype == "channel":
            try:
                n = int(msg.get("n"))
            except (TypeError, ValueError):
                return
            self.daemon.set_channel(n)
            self.daemon.broadcast_status()
        elif mtype in ("hello", "status"):
            self.send_status(self.daemon.build_status())


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
        self.channels = parse_channels(cfg.get("VOICE_CHANNELS"), self.channel)
        # Ensure the startup channel is a member of the named list.
        if self.channel not in [n for n, _ in self.channels]:
            self.channel = self.channels[0][0]
        self.ttl = self._parse_int(cfg.get("MESH_802_TTL"), 8)
        jitter_ms = self._parse_int(cfg.get("VOICE_JITTER_MS"), 80)
        self.jitter_frames = max(1, jitter_ms // FRAME_MS)
        self.tx_gain = self._parse_float(cfg.get("VOICE_TX_GAIN"), 4.0)

        self.ptt_hw = False                # OpenVLM hardware PTT held
        self.card = None
        self.sources = {}                  # node_id -> Source
        self.sources_lock = threading.Lock()
        self.channel_lock = threading.Lock()
        self.tx_lock = threading.Lock()
        self.tx_seq = 0
        self.stop = threading.Event()

        self.rx_sock = None
        self.tx_sock = None

        self.aplay_sink = None             # AplaySink or None
        self.ws_clients = set()
        self.ws_lock = threading.Lock()

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

    # -- status -------------------------------------------------------------

    def any_ptt(self):
        if self.ptt_hw:
            return True
        with self.ws_lock:
            return any(c.ptt for c in self.ws_clients)

    def channel_label(self, n=None):
        n = self.channel if n is None else n
        for num, label in self.channels:
            if num == n:
                return label
        return "Channel {}".format(n)

    def build_status(self):
        with self.sources_lock:
            active = sorted(self.sources)
        return {
            "ok": True,
            "node_id": self.node_id,
            "channel": self.channel,
            "channel_label": self.channel_label(),
            "group": self.group_ip(),
            "channels": [{"n": n, "label": l} for n, l in self.channels],
            "ptt": self.any_ptt(),
            "sources": active,
            "card": self.card,
            "hardware": self.card is not None,
        }

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
        """Live channel switch: leave old multicast group, join new."""
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

    def transmit_frame(self, frame, gain=1.0):
        """Send one 20 ms PCM frame on the current channel as this node."""
        if self.tx_sock is None:
            return
        if gain and abs(gain - 1.0) >= 0.01:
            frame = apply_gain(frame, gain)
        with self.channel_lock:
            chan = self.channel
            dest = (self.group_ip(chan), VOICE_PORT)
        with self.tx_lock:
            seq = self.tx_seq
            self.tx_seq += 1
        hdr = struct.pack(HDR_FORMAT, MAGIC, VERSION, CODEC_PCM16,
                          self.node_id, chan, 0, seq)
        try:
            self.tx_sock.sendto(hdr + frame, dest)
        except OSError as e:
            log("TX: send failed: {}".format(e))

    # -- WS client registry -------------------------------------------------

    def add_ws_client(self, client):
        with self.ws_lock:
            self.ws_clients.add(client)
        log("WS: phone connected ({} total)".format(len(self.ws_clients)))

    def remove_ws_client(self, client):
        with self.ws_lock:
            self.ws_clients.discard(client)
        log("WS: phone disconnected ({} left)".format(len(self.ws_clients)))

    def broadcast_status(self):
        status = self.build_status()
        with self.ws_lock:
            clients = list(self.ws_clients)
        for c in clients:
            c.send_status(status)

    # -- always-on threads --------------------------------------------------

    def rx_thread(self):
        """Receive voice packets, demux into per-source jitter buffers."""
        log("RX: listening on *:{} group {}".format(VOICE_PORT, self.group_ip()))
        while not self.stop.is_set():
            if self.rx_sock is None:
                time.sleep(0.2)
                continue
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

    def mixer_thread(self):
        """Self-clocked mixer: every 20 ms, mix active sources and fan the
        result out to all playback sinks (OpenVLM aplay + connected phones).
        Paced by a monotonic deadline so it runs with or without hardware."""
        log("MIX: self-clocked mixer running (jitter {} frames = {} ms)".format(
            self.jitter_frames, self.jitter_frames * FRAME_MS))
        next_t = time.monotonic()
        while not self.stop.is_set():
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

            # Fan out to sinks. Only bother if something is actually active
            # (audio present, or a sink exists that wants continuous feed).
            sink = self.aplay_sink
            if sink is not None:
                if sink.failed.is_set():
                    self._detach_openvlm_playback()
                else:
                    sink.write(out)
            with self.ws_lock:
                ws_clients = list(self.ws_clients)
            for c in ws_clients:
                c.write(out)

            next_t += FRAME_SEC
            sleep = next_t - time.monotonic()
            if sleep > 0:
                time.sleep(sleep)
            else:
                # Fell behind (scheduling hiccup); resync to avoid burst.
                next_t = time.monotonic()

    def control_thread(self):
        """Local UDP control socket: STATUS / CHANNEL <n> / CHANNELS."""
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.bind(CONTROL_ADDR)
        sock.settimeout(0.5)
        log("CTL: control socket on {}:{}".format(*CONTROL_ADDR))
        while not self.stop.is_set():
            try:
                data, addr = sock.recvfrom(256)
            except socket.timeout:
                continue
            except OSError:
                continue
            parts = data.decode(errors="replace").strip().split()
            reply = {"ok": False, "error": "unknown command"}
            if parts and parts[0].upper() == "STATUS":
                reply = self.build_status()
            elif parts and parts[0].upper() == "CHANNELS":
                reply = {"ok": True, "current": self.channel,
                         "channels": [{"n": n, "label": l}
                                      for n, l in self.channels]}
            elif len(parts) == 2 and parts[0].upper() == "CHANNEL":
                try:
                    n = int(parts[1])
                except ValueError:
                    n = -1
                if self.set_channel(n):
                    self.broadcast_status()
                    reply = {"ok": True, "channel": self.channel}
                else:
                    reply = {"ok": False, "error": "bad channel (must be 1-254)"}
            try:
                sock.sendto(json.dumps(reply).encode(), addr)
            except OSError:
                pass

    def ws_server_thread(self):
        """Accept WebSocket connections from the /voice web page (via nginx)."""
        srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            srv.bind(WS_ADDR)
        except OSError as e:
            log("WS: cannot bind {}:{}: {}".format(WS_ADDR[0], WS_ADDR[1], e))
            return
        srv.listen(8)
        srv.settimeout(0.5)
        log("WS: server on {}:{}".format(*WS_ADDR))
        while not self.stop.is_set():
            try:
                client_sock, _addr = srv.accept()
            except socket.timeout:
                continue
            except OSError:
                continue
            threading.Thread(target=self._serve_ws, args=(client_sock,),
                             daemon=True).start()

    def _serve_ws(self, client_sock):
        conn = WSConnection(client_sock)
        try:
            if not conn.handshake():
                conn.close()
                return
        except Exception as e:
            log("WS: handshake error: {}".format(e))
            try:
                client_sock.close()
            except OSError:
                pass
            return
        WSClient(conn, self).run()

    def status_broadcaster_thread(self):
        """Push status to connected phones periodically (talkers/channel)."""
        while not self.stop.is_set():
            time.sleep(1.0)
            with self.ws_lock:
                have = bool(self.ws_clients)
            if have:
                self.broadcast_status()

    # -- OpenVLM optional front-end ----------------------------------------

    def _attach_openvlm_playback(self, alsa_device):
        if self.aplay_sink is None:
            try:
                self.aplay_sink = AplaySink(alsa_device)
            except FileNotFoundError:
                log("MIX: aplay not found (install alsa-utils)")

    def _detach_openvlm_playback(self):
        if self.aplay_sink is not None:
            self.aplay_sink.close()
            self.aplay_sink = None

    def openvlm_ptt_thread(self, hidraw_path, session_failed):
        """Track hardware PTT state from the CM108 HID GPIO."""
        try:
            fd = os.open(hidraw_path, os.O_RDONLY | os.O_NONBLOCK)
        except OSError as e:
            log("PTT: cannot open {}: {}".format(hidraw_path, e))
            session_failed.set()
            return
        log("PTT: watching {}".format(hidraw_path))
        try:
            while not session_failed.is_set() and not self.stop.is_set():
                rlist, _, _ = select.select([fd], [], [], 0.25)
                if not rlist:
                    continue
                try:
                    report = os.read(fd, 64)
                except (BlockingIOError, OSError):
                    continue
                if not report:  # EOF: device unplugged
                    log("PTT: hidraw EOF (device removed?)")
                    session_failed.set()
                    break
                if len(report) > PTT_BYTE_INDEX:
                    pressed = (report[PTT_BYTE_INDEX] & PTT_PRESSED_MASK) != 0
                    if pressed != self.ptt_hw:
                        self.ptt_hw = pressed
                        log("PTT {}".format("PRESSED" if pressed else "RELEASED"))
                        self.broadcast_status()
        finally:
            os.close(fd)
            self.ptt_hw = False

    def openvlm_capture_thread(self, alsa_device, session_failed):
        """Capture OpenVLM mic; transmit 20 ms frames while hardware PTT held."""
        cmd = ["arecord", "-D", alsa_device, "-f", "S16_LE", "-c", "1",
               "-r", str(RATE), "-t", "raw", "-q"]
        try:
            arec = subprocess.Popen(cmd, stdout=subprocess.PIPE,
                                    stderr=subprocess.DEVNULL)
        except FileNotFoundError:
            log("TX: arecord not found (install alsa-utils)")
            session_failed.set()
            return
        log("TX: capturing from {} ({} Hz mono)".format(alsa_device, RATE))
        buf = b""
        try:
            while not session_failed.is_set() and not self.stop.is_set():
                chunk = arec.stdout.read(FRAME_BYTES - len(buf))
                if not chunk:
                    log("TX: arecord exited (device removed?)")
                    session_failed.set()
                    break
                buf += chunk
                if len(buf) < FRAME_BYTES:
                    continue
                frame, buf = buf[:FRAME_BYTES], buf[FRAME_BYTES:]
                if self.ptt_hw:
                    self.transmit_frame(frame, gain=self.tx_gain)
        finally:
            try:
                arec.terminate()
            except Exception:
                pass

    def openvlm_supervisor_thread(self):
        """Attach the OpenVLM front-end when present; detach on removal.
        The mesh/RX/mixer/WS keep running regardless of this thread."""
        announced = False
        while not self.stop.is_set():
            card = find_openvlm_card()
            hidraw = find_openvlm_hidraw()
            if card is None or hidraw is None:
                if not announced:
                    log("OpenVLM not present (card={}, hidraw={}); phone/mesh "
                        "path active, waiting for hardware...".format(card, hidraw))
                    announced = True
                time.sleep(5)
                continue

            announced = False
            self.card = card
            alsa_device = "plughw:{},0".format(card)
            log("OpenVLM attached: card {} ({}), ptt {}".format(
                card, alsa_device, hidraw))
            set_mixer(card)
            self._attach_openvlm_playback(alsa_device)
            self.broadcast_status()

            session_failed = threading.Event()
            threads = [
                threading.Thread(target=self.openvlm_ptt_thread,
                                 args=(hidraw, session_failed), daemon=True),
                threading.Thread(target=self.openvlm_capture_thread,
                                 args=(alsa_device, session_failed), daemon=True),
            ]
            for t in threads:
                t.start()

            # Watch for device loss (either thread trips session_failed).
            while not session_failed.is_set() and not self.stop.is_set():
                if find_openvlm_card() is None:
                    log("OpenVLM card vanished")
                    session_failed.set()
                    break
                time.sleep(2)

            session_failed.set()
            for t in threads:
                t.join(timeout=2)
            self._detach_openvlm_playback()
            self.card = None
            self.ptt_hw = False
            self.broadcast_status()
            log("OpenVLM detached; mesh/phone path still active")
            time.sleep(3)

    # -- lifecycle ----------------------------------------------------------

    def run(self):
        log("openvlm-voice starting: node_id={} channel={} ({}) group={} "
            "ttl={} jitter={}ms gain=x{} channels={}".format(
                self.node_id, self.channel, self.channel_label(),
                self.group_ip(), self.ttl, self.jitter_frames * FRAME_MS,
                self.tx_gain,
                ",".join("{}:{}".format(n, l) for n, l in self.channels)))

        # Open mesh sockets (retry until wlan1/mesh is up).
        while not self.stop.is_set():
            try:
                self.open_sockets()
                break
            except OSError as e:
                log("net: socket open failed ({}); retry in 3s".format(e))
                time.sleep(3)

        # Always-on threads: mesh RX, self-clocked mixer, control socket,
        # WebSocket server (phones), status broadcaster.
        for target in (self.rx_thread, self.mixer_thread, self.control_thread,
                       self.ws_server_thread, self.status_broadcaster_thread,
                       self.openvlm_supervisor_thread):
            threading.Thread(target=target, daemon=True).start()

        try:
            while not self.stop.is_set():
                time.sleep(1)
        except KeyboardInterrupt:
            self.stop.set()


def main():
    if os.geteuid() != 0:
        sys.exit("ERROR: must run as root (hidraw access). Try sudo.")
    VoiceDaemon().run()


if __name__ == "__main__":
    main()
