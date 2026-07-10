#!/usr/bin/env python3
"""
ATAK CoT Bridge — Stage 7

Bidirectional bridge between ATAK multicast CoT and Meshtastic LoRa.

TX: ATAK multicast (SA + Chat) → compress TAKPacketV2 → LoRa (portnum 257)
RX: LoRa (portnum 257) → decompress TAKPacketV2 → ATAK multicast

Also relays two voice transports for openvlm-voice.py over localhost UDP
(the bridge owns the Meshtastic serial port exclusively):
  - voice-text (portnum 260): one text packet per utterance (STT/TTS)
  - voice stream (portnum 256): live Codec2 3200 bps audio while PTT held

Standalone daemon — owns the serial port exclusively.

Usage:
    python3 cot_bridge.py [--port /dev/ttyACM0] [--debug]
"""

import argparse
import ipaddress
import json
import logging
import os
import signal
import socket
import struct
import sys
import threading
import time
from collections import defaultdict

from pubsub import pub

# ── Logging ──────────────────────────────────────────────────────

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
    stream=sys.stdout,
)
logger = logging.getLogger("cot_bridge")

# ── Multicast config ────────────────────────────────────────────

SA_MCAST_GROUP = "239.2.3.1"
SA_MCAST_PORT = 6969

CHAT_MCAST_GROUP = "224.10.10.1"
CHAT_MCAST_PORT = 17012

MCAST_IF = "br-lan"

# ── LoRa config ─────────────────────────────────────────────────

ATAK_FORWARDER_PORTNUM = 257
LORA_MTU = 237

# ── LoRa voice relay (openvlm-voice.py <-> radio) ───────────────
# The bridge owns the Meshtastic serial port exclusively, so it relays
# voice-text packets for the voice daemon over localhost UDP. The relay
# is payload-agnostic; the daemon does STT/TTS on either end.
# See docs/VoIP/lora_voice/lora_voice_text.md
MESH_CONF = "/etc/nucleus/mesh.conf"
VOICE_RELAY_LISTEN = ("127.0.0.1", 5558)   # voice daemon -> bridge -> LoRa TX
VOICE_RELAY_FORWARD = ("127.0.0.1", 5559)  # LoRa RX -> bridge -> voice daemon

# ── LoRa voice STREAM relay (live Codec2, VLoRa-compatible) ─────
# Live Codec2 3200 bps voice streamed over LoRa while PTT is held (the
# voice-text relay above sends one text packet per utterance instead).
# Wire format on LoRa portnum VOICE_LORA_STREAM_PORTNUM (default 256) is
# compatible with the VoiceOverLoRa (VLoRa) project's ATAK Vx bridges:
#   header: payload_size(B) seq(>H); seq 0 = stream INIT, 65535 = TERM
#   data:   up to 72 B of raw Codec2 3200 frames (9 x 8 B = 180 ms audio)
# TX in:  raw Codec2 bytes on UDP 127.0.0.1:4245 (openvlm-voice.py; the
#         VLoRa vlora_tx_bridge.py for ATAK Vx uses the same socket)
# RX out: header-stripped Codec2 bytes to UDP 127.0.0.1:4244
#         (openvlm-voice.py; the VLoRa vlora_rx_bridge.py also binds here)
# See docs/VoIP/lora_voice/lora_voice_stream.md
STREAM_RAW_LISTEN = ("127.0.0.1", 4245)   # raw Codec2 in -> LoRa TX
STREAM_FORWARD = ("127.0.0.1", 4244)      # LoRa RX -> Codec2 out
STREAM_MAX_PAYLOAD = 72                   # 9 x 8-byte Codec2 3200 frames
STREAM_HDR = struct.Struct(">BH")         # payload_size(B) seq(H)
STREAM_SEQ_INIT = 0                       # reserved seq: stream start
STREAM_SEQ_TERM = 65535                   # reserved seq: stream end
STREAM_CODEC2_ID = 2                      # codec id carried in INIT
STREAM_SILENCE_TIMEOUT = 0.5              # s of no input = PTT released

# ── Rate limiting ───────────────────────────────────────────────

TX_MIN_INTERVAL = 30  # seconds — min time between TX for same CoT UID

# ── Globals (initialized in main) ───────────────────────────────

compressor = None
builder = None
cot_parser = None
mcast_send_sock = None
iface = None
my_node_num = None
local_subnet = None  # br-lan subnet — only bridge multicast from local ATAK devices

