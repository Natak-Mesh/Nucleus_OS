# ATAK CoT Bridge — Planning Document

## Definitions

### TAK Protocol V1

**TAK Protocol V1** is a binary wire protocol that serializes **Cursor on Target (CoT)** data using **Google Protocol Buffers (Protobuf)**. It replaces legacy XML with a compact format optimized for bandwidth-constrained tactical networks. Each packet consists of a **3-byte header** (Magic Byte `0xbf` and 2-byte payload length) followed by a Protobuf-encoded payload.

### TAKPacketV2

**TAKPacketV2** is a Meshtastic-optimized binary format for **Cursor on Target (CoT)** data over low-bandwidth LoRa networks.

* **Compression:** Uses **zstd** with pre-trained static dictionaries (ID `0x00` for ground/chat; `0x01` for aircraft).
* **Serialization:** Decomposes CoT XML into a specialized Meshtastic Protobuf schema (`TAKPacket`).
* **Structure:** A 1-byte **Flags** header (indicating Dictionary ID) followed by the compressed payload.
* **Optimization:** Reduces standard PLI packets to **~95 bytes** to reliably fit within the **237-byte LoRa MTU**.

## Node Architecture

- **RPi4 MANET nodes** (this system runs on one)
- **wlan0** — AP for ATAK end-user devices, bridged to **br-lan**
- **wlan1** — 802.11s IP mesh connecting nodes to each other
- **USB Meshtastic radio** — LoRa radio for long-range parallel network

## Existing CoT Flow (IP Mesh)

```
ATAK device → multicast CoT (TAK Protocol V1) → wlan0 → br-lan
  → smcroute/babeld → wlan1 (802.11s mesh) → other nodes → other ATAK devices
```

## Libraries

### takproto (`~/meshtastic_repos/takproto`)

Handles **TAK Protocol V1** encoding/decoding. Python module (MIT license).

- `parse_proto(bytes)` — parses TAK Protocol V1 (auto-detects mesh `0xbf` header, stream, or raw XML) → `TakMessage` Python object
- `xml2proto(xml)` — converts CoT XML → TAK Protocol V1 protobuf bytes (mesh or stream format)
- `msg2proto(TakMessage)` — serializes TakMessage → TAK Protocol V1 wire bytes

### TAKPacket SDK (`~/meshtastic_repos/TAKPacket-SDK/python`)

Handles **TAKPacketV2** conversion and compression. Python module (GPL-3.0).

- `CotXmlParser.parse(xml)` — CoT XML → TAKPacketV2 protobuf
- `TakCompressor.compress(packet)` — TAKPacketV2 → compressed wire payload (≤237B LoRa MTU)
- `TakCompressor.decompress(wire)` — compressed wire payload → TAKPacketV2 protobuf
- `CotXmlBuilder.build(packet)` — TAKPacketV2 → CoT XML string

**CoT XML is the interchange format between the two libraries.**

### Required Glue: `takmessage_to_xml()`

takproto has no built-in TakMessage → CoT XML function. We need to write a small `takmessage_to_xml()` that reconstructs CoT XML from TakMessage fields. The logic is the exact reverse of takproto's `xml2message()`:

**TakMessage.cotEvent fields → XML mapping:**
- **Event envelope** (`<event>`): type, uid, how, sendTime/startTime/staleTime (convert ms-since-epoch → ISO 8601)
- **Point** (`<point>`): lat, lon, hae, ce, le
- **Detail typed fields:**
  - `<contact>` ← detail.contact (callsign, endpoint)
  - `<__group>` ← detail.group (name, role)
  - `<status>` ← detail.status (battery)
  - `<track>` ← detail.track (speed, course)
  - `<takv>` ← detail.takv (device, platform, os, version)
  - `<precisionlocation>` ← detail.precisionLocation (geopointsrc, altsrc)
- **Catch-all** ← `detail.xmlDetail` — raw XML string injected verbatim into `<detail>` for any elements that don't fit the typed fields

## Bridge Goal

Create a parallel long-range network by bridging CoT traffic to Meshtastic LoRa alongside the existing IP mesh.

### Outbound (TX)

1. Intercept/copy multicast TAK Protocol V1 messages from **br-lan**
2. **takproto** `parse_proto()` → TakMessage → reconstruct CoT XML
3. **TAKPacket SDK** `CotXmlParser.parse(xml)` → TAKPacketV2
4. **TAKPacket SDK** `TakCompressor.compress()` → compressed wire payload
5. Send via **Meshtastic CLI** out the LoRa radio

### Inbound (RX)

1. Receive TAKPacketV2 from other nodes' Meshtastic radios
2. **TAKPacket SDK** `TakCompressor.decompress()` → TAKPacketV2
3. **TAKPacket SDK** `CotXmlBuilder.build()` → CoT XML string
4. **takproto** `xml2proto(xml)` → TAK Protocol V1 mesh bytes
5. Inject as multicast CoT on **br-lan** for local ATAK devices

## Staged Implementation Plan

Each stage has a concrete verification step. Don't proceed until the current stage passes.

### Stage 0: Install Dependencies

**apt:** `python3-zstandard` (fallback; pip pulls it automatically)

**pip (from Natak forks):**
```bash
pip3 install --break-system-packages "git+https://github.com/Natak-Mesh/takproto.git"
pip3 install --break-system-packages "git+https://github.com/Natak-Mesh/TAKPacket-SDK.git#subdirectory=python"
```

