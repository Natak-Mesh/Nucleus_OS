# Meshtastic Integration — Architecture & Planning

## System Context

### Hardware
- **Radios:** RAK4631 (nRF52840 + SX1262 LoRa) — no WiFi, no Ethernet on the radio itself
- **Compute:** Raspberry Pi 4 — each Pi has a RAK4631 connected via USB serial
- **WiFi Mesh:** 802.11s mesh network between all Pis (same broadcast domain, 10.20.1.x/24)
- **Connection:** Pi controls the radio over serial at 115200 baud using the meshtastic Python library

### Network Topology
Every Nucleus node is a Pi + RAK4631 pair. The Pis form an 802.11s WiFi mesh for high-bandwidth local networking. The RAK4631 radios form an independent LoRa mesh for long-range, low-bandwidth messaging. The two networks are completely separate at the radio level — the Pi is the only bridge point between them.

Standalone Meshtastic radios (phones, field devices without Pis) participate only on the LoRa mesh. They reach the wider system through whichever Pi node hears them first.

---

## Dual-Transport Messaging Architecture

### The Concept
Use both LoRa and WiFi simultaneously for message delivery. LoRa provides range extension — that is the entire reason the radios exist. WiFi provides near-instant delivery between nodes that share the mesh network. Neither transport replaces the other. They run in parallel, and both are always active.

LoRa is long range, slow (seconds per hop), and low bandwidth, but works everywhere. WiFi UDP is short range (limited to the 802.11s mesh), near-instant (roughly 5ms), high bandwidth, and only works between Pis on the WiFi mesh.

### Why Not the Meshtastic Built-In UDP Broadcast?
Meshtastic firmware has a "Network" setting that can broadcast mesh packets over UDP on a local network. This feature only works on devices that have their own IP network connection — ESP32 boards with WiFi, or boards with Ethernet adapters. The RAK4631 is nRF52-based. It has no WiFi and no Ethernet. It cannot use this feature. Instead, the Pi handles the UDP broadcast layer using application-level code, since the Pi is already on the 802.11s WiFi mesh.

### Why Not MQTT?
MQTT was considered as a bridge between the LoRa and WiFi networks but has significant disadvantages for this use case. MQTT requires a broker — a centralized server that all nodes must connect to. This creates a single point of failure: if the broker node goes down, the bridge between transports stops working. It also adds latency (messages must route through the broker) and complexity (broker setup, topic design, subscriptions, authentication).

UDP broadcast requires no infrastructure at all. It is pure peer-to-peer. Every Pi on the broadcast domain hears every broadcast directly. Since all Pis share the same 10.20.1.x broadcast domain via 802.11s, UDP broadcast reaches every peer with no broker, no server, and no coordination.

---

## How It Works

### The MeshtasticManager as Integration Point
The MeshtasticManager class is the central piece. It has two input sources running simultaneously: the Meshtastic serial interface (receiving decoded LoRa packets from the radio) and the UDP listener (receiving broadcasts from other Pis over WiFi). Both inputs feed into the same message log, and the web UI reads from that single log. The web UI does not know or care which transport delivered a given message.

The Meshtastic serial interface is always active. The RAK4631 radio receives LoRa packets and delivers decoded data to the Pi over the serial connection. The meshtastic Python library fires a callback (`_on_text_receive`) every time a text message arrives. This happens regardless of whether the same message already arrived via UDP. The radio has no awareness of the UDP layer and cannot be told to skip a delivery.

The UDP listener is also always active. It runs as a background thread, listening for broadcast datagrams from other Pis on the WiFi mesh. When a message arrives via UDP, it goes through the same processing path as a LoRa-delivered message.

Both inputs pass through a deduplication gate before writing to the message log. Whichever transport delivers the message first gets it into the log. The second delivery of the same message is silently discarded.

### Sending a Message
When a user types a message on a Pi, two things happen simultaneously. The message is sent via serial to the local RAK4631, which transmits it on LoRa. This reaches distant nodes, standalone radios, and phones — anything on the LoRa mesh. At the same time, the message is broadcast via UDP to the WiFi mesh broadcast address (10.20.1.255 on port 4403). This reaches all other Pis within milliseconds. Both delivery paths are always used. LoRa for range, WiFi for speed.

### Receiving a Message from LoRa
When a Pi's RAK4631 hears a LoRa packet, the Meshtastic firmware decodes it and delivers it over serial. The Python library's callback fires. The message passes through the dedup check — if it hasn't been seen before, it gets added to the message log and displayed in the web UI. The Pi then rebroadcasts the message via UDP so all other Pis on the WiFi mesh get it immediately, without waiting for the LoRa mesh to route it hop by hop.

