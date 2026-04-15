# Full Meshtastic Integration into Nucleus — Planning

## Goal

Integrate meshtastic fully into Nucleus OS so that **no phone app is needed** for any meshtastic operation: messaging, radio configuration (including fleet-wide sharing), and ATAK CoT bridging over LoRa. Everything is accessible from the CLI menu and the web UI.

## System Context

- **Radios:** RAK4631 (nRF52840 + SX1262 LoRa) — no WiFi/Ethernet on the radio
- **Compute:** Raspberry Pi 4 — each Pi has a RAK4631 connected via USB serial at 115200 baud
- **WiFi Mesh:** 802.11s mesh between all Pis (same broadcast domain, 10.20.1.x/24)
- **Connection:** Pi controls the radio over serial using the meshtastic Python library (v2.7.8)
- **ATAK:** EUDs connect to Pi via br-lan (WiFi AP or Ethernet), send CoT multicast on 239.2.3.1:6969 and 224.10.10.1:17012

Every Nucleus node is a Pi + RAK4631 pair. The Pis form an 802.11s WiFi mesh for high-bandwidth local networking. The RAK4631 radios form an independent LoRa mesh for long-range, low-bandwidth messaging. The Pi is the bridge between the two networks — and now also the bridge between ATAK and LoRa.

---

## What Already Exists

### Completed (Phases 1–9)

| Component | Status | Location |
|-----------|--------|----------|
| MeshtasticManager — serial control, messaging, UDP dual-transport, dedup | ✅ | `/opt/nucleus/meshtastic/meshtastic_manager.py` |
| Flask API — connect/disconnect/send/status/messages/nodes | ✅ | `/opt/nucleus/meshtastic/meshtastic_api.py` |
| Web UI — radio control, messaging, node table, transport badges | ✅ | `/opt/nucleus/web/templates/meshtastic.html` |
| UDP relay — LoRa + WiFi dual-transport with dedup | ✅ | Built into meshtastic_manager.py |
| Configuration — mesh.conf UDP relay settings | ✅ | `/etc/nucleus/mesh.conf` |
| CLI menu — system monitoring, network testing, file transfer, reticulum | ✅ | `/opt/nucleus/cli/nucleus-menu.sh` |
| File transfer — scp between nodes via ~/transfer/ | ✅ | nucleus-menu.sh option 8 |
| ATAK multicast TTL handling | ✅ | `/opt/nucleus/bin/mesh-start.sh` |
| Meshtastic udev rules (prevent mtp-probe crash) | ✅ | `/etc/udev/rules.d/60-meshtastic.rules` |

### Not Yet Built

| Component | Status |
|-----------|--------|
| CLI menu — Meshtastic section | 🔲 Planned |
| Config sharing — export/apply/push via CLI | 🔲 Planned (see `meshtastic_config_sharing.md`) |
| ATAK CoT ↔ LoRa bridge | 🔲 Planned (this document) |
| Canned messages / quick send | 🔲 Planned |
| Codec2 voice notes | 🔲 Planned |

---

## Workstream 1: CLI Menu — Meshtastic Section

### Purpose

Add a **Meshtastic** section to `nucleus-menu.sh` providing power-user access to all meshtastic operations from the terminal. This is the command-line equivalent of the web UI, plus config operations the web UI doesn't have.

### Menu Structure

```
  Meshtastic
   11) Radio Status / Info
   12) Send Message
   13) Message Log
   14) Node List
   15) Listen (live messages)
   16) Traceroute

  Meshtastic Config
   17) Export radio config to file
   18) Apply config from file
   19) Push config to another node
   20) Push config to ALL mesh nodes
   21) Show channel URL
```

### Implementation Approach

**Primary method:** Call the existing Flask API via curl when the web app is running. This avoids serial port contention — the web app's meshtastic_manager already holds the serial connection.

```bash
# Example: send a message via the API
do_mesh_send() {
    printf "  Message: "
    read -r msg_text
    curl -s -X POST -H "Content-Type: application/json" \
        -d "{\"text\":\"${msg_text}\"}" \
        localhost:5000/api/meshtastic/send | python3 -m json.tool
}
```

