# Hybrid MANET Architectural Specification: Unified Messaging Framework

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
* **Payload (232 Bytes):** Application data in protobuf format (see 3.2).

### 3.2 Nucleus Message Format (Protobuf)
The system uses **Protocol Buffers (protobuf)** as its wire format. Protobuf provides compact binary encoding with schema evolution support (adding fields without breaking old nodes), language-agnostic codegen, and varint encoding that is already highly compact. Messages are designed to fit in a single Meshtastic packet.

Messages **can be converted to CoT (Cursor on Target) format if needed** for optional ATAK bridging, but CoT is not the native format.

```protobuf
syntax = "proto3";
package nucleus;

enum MessageType {
    TEXT = 0;
    POSITION = 1;
    ALERT = 2;
    STATUS = 3;
    HEARTBEAT = 4;
    COMMAND = 5;
}

message NucleusMessage {
    MessageType type = 1;       // What kind of message
    uint32 sender_id = 2;       // Node identifier (maps to callsign/UID)
    uint32 timestamp = 3;       // Unix epoch (seconds)
    sint32 latitude = 4;        // Scaled: lat × 1e7 (signed int32)
    sint32 longitude = 5;       // Scaled: lon × 1e7 (signed int32)
    bytes payload = 6;          // Free-form content (text, telemetry, etc.)
}
```

**Estimated sizes:**
* Chat message ("hello team"): ~40-60 bytes
* PLI (position report): ~20-25 bytes
* Alert with text: ~50-70 bytes

All well within the 232-byte application data ceiling.

**Design Principles:**
* **CoT-convertible, not CoT-native.** A separate converter module can map these fields to CoT protobuf/XML for TAK Server or ATAK when desired. This is an option, not a requirement.
* **Protobuf, not text.** Binary encoding keeps messages compact for the 237-byte LoRa MTU. No XML, no JSON on the wire.
* **Schema evolution.** Protobuf allows adding new fields in future versions without breaking older nodes — critical for a mesh where nodes may run different firmware versions.
* **Position is optional.** If `type` indicates a text-only message, lat/lon default to zero and cost only 1 byte each (varint zero).

### 3.3 Fragmentation Policy
* **Single Frame:** Standard messages must fit within the 237-byte limit.
* **Multi-Frame:** Larger data is handled by the NATS layer over Wi-Fi only. Large-scale fragmentation over LoRa/VHF is discouraged to prevent channel saturation.

---

## 4. Messaging & Routing: NATS

NATS serves as the messaging backbone of each node, operating entirely locally without internet requirements. There are two distinct NATS mechanisms at work, and it is important to understand they are separate capabilities:

### 4.1 NATS Core Clustering (Real-Time Routing)

