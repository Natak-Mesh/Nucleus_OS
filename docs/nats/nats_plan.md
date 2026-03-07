 Hybrid MANET Architectural Specification: Unified Messaging Framework

## 1. System Overview

### 1.1 Goal
Build a **communication application** that lets users send and receive messages seamlessly across whatever interfaces are available — Wi-Fi, LoRa, or VHF. The user sends a message. The system figures out how to deliver it. The transport is invisible.

### 1.2 Architecture
This framework defines a decentralized, multi-transport communication system for Raspberry Pi-based MANET nodes. It utilizes 802.11s Wi-Fi, Meshtastic LoRa, and Reticulum VHF interfaces to provide a "Single Interface Point" for messaging. The architecture prioritizes high-bandwidth Wi-Fi while ensuring seamless failover to long-range radio when nodes are dispersed.

---

## 2. Core Transport Layers
The system operates across three distinct physical and logical layers, managed by a centralized "Gatekeeper" module on each node.

| Layer | Physical Medium | Protocol | Role |
| :--- | :--- | :--- | :--- |
| **Primary** | 802.11s Wi-Fi | NATS (IP-based) | High-speed sync, bulk data, and real-time messaging. |
| **Secondary** | LoRa (A/E Key) | Meshtastic (Serial API) | Medium-range mesh for telemetry and critical alerts. |
| **Tertiary** | VHF / HF Radio | Reticulum (RNS) | Extreme-range, high-latency backup for disconnected nodes. |

---

## 3. The Unified Packet Specification
To ensure interoperability and zero-waste efficiency, the system utilizes a "Universal Packet" design optimized for the 237-byte MTU of Meshtastic LoRa.

### 3.1 Packet Structure (237 Bytes Total)
* **Global Message ID (4 Bytes):** A unique `uint32` hash generated at the source. Used for cross-interface deduplication.
* **Metadata Header (1 Byte):** Defines payload type (Text, Telemetry, Command) and priority flags.
* **Payload (232 Bytes):** Application data in the Nucleus Message Format (see 3.2).

### 3.2 Nucleus Message Format
The system uses its own dedicated message format — not CoT, not protobuf. A compact binary format designed to fit in a single Meshtastic packet. Fields are chosen so that messages **can be converted to CoT (Cursor on Target) format if needed** for optional ATAK bridging, but CoT is not the native format.

| Field | Size | CoT Equivalent | Description |
| :--- | :--- | :--- | :--- |
| Message Type | 1 byte | `type` | What kind of message (text, position, alert, status, etc.) |
| Sender ID | 2 bytes | `uid` | Node identifier (maps to callsign/UID) |
| Timestamp | 4 bytes | `time`/`start`/`stale` | Unix epoch (seconds) |
| Latitude | 4 bytes | `point.lat` | Signed int32, scaled (lat × 1e7) |
| Longitude | 4 bytes | `point.lon` | Signed int32, scaled (lon × 1e7) |
| Payload Data | 0-217 bytes | `detail` | Free-form content (text, telemetry, etc.) |

**Total fixed header: 15 bytes.** Leaves 217 bytes for payload within the 232-byte application data area.

**Design Principles:**
* **CoT-convertible, not CoT-native.** A separate converter module can map these fields to CoT protobuf/XML for TAK Server or ATAK when desired. This is an option, not a requirement.
* **Binary, not text.** Every byte matters at 237-byte MTU. No XML, no JSON on the wire.
* **Position is optional.** If Message Type indicates a text-only message, lat/lon can be zeroed or omitted to reclaim payload space.

### 3.3 Fragmentation Policy
* **Single Frame:** Standard messages must fit within the 237-byte limit.
* **Multi-Frame:** Larger data is handled by the NATS JetStream layer over Wi-Fi only. Large-scale fragmentation over LoRa/VHF is discouraged to prevent channel saturation.

---

## 4. Messaging & Persistence: NATS JetStream
NATS serves as the "logical brain" of the node, operating entirely locally without internet requirements.

* **Decentralized Clustering:** Nodes form a full-mesh NATS cluster over the 802.11s IP layer (routed via babeld). There is no central server.
* **Leaf Node Logic:** Each node runs a NATS Leaf Node, allowing it to function autonomously when isolated and sync instantly upon reconnection.
* **Eventual Consistency:** JetStream stores outbound messages on the local SD card. If a peer is offline, NATS queues the data and "flushes" it the moment a route is established.

---

## 5. The Gatekeeper Module
The Gatekeeper is the local routing intelligence that bridges NATS subjects to physical radio interfaces.

### 5.1 Outbound Selection Logic (Priority Pathing)
1. **NATS/IP:** If `babeld` confirms a Wi-Fi route, the message stays in the NATS IP stack.
2. **Meshtastic:** If IP is unavailable, the Gatekeeper checks the Meshtastic NodeDB for the peer. If found, it injects the 237-byte packet via the Serial API.
3. **Reticulum:** If both fail, the Gatekeeper hands the packet to Reticulum for VHF broadcast/routing.

### 5.2 Inbound Deduplication
The Gatekeeper monitors all interfaces (Serial, IP, VHF) simultaneously. When a packet arrives:
* The 4-byte **Global ID** is extracted.
* The ID is compared against a local "Seen-List" cache.
* If the ID is a duplicate (e.g., arrived via LoRa after Wi-Fi), it is discarded. If new, it is passed to the local NATS bus for application use.

---

## 6. Identity & Discovery
The system maps multiple hardware-specific addresses to a single human-readable Node Identity.