**Fallback:** For operations that need the meshtastic CLI directly (export-config, configure, traceroute, qr), use the serial release/reacquire pattern:
1. Check if web app holds serial: `curl -s localhost:5000/api/meshtastic/status`
2. If connected, release: `curl -s -X POST localhost:5000/api/meshtastic/disconnect`
3. Wait 2 seconds for serial release
4. Run the meshtastic CLI command
5. Optionally reconnect: `curl -s -X POST localhost:5000/api/meshtastic/connect`

### Menu Items Detail

#### 11) Radio Status / Info
```bash
# Via API (preferred)
curl -s localhost:5000/api/meshtastic/status | python3 -m json.tool

# Or via CLI (needs serial release)
meshtastic --info
```

Shows: connection state, node name/ID, port, known nodes, UDP relay status, channel info.

#### 12) Send Message
```bash
printf "  Message: "
read -r msg_text
curl -s -X POST -H "Content-Type: application/json" \
    -d "{\"text\":\"${msg_text}\"}" \
    localhost:5000/api/meshtastic/send
```

Interactive prompt for message text. Uses existing dual-transport (LoRa + WiFi UDP).

#### 13) Message Log
```bash
curl -s localhost:5000/api/meshtastic/messages | python3 -c "
import sys, json
data = json.load(sys.stdin)
for msg in data.get('messages', [])[-20:]:
    d = '>>>' if msg['direction'] == 'sent' else '<<<'
    who = msg.get('to') if msg['direction'] == 'sent' else msg.get('from', '?')
    t = msg.get('transport', '?')
    ts = msg.get('timestamp', '')
    print(f'  {ts}  {d}  [{who}]  ({t})  {msg.get(\"text\", \"\")}')
"
```

Shows recent messages with transport badges (LoRa/WiFi/local), newest last.

#### 14) Node List
```bash
curl -s localhost:5000/api/meshtastic/nodes | python3 -c "
import sys, json
data = json.load(sys.stdin)
print(f'  Known nodes: {data.get(\"count\", 0)}')
for n in data.get('nodes', []):
    local = ' (you)' if n.get('is_local') else ''
    print(f'  {n[\"short_name\"]}{local}  {n[\"last_heard\"]}  SNR: {n[\"snr\"]}  {n[\"position\"]}')
"
```

#### 15) Listen (live messages)
```bash
# Watch the message log file for changes
tail -f /tmp/meshtastic_messages.json | python3 -c "
import sys, json
# Stream new messages as they arrive
..."
```

Or simpler: poll the API every 2 seconds and display new messages. Ctrl-C to stop.

#### 16) Traceroute
```bash
# Needs serial release since meshtastic CLI does this directly
printf "  Target node ID (e.g. !abcd1234): "
read -r target_node
# Release serial...
meshtastic --traceroute "$target_node"
# Reconnect...
```

---

## Workstream 2: Config Sharing via CLI

### Purpose

Eliminate the meshtastic phone app for radio configuration. Export, apply, and push radio config between nodes using the meshtastic CLI's `--export-config` and `--configure` commands, combined with the existing file transfer infrastructure.

### Detailed Design

See `docs/cli_tools/meshtastic_config_sharing.md` for the full design. Summary:

#### 17) Export Radio Config
```bash
# Release serial if needed
meshtastic --export-config ~/transfer/natak-mesh.yaml
# Generates full config YAML in the transfer staging directory
```

Saves full config to `~/transfer/natak-mesh.yaml` — ready for SCP to other nodes.

#### 18) Apply Config from File
```bash
# List available configs in ~/transfer/
# User picks one
meshtastic --configure ~/transfer/natak-mesh.yaml
```

Applies a previously-exported config to the local radio. Prompts about owner name handling.

#### 19) Push Config to Another Node

Interactive flow:
1. Export local config
2. `pick_node()` to select target
3. SCP the YAML to target's `~/transfer/`
4. SSH to target, release serial if needed, run `meshtastic --configure`

#### 20) Push Config to ALL Mesh Nodes

Fleet deployment:
1. Export local config
2. Strip `owner`/`owner_short` (preserve node names)
3. Enumerate all Babel mesh peers
4. For each: SCP + SSH apply
5. Report success/failure per node

Options:
```
  Push config to all nodes:
   1) Channels + settings only (preserve node names)
   2) Full config including node names
   3) Channel URL only (fastest, channels + LoRa only)
```