**Reference:** [NATS Clustering Docs](https://github.com/nats-io/nats.docs/blob/master/running-a-nats-service/configuration/clustering/README.md)

NATS Core Clustering is a **gossip-based full mesh** protocol that transparently routes pub/sub messages between connected servers. Key properties:

* **Works with any number of nodes** — 1, 2, 5, 50. No quorum, no consensus, no Raft.
* **Gossip-based discovery** — You configure a few seed server IPs (e.g., known mesh neighbors). When a server connects to a seed, it discovers all other servers in the cluster via gossip. The full mesh forms automatically.
* **Self-routes are ignored** — A node can safely list its own IP in the seed list; NATS skips it.
* **Transparent pub/sub routing** — A subscriber on Node A automatically receives messages published on Node B. The application doesn't need to know which node a message came from.
* **One-hop forwarding** — Messages received from a client are forwarded to adjacent servers. Messages received from a route are delivered to local clients only (no infinite forwarding loops).
* **Dynamic self-healing** — When a node goes offline, clients reconnect to other known servers. When a node comes back, routes re-establish automatically.

This is what provides the "logical brain" for real-time messaging across the Wi-Fi mesh. When nodes are connected via 802.11s/babeld, NATS Core Clustering handles message delivery transparently.

### 4.2 JetStream R=1 Memory (Local Message Queue)

**Reference:** [JetStream Config Docs](https://github.com/nats-io/nats.docs/blob/master/running-a-nats-service/configuration/jetstream-config/resource_management.md), [JetStream Concepts](https://github.com/nats-io/nats.docs/blob/master/nats-concepts/jetstream/README.md)

JetStream is NATS' built-in persistence engine. It supports memory and file storage, with replication factors of R=1 (no replication), R=3, or R=5.

**We use JetStream with R=1 and memory storage only.** This means:

* **No Raft, no quorum** — R=1 is single-node, no consensus needed. Works with any number of nodes.
* **No SD card writes** — Memory storage (`max_mem`) keeps everything in RAM. Zero disk I/O from NATS.
* **Local-only persistence** — Each node's JetStream is independent. Streams are not replicated between nodes.
* **Used as the Gatekeeper's outbox** — When a message can't be delivered (no Wi-Fi route, destination unreachable), the Gatekeeper stores it in a local JetStream stream. When the route comes back, the Gatekeeper drains the queue and delivers the messages.

**What we are NOT using:**
* ~~JetStream clustering (Raft/quorum)~~ — Requires odd numbers of nodes, minimum 3 for R=3. Incompatible with arbitrary node counts in a MANET.
* ~~JetStream file storage~~ — Would cause SD card wear on the Raspberry Pi.
* ~~Leaf nodes~~ — Leaf nodes are a hub-spoke topology (they connect *to* a cluster). We have no hub in a MANET; all nodes are peers.

### 4.3 How the Two Work Together

| Scenario | Mechanism | What Happens |
| :--- | :--- | :--- |
| Nodes A and B are connected via Wi-Fi | NATS Core Cluster | Publish on Node A is transparently delivered to subscribers on Node B. Fire-and-forget. |
| Node B goes offline | JetStream R=1 Memory | Gatekeeper on Node A detects no route (via babeld). Stores outbound message in local JetStream stream as "outbox." |
| Node B comes back online | NATS Core Cluster + Gatekeeper | Cluster re-forms via gossip. Gatekeeper drains the outbox, publishes queued messages. Node B receives them. |
| Node B unreachable via Wi-Fi, reachable via LoRa | Gatekeeper → Meshtastic | Gatekeeper serializes to protobuf (≤237 bytes), injects via Meshtastic Serial API. |
| Node B unreachable via Wi-Fi and LoRa | Gatekeeper → Reticulum | Gatekeeper hands packet to Reticulum for VHF broadcast/routing. |

---

## 5. The Gatekeeper Module
The Gatekeeper is the local routing intelligence that bridges NATS subjects to physical radio interfaces.

### 5.1 Outbound Selection Logic (Priority Pathing)
1. **NATS/IP:** If `babeld` confirms a Wi-Fi route to the destination, the message stays in the NATS IP stack. Core clustering handles delivery transparently.
2. **Meshtastic:** If IP is unavailable, the Gatekeeper checks the Meshtastic NodeDB for the peer. If found, it serializes the protobuf to ≤237 bytes and injects via the Serial API.
3. **Reticulum:** If both fail, the Gatekeeper hands the packet to Reticulum for VHF broadcast/routing.

### 5.2 Inbound Deduplication
The Gatekeeper monitors all interfaces (Serial, IP, VHF) simultaneously. When a packet arrives:
* The 4-byte **Global ID** is extracted.
* The ID is compared against a local "Seen-List" cache.
* If the ID is a duplicate (e.g., arrived via LoRa after Wi-Fi), it is discarded. If new, it is passed to the local NATS bus for application use.

### 5.3 Store-and-Forward (Outbox Pattern)
When the Gatekeeper cannot deliver a message on any transport:
* The message is published to a local JetStream stream (`outbox.<destination_id>`) with a retention policy of `limits`, `max_age` set to a configurable TTL (e.g., 1 hour).
* A background task periodically checks babeld routes and Meshtastic NodeDB.
* When a route to the destination appears, the Gatekeeper consumes from the outbox stream and delivers the queued messages.
* Messages that exceed `max_age` are automatically discarded by JetStream — no manual cleanup needed.

---

## 6. Identity & Discovery
The system maps multiple hardware-specific addresses to a single human-readable Node Identity.

### 6.1 The Mapping Table
A localized registry linking Node Names to:
* **Meshtastic ID:** (e.g., `!a1b2c3d4`)
* **Reticulum Hash:** (e.g., `80cf...f21a`)
* **IP Address:** (e.g., `10.20.1.x`)

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

## 8. NATS Server Configuration

### 8.1 Per-Node Config

Each node runs a single `nats-server` instance with clustering and JetStream enabled. The config is derived from values already present in `/etc/nucleus/mesh.conf`.

```
# /etc/nucleus/nats-server.conf
#
# Generated from mesh.conf values:
#   server_name derived from MESH_IP (e.g., 10.20.1.12 → nucleus-12)
#   cluster routes derived from known neighbor IPs (same source as OPENDHT_BOOTSTRAP_IPS)

server_name: nucleus-12
listen: 0.0.0.0:4222

jetstream {
    max_mem: 64M
    store_dir: /tmp/nats-jetstream
    domain: nucleus
}

cluster {
    name: natak-mesh
    listen: 0.0.0.0:6222

    routes: [
        # Seed routes — known mesh neighbor IPs
        # Gossip discovers the rest automatically
        # Self-routes are ignored by NATS
        nats://10.20.1.11:6222
        nats://10.20.1.12:6222
    ]
}
```

**Configuration notes:**
* `server_name` — Must be unique per node. Derived from `MESH_IP` in `mesh.conf`. Required for JetStream.
* `cluster.name` — Must be identical on all nodes (`natak-mesh`).
* `cluster.routes` — Seed IPs for initial cluster discovery. These can be the same IPs already configured in `OPENDHT_BOOTSTRAP_IPS` in `mesh.conf`. Gossip discovers all other nodes automatically. A node's own IP can safely appear in the list (NATS ignores self-routes).
* `jetstream.max_mem` — RAM budget for JetStream streams. 64M is generous for message queuing. Adjustable based on available RAM.
* `jetstream.store_dir` — Required by NATS even with memory storage (used for internal metadata). Set to `/tmp/` to avoid SD card writes.
* `jetstream.domain` — Same domain across all nodes (`nucleus`). Required when JetStream is enabled in a cluster.

### 8.2 Installation

Three components are needed per node. No apt packages — NATS distributes pre-built binaries.

**nats-server:**
The NATS server binary (JetStream is built-in, not a separate package). Single Go binary, no dependencies.
* **Source:** https://github.com/nats-io/nats-server/releases
* **Asset:** `nats-server-vX.X.X-linux-arm64.tar.gz`
* **Install:** Extract → move to `/usr/local/bin/nats-server`

**nats CLI:**
Command-line tool for testing, managing streams, pub/sub, and cluster administration.
* **Source:** https://github.com/nats-io/natscli/releases
* **Asset:** `nats-X.X.X-linux-arm64.tar.gz`
* **Install:** Extract → move to `/usr/local/bin/nats`

**nats-py (Python Client):**
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
- Generate `nats-server.conf` from `mesh.conf` values (add to `config_generation.sh`)
- Configure JetStream with memory storage (R=1, `max_mem: 64M`)
- Verify NATS core clustering forms over the 802.11s/babeld IP layer
- Verify gossip discovery works (only seed IPs configured, other nodes discovered automatically)
- Basic pub/sub working across the mesh (`nats pub` / `nats sub` on different nodes)
- Create a systemd service for `nats-server`

### Phase 2 — Meshtastic Bridge (Gatekeeper v1)
Bridge NATS messaging to LoRa when Wi-Fi is unavailable.
- Gatekeeper daemon that subscribes to NATS subjects
- Outbound: when babeld shows no IP route for a destination, serialize protobuf to ≤237 bytes and inject via Meshtastic Serial API
- Inbound: listen on Meshtastic serial, deserialize protobuf, publish to local NATS bus
- Global ID deduplication (seen-list cache)
- Store-and-forward outbox using local JetStream memory streams
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

---

## 10. Dependencies

**Protobuf (wire format):**
- `protobuf` — Google's Python protobuf runtime for serialization/deserialization
- `protoc` — Protobuf compiler to generate Python bindings from `.proto` file (`apt install protobuf-compiler`)

**NATS (messaging backbone):**
- `nats-server` — Pre-built Go binary (see Section 8.2)
- `nats` CLI — Pre-built Go binary (see Section 8.2)
- `nats-py` — Async Python NATS client (`pip install nats-py`)

**CoT/ATAK interop (optional):**
- `takproto` — Handles conversion between NucleusMessage fields and CoT XML/TAK protobuf for ATAK and TAK Server

**Already on the node:**
- `meshtastic` Python package + MeshtasticManager (LoRa transport)
- Flask web app infrastructure (web UI)
- `babeld` (route table queries for transport selection)
- `reticulum` / `rnsd` (VHF transport)

---

## Appendix A: NATS Documentation References

All architectural decisions in this document are grounded in the official NATS documentation:

| Topic | Source |
| :--- | :--- |
| Core Clustering (gossip, full mesh, any node count) | [clustering/README.md](https://github.com/nats-io/nats.docs/blob/master/running-a-nats-service/configuration/clustering/README.md) |
| Cluster Configuration (routes, seed servers, cluster name) | [clustering/cluster_config.md](https://github.com/nats-io/nats.docs/blob/master/running-a-nats-service/configuration/clustering/cluster_config.md) |
| JetStream Concepts (memory/file storage, R=1/3/5, streams, consumers) | [nats-concepts/jetstream/README.md](https://github.com/nats-io/nats.docs/blob/master/nats-concepts/jetstream/README.md) |
| JetStream Clustering (Raft, quorum, why we don't use R>1) | [clustering/jetstream_clustering/README.md](https://github.com/nats-io/nats.docs/blob/master/running-a-nats-service/configuration/clustering/jetstream_clustering/README.md) |
| JetStream Configuration (max_mem, store_dir, domain) | [jetstream-config/resource_management.md](https://github.com/nats-io/nats.docs/blob/master/running-a-nats-service/configuration/jetstream-config/resource_management.md) |
| Leaf Nodes (hub-spoke topology — evaluated and rejected for MANET) | [leafnodes/README.md](https://github.com/nats-io/nats.docs/blob/master/running-a-nats-service/configuration/leafnodes/README.md) |