### 6.1 The Mapping Table
A localized registry linking Node Names to:
* **Meshtastic ID:** (e.g., `!a1b2c3d4`)
* **Reticulum Hash:** (e.g., `80cf...f21a`)
* **IP Address:** (e.g., `10.0.0.x`)

### 6.2 Heartbeat Strategy (Per-Transport)
Heartbeat frequency and method are tuned per transport to respect bandwidth constraints:

| Transport | Method | Frequency | Rationale |
| :--- | :--- | :--- | :--- |
| **Wi-Fi (NATS)** | Publish full mapping to `mesh.heartbeat` subject | Every 30-60 seconds | Bandwidth is cheap on IP. |
| **LoRa (Meshtastic)** | Lightweight 22-byte packet via Serial API | Every 5 minutes | Preserves scarce LoRa airtime. |
| **VHF (Reticulum)** | Passive — read existing announce/path tables | N/A | Zero additional transmissions. |

### 6.3 LoRa Heartbeat Packet (22 Bytes)
The LoRa heartbeat is intentionally minimal to preserve airtime (~0.5s air time per transmission):

| Field | Size | Description |
| :--- | :--- | :--- |
| Node Number | 1-2 bytes | Local node identifier |
| IP Address | 4 bytes | Node's mesh IP (e.g., `10.20.1.12`) |
| Reticulum Hash | 16 bytes | Truncated destination hash |

**Note:** The sender's Meshtastic ID is implicit — it is already known to the receiver because the packet arrived via the Meshtastic transport. This eliminates 4 bytes of redundancy.

### 6.4 Passive Correlation
For transports without a dedicated heartbeat (Reticulum), the Gatekeeper builds its mapping table by reading existing data sources:
* **babeld route table** → IP peers
* **Meshtastic NodeDB** → LoRa peers
* **Reticulum path table** → VHF/HF peers

The Wi-Fi heartbeat distributes the authoritative mapping. LoRa heartbeats provide a fallback for nodes that have never had Wi-Fi contact. Passive correlation is a last resort.

---

## 7. Broadcast & Multicast Operations
* **Broadcast:** Handled by mapping a generic NATS subject (e.g., `mesh.all`) to the native broadcast addresses of Meshtastic (`0xFFFFFFFF`) and Reticulum.
* **Multicast:** Utilizes shared NATS subjects and dedicated Meshtastic Secondary Channels.
* **Storm Control:** The Global ID prevents a broadcast received on one interface from being re-broadcast back out of the same node on a different interface.

---

## 8. Installation Requirements
Three components are needed per node. No apt packages — NATS distributes pre-built binaries.

### 8.1 nats-server
The NATS server binary (JetStream is built-in, not a separate package). Single Go binary, no dependencies.
* **Source:** https://github.com/nats-io/nats-server/releases
* **Asset:** `nats-server-vX.X.X-linux-arm64.tar.gz`
* **Install:** Extract → move to `/usr/local/bin/nats-server`

### 8.2 nats CLI
Command-line tool for testing, managing streams, pub/sub, and cluster administration.
* **Source:** https://github.com/nats-io/natscli/releases
* **Asset:** `nats-X.X.X-linux-arm64.tar.gz`
* **Install:** Extract → move to `/usr/local/bin/nats`

### 8.3 nats-py (Python Client)
Async Python NATS client with JetStream support. Used by the Gatekeeper module.
```bash
pip install --break-system-packages nats-py
```
*(Consistent with existing system Python packages: reticulum, flask, meshtastic.)*

---

## 9. Implementation Phases

### Phase 1 — NATS over Wi-Fi (Foundation)
Get the messaging backbone working across the mesh over IP.
- Install `nats-server` on each node
- Configure JetStream with local SD card storage
- Set up NATS clustering over the 802.11s/babeld IP layer
- Leaf node configuration so nodes function autonomously when isolated
- Basic pub/sub working across the mesh
- Validate store-and-forward: node goes offline, comes back, messages sync

### Phase 2 — Meshtastic Bridge (Gatekeeper v1)
Bridge NATS messaging to LoRa when Wi-Fi is unavailable.
- Gatekeeper daemon that subscribes to NATS subjects
- Outbound: when IP route is down for a destination, serialize to 237-byte packet and inject via Meshtastic Serial API
- Inbound: listen on Meshtastic serial, deserialize, publish to local NATS bus
- Global ID deduplication (seen-list cache)
- Identity mapping table (node name → Meshtastic ID + IP)
- LoRa heartbeat (22-byte packet every 5 minutes)

### Phase 3 — Reticulum Bridge (Gatekeeper v2)
Add VHF/HF as the third transport fallback.
- Add RNS as tertiary transport in the Gatekeeper
- Map NATS subjects to Reticulum destinations
- Handle announce/discovery model differences
- Extend identity mapping to include Reticulum hashes
- Passive correlation from Reticulum path tables

### Phase 4 — Discovery, Broadcast & Multicast
Polish and harden the full system.
- Wi-Fi heartbeat on `mesh.heartbeat` NATS subject
- Auto-populate mapping tables from heartbeats
- Broadcast/multicast subject mapping (`mesh.all` → Meshtastic `0xFFFFFFFF`, Reticulum broadcast)
- Storm control validation
- Edge case testing (simultaneous multi-interface arrivals, split-brain recovery)

**Note:** Phases 1 and 2 deliver a functional system. Phases 3 and 4 add depth and resilience.