#### 21) Show Channel URL
```bash
meshtastic --qr-all
```

Displays shareable channel URL(s) + terminal QR code. For verifying all nodes match or sharing with phone app users.

### Serial Port Contention

All config operations need the meshtastic CLI, which needs exclusive serial access. Strategy:

```bash
# Helper function for CLI menu
release_serial_if_needed() {
    local status
    status=$(curl -s localhost:5000/api/meshtastic/status 2>/dev/null)
    if echo "$status" | grep -q '"state": "CONNECTED"'; then
        printf "  ${DIM}Releasing serial port...${RESET}\n"
        curl -s -X POST localhost:5000/api/meshtastic/disconnect > /dev/null
        sleep 3  # Wait for radio reboot + serial release
        return 0  # Was connected, remember to reconnect
    fi
    return 1  # Was not connected
}

reconnect_serial() {
    printf "  ${DIM}Reconnecting serial...${RESET}\n"
    curl -s -X POST localhost:5000/api/meshtastic/connect > /dev/null
}
```

---

## Workstream 3: ATAK CoT ↔ Meshtastic LoRa Bridge

### Purpose

Bridge ATAK Cursor-on-Target (CoT) data between the WiFi mesh and the LoRa mesh. ATAK EUDs connected to a Pi's br-lan can exchange positions, markers, and chat with ATAK EUDs connected to remote Pis — via LoRa — without any meshtastic phone app.

### Why This Matters

Currently, ATAK CoT flows only over the WiFi 802.11s mesh between Pis. If two groups of ATAK users are beyond WiFi range but within LoRa range, they can't see each other's positions or exchange CoT. The ATAK CoT bridge solves this by:

1. Intercepting CoT multicast from local ATAK EUDs
2. Converting CoT XML → compact meshtastic TAKPacket protobuf
3. Sending TAKPacket over LoRa (tiny payload, fits in one packet)
4. Remote Pi receives TAKPacket, converts back to CoT XML
5. Remote Pi multicasts CoT to its local ATAK EUDs

This is exactly what the meshtastic Android ATAK plugin does — but we're doing it on the Pi as an infrastructure service, not requiring each user to have the plugin.

### Key Libraries

#### takproto (v3.0.1)

Python library purpose-built for converting between CoT XML and meshtastic's TAKPacket protobuf format. This is the standard tool the meshtastic community uses for TAK integration.

**CoT XML → TAKPacket protobuf (for sending over LoRa):**
```python
import takproto

# CoT XML from ATAK multicast
cot_xml = '<event uid="ANDROID-abc" type="a-f-G-U-C" ...>...</event>'

# Convert to meshtastic TAKPacket protobuf bytes
tak_packet_bytes = takproto.xml2proto(cot_xml)
# Returns: serialized TAKPacket protobuf, compressed if beneficial
# Typical size: 30-80 bytes (vs 500-2000 bytes for raw CoT XML)
```

**TAKPacket protobuf → CoT XML (for multicast to ATAK EUDs):**
```python
import takproto

# TAKPacket bytes received from LoRa
tak_packet_bytes = packet['decoded']['payload']

# Convert back to CoT XML
cot_xml = takproto.proto2xml(tak_packet_bytes)
# Returns: full CoT XML string ready for multicast
```

takproto handles:
- TAKPacket protobuf serialization/deserialization
- PLI (Position Location Information) encoding/decoding (lat/lon as int × 1e7)
- GeoChat message encoding/decoding
- Contact and Group (team/role) encoding
- Compression (is_compressed flag in TAKPacket)
- Detail XML preservation (opaque bytes for fields not in the protobuf schema)

#### pytak (v7.3.0)

Python library for TAK network operations. Provides:
- Multicast CoT sending/receiving helpers
- CoT event generation utilities
- TAK protocol constants (ports, multicast groups)

May be useful for the multicast listener/sender, though we can also use raw socket multicast (similar to our existing UDP relay pattern).

### Meshtastic Protobuf — ATAK Support

The meshtastic protobuf library (already installed, v2.7.8) defines the ATAK types:

