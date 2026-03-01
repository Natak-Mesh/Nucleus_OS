# Centralized Messaging — Nucleus OS

## Overview

A unified messaging system for Nucleus mesh nodes that works across both WiFi mesh and LoRa (Meshtastic). Messages use a compact protobuf format as the source of truth, sized to fit within Meshtastic's ~228 byte packet limit. The same bytes go over either transport. When ATAK/TAK Server interop is needed, the protobuf is expanded into full CoT XML at the edge.

## Design Constraints

- **Meshtastic max payload: ~228 bytes** — this is the hard ceiling that drives the format design
- Same protobuf packet must work over both WiFi (UDP) and LoRa (Meshtastic)
- CoT XML is a presentation format, not the wire format — it's too verbose for LoRa (~500-800 bytes for a simple chat)
- No ATAK dependency — messages display natively in the Nucleus web UI; CoT translation is optional

## Architecture

```
┌──────────────────────────────────────────┐
│            NatakMessage (protobuf)        │
│         ≤228 bytes — source of truth      │
└───────────┬──────────────┬───────────────┘
            │              │
     ┌──────▼──────┐ ┌────▼──────────┐
     │  WiFi Mesh  │ │  LoRa         │
     │  UDP on     │ │  Meshtastic   │
     │  wlan1      │ │  serial/data  │
     └──────┬──────┘ └────┬──────────┘
            │              │
     ┌──────▼──────────────▼───────────┐
     │       Receiving Node            │
     │                                 │
     │  ┌─────────────┐ ┌───────────┐ │
     │  │ Nucleus Web │ │ CoT       │ │
     │  │ UI (native  │ │ Expander  │ │
     │  │ display)    │ │ (optional)│ │
     │  └─────────────┘ └─────┬─────┘ │
     │                        │       │
     │                  ┌─────▼─────┐ │
     │                  │ ATAK /    │ │
     │                  │ TAK Server│ │
     │                  └───────────┘ │
     └─────────────────────────────────┘
```

## Components

### 1. Protobuf Schema (`natak_message.proto`)

Compact binary message format. Uses integer encoding tricks to minimize size:
- Node IDs as short integers (not full string callsigns)
- Timestamps as uint32 epoch seconds
- Lat/lon as sint32 scaled by 1e7 (instead of 8-byte doubles)
- Message type as enum (1 byte)

**Estimated sizes:**
- Chat message ("hello team"): ~40-60 bytes
- PLI (position report): ~20-25 bytes
- Alert with text: ~50-70 bytes

All well within the 228-byte ceiling.

### 2. Transports (same protobuf payload, two delivery methods)

**WiFi Mesh — UDP**
- Send protobuf bytes via UDP socket on wlan1
- Multicast (group chat) or unicast (direct message) to mesh node IPs
- Babeld routing handles multi-hop delivery
- Trivial: `sock.sendto(protobuf_bytes, (target_ip, port))`

**LoRa — Meshtastic**
- Send protobuf bytes as a binary data packet through the existing MeshtasticManager serial interface
- Meshtastic handles LoRa modulation, mesh routing, and retransmission
- Same bytes as WiFi, just a different pipe

### 3. Display Endpoints

**Nucleus Web UI (primary)**
- Chat/message view in the existing Flask web app
- Deserializes protobuf and displays messages directly
- No ATAK required

**CoT Expander (optional, for ATAK interop)**
- Translates NatakMessage protobuf → CoT XML
- Chat → GeoChat CoT event (`b-t-f` type)
- PLI → SA CoT event (`a-f-G-U-C` type)
- Pushes to TAK Server (TCP/TLS) or local ATAK (SA multicast `239.2.3.1:6969`)
- Only activated when ATAK integration is desired

## Transport Selection

**Current approach: User-selectable per message.**

When sending a message, the user (or calling code) picks the transport: **WiFi**, **LoRa**, or **Both**. This keeps things simple during development and testing. Automatic selection logic (e.g., WiFi-preferred with LoRa fallback based on babeld reachability) can be layered on later once real-world usage patterns are understood.

When "Both" is selected, the receiving node deduplicates by message UID — if the same message arrives on WiFi and LoRa, it's delivered once.

## Implementation Phases

1. **Protobuf schema** — define `.proto`, generate Python bindings, validate size targets
2. **WiFi transport** — UDP send/receive on wlan1, prove two nodes can exchange protobuf messages
3. **LoRa transport** — hook into MeshtasticManager, send same protobuf bytes over serial
4. **CoT expander** — protobuf → CoT XML translator for ATAK/TAK Server interop
5. **Web UI** — chat interface in Nucleus web app for native message display

## File Structure

```
/opt/nucleus/messaging/
├── proto/
│   └── natak_message.proto       # Protobuf definition
├── natak_pb2.py                  # Generated Python protobuf module
├── wifi_transport.py             # UDP send/receive on wlan1
├── lora_transport.py             # Meshtastic serial send/receive
├── cot_expander.py               # Protobuf → CoT XML (optional)
├── messaging_api.py              # Flask Blueprint for web UI + REST
└── README.md
```

## Dependencies

**Custom wire format (NatakMessage):**
- `protobuf` — Google's Python protobuf runtime for serialization/deserialization
- `protoc` — protobuf compiler to generate Python bindings from `.proto` file (`apt install protobuf-compiler`)

**CoT/ATAK interop (optional, only when ATAK integration is active):**
- `takproto` — handles conversion between our NatakMessage fields and CoT XML/TAK protobuf for ATAK and TAK Server

**Already on the node:**
- `meshtastic` Python package + MeshtasticManager (LoRa transport)
- Flask web app infrastructure (web UI)
- Python `socket` module (UDP transport — no additional packages needed)

## Progress

- [x] Architecture design agreed
- [x] Transport selection strategy decided (user-selectable per message)
- [ ] Protobuf schema defined
- [ ] WiFi transport implemented
- [ ] LoRa transport implemented
- [ ] CoT expander implemented
- [ ] Web UI integrated
