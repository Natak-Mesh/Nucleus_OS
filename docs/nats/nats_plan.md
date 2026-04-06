# Nucleus Messaging System — Architectural Plan

## 1. Goal

Build a standalone messaging system that lets nodes send and receive messages (text, position, alerts, status) across whatever transport is available — Wi-Fi or LoRa. The user sends a message. The system figures out how to deliver it. The transport is invisible.

Messages use a compact protobuf format that can be optionally converted to CoT for ATAK interop, but CoT is not the native format.

---

## 2. Architecture Overview

Two components per node. That's it.

| Component | What It Is | What It Does |
| :--- | :--- | :--- |
| **nats-server** | Pre-built Go binary | Core Clustering pub/sub over Wi-Fi. No JetStream. |
| **Nucleus Messenger** | Single Python daemon | Bridges NATS ↔ Meshtastic. Handles heartbeats, node table, store-and-forward, dedup, transport selection. Exposes API for the web UI. |

### Why This Shape

- **Wi-Fi (IP)** already works — babeld routes, 802.11s meshes. NATS Core Clustering adds reliable TCP-based pub/sub across all Wi-Fi nodes without multicast storm risk (see Section 7).
- **LoRa (Meshtastic)** already works — multi-hop flooding mesh, broadcast to all nodes, ≤233 byte payload. Keeps mesh resilience that RNode/Reticulum can't provide (GROUP destinations are single-hop only).
- **The Messenger daemon** is the only custom code. It bridges the two transports, maintains the node table, and exposes everything to the web UI.

### What We Removed (and Why)

| Removed | Reason |
| :--- | :--- |
| JetStream | Uses RAFT. RAFT needs quorum. Quorum is incompatible with dynamic MANET membership. |
| KV Store (node-map bucket) | Was built on JetStream. Replaced by in-memory dict in the daemon. |
| Separate Node Map service | Folded into the Messenger daemon. One process does everything. |
| Dual heartbeat services | Folded into the Messenger daemon. |
| Reticulum as a transport | VHF is rare/optional. Can be added later without architectural changes. |

---

## 3. Transport Layers

| Layer | Medium | Protocol | Role |
| :--- | :--- | :--- | :--- |
| **Primary** | 802.11s Wi-Fi | NATS Core Clustering (TCP) | High-speed messaging between all IP-reachable nodes |
| **Secondary** | LoRa | Meshtastic (Serial API) | Multi-hop flooding mesh for when Wi-Fi is unavailable |
| **Tertiary** | VHF / HF (future) | Reticulum | Extreme-range backup. Not in initial implementation. |

---

## 4. Message Format

### 4.1 Design Constraint: 233-Byte Ceiling

Meshtastic `DATA_PAYLOAD_LEN = 233` bytes. All messages must serialize to fit this so they can travel over any transport without modification.

### 4.2 NucleusMessage (Protobuf)

The same serialized protobuf is the packet on every transport. Fields:

| Field | Type | Purpose |
| :--- | :--- | :--- |
| `message_id` | uint32 | Global dedup ID, unique per message |
| `type` | enum | TEXT, POSITION, ALERT, STATUS, HEARTBEAT, COMMAND |
| `sender_id` | uint32 | Node identifier (maps to callsign/UID) |
| `timestamp` | uint32 | Unix epoch seconds |
| `latitude` | sint32 | Scaled: lat × 1e7 |
| `longitude` | sint32 | Scaled: lon × 1e7 |
| `payload` | bytes | Free-form content |

Estimated sizes: chat message ~45-65 bytes, PLI ~25-30 bytes, alert with text ~55-75 bytes. All well within 233 bytes.

### 4.3 Design Principles

- **One format, all transports.** No transport-specific wrappers.
- **Protobuf, not text.** Binary encoding. No XML or JSON on the wire.
- **CoT-convertible, not CoT-native.** A separate converter module can map fields to CoT when desired.
- **Schema evolution.** Protobuf allows adding fields without breaking older nodes.
- **Position is optional.** Zero-value lat/lon costs 1 byte each via varint.
- **Dedup is built in.** `message_id` is part of every message on every transport.

### 4.4 Fragmentation

Standard messages must fit in a single frame (≤233 bytes). Larger data is Wi-Fi only. No fragmentation over LoRa.

---

## 5. NATS Core Clustering (Wi-Fi Backbone)

### 5.1 What It Does

NATS Core Clustering is a gossip-based full mesh that transparently routes pub/sub messages between connected servers over TCP.

Key properties (verified from official NATS documentation):