```
TAKPacket:
  is_compressed: bool          # Whether detail bytes are compressed
  contact: Contact             # Callsign info
  group: Group                 # Team color + role
  status: Status               # Battery level
  payload_variant (oneof):
    pli: PLI                   # Position Location Information
    chat: GeoChat              # Chat message
    detail: bytes              # Raw CoT detail XML (opaque)

PLI:
  latitude_i: sfixed32         # Latitude × 1e7 (integer encoding)
  longitude_i: sfixed32        # Longitude × 1e7
  altitude: int32              # Meters
  speed: uint32                # m/s
  course: uint32               # Degrees

GeoChat:
  message: string              # Chat text
  to: string (optional)        # Destination callsign
  to_callsign: string (optional)

Contact:
  callsign: string             # e.g. "ALPHA-1"
  device_callsign: string      # e.g. "ANDROID-abc123"

Group:
  role: MemberRole             # TeamMember, TeamLead, HQ, Sniper, Medic, etc.
  team: Team                   # White, Yellow, Orange, Red, Blue, Cyan, Green, etc.

PortNum:
  ATAK_PLUGIN = 72             # Standard portnum for TAK data over meshtastic
  ATAK_FORWARDER = 257         # For forwarding raw CoT (not protobuf)
```

### Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                        Nucleus Node A                           │
│                                                                 │
│  ATAK EUD ──multicast CoT XML──→ Pi (br-lan)                   │
│                                      │                          │
│                               CoT Multicast Listener            │
│                               (239.2.3.1:6969)                  │
│                                      │                          │
│                               takproto.xml2proto()              │
│                               CoT XML → TAKPacket bytes         │
│                                      │                          │
│                               Rate Limiter                      │
│                               (1 PLI per node per 30-60s)       │
│                                      │                          │
│                        ┌─────────────┴──────────────┐           │
│                        ▼                            ▼           │
│               sendData(portNum=72)          UDP broadcast        │
│               → LoRa mesh                  → WiFi mesh          │
│               (30-80 bytes)                (full speed)          │
└────────────────────┬────────────────────────────────────────────┘
                     │ LoRa
                     ▼
┌─────────────────────────────────────────────────────────────────┐
│                        Nucleus Node B                           │
│                                                                 │
│               Receive TAKPacket                                 │
│               (portnum 72 callback)                             │
│                        │                                        │
│               takproto.proto2xml()                               │
│               TAKPacket bytes → CoT XML                         │
│                        │                                        │
│               Multicast CoT XML                                 │
│               (239.2.3.1:6969 on br-lan)                        │
│                        │                                        │
│  ATAK EUD ←──multicast CoT XML──← Pi (br-lan)                  │
└─────────────────────────────────────────────────────────────────┘
```

### New File: `/opt/nucleus/meshtastic/atak_bridge.py`

A new module that integrates with the existing meshtastic_manager.py.

#### Core Components

**1. CoT Multicast Listener Thread**

Listens for ATAK CoT XML on the standard multicast groups:
- `239.2.3.1:6969` — SA (Situational Awareness) — positions, markers
- `224.10.10.1:17012` — Discovery — ATAK peer announcements

Binds to `br-lan` interface specifically (so we only capture CoT from local ATAK EUDs, not from the WiFi mesh).

```python
class CoTListener:
    """Listens for ATAK CoT multicast on br-lan."""
    
    MCAST_GROUPS = [
        ("239.2.3.1", 6969),      # SA multicast
    ]
    
    def __init__(self, bridge, interface_name="br-lan"):
        self.bridge = bridge
        self.interface = interface_name
        self._running = False
    
    def start(self):
        """Start listening for CoT on multicast groups."""
        # Join multicast group on br-lan
        # Parse received CoT XML
        # Pass to bridge for conversion and LoRa send
```

**2. CoT ↔ TAKPacket Converter (via takproto)**

```python
import takproto

class CoTConverter:
    """Converts between CoT XML and meshtastic TAKPacket protobuf."""
    
    @staticmethod
    def cot_to_proto(cot_xml: str) -> bytes:
        """Convert CoT XML to TAKPacket protobuf bytes for LoRa transmission."""
        return takproto.xml2proto(cot_xml)
    
    @staticmethod
    def proto_to_cot(tak_bytes: bytes) -> str:
        """Convert TAKPacket protobuf bytes to CoT XML for multicast."""
        return takproto.proto2xml(tak_bytes)
