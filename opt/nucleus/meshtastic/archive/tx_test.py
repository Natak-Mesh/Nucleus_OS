#!/usr/bin/env python3
"""
TX Test — Send a synthetic PLI as ATAK_FORWARDER (portnum 257) over LoRa.

Run this on the OPPOSING node while the receiving node runs cot_bridge_rx.py.

Pipeline: CoT XML → CotXmlParser → TakCompressor.compress → sendData(portNum=257)

Usage:
    python3 tx_test.py [--port /dev/ttyACM0]
"""

import argparse
import sys
import time
from datetime import datetime, timezone, timedelta


def main():
    parser = argparse.ArgumentParser(description="Send synthetic PLI as ATAK_FORWARDER")
    parser.add_argument("--port", default=None, help="Serial port (default: auto-detect)")
    args = parser.parse_args()

    # ── Build synthetic PLI CoT XML ──────────────────────────────
    now = datetime.now(timezone.utc)
    stale = now + timedelta(minutes=5)
    time_str = now.strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"
    stale_str = stale.strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"

    cot_xml = f"""<?xml version="1.0" encoding="UTF-8"?>
<event version="2.0" uid="ANDROID-tx-test-node" type="a-f-G-U-C" how="m-g"
       time="{time_str}" start="{time_str}" stale="{stale_str}">
  <point lat="37.4154" lon="-77.6350" hae="50.0" ce="10.0" le="10.0"/>
  <detail>
    <contact callsign="TX-TEST" endpoint="*:-1:stcp"/>
    <__group name="Cyan" role="Team Member"/>
    <status battery="95"/>
    <takv device="RAK4631" platform="meshtastic" os="nrf52" version="2.7"/>
    <track speed="0.0" course="0.0"/>
    <precisionlocation geopointsrc="GPS" altsrc="GPS"/>
  </detail>
</event>"""

    print(f"=== TX Test: Sending synthetic PLI as ATAK_FORWARDER ===")
    print(f"CoT XML ({len(cot_xml)} bytes):")
    print(cot_xml)
    print()

    # ── TX Pipeline: XML → TAKPacketV2 → compress → wire bytes ──
    from meshtastic_tak.cot_xml_parser import CotXmlParser
    from meshtastic_tak.tak_compressor import TakCompressor

    cot_parser = CotXmlParser()
    compressor = TakCompressor()

    tak_packet = cot_parser.parse(cot_xml)
    print(f"TAKPacketV2 parsed OK")

    wire_bytes = compressor.compress(tak_packet)
    print(f"Compressed: {len(wire_bytes)} bytes (LoRa MTU limit: 237)")
    print(f"Wire payload (hex): {wire_bytes.hex()}")
    print()

    # ── Send via Meshtastic radio ────────────────────────────────
    import meshtastic.serial_interface

    print(f"Opening serial interface{' on ' + args.port if args.port else ' (auto-detect)'}...")
    iface = meshtastic.serial_interface.SerialInterface(devPath=args.port)
    print(f"Connected to {iface.devPath}, node: {iface.getLongName()}")

    print(f"Sending {len(wire_bytes)}B as ATAK_FORWARDER (portnum 257)...")
    result = iface.sendData(
        wire_bytes,
        portNum=257,  # ATAK_FORWARDER
        wantAck=True,
    )
    packet_id = result.id if result else None
    print(f"Sent! packet_id={packet_id}")

    # Wait for ack
    print("Waiting 5s for ack...")
    time.sleep(5)

    iface.close()
    print("Done. Radio released.")


if __name__ == "__main__":
    main()
