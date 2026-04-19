#!/usr/bin/env python3
"""
Stage 6 — ATAK CoT Bridge RX

Receives ATAK_FORWARDER (portnum 257) packets from LoRa, decompresses
TAKPacketV2, converts to TAK Protocol V1, injects as multicast on
239.2.3.1:6969 for local ATAK devices.

Pipeline:
    LoRa packet (portnum 257) → wire payload
      → TakCompressor.decompress() → TAKPacketV2
      → CotXmlBuilder.build() → CoT XML
      → xml2proto() → TAK Protocol V1 mesh bytes
      → multicast UDP 239.2.3.1:6969

Usage:
    python3 cot_bridge_rx.py [--port /dev/ttyACM0] [--debug]

Ctrl+C to stop.
"""

import argparse
import logging
import socket
import struct
import sys
import time

from pubsub import pub

# ── Logging ──────────────────────────────────────────────────────

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
    stream=sys.stdout,
)
logger = logging.getLogger("cot_bridge_rx")

# ── Multicast config ────────────────────────────────────────────

MCAST_GROUP = "239.2.3.1"
MCAST_PORT = 6969
MCAST_IF = "br-lan"  # Interface to send multicast on

# ── Pipeline objects (initialized in main) ───────────────────────

compressor = None
builder = None
mcast_sock = None
my_node_num = None

# ── Stats ────────────────────────────────────────────────────────

stats = {
    "total_packets": 0,
    "atak_packets": 0,
    "decompress_ok": 0,
    "decompress_fail": 0,
    "inject_ok": 0,
    "inject_fail": 0,
}


