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
    VOICE_STT_MODEL=                Vosk model override (dir name or abs path)
    VOICE_STT_GRAMMAR=              optional phrase-list file (constrained STT)
    MESH_IP, MESH_802_TTL are also read.

Run as root (hidraw access). Designed to run via openvlm-voice.service.
Safe on nodes WITHOUT an OpenVLM: the mesh + WS (phone) paths run regardless;
the OpenVLM front-end attaches/detaches with the USB device.

See: docs/VoIP/openvlm/mesh_voice.md
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

# LoRa voice-text transport — speech is transcribed locally (Vosk streaming
# STT) while PTT is held, sent as ONE text packet through cot-bridge (which
# owns the Meshtastic radio serial port), and spoken on the receiving node
# with Piper TTS. ~40 words (~15-20 s of speech) fit in a single packet.
# See docs/VoIP/lora_voice/lora_voice_text.md
LORA_TX_ADDR = ("127.0.0.1", 5558)   # daemon -> cot-bridge -> LoRa
LORA_RX_ADDR = ("127.0.0.1", 5559)   # cot-bridge -> daemon (we bind here)
LORA_MTU = 237                        # max app payload per Meshtastic packet
LORA_HDR = struct.Struct("<BB")       # flags(B) channel(B)
LORA_FLAG_TRUNCATED = 0x01            # transcript didn't fit in one packet
LORA_TEXT_MAX = LORA_MTU - LORA_HDR.size   # max UTF-8 text bytes per packet