- **Any number of nodes.** No quorum, no consensus, no RAFT. 1 node, 2 nodes, 50 nodes — all work.
- **Gossip discovery.** Configure a few seed IPs. When a server connects to a seed, it discovers all other servers via gossip. Full mesh forms automatically.
- **Self-routes ignored.** A node can list its own IP in the seed list safely.
- **One-hop forwarding.** Messages from a client are forwarded to adjacent servers. Messages from a route are delivered to local clients only. **This prevents forwarding storms.**
- **Self-healing.** Nodes reconnect automatically when routes come back.

### 5.2 What We Are NOT Using

- **JetStream** — Requires RAFT/quorum. Incompatible with dynamic MANET node counts.
- **Leaf nodes** — Hub-spoke topology. We have no hub.
- **Accounts/auth** — All nodes are trusted peers on the mesh.

### 5.3 NATS Subjects

| Subject | Purpose | Transport |
| :--- | :--- | :--- |
| `nucleus.msg` | All application messages (text, alerts, commands) | NATS only |
| `nucleus.heartbeat` | Identity heartbeats from all nodes | NATS only |

When a LoRa message arrives, the Messenger daemon publishes it to the local NATS bus. NATS clustering then forwards it to all Wi-Fi peers. This is the gateway behavior — nodes with both radios bridge between transports.

---

## 6. The Messenger Daemon

Single Python process per node. Connects to `nats://localhost:4222` using the async `nats-py` client. Also connects to the Meshtastic radio via Serial API (reusing existing `MeshtasticManager`).

### 6.1 Transport Selection (Outbound)

When a message needs to be sent:

1. **Check babeld** — is there a Wi-Fi route to the destination IP? If yes → publish via NATS. Clustering handles delivery.
2. **No IP route** → serialize protobuf to ≤233 bytes, send via Meshtastic Serial API (broadcast `0xFFFFFFFF` or direct to Meshtastic ID if known).
3. **Both available** → send on both. Dedup on the receiving end handles duplicates.
4. **Neither available** → queue in the local store-and-forward buffer.

### 6.2 Inbound Processing

The daemon monitors both NATS subscriptions and Meshtastic serial simultaneously.

When a message arrives from any source:
1. Deserialize protobuf, extract `message_id`
2. Check against the seen-list. If duplicate → discard.
3. If new → add to seen-list, deliver to local application layer (web UI, API)
4. If arrived on LoRa → also publish to local NATS bus (gateway bridging to Wi-Fi peers)
5. If arrived on NATS → do NOT re-send to Meshtastic (prevents cross-interface loops)

### 6.3 Store-and-Forward

In-memory Python queue with TTL (configurable, default 1 hour).

When the daemon can't deliver on any transport, messages go into the queue. A background task periodically checks babeld routes and Meshtastic NodeDB. When a route to the destination appears, queued messages are drained and sent. Messages exceeding TTL are discarded.

No JetStream. No disk writes. Just a deque with timestamps.

### 6.4 Deduplication (Seen-List)

In-memory set of recently seen `message_id` values with a sliding TTL window (e.g., 10 minutes). Prevents the same message from being processed twice when it arrives via multiple transports or is relayed through the mesh.

---

## 7. Storm Prevention

Three mechanisms working together:

