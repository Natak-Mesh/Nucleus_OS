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

### 3.1 Design Constraint: 233-Byte Ceiling

**Reference:** Meshtastic protobuf `Constants.DATA_PAYLOAD_LEN = 233` (from `mesh.proto`)

The Meshtastic `Data.payload` field accepts a maximum of **233 bytes**. This is the application-level payload limit after Meshtastic handles its own framing, encryption, and LoRa modulation. All Nucleus messages are sized to fit within this ceiling.

**The same protobuf format is used on ALL transports** — Wi-Fi (NATS), LoRa (Meshtastic), and VHF (Reticulum). The format is sized for the smallest pipe (LoRa at 233 bytes) so that any message can travel over any transport without modification. There is no separate wrapper or header; the serialized protobuf IS the packet.

### 3.2 Nucleus Message Format (Protobuf)
The system uses **Protocol Buffers (protobuf)** as its wire format. Protobuf provides compact binary encoding with schema evolution support (adding fields without breaking old nodes), language-agnostic codegen, and varint encoding that is already highly compact. Messages are designed to fit in a single Meshtastic packet (≤233 bytes serialized).

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
    uint32 message_id = 1;      // Global dedup ID (unique per message, used across all transports)
    MessageType type = 2;       // What kind of message
    uint32 sender_id = 3;       // Node identifier (maps to callsign/UID)
    uint32 timestamp = 4;       // Unix epoch (seconds)
    sint32 latitude = 5;        // Scaled: lat × 1e7 (signed int32)
    sint32 longitude = 6;       // Scaled: lon × 1e7 (signed int32)
    bytes payload = 7;          // Free-form content (text, telemetry, etc.)
}
```

**Estimated sizes:**
* Chat message ("hello team"): ~45-65 bytes
* PLI (position report): ~25-30 bytes
* Alert with text: ~55-75 bytes

All well within the 233-byte ceiling.

**Design Principles:**
* **One format, all transports.** The serialized NucleusMessage protobuf is the packet on every transport — Wi-Fi, LoRa, and VHF. No transport-specific wrappers or headers.
* **Sized for the bottleneck.** All messages must serialize to ≤233 bytes so they can traverse any transport, including LoRa.
* **CoT-convertible, not CoT-native.** A separate converter module can map these fields to CoT protobuf/XML for TAK Server or ATAK when desired. This is an option, not a requirement.
* **Protobuf, not text.** Binary encoding keeps messages compact. No XML, no JSON on the wire.
* **Schema evolution.** Protobuf allows adding new fields in future versions without breaking older nodes — critical for a mesh where nodes may run different firmware versions.
* **Position is optional.** If `type` indicates a text-only message, lat/lon default to zero and cost only 1 byte each (varint zero).
* **Deduplication is built in.** The `message_id` field is part of every message on every transport, enabling cross-interface deduplication without external framing.

### 3.3 Fragmentation Policy
* **Single Frame:** Standard messages must serialize to ≤233 bytes (the Meshtastic `DATA_PAYLOAD_LEN`).
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

**Note on JetStream Meta Group:** When JetStream is enabled in a NATS cluster, all JetStream-enabled servers automatically form a "Meta Group" that uses Raft for JetStream API operations (creating/deleting streams and consumers). This Meta Group requires quorum (½ cluster + 1). However, this is a non-issue for our use case: each node creates its outbox streams at startup when it is standalone (quorum = 1 = itself). Once created, R=1 streams continue to accept messages regardless of Meta Group quorum state. If a Wi-Fi peer goes down, there is no Wi-Fi peer to message anyway — the Gatekeeper bridges to LoRa/Reticulum instead.

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
| Node B unreachable via Wi-Fi, reachable via LoRa | Gatekeeper → Meshtastic | Gatekeeper serializes to protobuf (≤233 bytes), injects via Meshtastic Serial API. |
| Node B unreachable via Wi-Fi and LoRa | Gatekeeper → Reticulum | Gatekeeper hands packet to Reticulum for VHF broadcast/routing. |

---

## 5. The Gatekeeper Module
The Gatekeeper is the local routing intelligence that bridges NATS subjects to physical radio interfaces.

### 5.1 Outbound Selection Logic (Priority Pathing)
When a message needs to be sent, the Gatekeeper looks up the destination in the local **Node Map** (see Section 6) to retrieve its IP address, Meshtastic ID, and Reticulum hash. It then selects the transport based on reachability:

1. **NATS/IP:** Query `babeld` — is there a Wi-Fi route to the destination's IP? If yes, publish via NATS. Core clustering handles delivery transparently.
2. **Meshtastic:** If no IP route exists, use the destination's Meshtastic ID from the Node Map and serialize the protobuf to ≤233 bytes, inject via the Serial API.
3. **Reticulum:** If both IP and LoRa are unavailable, use the destination's Reticulum hash from the Node Map and hand the packet to Reticulum for VHF broadcast/routing.
4. **Outbox:** If no transport can reach the destination, queue the message in the local JetStream outbox (see Section 5.3).

The Gatekeeper never queries external systems (Meshtastic NodeDB, Reticulum path tables) at send time for addressing. All addresses come from the Node Map. External systems are only queried for **reachability** (babeld route check) or as **inputs to populate** the Node Map (see Section 6.2).

### 5.2 Inbound Deduplication
The Gatekeeper monitors all interfaces (Serial, IP, VHF) simultaneously. When a packet arrives:
* The protobuf is deserialized and the `message_id` field is extracted.
* The ID is compared against a local "Seen-List" cache.
* If the ID is a duplicate (e.g., arrived via LoRa after Wi-Fi), it is discarded. If new, it is passed to the local NATS bus for application use.

### 5.3 Store-and-Forward (Outbox Pattern)
When the Gatekeeper cannot deliver a message on any transport:
* The message is published to a local JetStream stream (`outbox.<destination_id>`) with a retention policy of `limits`, `max_age` set to a configurable TTL (e.g., 1 hour).
* A background task periodically checks babeld routes and Meshtastic NodeDB.
* When a route to the destination appears, the Gatekeeper consumes from the outbox stream and delivers the queued messages.
* Messages that exceed `max_age` are automatically discarded by JetStream — no manual cleanup needed.

---

## 6. Identity & Discovery: The Node Map

Each node on the mesh has three different addresses — one per transport. The **Node Map** is the local registry that ties them together into a single identity. It is the **single source of truth** for the Gatekeeper when addressing messages (see Section 5.1).

### 6.1 The Node Map (NATS KV Store)

The Node Map is implemented as a **JetStream Key/Value bucket** (`node-map`) on each node. Since JetStream R=1 memory is already running locally, KV is available with zero additional components — it's a built-in JetStream feature.

Each entry maps a node identifier to all known addresses for that node:

| Field | Example | Description |
| :--- | :--- | :--- |
| `sender_id` | `11` | Nucleus node number (matches protobuf `sender_id`) |
| `name` | `"Alpha"` | Human-readable node name |
| `ip` | `"10.20.1.11"` | Wi-Fi mesh IP (for NATS/babeld) |
| `meshtastic_id` | `"!a1b2c3d4"` | Meshtastic device ID (for LoRa) |
| `reticulum_hash` | `"80cf...f21a"` | Reticulum destination hash (for VHF) |
| `last_seen` | `1709800000` | Unix timestamp of last contact on any transport |

Entries may be incomplete — a node discovered only via LoRa heartbeat will have `meshtastic_id` and `ip` but may not yet have a `reticulum_hash`. The Gatekeeper works with whatever addresses are available.

### 6.2 How the Node Map Gets Populated

Three input sources feed the Node Map, in order of completeness and authority:

**1. Wi-Fi Heartbeats (Primary — most complete)**

| | |
| :--- | :--- |
| **Transport** | NATS publish to `mesh.heartbeat` subject |
| **Frequency** | Every 30-60 seconds |
| **Content** | Full identity: sender_id, name, IP, Meshtastic ID, Reticulum hash |
| **Rationale** | Bandwidth is cheap on Wi-Fi. This is the authoritative source. |

When a node receives a heartbeat via NATS, it updates (or creates) the corresponding entry in its local KV store. This is the most complete source because it carries all three addresses.

**2. LoRa Heartbeats (Fallback — for nodes never seen on Wi-Fi)**

| | |
| :--- | :--- |
| **Transport** | Meshtastic Serial API (22-byte packet) |
| **Frequency** | Every 5 minutes |
| **Content** | Node number (1-2 bytes) + IP address (4 bytes) + Reticulum hash (16 bytes) |
| **Rationale** | Preserves scarce LoRa airtime (~0.5s per transmission). |

The sender's **Meshtastic ID is implicit** — it is already known to the receiver because the packet arrived via the Meshtastic transport. This eliminates 4 bytes of redundancy from the packet. The receiving node can build a complete mapping entry from a single LoRa heartbeat: it knows the Meshtastic ID (from the transport), the IP (from the packet), and the Reticulum hash (from the packet).

**3. Passive Correlation (Bootstrap / last resort)**

| | |
| :--- | :--- |
| **Transport** | Local system queries (no transmissions) |
| **Frequency** | At startup, and periodically as background task |
| **Sources** | babeld route table → IP peers, Meshtastic NodeDB → LoRa peers, Reticulum path table → VHF peers |
| **Rationale** | Zero airtime cost. Populates partial entries before heartbeats arrive. |

At startup or when heartbeats haven't been received yet, the Gatekeeper reads existing data from local system tables. These may produce incomplete entries (e.g., knows the IP from babeld but not the Meshtastic ID). Entries are merged — if a partial entry already exists from passive correlation and a heartbeat arrives later with more fields, the entry is updated, not replaced.

### 6.3 Priority and Merging

The Node Map merges data from all sources. If a field is provided by multiple sources, the most recent value wins. Wi-Fi heartbeats are the most authoritative because they carry the complete identity published by the node itself. LoRa heartbeats fill in gaps for nodes not reachable via Wi-Fi. Passive correlation provides a bootstrap until heartbeats arrive.

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
- Outbound: when babeld shows no IP route for a destination, serialize protobuf to ≤233 bytes and inject via Meshtastic Serial API
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

---

## Appendix B: Stage 1 Implementation Specification — Node Map + Unified Status

This appendix provides the exact implementation details for the first deliverable: getting NATS running on the mesh and using it to power a unified connection status page that shows both Wi-Fi (babeld) and LoRa (Meshtastic) peers.

### B.1 NATS Infrastructure Setup

**Binaries to install on each node:**

| Binary | Source | Install Path |
| :--- | :--- | :--- |
| `nats-server` | [nats-io/nats-server releases](https://github.com/nats-io/nats-server/releases) — asset: `nats-server-vX.X.X-linux-arm64.tar.gz` | `/usr/local/bin/nats-server` |
| `nats` CLI | [nats-io/natscli releases](https://github.com/nats-io/natscli/releases) — asset: `nats-X.X.X-linux-arm64.tar.gz` | `/usr/local/bin/nats` |
| `nats-py` | `pip install --break-system-packages nats-py` | System Python |

**Config generation** — add to `/opt/nucleus/bin/config_generation.sh`:
1. Read `MESH_IP` from `/etc/nucleus/mesh.conf` (e.g., `10.20.1.12`)
2. Extract node number from last octet (e.g., `12`)
3. Read `OPENDHT_BOOTSTRAP_IPS` for seed routes (e.g., `10.20.1.11,10.20.1.12`)
4. Write `/etc/nucleus/nats-server.conf`:

```
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
        nats://10.20.1.11:6222
        nats://10.20.1.12:6222
    ]
}
```

**Systemd service** — `/etc/systemd/system/nats-server.service`:
```ini
[Unit]
Description=NATS Server (Nucleus Mesh)
After=mesh-start.service
Wants=mesh-start.service