def lora_airtime_ms(app_payload_len):
    """On-air time (ms) of one Meshtastic packet carrying app_payload_len
    bytes on SHORT_FAST (SF7 / BW 250 kHz / CR 4/5, 16-symbol preamble,
    explicit header + CRC). Deterministic LoRa PHY math for the fixed
    preset — the radio's actual airtime for this packet size."""
    sf = 7
    bw_khz = 250.0
    cr = 1                                   # coding rate 4/5
    # wire frame = app payload + 16 B Meshtastic header + protobuf framing
    pl = app_payload_len + 16 + 5
    t_sym = (1 << sf) / bw_khz               # symbol time in ms
    n_bits = 8 * pl - 4 * sf + 28 + 16       # explicit header, CRC on
    n_payload = 8 + max(-(-n_bits // (4 * sf)) * (cr + 4), 0)
    return int(round((16 + 4.25 + n_payload) * t_sym))

# Vosk STT models live in VOSK_MODEL_DIR. The first installed candidate is
# used; VOICE_STT_MODEL in mesh.conf overrides. The small model is the
# default: field-tested on Pi 4, it decodes faster than real-time (so the
# transcript really is ready at PTT release) at ~100 MB RAM. Larger models
# (e.g. vosk-model-en-us-0.22-lgraph) were tried and REJECTED on Pi 4:
# slower-than-real-time decode added 10+ s of latency after PTT release and
# ~500-700 MB RAM, for little practical accuracy gain. Use VOICE_STT_MODEL
# to opt into a bigger model on faster hardware only. For accuracy on Pi 4,
# use the opt-in grammar constraint (VOICE_STT_GRAMMAR) instead.
VOSK_MODEL_DIR = "/opt/nucleus/models/vosk"
VOSK_MODEL_CANDIDATES = [
    "vosk-model-small-en-us-0.15",      # default: real-time on Pi 4, low RAM
]

PIPER_MODEL_PATH = "/opt/nucleus/models/piper/en_US-lessac-low.onnx"

# The en_US-lessac-low Piper voice outputs 16 kHz S16 — exactly the mixer
# format (RATE below), so TTS audio feeds the mixer with no resampling.
#
# TTS runs via the resident PiperVoice Python API (piper-tts >= 1.4), loaded
# ONCE by tts_worker_thread. A per-message `piper` subprocess was measured at
# ~8.8 s on a Pi 4 (interpreter + onnxruntime + model load every time) vs
# ~2.3 s resident for the same text. Received text is synthesized in small
# word chunks whose PCM is pushed to the mixer as each chunk completes, so
# the first words play in well under a second; Piper -low synthesizes ~1.7x
# faster than real time on a Pi 4, so playback never outruns synthesis.
# See docs/VoIP/lora_voice/lora_voice_text.md
TTS_CHUNK_WORDS = 8                   # words per streaming synthesis chunk
TTS_SOURCE_MAX_FRAMES = 3000          # mixer Source cap for TTS clips (60 s)

TEXT_HISTORY_MAX = 50                 # sent+received messages kept for UI/CLI

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

# Supported hardware PTT devices. Matched by USB VID:PID (model, not unit),
# so any unit of the same model works. Each profile defines how to find the
# ALSA card and how to decode the PTT state from its hidraw reports.
#   card_match : lowercase substrings matched against /proc/asound/cards lines
#   ptt_byte   : index into the hidraw report holding the PTT bit
#   ptt_mask   : bitmask for "pressed" within that byte
#   supported  : False = known device but rejected (e.g. pulse-only "Zello"
#                variants whose button doesn't report held state). Listed
#                BEFORE any profile it would shadow so it is matched first.
PTT_DEVICES = [
    {
        # Zello variant: button sends a ~100ms pulse per click (app-side
        # latching), so hold-to-talk is impossible. Same USB ID as the hold
        # variant; distinguished by the "Audio" suffix in its name.
        "name": "NBT POC Audio (Zello variant)",
        "usb_id": "0020:0B21",
        "card_match": ("nbt poc audio",),
        "ptt_byte": 1,
        "ptt_mask": 0x01,
        "supported": False,
    },
    {
        "name": "OpenVLM (CM108)",
        "usb_id": "0D8C:0012",
        "card_match": ("openvlm",),
        "ptt_byte": 1,
        "ptt_mask": 0x04,
    },
    {
        "name": "NBT POC",
        "usb_id": "0020:0B21",
        "card_match": ("nbt poc",),
        "ptt_byte": 1,
        "ptt_mask": 0x01,
    },
]

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
# Hardware discovery (PTT sound card + hidraw, profile-driven)
# ---------------------------------------------------------------------------

def find_ptt_card(profile):
    """Locate the profile's ALSA card number from /proc/asound/cards."""
    try:
        with open("/proc/asound/cards") as f:
            text = f.read()
    except OSError:
        return None
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or not stripped[0].isdigit():
            continue
        low = line.lower()
        if any(m in low for m in profile["card_match"]):
            return int(stripped.split()[0])
    return None


def find_ptt_hidraw(profile):
    """Locate the profile's hidraw node by USB VID:PID."""
    vid, _, pid = profile["usb_id"].partition(":")
    hid_id = "{}:{}".format(vid.zfill(8), pid.zfill(8)).upper()
    for node in sorted(glob.glob("/sys/class/hidraw/hidraw*")):
        uevent = os.path.join(node, "device", "uevent")
        try:
            with open(uevent) as f:
                text = f.read().upper()
        except OSError:
            continue
        if profile["usb_id"].upper() in text or hid_id in text:
            return "/dev/" + os.path.basename(node)
    return None


def find_ptt_device():
    """Return (profile, card, hidraw_path) for the first attached PTT device,
    or (None, None, None) if none present."""
    for profile in PTT_DEVICES:
        card = find_ptt_card(profile)
        hidraw = find_ptt_hidraw(profile)
        if card is not None and hidraw is not None:
            return profile, card, hidraw
    return None, None, None


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
    """Jitter-buffered audio from one remote node.

    max_frames: queue cap. The default suits live streams (bounds latency);
    LoRa voice-text TTS clips are injected whole, so their Source is created
    with a cap large enough to hold the entire clip.
    """

    def __init__(self, node_id, jitter_frames, max_frames=MAX_QUEUE_FRAMES):
        self.node_id = node_id
        self.jitter_frames = jitter_frames
        self.max_frames = max_frames
        self.queue = []          # list of frame bytes (FIFO)
        self.playing = False     # False = accumulating jitter buffer
        self.last_seen = time.monotonic()

    def push(self, frame):
        self.last_seen = time.monotonic()
        self.queue.append(frame)
        if len(self.queue) > self.max_frames:
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
        # Replay the recent voice-text message history to the new client.
        self.conn.send_text(json.dumps(
            {"type": "texts", "items": self.daemon.text_snapshot()}))
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
            down = bool(msg.get("down"))
            if down and not self.ptt:
                self.daemon.lora_ptt_pressed()
            elif not down and self.ptt:
                self.daemon.lora_ptt_released()
            self.ptt = down
        elif mtype == "transport":
            mode = str(msg.get("mode", "")).lower()
            if self.daemon.set_transport(mode):
                self.daemon.broadcast_status()
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

        # LoRa voice-text transport (see docs/VoIP/lora_voice/lora_voice_text.md)
        self.lora_enabled = cfg.get("VOICE_LORA_ENABLED",
                                    "false").lower() in ("true", "1", "yes")
        self.lora_max_secs = self._parse_float(cfg.get("VOICE_LORA_MAX_SECS"),
                                               30.0)
        self.lora_max_pcm_frames = max(1, int(self.lora_max_secs * 1000
                                              / FRAME_MS))
        self.vosk_model = None             # loaded in stt_worker at startup
        self.lora_ready = False            # True once the Vosk model is loaded
        # Which Vosk model to load: VOICE_STT_MODEL override wins, else the
        # default candidate (small model — see VOSK_MODEL_CANDIDATES note).
        self.vosk_model_path = self._resolve_stt_model(
            cfg.get("VOICE_STT_MODEL"))
        # Optional grammar-constrained recognition (see _load_stt_grammar).
        self.stt_grammar = self._load_stt_grammar(cfg.get("VOICE_STT_GRAMMAR"))
        if self.lora_enabled:
            try:
                import vosk  # noqa: F401 — availability check only
            except ImportError:
                log("LORA: disabled — python 'vosk' package not installed "
                    "(pip3 install vosk)")
                self.lora_enabled = False
        if self.lora_enabled and self.vosk_model_path is None:
            log("LORA: disabled — no Vosk model found in {} "
                "(run install-packages.sh)".format(VOSK_MODEL_DIR))
            self.lora_enabled = False
        if self.lora_enabled:
            piper_ok = os.path.isfile(PIPER_MODEL_PATH)
            if piper_ok:
                try:
                    import piper  # noqa: F401 — availability check only
                except ImportError:
                    piper_ok = False
            if not piper_ok:
                log("LORA: warning — piper python package or its voice model "
                    "missing; received texts will display but not be spoken")
        self.transport = "ip"              # "ip" (live mcast) | "lora" (text)
        self.lora_active = False           # a clip is being captured
        self.lora_clip_frames = 0          # 20ms frames fed to STT this clip
        self.lora_clip_full = False        # hit clip limit: lockout to PTT-up
        self.lora_lock = threading.Lock()
        self.lora_tx_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.stt_q = queue.Queue(maxsize=2048)   # (cmd, data) to stt_worker
        self.tts_q = queue.Queue(maxsize=16)     # (node_key, text) to tts_worker
        self.text_history = []             # newest last, TEXT_HISTORY_MAX cap
        self.text_lock = threading.Lock()
        self.text_seq = 0

        self.ptt_hw = False                # OpenVLM hardware PTT held
        self.card = None
        self.wrong_ptt = None              # name of rejected PTT device, if any
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

    @staticmethod
    def _resolve_stt_model(override):
        """Pick the Vosk model directory to load.

        VOICE_STT_MODEL (a directory name under VOSK_MODEL_DIR, or an
        absolute path) wins if it exists; otherwise the first installed
        VOSK_MODEL_CANDIDATES entry. None = nothing found.
        """
        if override:
            path = override if os.path.isabs(override) \
                else os.path.join(VOSK_MODEL_DIR, override)
            if os.path.isdir(path):
                return path
            log("LORA: VOICE_STT_MODEL '{}' not found — auto-detecting "
                "instead".format(override))
        for name in VOSK_MODEL_CANDIDATES:
            path = os.path.join(VOSK_MODEL_DIR, name)
            if os.path.isdir(path):
                return path
        return None

    @staticmethod
    def _load_stt_grammar(path):
        """Load an optional grammar phrase list for constrained recognition.

        VOICE_STT_GRAMMAR points at a text file with one lowercase word or
        phrase per line (blank lines / '#' comments ignored). Constraining
        the recognizer to a fixed radio vocabulary (callsigns, prowords,
        digits...) makes it dramatically more accurate on those phrases;
        out-of-vocabulary speech maps to [unk] instead of a forced wrong
        match. Returns the JSON string Vosk expects, or None for the default
        free-form recognition.
        """
        if not path:
            return None
        try:
            with open(path) as f:
                phrases = []
                for line in f:
                    line = line.strip().lower()
                    if line and not line.startswith("#"):
                        phrases.append(line)
        except OSError as e:
            log("LORA: cannot read VOICE_STT_GRAMMAR {}: {} — using "
                "free-form recognition".format(path, e))
            return None
        if not phrases:
            log("LORA: VOICE_STT_GRAMMAR {} is empty — using free-form "
                "recognition".format(path))
            return None
        if "[unk]" not in phrases:
            phrases.append("[unk]")
        log("LORA: STT grammar loaded from {} ({} phrases + [unk])".format(
            path, len(phrases) - 1))
        return json.dumps(phrases)

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
            "wrong_ptt": self.wrong_ptt,
            "transport": self.transport,
            "lora": {
                "enabled": self.lora_enabled,
                "ready": self.lora_ready,
                "stt": "vosk",
                "stt_model": (os.path.basename(self.vosk_model_path)
                              if self.vosk_model_path else None),
                "stt_grammar": self.stt_grammar is not None,
                "max_secs": round(self.lora_max_secs, 1),
            },
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
        """Handle one 20 ms PCM frame while PTT is held.

        IP transport: send live on the current multicast channel.
        LoRa transport: stream the frame into the Vosk recognizer; the
        transcript is finalized and sent as one text packet on PTT release
        (or when the clip time limit is reached)."""
        if self.transport == "lora":
            # Feed the recognizer the RAW frame. The software TX gain exists
            # for playback loudness on the IP path and hard-clips at high
            # settings (e.g. the OpenVLM's 4x) — clipped audio wrecks STT
            # accuracy, and Vosk doesn't need the level boost.
            self._lora_buffer_frame(frame)
            return
        if gain and abs(gain - 1.0) >= 0.01:
            frame = apply_gain(frame, gain)
        if self.tx_sock is None:
            return
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

    # -- LoRa voice-text transport (Vosk STT -> cot-bridge -> Piper TTS) -----

    def set_transport(self, mode):
        """Switch TX transport. RX always listens on both paths."""
        if mode not in ("ip", "lora"):
            return False
        if mode == "lora" and not (self.lora_enabled and self.lora_ready):
            return False
        with self.lora_lock:
            if mode == self.transport:
                return True
            self.transport = mode
            self.lora_active = False
            self.lora_clip_frames = 0
            self.lora_clip_full = False
        log("transport -> {}".format(mode))
        return True

    def _stt_put(self, item):
        """Enqueue to the STT worker without ever blocking the audio path."""
        try:
            self.stt_q.put_nowait(item)
        except queue.Full:
            log("LORA: STT queue full — dropping audio")

    def lora_ptt_pressed(self):
        """PTT down edge: start a fresh streaming recognizer (LoRa mode)."""
        if self.transport != "lora":
            return
        with self.lora_lock:
            self.lora_active = True
            self.lora_clip_frames = 0
            self.lora_clip_full = False
        self._stt_put(("start", None))

    def lora_ptt_released(self):
        """PTT up edge: finalize the transcript and send it (LoRa mode)."""
        if self.transport != "lora":
            return
        finish = False
        with self.lora_lock:
            if self.lora_active and not self.lora_clip_full:
                finish = True
            self.lora_active = False
            self.lora_clip_full = False
        if finish:
            self._stt_put(("stop", None))

    def _lora_buffer_frame(self, frame):
        """Stream one 20 ms PCM frame into the recognizer. When the clip time
        limit is hit the transcript is finalized + sent immediately, and
        further audio is discarded until PTT is released."""
        hit_limit = False
        with self.lora_lock:
            if not self.lora_active or self.lora_clip_full:
                return
            self.lora_clip_frames += 1
            if self.lora_clip_frames >= self.lora_max_pcm_frames:
                self.lora_clip_full = True
                hit_limit = True
        self._stt_put(("frame", frame))
        if hit_limit:
            log("LORA: clip limit reached — finalizing transcript")
            self._stt_put(("stop", None))

    def stt_worker_thread(self):
        """Owns the Vosk model + per-clip streaming recognizer. Frames arrive
        live while PTT is held, so the transcript is ready ~instantly on
        release. Finalized text is packetized and handed to cot-bridge."""
        try:
            from vosk import Model, KaldiRecognizer, SetLogLevel
            SetLogLevel(-1)
            log("LORA: loading Vosk model ({})...".format(
                self.vosk_model_path))
            t0 = time.monotonic()
            self.vosk_model = Model(self.vosk_model_path)
            self.lora_ready = True
            log("LORA: voice-text ready — Vosk model '{}' loaded in {:.1f}s "
                "({}, max clip {:.0f}s)".format(
                    os.path.basename(self.vosk_model_path),
                    time.monotonic() - t0,
                    "grammar-constrained" if self.stt_grammar else "free-form",
                    self.lora_max_secs))
            self.broadcast_status()
        except Exception as e:
            log("LORA: disabled — Vosk model load failed: {}".format(e))
            self.lora_enabled = False
            self.broadcast_status()
            return
        rec = None
        while not self.stop.is_set():
            try:
                cmd, data = self.stt_q.get(timeout=0.5)
            except queue.Empty:
                continue
            if cmd == "start":
                if self.stt_grammar is not None:
                    rec = KaldiRecognizer(self.vosk_model, RATE,
                                          self.stt_grammar)
                else:
                    rec = KaldiRecognizer(self.vosk_model, RATE)
            elif cmd == "frame":
                if rec is not None:
                    try:
                        rec.AcceptWaveform(data)
                    except Exception as e:
                        log("LORA: STT error: {}".format(e))
                        rec = None
            elif cmd == "stop":
                if rec is None:
                    continue
                try:
                    text = json.loads(rec.FinalResult()).get("text", "").strip()
                except Exception as e:
                    log("LORA: STT finalize failed: {}".format(e))
                    text = ""
                rec = None
                if text:
                    self._lora_send_text(text)
                else:
                    log("LORA: no speech recognized — nothing sent")
                    self._push_text_event(
                        "tx", self.node_id, self.channel,
                        "(no speech recognized — not sent)", sent=False)

    def _lora_send_text(self, text):
        """Fit the transcript into ONE packet (truncate at a word boundary if
        needed — never fragment) and hand it to the cot-bridge relay
        (UDP 127.0.0.1:5558) for transmission as one Meshtastic packet."""
        flags = 0
        data = text.encode("utf-8")
        if len(data) > LORA_TEXT_MAX:
            flags |= LORA_FLAG_TRUNCATED
            cut = data[:LORA_TEXT_MAX]
            sp = cut.rfind(b" ")
            if sp > LORA_TEXT_MAX // 2:
                cut = cut[:sp]              # back up to the last whole word
            while cut and (cut[-1] & 0xC0) == 0x80:
                cut = cut[:-1]              # never split a UTF-8 sequence
            data = cut
            text = data.decode("utf-8", errors="ignore").strip()
        payload = LORA_HDR.pack(flags, self.channel) + data
        airtime_ms = lora_airtime_ms(len(payload))
        try:
            self.lora_tx_sock.sendto(payload, LORA_TX_ADDR)
        except OSError as e:
            log("LORA: send failed: {}".format(e))
            return
        log("LORA TX: {}B text packet{}, {} ms air: \"{}\"".format(
            len(payload), " (truncated)" if flags else "", airtime_ms, text))
        self._push_text_event("tx", self.node_id, self.channel, text,
                              truncated=bool(flags), airtime_ms=airtime_ms)

    # -- voice-text message history ------------------------------------------

    def text_snapshot(self):
        with self.text_lock:
            return list(self.text_history)

    def _push_text_event(self, direction, node, channel, text,
                         truncated=False, sent=True, airtime_ms=None):
        """Record a sent/received text and push it to connected web clients."""
        with self.text_lock:
            self.text_seq += 1
            item = {
                "seq": self.text_seq,
                "dir": direction,          # "tx" | "rx"
                "node": node,
                "channel": channel,
                "text": text,
                "truncated": truncated,
                "sent": sent,
                "ts": int(time.time()),
            }
            if airtime_ms is not None:
                item["airtime_ms"] = airtime_ms   # LoRa on-air time (TX)
            self.text_history.append(item)
            if len(self.text_history) > TEXT_HISTORY_MAX:
                del self.text_history[:len(self.text_history)
                                      - TEXT_HISTORY_MAX]
        msg = json.dumps({"type": "text", "item": item})
        with self.ws_lock:
            clients = list(self.ws_clients)
        for c in clients:
            c.conn.send_text(msg)

    def lora_rx_thread(self):
        """Receive LoRa voice-text packets from the cot-bridge relay (UDP
        5559): log/display the text and queue it for Piper TTS playback."""
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            sock.bind(LORA_RX_ADDR)
        except OSError as e:
            log("LORA: cannot bind {}:{}: {}".format(
                LORA_RX_ADDR[0], LORA_RX_ADDR[1], e))
            return
        log("LORA: RX relay socket on {}:{}".format(*LORA_RX_ADDR))
        while not self.stop.is_set():
            rlist, _, _ = select.select([sock], [], [], 0.5)
            if not rlist:
                continue
            try:
                data, _addr = sock.recvfrom(2048)
            except OSError:
                continue
            # cot-bridge prepends the sender's 4-byte meshtastic node num
            if len(data) < 4 + LORA_HDR.size + 1:
                continue
            sender = struct.unpack("<I", data[:4])[0]
            try:
                self._lora_handle_text(sender, data[4:])
            except Exception as e:
                log("LORA: RX handling failed: {}".format(e))

    def _lora_handle_text(self, sender, payload):
        """One received voice-text packet: record it, show it, speak it."""
        flags, channel = LORA_HDR.unpack(payload[:LORA_HDR.size])
        text = payload[LORA_HDR.size:].decode("utf-8", errors="replace").strip()
        if not text:
            return
        if channel != self.channel:
            return                          # different voice channel
        node_key = sender & 0xFFFF
        truncated = bool(flags & LORA_FLAG_TRUNCATED)
        log("LORA RX: text from node {}{}: \"{}\"".format(
            sender, " (truncated)" if truncated else "", text))
        self._push_text_event("rx", node_key, channel, text,
                              truncated=truncated)
        # Speak it via Piper TTS; the worker serializes overlapping messages.
        try:
            self.tts_q.put_nowait((node_key, text))
        except queue.Full:
            log("LORA: TTS queue full — message displayed but not spoken")

    def tts_worker_thread(self):
        """Speak received texts through the mixer so every sink (headset +
        phones) hears them, one message at a time.

        The Piper voice is loaded ONCE here and kept resident: a `piper`
        subprocess per message cost ~8.8 s on a Pi 4 (interpreter +
        onnxruntime + model load every time) vs ~2.3 s resident for the same
        text. Each text is synthesized in TTS_CHUNK_WORDS-word chunks and
        each chunk's PCM is pushed to the mixer as soon as it is ready, so
        the first words play in well under a second; Piper -low synthesizes
        faster than real time on a Pi 4, so playback never runs dry
        mid-message."""
        voice = None
        try:
            from piper import PiperVoice
            if os.path.isfile(PIPER_MODEL_PATH):
                voice = PiperVoice.load(PIPER_MODEL_PATH)
                for _ in voice.synthesize("ready"):    # warm-up inference
                    pass
        except Exception as e:
            log("LORA: piper TTS unavailable ({}); received texts will "
                "display but not be spoken".format(e))
            voice = None

        while not self.stop.is_set():
            try:
                node_key, text = self.tts_q.get(timeout=0.5)
            except queue.Empty:
                continue
            if voice is None:
                continue                    # display-only fallback
            # Vosk emits no punctuation, so Piper sees the whole transcript
            # as one long sentence and would synthesize it all before any
            # audio is available. Chunking by word count restores streaming.
            words = text.split()
            chunks = [" ".join(words[i:i + TTS_CHUNK_WORDS])
                      for i in range(0, len(words), TTS_CHUNK_WORDS)]
            src = Source(node_key, 1, max_frames=TTS_SOURCE_MAX_FRAMES)
            total_frames = 0
            started = None
            carry = b""                     # partial frame across chunks
            failed = False
            for chunk in chunks:
                try:
                    # Piper -low voices output 16 kHz S16 mono == the mixer
                    # format, so the chunk PCM feeds the mixer directly.
                    pcm = b"".join(
                        c.audio_int16_bytes
                        if hasattr(c, "audio_int16_bytes") else bytes(c)
                        for c in voice.synthesize(chunk))
                except Exception as e:
                    log("LORA: piper TTS failed: {}".format(e))
                    failed = True
                    break
                carry += pcm
                nframes = len(carry) // FRAME_BYTES
                if not nframes:
                    continue
                frames = [carry[i:i + FRAME_BYTES]
                          for i in range(0, nframes * FRAME_BYTES,
                                         FRAME_BYTES)]
                carry = carry[nframes * FRAME_BYTES:]
                with self.sources_lock:
                    # (Re)attach in case the mixer expired the source.
                    if self.sources.get(node_key) is not src:
                        self.sources[node_key] = src
                    for f in frames:
                        src.push(f)
                total_frames += nframes
                if started is None:
                    started = time.monotonic()
            if carry and not failed:
                # Pad the trailing partial frame with silence.
                with self.sources_lock:
                    if self.sources.get(node_key) is not src:
                        self.sources[node_key] = src
                    src.push(carry + SILENCE[len(carry):])
                total_frames += 1
                if started is None:
                    started = time.monotonic()
            if not total_frames:
                continue
            log("LORA: speaking {:.1f}s TTS clip from node {}".format(
                total_frames * FRAME_MS / 1000.0, node_key))
            self.broadcast_status()
            # Let the clip play out before starting the next message.
            end = started + total_frames * FRAME_SEC + 0.3
            while not self.stop.is_set():
                remain = end - time.monotonic()
                if remain <= 0:
                    break
                time.sleep(min(remain, 0.5))

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
            elif parts and parts[0].upper() == "TEXTS":
                reply = {"ok": True, "texts": self.text_snapshot()}
            elif len(parts) == 2 and parts[0].upper() == "TRANSPORT":
                if self.set_transport(parts[1].lower()):
                    self.broadcast_status()
                    reply = {"ok": True, "transport": self.transport}
                else:
                    reply = {"ok": False,
                             "error": "bad transport (ip|lora; lora requires "
                                      "VOICE_LORA_ENABLED=true and the Vosk "
                                      "model)"}
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

    def openvlm_ptt_thread(self, hidraw_path, profile, session_failed):
        """Track hardware PTT state from the device's hidraw reports."""
        ptt_byte = profile["ptt_byte"]
        ptt_mask = profile["ptt_mask"]
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
                if len(report) > ptt_byte:
                    pressed = (report[ptt_byte] & ptt_mask) != 0
                    if pressed != self.ptt_hw:
                        self.ptt_hw = pressed
                        if pressed:
                            self.lora_ptt_pressed()
                        else:
                            self.lora_ptt_released()
                        log("PTT {}".format("PRESSED" if pressed else "RELEASED"))
                        self.broadcast_status()
        finally:
            os.close(fd)
            if self.ptt_hw:
                self.ptt_hw = False
                self.lora_ptt_released()   # flush a clip cut off by unplug
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
        """Attach a hardware PTT front-end when present; detach on removal.
        The mesh/RX/mixer/WS keep running regardless of this thread."""
        announced = False
        while not self.stop.is_set():
            profile, card, hidraw = find_ptt_device()
            if profile is None:
                if self.wrong_ptt is not None:
                    self.wrong_ptt = None
                    self.broadcast_status()
                if not announced:
                    log("PTT hardware not present; phone/mesh path active, "
                        "waiting for hardware...")
                    announced = True
                time.sleep(5)
                continue

            if not profile.get("supported", True):
                if self.wrong_ptt != profile["name"]:
                    self.wrong_ptt = profile["name"]
                    log("WARNING: unsupported PTT device detected: {} "
                        "(pulse-only button, no hold-to-talk). Ignoring it; "
                        "plug in a supported PTT.".format(profile["name"]))
                    self.broadcast_status()
                announced = False
                time.sleep(5)
                continue

            if self.wrong_ptt is not None:
                self.wrong_ptt = None
                self.broadcast_status()
            announced = False
            self.card = card
            alsa_device = "plughw:{},0".format(card)
            log("{} attached: card {} ({}), ptt {}".format(
                profile["name"], card, alsa_device, hidraw))
            set_mixer(card)
            self._attach_openvlm_playback(alsa_device)
            self.broadcast_status()

            session_failed = threading.Event()
            threads = [
                threading.Thread(target=self.openvlm_ptt_thread,
                                 args=(hidraw, profile, session_failed),
                                 daemon=True),
                threading.Thread(target=self.openvlm_capture_thread,
                                 args=(alsa_device, session_failed), daemon=True),
            ]
            for t in threads:
                t.start()

            # Watch for device loss (either thread trips session_failed).
            while not session_failed.is_set() and not self.stop.is_set():
                if find_ptt_card(profile) is None:
                    log("{} card vanished".format(profile["name"]))
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
            log("{} detached; mesh/phone path still active".format(
                profile["name"]))
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
        targets = [self.rx_thread, self.mixer_thread, self.control_thread,
                   self.ws_server_thread, self.status_broadcaster_thread,
                   self.openvlm_supervisor_thread]
        if self.lora_enabled:
            targets += [self.lora_rx_thread, self.stt_worker_thread,
                        self.tts_worker_thread]
            log("LORA: voice-text transport starting (Vosk STT + Piper TTS, "
                "max clip {:.0f}s)".format(self.lora_max_secs))
        for target in targets:
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
