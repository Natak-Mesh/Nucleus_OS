#!/usr/bin/env python3
"""
ATAK CoT Bridge — Stage 7

Bidirectional bridge between ATAK multicast CoT and Meshtastic LoRa.

TX: ATAK multicast (SA + Chat) → compress TAKPacketV2 → LoRa (portnum 257)
RX: LoRa (portnum 257) → decompress TAKPacketV2 → ATAK multicast

Standalone daemon — owns the serial port exclusively.
Not used simultaneously with meshtastic_manager.py.

Usage:
    python3 cot_bridge.py [--port /dev/ttyACM0] [--debug]
"""

import argparse
import logging
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

# ── Rate limiting ───────────────────────────────────────────────

TX_MIN_INTERVAL = 30  # seconds — min time between TX for same CoT UID

# ── Globals (initialized in main) ───────────────────────────────

compressor = None
builder = None
cot_parser = None
mcast_send_sock = None
iface = None
my_node_num = None

# Track last TX time per CoT UID for rate limiting
_tx_last_sent = defaultdict(float)  # uid → timestamp
_tx_lock = threading.Lock()

# Track recently RX'd CoT UIDs to prevent re-TX loop
_rx_recent_uids = {}  # uid → timestamp
_rx_lock = threading.Lock()
RX_UID_EXPIRY = 60  # seconds

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
}


# ═══════════════════════════════════════════════════════════════
#  TX SIDE: Multicast → LoRa
# ═══════════════════════════════════════════════════════════════

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

        cot_type = tak_msg.cotEvent.type
        logger.info(f"TX → LoRa | {uid} | {cot_type} | {len(wire_bytes)}B")

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


def _inject_multicast(tak_v1_bytes, cot_xml):
    """Send TAK Protocol V1 bytes to the appropriate multicast group."""
    if _is_chat_event(cot_xml):
        group, port = CHAT_MCAST_GROUP, CHAT_MCAST_PORT
    else:
        group, port = SA_MCAST_GROUP, SA_MCAST_PORT

    try:
        mcast_send_sock.sendto(tak_v1_bytes, (group, port))
        stats["rx_inject_ok"] += 1
        return group, port
    except Exception as e:
        logger.error(f"Multicast inject failed: {e}")
        stats["rx_errors"] += 1
        return None, None


def onReceive(packet, interface):
    """pypubsub callback: handle all received mesh packets."""
    stats["rx_total"] += 1

    decoded = packet.get("decoded", {})
    portnum = decoded.get("portnum", "")

    if portnum != "ATAK_FORWARDER":
        return

    sender = packet.get("from", "?")
    from_id = packet.get("fromId", "?")

    # Skip self-originated packets
    if sender == my_node_num:
        return

    payload = decoded.get("payload")
    if not payload:
        return

    stats["rx_atak"] += 1
    rx_snr = packet.get("rxSnr", "?")
    rx_rssi = packet.get("rxRssi", "?")

    try:
        # Step 1: Decompress
        tak_packet = compressor.decompress(payload)
        stats["rx_decompress_ok"] += 1

        # Step 2: Build CoT XML
        cot_xml = builder.build(tak_packet)

        # Step 3: Convert to TAK Protocol V1
        import takproto
        tak_v1_bytes = takproto.xml2proto(cot_xml)
        if not tak_v1_bytes:
            logger.error("xml2proto returned empty")
            return

        # Track UID to prevent re-TX loop
        _track_rx_uid(cot_xml)

        # Step 4: Inject multicast
        group, port = _inject_multicast(tak_v1_bytes, cot_xml)
        if group:
            uid, callsign = _extract_uid_callsign(cot_xml)
            logger.info(
                f"RX ← LoRa | {from_id} | {uid} | {callsign} | "
                f"{len(payload)}B→{len(tak_v1_bytes)}B | "
                f"SNR={rx_snr} | → {group}:{port}"
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


def onConnection(interface_obj, topic=pub.AUTO_TOPIC):
    """Called when serial connection is established."""
    global my_node_num
    my_node_num = interface_obj.myInfo.my_node_num
    logger.info(f"Radio connected: {interface_obj.getLongName()} (node {my_node_num})")


def onDisconnect(interface_obj, topic=pub.AUTO_TOPIC):
    """Called when serial connection is lost."""
    logger.warning("Radio connection lost!")


# ═══════════════════════════════════════════════════════════════
#  MAIN
# ═══════════════════════════════════════════════════════════════

def main():
    global compressor, builder, cot_parser, mcast_send_sock, iface

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

    print()
    print("=" * 60)
    print("  ATAK CoT Bridge — Bidirectional LoRa ↔ Multicast")
    print(f"  TX: {SA_MCAST_GROUP}:{SA_MCAST_PORT} + {CHAT_MCAST_GROUP}:{CHAT_MCAST_PORT} → LoRa")
    print(f"  RX: LoRa → multicast on {MCAST_IF}")
    print(f"  Rate limit: {TX_MIN_INTERVAL}s per UID")
    print("=" * 60)
    print()

    # ── Keep alive ───────────────────────────────────────────
    try:
        while True:
            time.sleep(10)
            # Periodic cleanup of expired RX UIDs
            now = time.time()
            with _rx_lock:
                expired = [u for u, t in _rx_recent_uids.items() if now - t > RX_UID_EXPIRY]
                for u in expired:
                    del _rx_recent_uids[u]
            with _tx_lock:
                expired = [u for u, t in _tx_last_sent.items() if now - t > TX_MIN_INTERVAL * 2]
                for u in expired:
                    del _tx_last_sent[u]
    except KeyboardInterrupt:
        print()
        logger.info("Shutting down...")
        logger.info(f"TX stats: mcast={stats['tx_mcast_received']} parsed={stats['tx_parsed']} "
                     f"sent={stats['tx_sent']} rate_limited={stats['tx_rate_limited']} "
                     f"too_large={stats['tx_too_large']} errors={stats['tx_errors']}")
        logger.info(f"RX stats: total={stats['rx_total']} atak={stats['rx_atak']} "
                     f"decompress={stats['rx_decompress_ok']} inject={stats['rx_inject_ok']} "
                     f"errors={stats['rx_errors']}")
        iface.close()
        mcast_send_sock.close()
        if sa_sock:
            sa_sock.close()
        if chat_sock:
            chat_sock.close()


if __name__ == "__main__":
    main()