```

**3. Rate Limiter**

LoRa airtime is precious. ATAK sends PLI every 3-10 seconds per EUD. With 6 EUDs, that's a PLI every 0.5-1.7 seconds — far too fast for LoRa.

```python
class CoTRateLimiter:
    """Rate-limits CoT forwarding to LoRa to prevent airtime saturation."""
    
    PLI_INTERVAL = 60      # Seconds between PLI updates per callsign
    CHAT_INTERVAL = 0      # Chat messages sent immediately (no throttling)
    MARKER_INTERVAL = 0    # Markers sent immediately
    
    def __init__(self):
        self._last_pli: Dict[str, float] = {}  # callsign → timestamp
    
    def should_forward(self, cot_xml: str) -> bool:
        """Check if this CoT event should be forwarded to LoRa.
        
        PLI (position) updates are throttled per callsign.
        Chat and markers are always forwarded immediately.
        """
        # Parse event type from CoT XML
        # a-f-G-U-C = friendly ground unit — PLI, throttle
        # b-m-p-s-p-i = marker — forward immediately
        # b-t-f = chat — forward immediately
```

**4. LoRa Sender**

Uses the existing meshtastic_manager's serial connection to send TAKPacket data:

```python
def send_tak_to_lora(self, tak_bytes: bytes, channel: int = 0):
    """Send TAKPacket protobuf over LoRa via meshtastic sendData."""
    if self.manager.interface is None:
        return  # Not connected, skip LoRa (WiFi UDP still works)
    
    self.manager.interface.sendData(
        tak_bytes,
        destinationId=BROADCAST_ADDR,
        portNum=72,  # ATAK_PLUGIN
        wantAck=False,  # Broadcast, no ack needed
        channelIndex=channel,
    )
```

**5. LoRa Receiver**

Subscribe to portnum 72 (ATAK_PLUGIN) to receive TAKPacket from remote nodes:

```python
def _on_tak_receive(self, packet, interface):
    """Called when a TAKPacket is received via LoRa."""
    try:
        tak_bytes = packet.get("decoded", {}).get("payload", b"")
        packet_id = packet.get("id")
        
        # Dedup (same mechanism as text messages)
        if not self.manager._check_dedup(packet_id):
            return
        
        # Convert to CoT XML
        cot_xml = takproto.proto2xml(tak_bytes)
        
        # Multicast to local ATAK EUDs on br-lan
        self._multicast_cot(cot_xml)
        
        # Also broadcast via WiFi UDP to other Pis
        self._udp_broadcast_tak(tak_bytes, packet_id)
    except Exception as e:
        logger.error(f"Error handling TAKPacket: {e}")