[Service]
ExecStart=/usr/local/bin/nats-server -c /etc/nucleus/nats-server.conf
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

**UFW** — open ports 4222/tcp and 6222/tcp on wlan1.

**Verification test:** On Node A: `nats sub test`. On Node B: `nats pub test hello`. Node A receives the message, confirming NATS clustering works over the 802.11s/babeld mesh.

---

### B.2 Node Map Population Service

A Python service running as a background thread inside the existing Flask app (`app.py`). Connects to `nats://localhost:4222` using `nats-py` (async client).

#### B.2.1 At Startup — Read Own Identity

The service reads this node's own identities from two sources:

**From `/etc/nucleus/mesh.conf`:**
- `MESH_IP` → e.g., `10.20.1.12` — this node's Wi-Fi mesh IP
- Last octet of `MESH_IP` → `sender_id` (e.g., `12`)

**From Meshtastic serial interface** (via existing `MeshtasticManager`):
- `self.interface.getMyNodeInfo()["num"]` → this node's Meshtastic node number (uint32)
- Convert node number to Meshtastic ID string: `"!" + hex(num)[2:]` → e.g., `"!a1b2c3d4"`
- `self.interface.getLongName()` → this node's human-readable name (e.g., `"Alpha"`)

**From Reticulum** (deferred — not in Stage 1):
- `reticulum_hash` set to `null` for now