# LoRa voice relay state (initialized in main; None = voice relay disabled)
voice_portnum = None      # int app port for voice packets (VOICE_LORA_PORTNUM)
voice_hop_limit = 0       # hop limit for voice TX (VOICE_LORA_HOP_LIMIT)
voice_port_match = set()  # values decoded["portnum"] may take for that port
voice_fwd_sock = None     # UDP socket for forwarding RX voice to the daemon

# LoRa voice STREAM relay state (None = streaming voice disabled)
stream_portnum = None     # int app port (VOICE_LORA_STREAM_PORTNUM)
stream_hop_limit = 0      # hop limit for stream TX (VOICE_LORA_HOP_LIMIT)
stream_port_match = set() # values decoded["portnum"] may take for that port
stream_fwd_sock = None    # UDP socket for forwarding RX stream audio

# Track last TX time per CoT UID for rate limiting
_tx_last_sent = defaultdict(float)  # uid → timestamp
_tx_lock = threading.Lock()

# Track recently RX'd CoT UIDs to prevent re-TX loop
_rx_recent_uids = {}  # uid → timestamp
_rx_lock = threading.Lock()
RX_UID_EXPIRY = 60  # seconds

# Track last-seen time per node for web dashboard (updated on every RX)
_node_last_seen = {}  # node_num → timestamp

# ── Stats ────────────────────────────────────────────────────────

stats = {
    "tx_mcast_received": 0,
    "tx_parsed": 0,
    "tx_compressed": 0,
    "tx_sent": 0,
    "tx_rate_limited": 0,
    "tx_too_large": 0,
    "tx_errors": 0,
    "rx_total": 0,
    "rx_atak": 0,
    "rx_decompress_ok": 0,
    "rx_inject_ok": 0,
    "rx_errors": 0,
    "voice_tx": 0,
    "voice_rx": 0,
    "voice_errors": 0,
    "stream_tx": 0,
    "stream_rx": 0,
    "stream_errors": 0,
}


# ═══════════════════════════════════════════════════════════════
#  LoRa VOICE RELAY: openvlm-voice.py <-> Meshtastic radio
# ═══════════════════════════════════════════════════════════════

def _read_mesh_conf():
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
    except OSError:
        pass
    return cfg


def _load_voice_config():
    """Read VOICE_LORA_* from mesh.conf.

    Returns (portnum, hop_limit), or (None, 0) if LoRa voice is disabled.
    """
    cfg = _read_mesh_conf()
    if cfg.get("VOICE_LORA_ENABLED", "false").lower() not in ("true", "1", "yes"):
        return None, 0
    try:
        portnum = int(cfg.get("VOICE_LORA_PORTNUM", 256))
    except ValueError:
        portnum = 256
    try:
        hop = int(cfg.get("VOICE_LORA_HOP_LIMIT", 0))
    except ValueError:
        hop = 0
    return portnum, hop


def _load_stream_config():
    """Read VOICE_LORA_STREAM_* from mesh.conf.

    Returns (portnum, hop_limit), or (None, 0) if the streaming voice
    transport is disabled. The hop limit is shared with the voice-text
    transport (VOICE_LORA_HOP_LIMIT) — both want minimal rebroadcast.
    """
    cfg = _read_mesh_conf()
    if cfg.get("VOICE_LORA_STREAM_ENABLED",
               "false").lower() not in ("true", "1", "yes"):
        return None, 0
    try:
        portnum = int(cfg.get("VOICE_LORA_STREAM_PORTNUM", 256))
    except ValueError:
        portnum = 256
    try:
        hop = int(cfg.get("VOICE_LORA_HOP_LIMIT", 0))
    except ValueError:
        hop = 0
    return portnum, hop


def _voice_port_match_values(portnum):
    """All values decoded['portnum'] may present for this port number.

    The meshtastic lib renders known enum values as their name string
    (e.g. 256 -> 'PRIVATE_APP') and unknown ones as the integer.
    """
    values = {portnum, str(portnum)}
    try:
        from meshtastic.protobuf import portnums_pb2
        values.add(portnums_pb2.PortNum.Name(portnum))
    except Exception:
        pass
    return values


def _voice_relay_loop(sock):
    """Thread loop: voice daemon hands us an encoded clip → send over LoRa."""
    logger.info(
        f"Voice relay: listening on {VOICE_RELAY_LISTEN[0]}:{VOICE_RELAY_LISTEN[1]} "
        f"→ LoRa portnum {voice_portnum} (hop_limit={voice_hop_limit})"
    )
    while True:
        try:
            data, _addr = sock.recvfrom(2048)
        except OSError:
            break
        if not data:
            continue
        if len(data) > LORA_MTU:
            stats["voice_errors"] += 1
            logger.warning(f"Voice TX dropped ({len(data)}B > {LORA_MTU}B MTU)")
            continue
        try:
            iface.sendData(data, portNum=voice_portnum, wantAck=False,
                           hopLimit=voice_hop_limit)
            stats["voice_tx"] += 1
            logger.info(f"VOICE TX → LoRa | {len(data)}B")
        except Exception as e:
            stats["voice_errors"] += 1
            logger.error(f"Voice TX error: {e}")
    logger.info("Voice relay exiting")