```

**6. CoT Multicast Sender**

Sends reconstructed CoT XML back onto br-lan for local ATAK EUDs:

```python
def _multicast_cot(self, cot_xml: str):
    """Multicast CoT XML on br-lan for local ATAK EUDs."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
    sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, 32)
    # Bind to br-lan interface
    sock.setsockopt(
        socket.IPPROTO_IP, socket.IP_MULTICAST_IF,
        socket.inet_aton(self._br_lan_ip)
    )
    sock.sendto(cot_xml.encode("utf-8"), ("239.2.3.1", 6969))
    sock.close()
```

**7. WiFi UDP Dual-Transport for TAK**

Same pattern as text messages — TAKPacket data is also broadcast via WiFi UDP between Pis for near-instant delivery. The UDP payload includes a `type: "tak"` field to distinguish from text messages:

```python
{
    "type": "tak",
    "packet_id": 12345,
    "tak_data": "<base64-encoded TAKPacket protobuf>",
    "source_ip": "10.20.1.9",
    "timestamp": "2026-04-14T18:30:00"
}
```

The existing UDP listener in meshtastic_manager.py gets extended to handle `type: "tak"` payloads in addition to `type: "text"`.

### LoRa Bandwidth Analysis

| CoT Type | Raw XML Size | TAKPacket Protobuf Size | Fits in 1 LoRa Packet? |
|----------|-------------|------------------------|----------------------|
| PLI (position) | 800-1500 bytes | 30-50 bytes | ✅ Yes (233 byte limit) |
| GeoChat (message) | 500-1000 bytes | 20-60 bytes | ✅ Yes |
| Marker (point) | 600-1200 bytes | 40-100 bytes | ✅ Yes |
| Complex CoT (detail) | 1000-3000 bytes | 100-200 bytes | ✅ Usually |

The protobuf conversion achieves **10-20x compression** vs raw CoT XML. This is why ATAK over meshtastic works at all — the TAKPacket protobuf format is designed specifically for LoRa's constraints.

### Rate Limiting Strategy

With a 6-node LoRa mesh in ROUTER mode, every packet is retransmitted by every node (up to 6 transmissions per sent packet). Airtime budget:

| Scenario | Packets/min | LoRa Transmissions/min | Acceptable? |
|----------|------------|----------------------|-------------|
| 4 EUDs, PLI every 60s | 4/min | 24/min | ✅ Good |
| 4 EUDs, PLI every 30s | 8/min | 48/min | ⚠️ Moderate |
| 4 EUDs, PLI every 10s | 24/min | 144/min | ❌ Too much |
| 4 EUDs, PLI every 60s + 2 chats/min | 6/min | 36/min | ✅ Good |

**Default: 60 seconds between PLI per callsign.** Configurable in mesh.conf.

Chat messages and markers are NOT rate-limited — they're infrequent and operationally important.

### Configuration

Add to `/etc/nucleus/mesh.conf`:

```bash
# ATAK CoT ↔ Meshtastic Bridge
MESHTASTIC_ATAK_BRIDGE=false          # Enable/disable the CoT bridge
MESHTASTIC_ATAK_PLI_INTERVAL=60       # Seconds between PLI per callsign over LoRa
MESHTASTIC_ATAK_CHANNEL=0             # Meshtastic channel for TAK data
MESHTASTIC_ATAK_MCAST_GROUP=239.2.3.1 # CoT SA multicast group
MESHTASTIC_ATAK_MCAST_PORT=6969       # CoT SA multicast port
```

### Integration with Existing Infrastructure

The ATAK bridge integrates cleanly with existing components:

1. **meshtastic_manager.py** — Uses the existing serial connection, dedup system, and UDP relay
2. **mesh-start.sh** — Already handles multicast TTL bumping for ATAK CoT on br-lan
3. **smcroute** — Already configured for multicast routing between interfaces
4. **Flask API** — New endpoints for bridge status and control:

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/api/meshtastic/atak/status` | GET | Bridge status (enabled, stats, last CoT) |
| `/api/meshtastic/atak/enable` | POST | Enable the ATAK bridge |
| `/api/meshtastic/atak/disable` | POST | Disable the ATAK bridge |

5. **CLI menu** — Status display shows ATAK bridge state alongside UDP relay state

### Deduplication

The ATAK bridge uses the same dedup mechanism as text messages:
- Each TAKPacket sent via LoRa gets a meshtastic packet ID
- That ID is registered in the existing `_seen_packets` dictionary
- WiFi UDP relay of TAK data includes the same packet ID
- Whichever transport delivers first wins; duplicates are silently discarded

Additionally, CoT-level dedup by UID + timestamp prevents re-multicast of CoT events we originally sent:
- Track CoT event UIDs we've forwarded to LoRa
- When receiving CoT from LoRa/UDP, check if it's one we originally sent
- Prevents echo loops (ATAK → Pi → LoRa → Remote Pi → WiFi UDP → back to us)

### Error Handling

- **Radio disconnected:** CoT listener still runs. CoT is forwarded via WiFi UDP only, LoRa is skipped.
- **takproto conversion fails:** Log the error, skip the event. Don't crash.
- **Multicast socket bind fails:** Log error, disable bridge gracefully. Common cause: br-lan not up yet.
- **LoRa airtime exhaustion:** Rate limiter prevents this. If queue builds up, drop oldest PLI (positions go stale fast).

---

## Implementation Order

### Phase A: CLI Menu + Messaging (quick win)

Add the Meshtastic section to `nucleus-menu.sh`:
- Options 11-16: Radio status, send message, message log, node list, listen, traceroute
- Uses existing Flask API endpoints
- Serial release/reacquire helper function for CLI-only operations

**Effort:** Low. All backend infrastructure exists. Pure bash menu integration.

### Phase B: Config Sharing (eliminates phone app for config)

Implement config menu options 17-21 in `nucleus-menu.sh`:
- Export/apply/push/fleet push/show URL
- Serial release/reacquire for meshtastic CLI commands
- Owner name stripping for fleet push
- Uses existing file transfer infrastructure (scp, pick_node)

**Effort:** Medium. Bash scripting + serial port coordination + error handling.

### Phase C: ATAK CoT Bridge (the big integration)

New module: `/opt/nucleus/meshtastic/atak_bridge.py`

**C1: Dependencies**
- Install `takproto` and `pytak`
- Add to `install-packages.sh`

**C2: CoT Listener + Converter**
- Multicast listener on `239.2.3.1:6969` (br-lan)
- takproto.xml2proto() conversion
- Rate limiter for PLI
- Unit test with captured CoT XML

**C3: LoRa Send/Receive**
- sendData with portNum=ATAK_PLUGIN (72)
- Subscribe to meshtastic.receive.data callback for portnum 72
- Dedup integration

**C4: CoT Multicast Sender**
- proto2xml() conversion
- Multicast reconstructed CoT back to 239.2.3.1:6969 on br-lan
- Source dedup (don't re-multicast our own CoT)

**C5: WiFi UDP Dual-Transport**
- Extend UDP relay to handle `type: "tak"` payloads
- Same pattern as text messages

**C6: Configuration + API**
- mesh.conf settings
- Flask API endpoints for bridge control
- CLI menu integration (bridge status in radio status display)

**C7: Testing**
- Single-node test: ATAK EUD → Pi → LoRa (verify TAKPacket sent)
- Two-node test: ATAK on node A → LoRa → ATAK on node B sees position
- Rate limit test: Multiple EUDs, verify PLI throttling works
- Dual-transport test: Verify WiFi UDP TAK relay between Pis
- Edge cases: Radio disconnect during bridge operation, CoT malformed XML

**Effort:** High. New module with multicast networking, protobuf conversion, rate limiting, dedup, dual-transport. But the architecture is clean and mirrors the proven text messaging pipeline.

---

## Dependencies

| Package | Version | Purpose | Installed? |
|---------|---------|---------|-----------|
| `meshtastic` | 2.7.8 | Radio serial control, sendData, TAKPacket protobuf | ✅ Yes |
| `takproto` | 3.0.1 | CoT XML ↔ TAKPacket protobuf conversion | ❌ Install needed |
| `pytak` | 7.3.0 | TAK network utilities, CoT helpers | ❌ Install needed |
| `sshpass` | — | Node-to-node SCP/SSH for config push | ✅ Yes |
| `pyyaml` | — | YAML config file handling | ✅ Yes (meshtastic dep) |
| `curl` | — | API calls from CLI menu | ✅ Yes |

---

## File Locations

### Existing
```
/opt/nucleus/meshtastic/meshtastic_manager.py   # Core manager (serial + UDP + dedup)
/opt/nucleus/meshtastic/meshtastic_api.py        # Flask API blueprint
/opt/nucleus/web/templates/meshtastic.html       # Web UI template
/opt/nucleus/cli/nucleus-menu.sh                 # CLI menu (to be extended)
/etc/nucleus/mesh.conf                           # Configuration (to be extended)
```

### New
```
/opt/nucleus/meshtastic/atak_bridge.py           # ATAK CoT ↔ LoRa bridge module
```

---

## Compatibility Notes

### ATAK Plugin Interop

The TAKPacket protobuf format (portnum 72) is the same format used by the official meshtastic ATAK plugin on Android. This means:
- CoT sent by our bridge will be visible to anyone running the meshtastic Android ATAK plugin
- CoT sent by Android ATAK plugin users will be received and rebroadcast by our bridge
- The formats are identical because takproto uses the same protobuf schema

### Standalone Meshtastic Radios

Meshtastic radios without ATAK support will silently ignore portnum 72 packets — standard meshtastic behavior for unhandled portnums. No interference with normal text messaging.

### OpenTAKServer Integration

If OpenTAKServer is running on the Nucleus network, the bridge could potentially also feed received LoRa CoT into OTS via its API. This is a future enhancement — the bridge's multicast output already serves ATAK EUDs directly.