This gives the service the complete identity for the local node:
```json
{
    "sender_id": 12,
    "name": "Alpha",
    "ip": "10.20.1.12",
    "meshtastic_id": "!a1b2c3d4",
    "reticulum_hash": null
}
```

#### B.2.2 Create KV Bucket

At startup, create (or open if exists) the JetStream KV bucket `node-map`:
- Storage: memory
- Replicas: 1
- TTL / max_age: 300 seconds (entries expire if no heartbeat refreshes them — indicates the node is gone)

Write this node's own entry immediately.

#### B.2.3 Wi-Fi Heartbeat — Publish

Every 30 seconds, publish to NATS subject `mesh.heartbeat.<sender_id>`.

**Payload** (JSON — only travels over Wi-Fi where bandwidth is cheap):
```json
{
    "sender_id": 12,
    "name": "Alpha",
    "ip": "10.20.1.12",
    "meshtastic_id": "!a1b2c3d4",
    "reticulum_hash": null,
    "timestamp": 1709800030
}
```

This contains **all five identity fields**: `sender_id`, `name`, `ip`, `meshtastic_id`, and `reticulum_hash`. Every field that this node knows about itself is included explicitly. Because NATS Core Clustering is active, this publish is transparently delivered to all other NATS-connected nodes on the Wi-Fi mesh.

