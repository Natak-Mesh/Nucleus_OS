# Meshtastic Integration — Architecture & Status

## System Context

- **Radios:** RAK4631 (nRF52840 + SX1262 LoRa) — no WiFi/Ethernet on the radio
- **Compute:** Raspberry Pi 4 — each Pi has a RAK4631 connected via USB serial at 115200 baud
- **WiFi Mesh:** 802.11s mesh between all Pis (same broadcast domain, 10.20.1.x/24)
- **Connection:** Pi controls the radio over serial using the meshtastic Python library

Every Nucleus node is a Pi + RAK4631 pair. The Pis form an 802.11s WiFi mesh for high-bandwidth local networking. The RAK4631 radios form an independent LoRa mesh for long-range, low-bandwidth messaging. The Pi is the only bridge point between the two networks.

The Nucleus web UI (`http://<node-ip>:5000/meshtastic`) is the primary interface for interacting with the meshtastic radio. No phone app required.

---

## Completed Features (Phases 1–9)

### Serial Control
- MeshtasticManager class connects/disconnects to RAK4631 via serial
- States: `DISCONNECTED` → `CONNECTING` → `CONNECTED` → `DISCONNECTING`
- Disconnect reboots the radio to restore BLE if needed
- Web UI buttons: "Take Control" / "Release to BLE" / "Clear Node DB"

### Text Messaging
- Send/receive text messages via `sendText()` over LoRa
- Message log with newest-first display, stored in `/tmp/meshtastic_messages.json`
- Send form in web UI with channel support

### Node Discovery
- Node table showing short name, position (lat/lon), last heard, SNR
- Color-coded SNR (good/ok/poor), local node highlighted
- Auto-refreshes every 3 seconds

### Dual-Transport: LoRa + WiFi UDP
- Every message sent goes out on both LoRa (via radio) and WiFi UDP (broadcast to 10.20.1.255:4403)
- LoRa provides range extension; WiFi provides near-instant delivery between Pis
- Messages received via LoRa are rebroadcast on WiFi UDP so all Pis get them immediately
- Messages received via WiFi UDP are NOT re-injected into LoRa (prevents duplicate traffic)
- All radios stay in ROUTER role — LoRa mesh operates autonomously

### Deduplication
- Application-level dedup using packet ID dictionary with 5-minute expiry
- Thread-safe — both LoRa serial callback and UDP listener check the same dictionary
- Whichever transport delivers first wins; second delivery is silently discarded

### Transport Tagging
- Every message tagged: **local** (green, you sent it), **LoRa** (amber, arrived via radio), **WiFi** (cyan, arrived via UDP)
- Badges displayed in web UI message log

### Configuration
```
# /etc/nucleus/mesh.conf
MESHTASTIC_UDP_RELAY=true     # Enable/disable WiFi UDP relay
MESHTASTIC_UDP_PORT=4403      # UDP port (all nodes must match)
# Broadcast address derived from MESH_IP automatically
```

### Flask API Endpoints
| Endpoint | Method | Purpose |
|---|---|---|
| `/api/meshtastic/connect` | POST | Take serial control |
| `/api/meshtastic/disconnect` | POST | Release radio (reboot to BLE) |
| `/api/meshtastic/status` | GET | Connection state + UDP relay info |
| `/api/meshtastic/send` | POST | Send text message |
| `/api/meshtastic/messages` | GET | Recent messages |
| `/api/meshtastic/nodes` | GET | Known mesh nodes |
| `/api/meshtastic/clear-messages` | POST | Clear message log |
| `/api/meshtastic/reset-nodedb` | POST | Clear radio's node database |

### CLI
```bash
python3 /opt/nucleus/meshtastic/meshtastic_manager.py connect
python3 /opt/nucleus/meshtastic/meshtastic_manager.py send "hello"
python3 /opt/nucleus/meshtastic/meshtastic_manager.py messages
python3 /opt/nucleus/meshtastic/meshtastic_manager.py status
python3 /opt/nucleus/meshtastic/meshtastic_manager.py disconnect
```