# ═══════════════════════════════════════════════════════════════
#  LoRa VOICE STREAM RELAY: live Codec2 <-> Meshtastic radio
#  (VLoRa-compatible framing — see the STREAM_* constants above)
# ═══════════════════════════════════════════════════════════════

def _stream_build_init():
    """Stream INIT packet (seq 0): announces codec (Codec2) to receivers."""
    payload = struct.pack(">HB", 0, STREAM_CODEC2_ID)
    return STREAM_HDR.pack(len(payload), STREAM_SEQ_INIT) + payload


def _stream_build_data(seq, audio):
    """Stream data packet: 3-byte header + raw Codec2 frames."""
    return STREAM_HDR.pack(len(audio), seq) + audio


def _stream_build_term():
    """Stream TERM packet (seq 65535): PTT released, stream over."""
    return STREAM_HDR.pack(0, STREAM_SEQ_TERM)


def _stream_send(pkt, label):
    """Send one voice-stream packet over LoRa."""
    try:
        iface.sendData(pkt, portNum=stream_portnum, wantAck=False,
                       hopLimit=stream_hop_limit)
        stats["stream_tx"] += 1
        logger.debug(f"STREAM TX → LoRa | {label} | {len(pkt)}B")
    except Exception as e:
        stats["stream_errors"] += 1
        logger.error(f"Stream TX error ({label}): {e}")


def _stream_raw_loop(sock):
    """Thread loop: raw Codec2 bytes from the voice daemon (UDP 4245) are
    packetized (INIT / seq'd data / TERM) and sent over LoRa LIVE as they
    arrive — this is a streaming transport, not a burst-at-release one.
    First packet after idle = PTT down; STREAM_SILENCE_TIMEOUT with no
    input = PTT up (flush partial packet + TERM)."""
    logger.info(
        f"Voice stream: listening on {STREAM_RAW_LISTEN[0]}:{STREAM_RAW_LISTEN[1]} "
        f"→ LoRa portnum {stream_portnum} (hop_limit={stream_hop_limit})"
    )
    sock.settimeout(0.2)
    buf = bytearray()
    seq = 1
    active = False
    last_rx = 0.0
    pkts = 0
    sent = 0
    while True:
        try:
            data, _addr = sock.recvfrom(2048)
        except socket.timeout:
            if active and time.time() - last_rx > STREAM_SILENCE_TIMEOUT:
                if buf:
                    _stream_send(_stream_build_data(seq, bytes(buf)),
                                 f"DATA seq={seq} [flush]")
                    pkts += 1
                    sent += len(buf)
                    buf.clear()
                _stream_send(_stream_build_term(), "TERM")
                active = False
                logger.info(
                    f"STREAM TX | key-up | packets={pkts} bytes={sent}B")
            continue
        except OSError:
            break
        if not data:
            continue
        if not active:
            active = True
            seq = 1
            pkts = 0
            sent = 0
            buf.clear()
            _stream_send(_stream_build_init(), "INIT")
            logger.info("STREAM TX | key-down")
        last_rx = time.time()
        buf.extend(data)
        while len(buf) >= STREAM_MAX_PAYLOAD:
            chunk = bytes(buf[:STREAM_MAX_PAYLOAD])
            del buf[:STREAM_MAX_PAYLOAD]
            _stream_send(_stream_build_data(seq, chunk), f"DATA seq={seq}")
            seq = (seq % (STREAM_SEQ_TERM - 1)) + 1
            pkts += 1
            sent += len(chunk)
    logger.info("Voice stream relay exiting")