#### B.2.4 Wi-Fi Heartbeat — Subscribe

Subscribe to `mesh.heartbeat.>` (wildcard — receives heartbeats from all nodes).

When a heartbeat is received:
1. Parse the JSON payload
2. Use `sender_id` (as a string) as the KV key
3. Write/update the entry in the local `node-map` KV bucket with all fields from the heartbeat
4. Set `mapping_source` to `"wifi_heartbeat"`

#### B.2.5 LoRa Heartbeat — Transmit

Every 5 minutes, send a 22-byte binary packet via Meshtastic Serial API to broadcast address `0xFFFFFFFF`, using a custom portnum (`PRIVATE_APP` = 256):

| Offset | Size | Field | Value |
|:-------|:-----|:------|:------|
| 0 | 2 bytes | `sender_id` | `uint16` big-endian, e.g., `12` |
| 2 | 4 bytes | IP address | 4 raw octets, e.g., `[10, 20, 1, 12]` |
| 6 | 16 bytes | Reticulum hash | 16 raw bytes (all zeros if not available) |

Total: 22 bytes.

The sender's **Meshtastic ID** is NOT in the packet. It is implicit — every Meshtastic `MeshPacket` carries the sender's node number in the `MeshPacket.from` field at the transport layer. The receiver extracts it there.

#### B.2.6 LoRa Heartbeat — Receive

Subscribe to incoming Meshtastic data packets on custom portnum 256. When a 22-byte packet arrives:

1. Parse binary fields:
   - Bytes 0-1: `sender_id` (`uint16` big-endian)
   - Bytes 2-5: `ip` (4 octets → format as `"X.X.X.X"`)
   - Bytes 6-21: `reticulum_hash` (16 bytes → hex string, or `null` if all zeros)
2. Extract sender's Meshtastic ID from `MeshPacket.from` (uint32 from the transport layer)
3. Convert `MeshPacket.from` to Meshtastic ID string: `"!" + hex(from_num)[2:]`
4. Write/update the entry in the local `node-map` KV bucket:
   - `sender_id`: from packet bytes 0-1
   - `ip`: from packet bytes 2-5
   - `meshtastic_id`: from `MeshPacket.from` (implicit, extracted from transport)
   - `reticulum_hash`: from packet bytes 6-21 (or `null` if zeros)
   - `last_seen`: current timestamp
   - `mapping_source`: `"lora_heartbeat"`

