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