def _handle_stream_rx(packet, decoded):
    """One received LoRa voice-stream packet: strip the 3-byte header and
    forward the raw Codec2 bytes to the voice daemon (UDP 4244) as they
    arrive, so playback starts while the sender is still talking. The
    sender's 4-byte meshtastic node num is prepended (like the voice-text
    relay) so the daemon can attribute the stream to a node. INIT and
    TERM markers carry no audio and are only logged."""
    payload = decoded.get("payload")
    if not payload or len(payload) < STREAM_HDR.size:
        return
    from_id = packet.get("fromId", "?")
    rx_snr = packet.get("rxSnr", "?")
    try:
        size, seq = STREAM_HDR.unpack(payload[:STREAM_HDR.size])
        audio = payload[STREAM_HDR.size:]
        if seq == STREAM_SEQ_INIT:
            logger.info(f"STREAM RX ← LoRa | {from_id} | key-down | SNR={rx_snr}")
            return
        if seq == STREAM_SEQ_TERM:
            logger.info(f"STREAM RX ← LoRa | {from_id} | key-up | SNR={rx_snr}")
            return
        if len(audio) < size:
            stats["stream_errors"] += 1
            logger.warning(f"Stream RX size mismatch "
                           f"(hdr={size}B got={len(audio)}B seq={seq})")
            return
        sender = packet.get("from")
        num = sender if isinstance(sender, int) else 0
        stream_fwd_sock.sendto(
            struct.pack("<I", num & 0xFFFFFFFF) + audio, STREAM_FORWARD)
        stats["stream_rx"] += 1
        logger.debug(f"STREAM RX ← LoRa | {from_id} | seq={seq} | "
                     f"{len(audio)}B | SNR={rx_snr}")
    except Exception as e:
        stats["stream_errors"] += 1
        logger.error(f"Stream RX error: {e}")


# ═══════════════════════════════════════════════════════════════
#  TX SIDE: Multicast → LoRa
# ═══════════════════════════════════════════════════════════════

def _get_local_subnet():
    """Get br-lan's IP network (e.g., 10.20.22.0/24) for source filtering.

    Retries every 2s for up to 30s to handle boot race conditions where
    br-lan may not have an IP assigned yet when the service starts.
    """
    import fcntl
    max_attempts = 15
    for attempt in range(1, max_attempts + 1):
        try:
            ifname = MCAST_IF.encode()
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            # Get IP address
            ip_bytes = fcntl.ioctl(
                s.fileno(), 0x8915,  # SIOCGIFADDR
                struct.pack("256s", ifname[:15])
            )[20:24]
            # Get netmask
            mask_bytes = fcntl.ioctl(
                s.fileno(), 0x891b,  # SIOCGIFNETMASK
                struct.pack("256s", ifname[:15])
            )[20:24]
            s.close()
            ip_str = socket.inet_ntoa(ip_bytes)
            mask_str = socket.inet_ntoa(mask_bytes)
            network = ipaddress.ip_network(f"{ip_str}/{mask_str}", strict=False)
            if attempt > 1:
                logger.info(f"{MCAST_IF} subnet detected on attempt {attempt}/{max_attempts}")
            return network
        except Exception as e:
            if attempt < max_attempts:
                logger.info(f"Waiting for {MCAST_IF} IP (attempt {attempt}/{max_attempts}): {e}")
                time.sleep(2)
            else:
                logger.warning(f"Could not determine {MCAST_IF} subnet after {max_attempts} attempts: {e}")
                return None


def _create_mcast_listener(group, port):
    """Create a UDP socket that joins a multicast group on br-lan."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.bind(("", port))
    # Join multicast group on br-lan
    try:
        # Get br-lan IP for IGMP membership
        import fcntl
        ifname = MCAST_IF.encode()
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        ip_bytes = fcntl.ioctl(
            s.fileno(), 0x8915,  # SIOCGIFADDR
            struct.pack("256s", ifname[:15])
        )[20:24]
        s.close()
        mreq = socket.inet_aton(group) + ip_bytes
    except Exception:
        # Fallback: join on all interfaces
        mreq = socket.inet_aton(group) + socket.inet_aton("0.0.0.0")
    sock.setsockopt(socket.IPPROTO_IP, socket.IP_ADD_MEMBERSHIP, mreq)
    sock.settimeout(2.0)
    return sock


def _is_chat_event(cot_xml):
    """Check if a CoT XML string is a GeoChat event."""
    return "GeoChat" in cot_xml or "b-t-f" in cot_xml


def _tx_rate_ok(uid):
    """Check if we're allowed to TX this UID (rate limiting)."""
    now = time.time()
    with _tx_lock:
        last = _tx_last_sent.get(uid, 0)
        if now - last < TX_MIN_INTERVAL:
            return False
        _tx_last_sent[uid] = now
        return True


def _was_recently_rxd(uid):
    """Check if this UID was recently received from LoRa (loop prevention)."""
    now = time.time()
    with _rx_lock:
        ts = _rx_recent_uids.get(uid)
        if ts and (now - ts) < RX_UID_EXPIRY:
            return True
        return False