| Risk | Mechanism | How It Works |
| :--- | :--- | :--- |
| NATS forwarding loops | NATS one-hop rule | Messages from a route are delivered to local clients only, never re-forwarded to other routes. Built into the NATS protocol. |
| Cross-interface loops (LoRa → NATS → LoRa) | Directional rule in the daemon | Messages arriving on NATS are never re-sent to Meshtastic. Messages arriving on LoRa are published to NATS (for Wi-Fi peers) but marked as seen (won't be re-sent to LoRa). |
| Duplicate delivery | `message_id` seen-list | Same message arriving on multiple transports is deduplicated before application delivery. |

---

## 8. Node Discovery & Identity

### 8.1 The Node Table

In-memory Python dict in the Messenger daemon. Each entry maps a node to all known addresses:

| Field | Description |
| :--- | :--- |
| `sender_id` | Nucleus node number (matches protobuf field) |
| `name` | Human-readable node name |
| `ip` | Wi-Fi mesh IP (for babeld/NATS) |
| `meshtastic_id` | Meshtastic device ID (for LoRa) |
| `last_seen` | Unix timestamp of last contact on any transport |
| `mapping_source` | How this entry was discovered |

Entries may be incomplete. A node discovered only via LoRa may not have an IP yet. The daemon works with whatever addresses are available.

Entries have a TTL (default 5 minutes). If no heartbeat refreshes an entry, it is aged out — the node is considered gone.

### 8.2 How the Node Table Gets Populated

Three sources, in order of authority:

**Wi-Fi Heartbeats (primary — most complete)**
- Sent every 30 seconds on NATS subject `nucleus.heartbeat`
- Contains all identity fields: sender_id, name, IP, Meshtastic ID
- NATS clustering delivers to all Wi-Fi-connected nodes transparently
- `mapping_source = "wifi_heartbeat"`

**LoRa Heartbeats (fallback — for nodes not on Wi-Fi)**
- Sent every 5 minutes via Meshtastic broadcast (`0xFFFFFFFF`, portnum `PRIVATE_APP` = 256)
- 22-byte binary packet: sender_id (2 bytes) + IP (4 bytes) + reserved (16 bytes)
- Sender's Meshtastic ID is implicit — extracted from `MeshPacket.from` at the transport layer
- `mapping_source = "lora_heartbeat"`

**Passive Correlation (bootstrap / last resort)**
- At startup and periodically as a background task
- Reads babeld neighbor table → IP peers
- Reads Meshtastic NodeDB → LoRa peers with names, SNR, hop count
- Produces partial entries. Never overwrites heartbeat-sourced entries.
- `mapping_source = "passive"`

### 8.3 Own Identity (At Startup)

The daemon reads its own identity from:
- `MESH_IP` from `/etc/nucleus/mesh.conf` → IP and sender_id (last octet)
- Meshtastic serial interface → Meshtastic ID and node name
- Publishes own entry immediately on startup

---

## 9. Unified Status API & Web Page

### 9.1 API Endpoint: `GET /api/node-map`

Reads all entries from the node table. Enriches each with live reachability data:

**Wi-Fi reachability:** Is the node's IP in babeld's neighbor list? If yes, include babel cost and WiFi signal average.

**LoRa reachability:** Is the node's Meshtastic ID in the NodeDB with a recent `lastHeard`? If yes, include SNR and hop count.

Response includes: all node entries with reachability flags, signal quality metrics, mapping source, and last-seen timestamps. Also includes self-identification for the responding node.

### 9.2 Web Page

Table showing all known nodes. Auto-refreshes every 5 seconds.

Columns: Node name/ID, IP, Wi-Fi status (reachable/unreachable + signal quality), LoRa status (reachable/unreachable + SNR + hops), mapping source, last seen.

Green/red indicators for transport reachability. "???" for name when only passive discovery has occurred.

---

## 10. Installation

### Per-Node Requirements

**nats-server** — Single Go binary, no dependencies.
- Source: `github.com/nats-io/nats-server/releases`
- Asset: `nats-server-vX.X.X-linux-arm64.tar.gz`
- Install to `/usr/local/bin/nats-server`

**nats CLI** — For testing and debugging.
- Source: `github.com/nats-io/natscli/releases`
- Asset: `nats-X.X.X-linux-arm64.tar.gz`
- Install to `/usr/local/bin/nats`

**Python packages:**
- `nats-py` — async NATS client
- `protobuf` — protobuf runtime
- `protoc` — protobuf compiler (apt: `protobuf-compiler`)

### Config Generation

Add NATS config generation to `config_generation.sh`. Reads `MESH_IP` and `OPENDHT_BOOTSTRAP_IPS` from `mesh.conf`. Generates `/etc/nucleus/nats-server.conf` with:
- `server_name` derived from MESH_IP last octet
- `cluster.name` = `natak-mesh` (same on all nodes)
- `cluster.routes` from known neighbor IPs (same source as OPENDHT bootstrap)
- Client listen on `0.0.0.0:4222`, cluster listen on `0.0.0.0:6222`
- **No `jetstream` block**

### Systemd Service

`nats-server.service` — starts after `mesh-start.service`, runs with `Restart=always`.

### Firewall

Open ports 4222/tcp (client) and 6222/tcp (cluster) on the mesh interface.

---

## 11. Implementation Phases

### Phase 1 — NATS Over Wi-Fi

Get Core Clustering working across the mesh.
- Install `nats-server` and `nats` CLI on each node
- Add config generation to `config_generation.sh`
- Create systemd service
- Open firewall ports
- Verify: `nats sub test` on Node A, `nats pub test hello` on Node B → message arrives

### Phase 2 — Messenger Daemon (Core)

Build the single daemon that ties everything together.
- Async Python daemon connecting to local NATS + Meshtastic serial
- NucleusMessage protobuf definition and compilation
- NATS pub/sub for `nucleus.msg` and `nucleus.heartbeat`
- Meshtastic send/receive via Serial API
- Transport selection logic (babeld route check)
- Deduplication via seen-list
- Directional gateway bridging (LoRa → NATS, not NATS → LoRa)

### Phase 3 — Discovery & Node Table

Make nodes discover each other automatically.
- Wi-Fi heartbeat loop (30s interval on NATS)
- LoRa heartbeat loop (5min interval on Meshtastic broadcast)
- Passive correlation from babeld + Meshtastic NodeDB
- Node table with TTL-based aging
- Own identity reading from mesh.conf + Meshtastic interface

### Phase 4 — API, Web UI & Polish

Expose everything to the user.
- `/api/node-map` endpoint with enriched reachability data
- Unified status web page
- Store-and-forward queue with TTL
- Edge case testing (split-brain, simultaneous multi-interface arrival, node churn)
- Optional: CoT converter module for ATAK bridging

**Phases 1-2 deliver a working messaging system. Phase 3 adds automatic discovery. Phase 4 adds visibility and resilience.**

---

## 12. Known Problems & Mitigations

### Problem: NATS seed routes are static

NATS gossip discovers new nodes, but it needs at least one reachable seed to bootstrap. If the seed IPs in `nats-server.conf` are all unreachable (those nodes are powered off), a new node joining the mesh can't discover the cluster.

**Mitigation:** Use the same IPs already in `OPENDHT_BOOTSTRAP_IPS`. Include multiple seeds. Once a node reaches ANY seed, gossip discovers the rest. Also: nodes already in the cluster can be discovered via gossip even if they aren't listed as seeds. The seed list is just a starting point.

### Problem: babeld route check latency

The daemon checks babeld to decide transport. If babeld hasn't converged yet (route is stale or delayed), the daemon may choose the wrong transport.

**Mitigation:** If a NATS publish fails or times out, fall back to Meshtastic. Babeld convergence is fast (typically seconds) on the 802.11s mesh. This is an edge case during topology changes.

### Problem: Meshtastic channel saturation

LoRa heartbeats every 5 minutes from all nodes, plus application messages, could saturate the LoRa channel with many nodes (20+).

**Mitigation:** Heartbeat interval is configurable. With many nodes on Wi-Fi, LoRa heartbeats are less critical (Wi-Fi heartbeats carry the same data). Consider adaptive intervals — increase LoRa heartbeat frequency only when Wi-Fi coverage is sparse.

### Problem: Store-and-forward is volatile

The in-memory queue is lost if the daemon restarts. Messages queued for offline nodes disappear.

**Mitigation:** Acceptable tradeoff. The alternative (JetStream) introduces RAFT/quorum problems that are worse in a MANET. If persistence becomes critical in the future, a simple append-to-tmpfs file could provide crash survival without SD card wear.

### Problem: Node table is local only

Each node builds its own view of the network from heartbeats it receives. Two nodes may have different views if they have different connectivity.

**Mitigation:** This is by design. In a MANET, no single node has a global view. Each node's table reflects what IT can reach. This is the same model Meshtastic and babeld use — local state, not global consensus.

### Problem: Even number of NATS servers

NATS Core Clustering works with any count, but if you later want JetStream (which we removed), you need odd numbers. This is a non-issue NOW but worth noting.

**Mitigation:** Don't add JetStream. If persistence is ever needed, use a local-only solution (tmpfs file, SQLite in /tmp) instead of distributed consensus.

---

## 13. Dependencies

**New:**
- `nats-server` — Pre-built Go binary
- `nats` CLI — Pre-built Go binary
- `nats-py` — Python async NATS client
- `protobuf` + `protoc` — Protobuf runtime and compiler

**Already on the node:**
- `meshtastic` Python package + MeshtasticManager
- Flask web app infrastructure
- `babeld` (route table queries)
- smcroute (multicast forwarding — not used by this system but coexists)

---

## Appendix: Design Decisions Log

| Decision | Alternatives Considered | Why This Choice |
| :--- | :--- | :--- |
| NATS Core over UDP multicast for Wi-Fi | UDP multicast is zero-infrastructure but 802.11s floods multicast frames at lowest data rate, causing airtime saturation. NATS uses TCP unicast between servers — higher data rate, acknowledged, no flooding. | NATS avoids 802.11s multicast storm problem |
| Meshtastic over Reticulum for LoRa | Reticulum GROUP destinations are single-hop only — transport nodes don't forward them. Meshtastic provides multi-hop flooding mesh for broadcast, which is the entire point of adding LoRa. | Meshtastic provides multi-hop broadcast that Reticulum cannot |
| No JetStream | JetStream Meta Group uses RAFT, which requires quorum (½ + 1). In a MANET with dynamic membership, quorum shifts unpredictably. R=1 streams work standalone but Meta Group state becomes unreliable as nodes join/leave. | RAFT is fundamentally incompatible with dynamic MANET membership |
| In-memory node table over KV store | KV store required JetStream. In-memory dict with TTL is simpler, has no quorum dependency, and the data is ephemeral by nature (heartbeats rebuild it continuously). | Simplicity, no RAFT dependency |
| In-memory store-and-forward over JetStream streams | Same RAFT concern. An in-memory deque with TTL provides the same functionality for the store-and-forward use case without distributed consensus. Volatile on restart, but acceptable. | Simplicity, no RAFT dependency |