This produces a **complete mapping** from a single LoRa heartbeat: `sender_id` (explicit), `ip` (explicit), `meshtastic_id` (implicit from transport), `reticulum_hash` (explicit).

#### B.2.7 Passive Correlation — Background Task

Every 30 seconds, as a fallback for nodes that haven't sent any heartbeat yet:

**babeld** → query the babeld monitoring socket at `[::1]:33123` (reuse existing `query_babeld()` from `app.py`) → parse neighbor list → for each peer IP not already in the KV store, create a partial entry with only `ip` and `last_seen` populated. Set `mapping_source` to `"passive"`.

**Meshtastic NodeDB** → read `self.interface.nodes` (the radio's local node database, a dict keyed by node ID string) → for each node entry:
- Extract `node["user"]["id"]` → Meshtastic ID (e.g., `"!a1b2c3d4"`)
- Extract `node["user"]["longName"]` → name
- Extract `node["num"]` → node number
- Extract `node.get("snr")` → SNR
- Extract `node.get("lastHeard")` → last heard timestamp
- Extract `node.get("hopsAway")` → hop count

For any Meshtastic node not already in the KV store with a heartbeat-sourced entry, create a partial entry with `meshtastic_id`, `name`, and `last_seen` populated. Set `mapping_source` to `"passive"`.

Passive entries are **never overwritten by other passive entries**, but ARE overwritten when a Wi-Fi or LoRa heartbeat arrives for that node (heartbeats always take priority).

---

### B.3 Unified Connection Status API

**Endpoint:** `GET /api/node-map`

Reads all entries from the `node-map` KV bucket. For each entry, enriches with live reachability data:

**Wi-Fi reachability check:** Is `entry.ip` present in the current babeld neighbor list? (Reuse `parse_babeld_dump()` and `query_babeld()` from `app.py`.) If yes, also pull:
- Babel cost from the neighbor entry
- WiFi signal average from `get_wifi_station_stats()` (correlated via MAC address, same method as existing `get_mesh_nodes()`)

**LoRa reachability check:** Is `entry.meshtastic_id` present in the Meshtastic NodeDB (`self.interface.nodes`)? If yes, and `lastHeard` is within the last 15 minutes, the node is LoRa-reachable. Pull:
- `snr` from the node entry
- `hopsAway` from the node entry
- `lastHeard` from the node entry

**Response format:**
```json
{
    "nodes": [
        {
            "sender_id": 11,
            "name": "Alpha",
            "ip": "10.20.1.11",
            "meshtastic_id": "!a1b2c3d4",
            "reticulum_hash": null,
            "wifi_reachable": true,
            "wifi_cost": 256,
            "wifi_signal_avg": -52,
            "lora_reachable": true,
            "lora_snr": 10.5,
            "lora_hops_away": 0,
            "lora_last_heard": 1709800000,
            "last_seen": 1709800030,
            "mapping_source": "wifi_heartbeat"
        }
    ],
    "self": {
        "sender_id": 12,
        "name": "Bravo",
        "ip": "10.20.1.12",
        "meshtastic_id": "!e5f6g7h8"
    },
    "timestamp": "2026-03-07T13:00:00"
}
```

`mapping_source` values: `"wifi_heartbeat"` (authoritative, all fields present), `"lora_heartbeat"` (complete, derived from LoRa), `"passive"` (partial, from babeld/NodeDB only).

---

### B.4 Unified Connection Status Web Page

A new page or updated dashboard that renders the `/api/node-map` response as a table. Auto-refreshes every 5 seconds (matching the existing monitor page pattern).

| Node | IP | Wi-Fi | LoRa | Source | Last Seen |
|:-----|:---|:------|:-----|:-------|:----------|
| Alpha (11) | 10.20.1.11 | ✅ cost 256, -52 dBm | ✅ SNR 10.5, 0 hops | wifi_heartbeat | 30s ago |
| Charlie (13) | 10.20.1.13 | ❌ | ✅ SNR 5.2, 1 hop | lora_heartbeat | 2m ago |
| ??? (14) | 10.20.1.14 | ✅ cost 350 | ❌ | passive | 10s ago |

- Green checkmark: transport is reachable
- Red X: transport is not reachable or no address known
- "Source" column shows how the identity mapping was established
- "???" for name indicates a passive entry where the node name is not yet known