def _tx_process_packet(data):
    """Process a multicast TAK Protocol V1 packet for TX over LoRa."""
    import takproto
    sys.path.insert(0, "/opt/nucleus/meshtastic")
    from takmessage_to_xml import takmessage_to_xml

    stats["tx_mcast_received"] += 1

    try:
        # Step 1: Parse TAK Protocol V1 → TakMessage
        tak_msg = takproto.parse_proto(bytearray(data))
        if tak_msg is None:
            return
        stats["tx_parsed"] += 1

        # Step 2: TakMessage → CoT XML
        cot_xml = takmessage_to_xml(tak_msg)
        uid = tak_msg.cotEvent.uid

        # Loop prevention: don't re-TX packets we just received from LoRa
        if _was_recently_rxd(uid):
            logger.debug(f"TX skip (from LoRa): {uid}")
            return

        # Rate limiting
        if not _tx_rate_ok(uid):
            stats["tx_rate_limited"] += 1
            logger.debug(f"TX rate limited: {uid}")
            return

        # Step 3: CoT XML → TAKPacketV2 → compress
        tak_packet = cot_parser.parse(cot_xml)
        wire_bytes = compressor.compress(tak_packet)
        stats["tx_compressed"] += 1

        if len(wire_bytes) > LORA_MTU:
            stats["tx_too_large"] += 1
            logger.warning(f"TX too large ({len(wire_bytes)}B > {LORA_MTU}B): {uid}")
            return

        # Step 4: Send over LoRa
        iface.sendData(wire_bytes, portNum=ATAK_FORWARDER_PORTNUM, wantAck=False)
        stats["tx_sent"] += 1

        if uid:
            cot_type = tak_msg.cotEvent.type
            logger.info(f"TX → LoRa | {uid} | {cot_type} | {len(wire_bytes)}B")
        else:
            logger.info(f"TX → LoRa | [discovery] | {len(wire_bytes)}B")

    except Exception as e:
        stats["tx_errors"] += 1
        logger.error(f"TX error: {e}")


def _mcast_listener_loop(sock, name):
    """Thread loop: listen on a multicast socket, process packets for TX."""
    logger.info(f"TX listener started: {name}")
    while True:
        try:
            data, addr = sock.recvfrom(4096)
        except socket.timeout:
            continue
        except OSError:
            break

        # Only bridge multicast from local ATAK devices (not WiFi mesh traffic)
        if local_subnet is not None:
            src_ip = addr[0]
            if ipaddress.ip_address(src_ip) not in local_subnet:
                logger.debug(f"TX skip (non-local src {src_ip}): {name}")
                continue

        try:
            _tx_process_packet(data)
        except Exception as e:
            logger.error(f"TX listener ({name}) error: {e}")

    logger.info(f"TX listener exiting: {name}")


# ═══════════════════════════════════════════════════════════════
#  RX SIDE: LoRa → Multicast
# ═══════════════════════════════════════════════════════════════