### Key Design Decisions
1. WiFi UDP is peer-to-peer broadcast — no broker, no server, no single point of failure
2. Dedup is mandatory and application-level — not part of the meshtastic library
3. Either transport can fail independently (graceful degradation)
4. The radio's LoRa rebroadcast behavior is never suppressed or modified
5. UDP payload is JSON with packet ID, sender info, text, channel, timestamp, origin, source IP

---

## Planned Features

### Phase 10: Canned Messages / Quick Send

Pre-defined quick-tap message buttons in the web UI for common field communications. Saves typing on mobile browsers in field conditions.

**Examples:** "Moving", "In position", "Copy", "Need resupply", "All clear", "Contact north", "Send it"

**Implementation:**
- Row of buttons above the message input in the meshtastic web UI
- Each button calls the existing `sendText()` path — same LoRa + UDP dual transport
- Configurable presets — either in a config file or editable in the web UI
- Zero new backend work beyond a config endpoint; this is pure UI + existing send infrastructure

**Effort:** Low. Quick win.

---

### Phase 11: Codec2 Voice Notes

Push-to-talk voice notes sent over LoRa and/or WiFi UDP. Uses Codec2, an ultra-low-bitrate open-source voice codec designed for HF/VHF radio. This is the same codec the meshtastic community has experimented with for audio (portnum 9 = `AUDIO_APP`).

#### Why Codec2

Standard audio codecs (Opus, AAC, MP3) produce bitrates far too high for LoRa. Codec2 was purpose-built for extremely constrained radio channels:

| Codec2 Mode | Bitrate | Bytes/sec | 2.5s clip | Fits in 1 LoRa packet? |
|---|---|---|---|---|
| 700C | 700 bps | 87.5 B/s | ~219 bytes | ✅ Yes (233 byte limit) |
| 1200 | 1200 bps | 150 B/s | ~375 bytes | ❌ No (2 packets) |
| 1300 | 1300 bps | 162.5 B/s | ~406 bytes | ❌ No (2 packets) |
| 2400 | 2400 bps | 300 B/s | ~750 bytes | ❌ No (4 packets) |

#### LoRa Constraint: One Packet = One Voice Note

The max LoRa data payload is **233 bytes**. At Codec2 700bps, **~2.5 seconds of voice fits in one packet**. This is the target.

One packet = same mesh impact as sending a text message. The LoRa mesh retransmits it like any other packet. No chunking, no reassembly, no fragmentation protocol needed.

2.5 seconds is short but matches military/field voice brevity: "Contact north", "Moving to rally", "Copy", "Need medevac", "All clear", "Send it".

Multi-packet voice notes (longer clips) could be sent WiFi-only between Pis where bandwidth is not a concern.

#### Mesh Flooding Consideration

Every LoRa packet gets retransmitted by ROUTER nodes. With 6 nodes in the mesh, 1 voice packet = up to 6 LoRa transmissions. This is identical to a text message and is acceptable. Multi-packet voice (2+ packets) multiplies this — a 4-packet clip could generate 24 transmissions, eating shared airtime and potentially delaying other traffic (including video streams or ATAK data on the WiFi mesh if LoRa retransmits cause serial processing delays).

**Rule: LoRa voice notes are limited to one packet (~2.5s at 700bps).** Longer recordings go WiFi-only.

#### Architecture

**Sending (browser → Pi → mesh):**
1. User holds "Record" button in the web UI
2. Browser captures audio via Web Audio API / MediaRecorder (all modern browsers, works on phones)
3. On release, raw PCM audio is POST'd to the Pi backend (`/api/meshtastic/send-audio`)
4. Pi encodes PCM → Codec2 700bps using `pycodec2` or `c2enc` CLI
5. If ≤ 233 bytes: send via `interface.sendData(data, portNum=9)` — one LoRa packet to the mesh
6. Simultaneously broadcast via WiFi UDP (same dual-transport pattern as text messages, with `type: "audio"` and base64-encoded Codec2 payload)
7. If > 233 bytes: send WiFi UDP only, skip LoRa (too many packets)