def _setup_mcast_socket():
    """Create a UDP socket for multicast injection on br-lan."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
    sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, 32)
    # Bind to br-lan interface for multicast output
    try:
        sock.setsockopt(
            socket.SOL_SOCKET,
            socket.SO_BINDTODEVICE,
            MCAST_IF.encode() + b"\0",
        )
    except OSError as e:
        logger.warning(f"Could not bind to {MCAST_IF}: {e} (multicast may go out wrong interface)")
    return sock


def _inject_multicast(tak_v1_bytes):
    """Send TAK Protocol V1 bytes as multicast UDP."""
    global mcast_sock
    try:
        mcast_sock.sendto(tak_v1_bytes, (MCAST_GROUP, MCAST_PORT))
        stats["inject_ok"] += 1
        return True
    except Exception as e:
        logger.error(f"Multicast inject failed: {e}")
        stats["inject_fail"] += 1
        return False


# ── Packet handler ───────────────────────────────────────────────

def onReceive(packet, interface):
    """Handle all received mesh packets. Filter for ATAK_FORWARDER."""
    global my_node_num
    stats["total_packets"] += 1

    decoded = packet.get("decoded", {})
    portnum = decoded.get("portnum", "")

    # Only process ATAK_FORWARDER (portnum 257)
    if portnum != "ATAK_FORWARDER":
        return

    sender = packet.get("from", "?")
    from_id = packet.get("fromId", "?")

    # Skip packets from ourselves (avoid loopback)
    if sender == my_node_num:
        logger.debug(f"Ignoring ATAK_FORWARDER from self ({from_id})")
        return

    payload = decoded.get("payload")
    if not payload:
        logger.warning(f"ATAK_FORWARDER from {from_id} has no payload")
        return

    stats["atak_packets"] += 1
    rx_snr = packet.get("rxSnr", "?")
    rx_rssi = packet.get("rxRssi", "?")
    logger.info(
        f"ATAK_FORWARDER from {from_id} | {len(payload)}B | "
        f"SNR={rx_snr} RSSI={rx_rssi}"
    )

    # ── RX Pipeline ──────────────────────────────────────────
    try:
        # Step 1: Decompress wire payload → TAKPacketV2
        tak_packet = compressor.decompress(payload)
        stats["decompress_ok"] += 1
    except Exception as e:
        logger.error(f"Decompress failed: {e}")
        stats["decompress_fail"] += 1
        return

    try:
        # Step 2: TAKPacketV2 → CoT XML
        cot_xml = builder.build(tak_packet)
        logger.info(f"  CoT XML ({len(cot_xml)}B): uid/type extracted below")
        logger.debug(f"  Full XML: {cot_xml}")
    except Exception as e:
        logger.error(f"CotXmlBuilder.build() failed: {e}")
        return

    try:
        # Step 3: CoT XML → TAK Protocol V1 mesh bytes
        import takproto
        tak_v1_bytes = takproto.xml2proto(cot_xml)
        if not tak_v1_bytes:
            logger.error("xml2proto returned empty bytes")
            return
        logger.info(f"  TAK Protocol V1: {len(tak_v1_bytes)}B")
    except Exception as e:
        logger.error(f"xml2proto failed: {e}")
        return

    # Step 4: Inject as multicast
    if _inject_multicast(tak_v1_bytes):
        logger.info(f"  → Injected to {MCAST_GROUP}:{MCAST_PORT}")

    # Log summary
    _log_cot_summary(cot_xml)


def _log_cot_summary(cot_xml):
    """Extract and log key CoT fields for visibility."""
    try:
        import xml.etree.ElementTree as ET
        root = ET.fromstring(cot_xml)
        uid = root.get("uid", "?")
        cot_type = root.get("type", "?")
        point = root.find("point")
        lat = point.get("lat", "?") if point is not None else "?"
        lon = point.get("lon", "?") if point is not None else "?"
        detail = root.find("detail")
        callsign = "?"
        team = "?"
        if detail is not None:
            contact = detail.find("contact")
            if contact is not None:
                callsign = contact.get("callsign", "?")
            group = detail.find("__group")
            if group is not None:
                team = group.get("name", "?")
        logger.info(
            f"  CoT: uid={uid} type={cot_type} "
            f"callsign={callsign} team={team} lat={lat} lon={lon}"
        )
    except Exception as e:
        logger.debug(f"Could not parse CoT summary: {e}")


def onConnection(interface, topic=pub.AUTO_TOPIC):
    """Called when connection is established."""
    global my_node_num
    my_node_num = interface.myInfo.my_node_num
    logger.info(f"Connected: {interface.getLongName()} (node {my_node_num})")


def onDisconnect(interface, topic=pub.AUTO_TOPIC):
    """Called when connection is lost."""
    logger.warning("Connection lost!")


# ── Main ─────────────────────────────────────────────────────────

def main():
    global compressor, builder, mcast_sock

    parser = argparse.ArgumentParser(description="ATAK CoT Bridge RX (Stage 6)")
    parser.add_argument("--port", default=None, help="Serial port (default: auto-detect)")
    parser.add_argument("--debug", action="store_true", help="Enable verbose debug logging")
    args = parser.parse_args()

    if args.debug:
        logging.getLogger("meshtastic").setLevel(logging.DEBUG)
        logger.setLevel(logging.DEBUG)
    else:
        logging.getLogger("meshtastic").setLevel(logging.WARNING)

    # ── Initialize pipeline objects ──────────────────────────
    from meshtastic_tak.tak_compressor import TakCompressor
    from meshtastic_tak.cot_xml_builder import CotXmlBuilder

    compressor = TakCompressor()
    builder = CotXmlBuilder()
    logger.info("RX pipeline initialized (TakCompressor + CotXmlBuilder)")

    # ── Setup multicast socket ───────────────────────────────
    mcast_sock = _setup_mcast_socket()
    logger.info(f"Multicast socket ready: {MCAST_GROUP}:{MCAST_PORT} on {MCAST_IF}")

    # ── Subscribe BEFORE creating interface ──────────────────
    pub.subscribe(onReceive, "meshtastic.receive")
    pub.subscribe(onConnection, "meshtastic.connection.established")
    pub.subscribe(onDisconnect, "meshtastic.connection.lost")
    logger.info("Subscribed to meshtastic.receive")

    # ── Open serial interface ────────────────────────────────
    import meshtastic.serial_interface

    logger.info(f"Opening SerialInterface(devPath={args.port})...")
    try:
        iface = meshtastic.serial_interface.SerialInterface(devPath=args.port)
    except Exception as e:
        logger.error(f"Failed to open serial interface: {e}")
        sys.exit(1)

    logger.info(f"Interface open on {iface.devPath}")
    print()
    print("=" * 60)
    print("  ATAK CoT Bridge RX — Listening for ATAK_FORWARDER")
    print(f"  Multicast inject: {MCAST_GROUP}:{MCAST_PORT}")
    print("=" * 60)
    print()

    # ── Keep alive ───────────────────────────────────────────
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print()
        logger.info("Shutting down...")
        logger.info(
            f"Stats: total={stats['total_packets']} "
            f"atak={stats['atak_packets']} "
            f"decompress_ok={stats['decompress_ok']} "
            f"decompress_fail={stats['decompress_fail']} "
            f"inject_ok={stats['inject_ok']} "
            f"inject_fail={stats['inject_fail']}"
        )
        iface.close()
        mcast_sock.close()


if __name__ == "__main__":
    main()
