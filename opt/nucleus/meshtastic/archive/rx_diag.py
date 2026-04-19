#!/usr/bin/env python3
"""
Meshtastic RX Diagnostic — mirrors `meshtastic --listen` exactly.

Tests whether SerialInterface + pub.subscribe receives remote LoRa packets.
Enables full SDK debug logging so we can see every fromRadio message.

Usage:
    python3 rx_diag.py [--port /dev/ttyACM0] [--debug]

Ctrl+C to stop.
"""

import argparse
import logging
import sys
import time
from datetime import datetime

from pubsub import pub

# ── Logging setup ────────────────────────────────────────────────

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s %(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
    stream=sys.stdout,
)
logger = logging.getLogger("rx_diag")


# ── Callbacks (subscribe BEFORE creating interface, like CLI) ────

my_node_num = None
packet_count = 0
remote_count = 0
local_count = 0


def onReceive(packet, interface):
    """Called for ALL received mesh packets (parent topic)."""
    global packet_count, remote_count, local_count, my_node_num
    packet_count += 1

    sender = packet.get("from", "?")
    to = packet.get("to", "?")
    from_id = packet.get("fromId", "?")
    to_id = packet.get("toId", "?")

    decoded = packet.get("decoded", {})
    portnum = decoded.get("portnum", "ENCRYPTED/UNKNOWN")

    # Determine if local or remote
    is_local = (sender == my_node_num) if my_node_num else None
    if is_local:
        local_count += 1
        tag = "LOCAL"
    elif is_local is False:
        remote_count += 1
        tag = "REMOTE"
    else:
        tag = "UNKNOWN_ORIGIN"

    # SNR/RSSI (only present on received-over-radio packets)
    rx_snr = packet.get("rxSnr", None)
    rx_rssi = packet.get("rxRssi", None)
    hop_limit = packet.get("hopLimit", None)
    hop_start = packet.get("hopStart", None)

    # Build summary line
    parts = [
        f"#{packet_count}",
        f"[{tag}]",
        f"from={sender}({from_id})",
        f"to={to}({to_id})",
        f"port={portnum}",
    ]
    if rx_snr is not None:
        parts.append(f"SNR={rx_snr}")
    if rx_rssi is not None:
        parts.append(f"RSSI={rx_rssi}")
    if hop_limit is not None:
        parts.append(f"hopLimit={hop_limit}")
    if hop_start is not None:
        parts.append(f"hopStart={hop_start}")

    # Payload preview
    payload = decoded.get("payload")
    if payload:
        parts.append(f"payload={len(payload)}B")

    # Text message shortcut
    text = decoded.get("text")
    if text:
        parts.append(f'text="{text}"')

    print(f"  PKT {' | '.join(parts)}")
    print(f"      stats: total={packet_count} local={local_count} remote={remote_count}")


def onConnection(interface, topic=pub.AUTO_TOPIC):
    """Called when connection is established."""
    global my_node_num
    my_node_num = interface.myInfo.my_node_num
    logger.info(f"Connected! my_node_num={my_node_num}")
    logger.info(f"Long name: {interface.getLongName()}")
    logger.info(f"Short name: {interface.getShortName()}")
    nodes = interface.nodes
    if nodes:
        logger.info(f"Known nodes: {len(nodes)}")


def onDisconnect(interface, topic=pub.AUTO_TOPIC):
    """Called when connection is lost."""
    logger.warning("Connection lost!")


# ── Main ─────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Meshtastic RX Diagnostic")
    parser.add_argument("--port", default=None, help="Serial port (default: auto-detect)")
    parser.add_argument("--debug", action="store_true", help="Enable SDK debug logging (very verbose)")
    args = parser.parse_args()

    # Enable SDK debug logging if requested
    if args.debug:
        logging.getLogger("meshtastic").setLevel(logging.DEBUG)
        logging.getLogger("meshtastic.mesh_interface").setLevel(logging.DEBUG)
        logging.getLogger("meshtastic.stream_interface").setLevel(logging.DEBUG)
        logging.getLogger("meshtastic.serial_interface").setLevel(logging.DEBUG)
        logger.info("SDK debug logging ENABLED (very verbose)")
    else:
        logging.getLogger("meshtastic").setLevel(logging.WARNING)
        logger.info("SDK debug logging OFF (use --debug to enable)")

    # Subscribe BEFORE creating interface (mirrors CLI line 1405 → 1162)
    pub.subscribe(onReceive, "meshtastic.receive")
    pub.subscribe(onConnection, "meshtastic.connection.established")
    pub.subscribe(onDisconnect, "meshtastic.connection.lost")
    logger.info("Subscribed to meshtastic.receive (parent topic)")

    # Create interface (mirrors CLI line 1438)
    import meshtastic.serial_interface
    logger.info(f"Opening SerialInterface(devPath={args.port})...")
    try:
        iface = meshtastic.serial_interface.SerialInterface(devPath=args.port)
    except Exception as e:
        logger.error(f"Failed to open serial interface: {e}")
        sys.exit(1)

    port = iface.devPath
    logger.info(f"Interface open on {port}")
    logger.info("Listening for packets... (Ctrl+C to stop)")
    logger.info("Send a text message from another node to test remote RX.")
    print()
    print("=" * 70)
    print("  WAITING FOR PACKETS — send something from another node")
    print("=" * 70)
    print()

    # Keep alive (mirrors CLI line 1499)
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print()
        logger.info(f"Stopping. Total packets: {packet_count} (local={local_count}, remote={remote_count})")
        iface.close()


if __name__ == "__main__":
    main()