Meanwhile, the RAK4631 firmware independently decides whether to rebroadcast the packet on LoRa based on its own internal seen-packet table and the remaining hop count. The Pi does not interfere with this decision. The LoRa mesh operates autonomously.

### Receiving a Message from UDP
When a Pi's UDP listener receives a broadcast from another Pi, the message passes through the same dedup check. If the message is new (not yet seen via LoRa or a previous UDP broadcast), it gets added to the message log and displayed. If it has already been seen, it is discarded.

Messages received via UDP are not forwarded to the local RAK4631 for LoRa transmission. The originating node already transmitted on LoRa. Injecting the message into LoRa again from another node would create duplicate traffic on the LoRa mesh.

### LoRa Retransmission Is Unaffected
All radios stay in ROUTER role. The LoRa mesh operates completely independently of the WiFi layer. Receiving a message via WiFi UDP does not reduce or change LoRa retransmissions. The RAK4631 firmware makes rebroadcast decisions on its own, based on its internal state. The Pi cannot suppress firmware-level LoRa rebroadcasts, and it should not try to.

This means a message will often arrive at a Pi via both WiFi UDP (fast, milliseconds) and LoRa serial (slower, seconds after firmware processing and potential multi-hop routing). The deduplication layer handles this overlap — the user sees the message once, delivered via whichever path was fastest, which will almost always be WiFi.

---

## Deduplication

### Why It's Needed
Since both transports deliver the same messages, the same message can arrive twice: once via UDP and once via LoRa serial. Without deduplication, the user would see every message twice in the log.

### How It Works
The dedup mechanism is a simple dictionary maintained by MeshtasticManager, mapping packet IDs to timestamps. This is something we create in our code — it is not part of the Meshtastic Python library or firmware.

Every Meshtastic packet has a unique ID assigned by the originating radio when the packet is first created. This ID stays the same across all LoRa hops and rebroadcasts. The UDP broadcast payload includes this same packet ID.

When a message arrives from either transport, the handler extracts the packet ID and checks the dictionary. If the ID is already present, the message is a duplicate and is discarded. If the ID is not present, it is added to the dictionary with the current timestamp, and the message is processed normally and added to the log.

The dictionary entries are periodically cleaned up — any entry older than about 5 minutes is removed so the dictionary doesn't grow indefinitely. Meshtastic packet IDs are unique per transmission, so there is no collision risk within this window.

Both the LoRa serial callback and the UDP listener callback check the same dictionary. This is the single gate that prevents duplicates regardless of which transport delivered first.

### Packet ID Origin
The Meshtastic packet ID (accessed via `packet["id"]` in the Python library) is a 32-bit integer assigned by the originating radio's firmware. It is not something the Pi generates. It is embedded in the LoRa packet and decoded by the meshtastic library when the packet arrives over serial. When we broadcast via UDP, we include this same ID in the payload so the receiving Pi can compare it against IDs from LoRa-delivered packets.

---

## UDP Reliability

UDP is fire-and-forget — there is no acknowledgment, no retry, and no guaranteed delivery. This is acceptable for this use case for two reasons.

First, UDP packet loss on a local network (even an 802.11s mesh) is very low — typically well under 1%. These are short hops on a local broadcast domain, not unreliable internet paths.

Second, LoRa serves as the reliability backstop. If a UDP packet is lost, the same message is still traveling through the LoRa mesh and will arrive via serial a few seconds later. The dual-transport design provides built-in redundancy. The fast path (UDP) handles the common case; the reliable path (LoRa) catches anything that slips through.

If UDP reliability ever became a concern, application-level acknowledgments could be added later, but this would add complexity for minimal benefit given the LoRa fallback.

---

## Meshtastic Portnum vs Network Port

The Meshtastic protocol uses a concept called "portnum" which is an application-layer identifier inside the protobuf packet. For example, portnum 1 is text messages, portnum 3 is position updates, portnum 4 is node info, portnum 67 is telemetry. These are not network ports — they are more like message type tags within the Meshtastic protocol.

All of these portnums flow over the single serial connection between the Pi and the RAK4631. The Meshtastic Python library receives them all on that one serial link, decodes the protobuf, and dispatches them to different pub/sub topics internally.

For the WiFi UDP broadcast layer, we use one network port (4403) and include the message type information in the JSON payload. A "type" field in the JSON distinguishes text messages from position updates or other data types. One network port, many message types — the same pattern the serial interface uses.

Initially, only text messages need to be relayed over UDP. Position, telemetry, and nodeinfo could be added later using the same UDP port with different type values in the payload.

---

## Standalone and Non-WiFi Meshtastic Devices

Phones, handheld radios, and field devices that are not connected to a Pi participate only via LoRa. They are completely unaffected by the WiFi UDP layer.