**Verify:**
```bash
python3 -c "
import takproto
from meshtastic_tak.cot_xml_parser import CotXmlParser
from meshtastic_tak.tak_compressor import TakCompressor
from meshtastic_tak.cot_xml_builder import CotXmlBuilder
print('all imports OK')
"
```

### Stage 1: `takmessage_to_xml()` Glue Function

Write the missing TakMessage → CoT XML converter (reverse of takproto's `xml2message()`). Small standalone module.

**Verify:** Round-trip test — known CoT XML → `xml2message()` → `takmessage_to_xml()` → parse result XML, compare key fields (uid, type, lat, lon, callsign, group, etc.)

### Stage 2: TX Pipeline (Offline)

Full outbound conversion chain, no network:
```
TAK Protocol V1 bytes → parse_proto() → takmessage_to_xml()
  → CotXmlParser.parse() → TakCompressor.compress() → wire bytes
```

**Verify:** Feed sample TAK Protocol V1 PLI packet, confirm compressed output ≤ 237 bytes. Decompress the output and verify it round-trips.

### Stage 3: RX Pipeline (Offline)

Full inbound conversion chain, no network:
```
compressed wire bytes → TakCompressor.decompress() → CotXmlBuilder.build()
  → xml2proto() → TAK Protocol V1 mesh bytes
```

**Verify:** Feed the compressed bytes from Stage 2, get TAK Protocol V1 bytes back, parse them with `parse_proto()` and confirm fields match the original.

### Stage 4: Multicast Listener (Live Network)

Listen on `239.2.3.1:6969` (standard TAK SA) on br-lan. Capture and parse real TAK Protocol V1 packets from ATAK devices.

**Verify:** Run with an ATAK device on the AP, see parsed PLI events with callsign, lat/lon, team color logged to console.

### Stage 5: Meshtastic TX (Live Radio)

Connect to meshtastic radio, send compressed TAKPacketV2 via `sendData(data, portNum=257)` (`ATAK_FORWARDER`).

**Verify:** Send a synthetic PLI. Another meshtastic node with ATAK plugin (or TAK Forwarder app) receives and displays it.

### Stage 6: Meshtastic RX (Live Radio)

Subscribe to incoming `ATAK_FORWARDER` (portnum 257) packets from the radio, decompress, convert to TAK Protocol V1, inject as multicast on br-lan.

**Verify:** Another node sends TAK data over LoRa, local ATAK device on our AP sees the position.

### Stage 7: Bridge Service

Combine TX + RX into a single `cot_bridge.py` daemon. Integrate with existing `meshtastic_manager.py`'s serial connection. Add rate limiting and dedup (avoid bridging packets that came FROM LoRa back TO LoRa).

**Verify:** Two nodes, each with ATAK devices — positions flow bidirectionally over LoRa.

## Key Technical Decisions

- **Portnum:** `ATAK_FORWARDER` (257) — interoperable with stock meshtastic ATAK nodes.
- **Multicast group:** `239.2.3.1:6969` — standard TAK SA, already routed by smcroute.
- **CoT XML is the interchange format** between takproto and meshtastic_tak libraries.
- **PLI is the priority** — validate with PLI first. Chat, markers, shapes flow naturally via the libraries.

## Progress Tracker

- [x] Stage 0: Dependencies installed — takproto 3.0.1, meshtastic-tak 0.1.0, zstandard 0.25.0. All imports verified.
- [x] Stage 1: `takmessage_to_xml()` — Code at `opt/nucleus/meshtastic/takmessage_to_xml.py`. Verified with round-trip test: fed the "Eliopoli HQ" PLI from takproto's test suite through `xml2message()` → `takmessage_to_xml()`, then parsed the output XML and compared 17 fields (uid, type, how, lat, lon, callsign, endpoint, group name/role, battery, takv device/platform/version, track speed/course, xmlDetail fragments). All 17 checks passed.
- [x] Stage 2: TX pipeline (offline) — Fed real 310B TAK Protocol V1 mesh bytes through full chain: `parse_proto()` → `takmessage_to_xml()` → `CotXmlParser.parse()` → `TakCompressor.compress()` → 183B compressed (fits 237B LoRa MTU). Decompressed and verified 7 fields (uid, callsign, lat, lon, team, role, battery). All passed.
- [x] Stage 3: RX pipeline (offline) — Fed 183B compressed TAKPacketV2 through full inbound chain: `TakCompressor.decompress()` → `CotXmlBuilder.build()` → `xml2proto()` → 288B TAK Protocol V1 mesh bytes. Parsed back with `parse_proto()` and verified 10 fields (uid, type, callsign, lat, lon, group name/role, battery, takv platform/device). All passed.
- [x] Stage 4: Multicast listener (live network) — Listened on `239.2.3.1:6969`, captured 10 real packets from 2 ATAK devices. Parsed PLIs (callsign=0023, team=Cyan; callsign=McCOY, team=Cyan; both type `a-f-G-U-C`) and shared objects (`a-n-G`, `a-h-G`). All parsed correctly with positions and callsigns via `parse_proto()`.
- [ ] Stage 5: Meshtastic TX (live radio)
- [ ] Stage 6: Meshtastic RX (live radio)
- [ ] Stage 7: Bridge service