def _setup_mcast_send_socket():
    """Create a UDP socket for multicast injection on br-lan."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
    sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, 32)
    try:
        sock.setsockopt(
            socket.SOL_SOCKET, socket.SO_BINDTODEVICE,
            MCAST_IF.encode() + b"\0",
        )
    except OSError as e:
        logger.warning(f"Could not bind send socket to {MCAST_IF}: {e}")
    return sock


def _inject_multicast(cot_xml):
    """Send CoT XML to the appropriate multicast group."""
    if _is_chat_event(cot_xml):
        group, port = CHAT_MCAST_GROUP, CHAT_MCAST_PORT
    else:
        group, port = SA_MCAST_GROUP, SA_MCAST_PORT

    xml_bytes = cot_xml.encode("utf-8") if isinstance(cot_xml, str) else cot_xml
    try:
        mcast_send_sock.sendto(xml_bytes, (group, port))
        stats["rx_inject_ok"] += 1
        return group, port
    except Exception as e:
        logger.error(f"Multicast inject failed: {e}")
        stats["rx_errors"] += 1
        return None, None


def onReceive(packet, interface):
    """pypubsub callback: handle all received mesh packets."""
    stats["rx_total"] += 1

    sender = packet.get("from", "?")
    from_id = packet.get("fromId", "?")

    # Skip self-originated packets
    if sender == my_node_num:
        return

    # Track last-seen time for web dashboard (updates on ALL packet types)
    if isinstance(sender, int):
        _node_last_seen[sender] = int(time.time())

    decoded = packet.get("decoded", {})
    portnum = decoded.get("portnum", "")

    # LoRa voice stream chunk → forward to the voice daemon (localhost UDP)
    if stream_portnum is not None and portnum in stream_port_match:
        _handle_stream_rx(packet, decoded)
        return

    # LoRa voice text → forward to the openvlm-voice daemon (localhost UDP)
    if voice_portnum is not None and portnum in voice_port_match:
        payload = decoded.get("payload")
        if payload:
            try:
                num = sender if isinstance(sender, int) else 0
                voice_fwd_sock.sendto(
                    struct.pack("<I", num & 0xFFFFFFFF) + payload,
                    VOICE_RELAY_FORWARD,
                )
                stats["voice_rx"] += 1
                logger.info(f"VOICE RX ← LoRa | {from_id} | {len(payload)}B")
            except Exception as e:
                stats["voice_errors"] += 1
                logger.error(f"Voice RX forward error: {e}")
        return

    if portnum != "ATAK_FORWARDER":
        return

    payload = decoded.get("payload")
    if not payload:
        return

    stats["rx_atak"] += 1
    rx_snr = packet.get("rxSnr", "?")

    # Look up sender's short name from node database
    sender_name = from_id
    try:
        node_info = iface.nodes.get(f"{from_id}")
        if node_info:
            sender_name = node_info.get("user", {}).get("shortName", from_id)
    except Exception:
        pass

    try:
        # Step 1: Decompress
        tak_packet = compressor.decompress(payload)
        stats["rx_decompress_ok"] += 1

        # Step 2: Build CoT XML
        cot_xml = builder.build(tak_packet)

        # Track UID to prevent re-TX loop
        _track_rx_uid(cot_xml)

        # Step 3: Inject CoT XML as multicast
        group, port = _inject_multicast(cot_xml)
        if group:
            uid, _ = _extract_uid_callsign(cot_xml)
            if uid and uid != "unknown" and uid != "?":
                logger.info(
                    f"RX ← LoRa | {sender_name} | {uid} | "
                    f"{len(payload)}B | SNR={rx_snr}"
                )
            else:
                logger.info(
                    f"RX ← LoRa | {sender_name} | [discovery] | "
                    f"{len(payload)}B | SNR={rx_snr}"
                )

    except Exception as e:
        stats["rx_errors"] += 1
        logger.error(f"RX error from {from_id}: {e}")


def _track_rx_uid(cot_xml):
    """Track recently received CoT UIDs to prevent re-TX loop."""
    try:
        import xml.etree.ElementTree as ET
        root = ET.fromstring(cot_xml)
        uid = root.get("uid", "")
        if uid:
            with _rx_lock:
                _rx_recent_uids[uid] = time.time()
    except Exception:
        pass


def _extract_uid_callsign(cot_xml):
    """Extract uid and callsign from CoT XML for logging."""
    try:
        import xml.etree.ElementTree as ET
        root = ET.fromstring(cot_xml)
        uid = root.get("uid", "?")
        detail = root.find("detail")
        callsign = "?"
        if detail is not None:
            contact = detail.find("contact")
            if contact is not None:
                callsign = contact.get("callsign", "?")
        return uid, callsign
    except Exception:
        return "?", "?"


# ═══════════════════════════════════════════════════════════════
#  NODE DUMP: Periodically write iface.nodes to JSON for web UI
# ═══════════════════════════════════════════════════════════════

NODE_DUMP_PATH = "/tmp/meshtastic_nodes.json"
NODE_DUMP_INTERVAL = 15  # seconds
NODE_MAX_AGE = 3600  # seconds — exclude nodes not heard in this long


def _dump_nodes():
    """Write iface.nodes to a JSON file for the web dashboard.

    Writes atomically (tmp file + rename) to avoid partial reads.
    Excludes the local node (my_node_num) from the list.
    """
    if iface is None or not hasattr(iface, 'nodes') or iface.nodes is None:
        return

    try:
        now = int(time.time())
        # Snapshot the dict to avoid RuntimeError from concurrent modification
        # (meshtastic library updates iface.nodes from its own thread)
        nodes_snapshot = dict(iface.nodes)
        nodes_list = []
        for node_id, node in nodes_snapshot.items():
            # Skip our own node
            num = node.get("num")
            if num == my_node_num:
                continue

            user = node.get("user", {})
            last_heard = node.get("lastHeard") or 0
            # Use our own tracking if more recent than firmware's lastHeard
            our_seen = _node_last_seen.get(num, 0)
            last_heard = max(last_heard, our_seen)
            # Skip nodes never heard or too old
            if not last_heard or (now - last_heard) > NODE_MAX_AGE:
                continue

            nodes_list.append({
                "id": user.get("id", node_id),
                "short_name": user.get("shortName", "?"),
                "long_name": user.get("longName", ""),
                "last_heard": last_heard,
                "snr": node.get("snr"),
                "hops_away": node.get("hopsAway"),
            })

        # Sort by most recently heard
        nodes_list.sort(key=lambda n: n["last_heard"], reverse=True)

        dump = {
            "timestamp": int(time.time()),
            "nodes": nodes_list,
        }

        tmp_path = NODE_DUMP_PATH + ".tmp"
        with open(tmp_path, "w") as f:
            json.dump(dump, f)
        os.replace(tmp_path, NODE_DUMP_PATH)

    except Exception as e:
        logger.warning(f"Node dump error: {e}")


def onConnection(interface, topic=pub.AUTO_TOPIC):
    """Called when serial connection is established."""
    global my_node_num
    my_node_num = interface.myInfo.my_node_num
    logger.info(f"Radio connected: {interface.getLongName()} (node {my_node_num})")


def onDisconnect(interface, topic=pub.AUTO_TOPIC):
    """Called when serial connection is lost."""
    logger.warning("Radio connection lost!")


# ═══════════════════════════════════════════════════════════════
#  MAIN
# ═══════════════════════════════════════════════════════════════

def main():
    global compressor, builder, cot_parser, mcast_send_sock, iface, local_subnet
    global voice_portnum, voice_hop_limit, voice_port_match, voice_fwd_sock
    global stream_portnum, stream_hop_limit, stream_port_match, stream_fwd_sock

    parser = argparse.ArgumentParser(description="ATAK CoT Bridge (Stage 7)")
    parser.add_argument("--port", default=None, help="Serial port (default: auto-detect)")
    parser.add_argument("--debug", action="store_true", help="Enable verbose logging")
    args = parser.parse_args()

    if args.debug:
        logging.getLogger("meshtastic").setLevel(logging.DEBUG)
        logger.setLevel(logging.DEBUG)
    else:
        logging.getLogger("meshtastic").setLevel(logging.WARNING)

    # ── Initialize pipeline objects ──────────────────────────
    from meshtastic_tak.cot_xml_parser import CotXmlParser
    from meshtastic_tak.tak_compressor import TakCompressor
    from meshtastic_tak.cot_xml_builder import CotXmlBuilder

    compressor = TakCompressor()
    builder = CotXmlBuilder()
    cot_parser = CotXmlParser()
    logger.info("Pipeline initialized (TakCompressor + CotXmlBuilder + CotXmlParser)")

    # ── Detect local subnet for TX source filtering ──────────
    local_subnet = _get_local_subnet()
    if local_subnet:
        logger.info(f"TX source filter: only bridging multicast from {local_subnet}")
    else:
        logger.warning("TX source filter DISABLED — could not detect br-lan subnet")

    # ── Setup multicast sockets ──────────────────────────────
    mcast_send_sock = _setup_mcast_send_socket()
    logger.info(f"Multicast send socket ready on {MCAST_IF}")

    # ── Subscribe to pypubsub BEFORE opening serial ──────────
    pub.subscribe(onReceive, "meshtastic.receive")
    pub.subscribe(onConnection, "meshtastic.connection.established")
    pub.subscribe(onDisconnect, "meshtastic.connection.lost")

    # ── Open serial interface ────────────────────────────────
    import meshtastic.serial_interface

    logger.info(f"Opening SerialInterface(devPath={args.port})...")
    try:
        iface = meshtastic.serial_interface.SerialInterface(devPath=args.port)
    except Exception as e:
        logger.error(f"Failed to open serial interface: {e}")
        sys.exit(1)
    logger.info(f"Radio open on {iface.devPath}")

    # ── Start TX multicast listeners ─────────────────────────
    try:
        sa_sock = _create_mcast_listener(SA_MCAST_GROUP, SA_MCAST_PORT)
        sa_thread = threading.Thread(
            target=_mcast_listener_loop, args=(sa_sock, "SA"),
            daemon=True,
        )
        sa_thread.start()
        logger.info(f"TX: Listening on {SA_MCAST_GROUP}:{SA_MCAST_PORT} (SA)")
    except Exception as e:
        logger.error(f"Could not start SA listener: {e}")
        sa_sock = None

    try:
        chat_sock = _create_mcast_listener(CHAT_MCAST_GROUP, CHAT_MCAST_PORT)
        chat_thread = threading.Thread(
            target=_mcast_listener_loop, args=(chat_sock, "Chat"),
            daemon=True,
        )
        chat_thread.start()
        logger.info(f"TX: Listening on {CHAT_MCAST_GROUP}:{CHAT_MCAST_PORT} (Chat)")
    except Exception as e:
        logger.error(f"Could not start Chat listener: {e}")
        chat_sock = None

    # ── LoRa voice relay for openvlm-voice.py ────────────────
    voice_portnum, voice_hop_limit = _load_voice_config()
    voice_relay_sock = None
    if voice_portnum is not None:
        voice_port_match = _voice_port_match_values(voice_portnum)
        voice_fwd_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            voice_relay_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            voice_relay_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            voice_relay_sock.bind(VOICE_RELAY_LISTEN)
            threading.Thread(
                target=_voice_relay_loop, args=(voice_relay_sock,), daemon=True,
            ).start()
        except Exception as e:
            logger.error(f"Could not start voice relay: {e}")
            voice_relay_sock = None
    else:
        logger.info("LoRa voice relay disabled (VOICE_LORA_ENABLED != true)")

    # ── LoRa voice stream relay (live Codec2) ────────────────
    stream_portnum, stream_hop_limit = _load_stream_config()
    stream_raw_sock = None
    if stream_portnum is not None:
        stream_port_match = _voice_port_match_values(stream_portnum)
        stream_fwd_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            stream_raw_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            stream_raw_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            stream_raw_sock.bind(STREAM_RAW_LISTEN)
            threading.Thread(
                target=_stream_raw_loop, args=(stream_raw_sock,), daemon=True,
            ).start()
        except Exception as e:
            logger.error(f"Could not start voice stream relay: {e}")
            stream_raw_sock = None
    else:
        logger.info("LoRa voice stream relay disabled "
                    "(VOICE_LORA_STREAM_ENABLED != true)")

    print()
    print("=" * 60)
    print("  ATAK CoT Bridge — Bidirectional LoRa ↔ Multicast")
    print(f"  TX: {SA_MCAST_GROUP}:{SA_MCAST_PORT} + {CHAT_MCAST_GROUP}:{CHAT_MCAST_PORT} → LoRa")
    print(f"  RX: LoRa → multicast on {MCAST_IF}")
    print(f"  Rate limit: {TX_MIN_INTERVAL}s per UID")
    print("=" * 60)
    print()

    # ── Shutdown handler (works for both SIGTERM and KeyboardInterrupt) ──
    def _shutdown(signum=None, frame=None):
        sig_name = signal.Signals(signum).name if signum else "KeyboardInterrupt"
        logger.info(f"Shutting down ({sig_name})...")
        logger.info(f"TX stats: mcast={stats['tx_mcast_received']} parsed={stats['tx_parsed']} "
                     f"sent={stats['tx_sent']} rate_limited={stats['tx_rate_limited']} "
                     f"too_large={stats['tx_too_large']} errors={stats['tx_errors']}")
        logger.info(f"RX stats: total={stats['rx_total']} atak={stats['rx_atak']} "
                     f"decompress={stats['rx_decompress_ok']} inject={stats['rx_inject_ok']} "
                     f"errors={stats['rx_errors']}")
        if voice_portnum is not None:
            logger.info(f"Voice stats: tx={stats['voice_tx']} rx={stats['voice_rx']} "
                         f"errors={stats['voice_errors']}")
        if stream_portnum is not None:
            logger.info(f"Stream stats: tx={stats['stream_tx']} "
                         f"rx={stats['stream_rx']} errors={stats['stream_errors']}")
        if voice_relay_sock:
            try:
                voice_relay_sock.close()
            except Exception:
                pass
        if stream_raw_sock:
            try:
                stream_raw_sock.close()
            except Exception:
                pass
        try:
            iface.close()
        except Exception:
            pass
        try:
            mcast_send_sock.close()
        except Exception:
            pass
        if sa_sock:
            try:
                sa_sock.close()
            except Exception:
                pass
        if chat_sock:
            try:
                chat_sock.close()
            except Exception:
                pass
        logger.info("Serial interface closed — radio released")
        sys.exit(0)

    signal.signal(signal.SIGTERM, _shutdown)

    # ── Keep alive ───────────────────────────────────────────
    last_node_dump = 0
    try:
        while True:
            time.sleep(10)
            try:
                now = time.time()

                # Dump node database for web dashboard
                if now - last_node_dump >= NODE_DUMP_INTERVAL:
                    _dump_nodes()
                    last_node_dump = now

                # Periodic cleanup of expired RX UIDs
                with _rx_lock:
                    expired = [u for u, t in _rx_recent_uids.items() if now - t > RX_UID_EXPIRY]
                    for u in expired:
                        del _rx_recent_uids[u]
                with _tx_lock:
                    expired = [u for u, t in _tx_last_sent.items() if now - t > TX_MIN_INTERVAL * 2]
                    for u in expired:
                        del _tx_last_sent[u]
            except Exception as e:
                logger.warning(f"Main loop error (continuing): {e}")
    except KeyboardInterrupt:
        _shutdown()


if __name__ == "__main__":
    main()