**Receiving (mesh → Pi → browser):**
1. LoRa path: arrives via `meshtastic.receive.data.9` pub/sub callback (portnum 9 = AUDIO_APP)
2. WiFi UDP path: arrives via existing UDP listener (JSON payload with `type: "audio"`)
3. Both pass through the existing dedup gate (same packet ID mechanism)
4. Pi decodes Codec2 → PCM
5. Web UI fetches decoded audio and plays it via Web Audio API
6. Displayed inline in the message log as a playable audio element with transport badge

**WiFi-only path (longer clips):**
For Pi-to-Pi communication, Codec2 isn't even necessary — we could send Opus or raw PCM over WiFi UDP since bandwidth is plentiful. But using Codec2 consistently keeps the format uniform. Alternatively, longer clips could use Opus over WiFi for better quality.

#### Dependencies

- **Codec2 C library:** `apt install codec2` (or build from source — it's lightweight)
- **Python binding:** `pycodec2` pip package, or shell out to `c2enc`/`c2dec` CLI tools
- **Browser:** Web Audio API for recording + playback (standard in Chrome, Firefox, Safari)
- **No additional radio configuration:** portnum 9 (AUDIO_APP) is already in the meshtastic firmware spec

#### Compatibility

Portnum 9 (AUDIO_APP) is defined in the meshtastic protobuf spec. Any meshtastic device that implements Codec2 audio reception would be able to hear these voice notes. Currently few meshtastic clients implement this, but the packet format is standards-compliant. Standalone radios without Codec2 support would silently ignore the packets (standard meshtastic behavior for unhandled portnums).

#### Web UI Design

- **Record button:** Push-to-talk style, next to the text send form. Hold to record, release to send.
- **Duration indicator:** Shows recording time with a color change at ~2s warning (approaching LoRa limit)
- **LoRa/WiFi indicator:** Shows whether the clip will go LoRa+WiFi (≤2.5s) or WiFi-only (>2.5s)
- **Playback:** Received voice notes appear in the message log as a small audio player with transport badge
- **Fallback:** If Codec2 isn't installed on the Pi, voice notes are disabled with a message in the UI

#### New API Endpoints

| Endpoint | Method | Purpose |
|---|---|---|
| `/api/meshtastic/send-audio` | POST | Upload recorded audio, encode + send |
| `/api/meshtastic/audio/<id>` | GET | Fetch decoded audio for playback |

#### Effort

High. Requires: Codec2 integration, browser audio recording, new send/receive pipeline, UI work, testing across browsers and devices. But technically sound and genuinely useful in field comms.

---

## Implementation Phases — Status

| Phase | Description | Status |
|---|---|---|
| 1 | Meshtastic library installed, RAK4631 detected | ✅ Complete |
| 2 | MeshtasticManager with serial control + CLI | ✅ Complete |
| 3 | Flask API (meshtastic_api.py) | ✅ Complete |
| 4 | Web UI integration — template, nav, message log, send form | ✅ Complete |
| 5 | UDP broadcast sender (LoRa receive → WiFi broadcast) | ✅ Complete |
| 6 | UDP listener thread (WiFi → message log, independent of serial) | ✅ Complete |
| 7 | Deduplication + transport tagging | ✅ Complete |
| 8 | Web UI transport badges + UDP relay status panel | ✅ Complete |
| 9 | Configuration (mesh.conf settings for UDP relay) | ✅ Complete |
| 10 | Canned messages / quick send buttons | 🔲 Planned |
| 11 | Codec2 voice notes (push-to-talk, LoRa + WiFi) | 🔲 Planned |

---

## File Locations

```
/opt/nucleus/meshtastic/meshtastic_manager.py   # Core manager (serial + UDP + dedup)
/opt/nucleus/meshtastic/meshtastic_api.py        # Flask API blueprint
/opt/nucleus/web/templates/meshtastic.html       # Web UI template
/etc/nucleus/mesh.conf                           # Configuration
```