When a standalone device sends a message, the LoRa mesh routes it normally, hop by hop. The first Pi node whose RAK4631 hears it receives the message via serial. That Pi then broadcasts it via UDP to all other Pis on the WiFi mesh. All Pis now have the message — even those that were out of LoRa range of the original sender.

This means the WiFi mesh effectively extends the reach of LoRa messages to all Pi nodes. A message that would take 3-4 LoRa hops (10+ seconds) arrives at all WiFi-connected Pis in milliseconds once any single Pi hears it on LoRa.

---

## Graceful Degradation

Either transport can fail independently without breaking the other. If the WiFi mesh goes down, LoRa still works normally — messages just arrive at the speed of LoRa instead of instantly. If a radio is disconnected, the UDP listener still receives messages from other Pis that have working radios. If both transports are working, users get the best of both worlds: instant WiFi delivery with LoRa range extension.

---

## What Needs to Be Built

### Additions to MeshtasticManager
A UDP broadcast sender that fires whenever a message is received from LoRa serial or sent by the local user, broadcasting it as a UDP datagram to the WiFi mesh broadcast address.

A UDP listener thread that runs in the background, receiving UDP broadcasts from other Pis and feeding received messages into the same message pipeline used by the serial interface.

A deduplication layer consisting of a dictionary of recently-seen packet IDs with timestamps, checked by both the LoRa serial callback and the UDP listener callback before any message is added to the message log. Entries older than approximately 5 minutes are periodically cleaned up.

Transport tagging so each message in the log indicates how it was delivered (LoRa, WiFi, or both) for debugging and potential UI display.

### Configuration
The UDP broadcast address should be derived from the mesh.conf MESH_IP and subnet (e.g., 10.20.1.255). The UDP port defaults to 4403 to match Meshtastic convention. An enable/disable flag for the WiFi UDP relay should be available in case a node should operate as LoRa-only.

### Web UI Changes
The message log could show a transport indicator for each message (LoRa vs WiFi). The status display could show UDP listener state alongside the serial connection state.

### Message Payload Format
The UDP broadcast payload should be a simple JSON envelope containing the packet ID (for dedup), sender name and ID, message text, channel, timestamp, message type, and an origin indicator that distinguishes "user sent this" from "radio heard this on LoRa" to prevent re-injection loops. JSON is sufficient for the message volumes involved. Binary protobuf could be considered later for efficiency but is not necessary.

---

## Implementation Phases

### Complete
- Phase 1: Meshtastic Python library installed, RAK4631 detected on /dev/ttyACM0
- Phase 2: MeshtasticManager with serial connect/disconnect/send/receive, CLI-testable
- Phase 3: Flask API (meshtastic_api.py) — endpoints built, registered as blueprint in main app
- Phase 4: Web UI integration — template, nav link, message log, node table, send form
- Phase 5: UDP broadcast sender — fires on LoRa receive and user send, JSON payload to WiFi mesh broadcast address
- Phase 6: UDP listener thread — background thread in MeshtasticManager.__init__, receives broadcasts from other Pis, dedup gate, independent of serial connection
- Phase 7: Deduplication + transport tagging — seen-packets dict with 5-min expiry, thread-safe lock, "transport" field on all messages (lora/wifi/local)
- Phase 8: Web UI updates — transport badges (LoRa/WiFi/local) on messages, UDP relay status panel (enabled, listener state, broadcast address)
- Phase 9: Configuration — MESHTASTIC_UDP_RELAY and MESHTASTIC_UDP_PORT in mesh.conf, broadcast address derived from MESH_IP

---

## Key Design Decisions

1. **All radios stay ROUTER.** LoRa rebroadcasting is not suppressed. Range extension is the entire purpose of the LoRa mesh. WiFi delivery does not reduce or replace LoRa retransmissions.

2. **WiFi UDP does not inject messages into LoRa.** Messages received via UDP are not forwarded to the local radio for LoRa transmission. Only the originating node transmits on LoRa. This prevents duplicate LoRa traffic.

3. **No broker, no server.** UDP broadcast is peer-to-peer. Every Pi is equal. No coordination or infrastructure is needed.

4. **Deduplication is mandatory and application-level.** The seen-IDs dictionary is created and maintained in our code, not in the Meshtastic library or firmware. Both transport callbacks check the same dictionary before writing to the message log.

5. **Graceful degradation.** Either transport can fail independently. WiFi down means LoRa-only delivery (slower but functional). Radio disconnected means UDP-only delivery (no range extension but Pis still communicate). Both working means instant delivery with full range.

6. **The Meshtastic radio is always in the loop.** The serial interface is always active and always receives packets. The radio has no awareness of the UDP layer. Dedup filtering happens after the packet has been received and decoded, at the application layer in Python.

---

## Deployment & Usage

### Configuration

Two settings in `/etc/nucleus/mesh.conf` control the UDP relay:

```
MESHTASTIC_UDP_RELAY=true
MESHTASTIC_UDP_PORT=4403
```

- **MESHTASTIC_UDP_RELAY** — Master switch. `true` enables the WiFi UDP relay between Pis. `false` disables it (LoRa-only mode).
- **MESHTASTIC_UDP_PORT** — UDP port for broadcasts. Default 4403. All nodes must use the same port.
- The broadcast address is derived automatically from `MESH_IP` (last octet replaced with 255, e.g., `10.20.1.20` → `10.20.1.255`).

### Deploying to a Node

The `deploy.sh` script in the repo root handles all file deployment. It copies:
- `etc/nucleus/mesh.conf` → `/etc/nucleus/mesh.conf`
- `opt/nucleus/meshtastic/` → `/opt/nucleus/meshtastic/` (recursive)
- `opt/nucleus/web/` → `/opt/nucleus/web/` (recursive)

Run from the repo directory:
```bash
sudo ./deploy.sh
```

Or copy individual files manually:
```bash
sudo cp etc/nucleus/mesh.conf /etc/nucleus/mesh.conf
sudo cp opt/nucleus/meshtastic/meshtastic_manager.py /opt/nucleus/meshtastic/
sudo cp opt/nucleus/web/templates/meshtastic.html /opt/nucleus/web/templates/
sudo chown -R natak:natak /opt/nucleus/
```

After deploying, restart the web service:
```bash
sudo systemctl restart mesh-web
```

### Verifying the UDP Relay

1. Open the Meshtastic page in the web UI (`http://<node-ip>:5000/meshtastic`).
2. The **UDP Relay** status panel (always visible, independent of radio connection) should show:
   - UDP Relay: **Enabled** (green)
   - UDP Listener: **Running** (green)
   - Broadcast: **10.20.1.255:4403** (or your subnet's broadcast address)
3. Click **Take Control** to connect to the radio via serial.
4. Send a message — it goes out on both LoRa and UDP simultaneously. The message log shows a green **local** badge.
5. When another Pi sends a message, it arrives with either a cyan **WiFi** badge (via UDP, fast) or an amber **LoRa** badge (via serial, slower). Dedup ensures you see it once — whichever path was fastest.

### Transport Badges

Each message in the web UI and CLI output is tagged with its delivery transport:
- **local** (green) — You sent this message from this node.
- **LoRa** (amber) — Arrived via the RAK4631 radio's serial interface.
- **WiFi** (cyan) — Arrived via UDP broadcast from another Pi on the 802.11s mesh.

### CLI Usage

The CLI commands work as before, with transport information now included:

```bash
python3 /opt/nucleus/meshtastic/meshtastic_manager.py connect          # Connect + start listening
python3 /opt/nucleus/meshtastic/meshtastic_manager.py send "hello"     # Send via LoRa + UDP
python3 /opt/nucleus/meshtastic/meshtastic_manager.py messages         # Shows (lora), (wifi), (local) per message
python3 /opt/nucleus/meshtastic/meshtastic_manager.py status           # Shows connection + UDP relay state
python3 /opt/nucleus/meshtastic/meshtastic_manager.py disconnect       # Release radio back to BLE
```

### Per-Node Configuration

Every Pi in the mesh needs:
- `MESHTASTIC_UDP_RELAY=true` in its `/etc/nucleus/mesh.conf`
- The updated `meshtastic_manager.py` and `meshtastic.html`
- A restart of the `mesh-web` service

To disable UDP relay on a specific node (LoRa-only), set `MESHTASTIC_UDP_RELAY=false` in that node's `mesh.conf` and restart. The node still works — it just won't send or receive via WiFi UDP.

### Message Flow Example

**User sends "hello" on Node A:**
1. Node A sends "hello" to its RAK4631 via serial → LoRa transmission begins.
2. Node A simultaneously UDP broadcasts the message to 10.20.1.255:4403.
3. Node A registers the packet ID in its dedup dictionary.
4. Node B's UDP listener gets it in ~5ms → dedup passes → logged with WiFi badge.
5. Node B's radio eventually delivers it via serial seconds later → dedup catches it → silently dropped.
6. User on Node B sees the message once, with a WiFi badge (the fast path won).

**A phone user sends "hey" on LoRa (no Pi attached):**
1. LoRa mesh routes it hop by hop.
2. Node A's radio hears it first → serial callback fires → dedup passes → logged with LoRa badge.
3. Node A immediately UDP broadcasts it to the WiFi mesh.
4. Node B gets it via UDP in ~5ms → dedup passes → logged with WiFi badge.
5. Node B's radio eventually delivers it via serial → dedup catches it → dropped.
6. Node C (out of WiFi range, no UDP) gets it purely via LoRa → logged with LoRa badge.
