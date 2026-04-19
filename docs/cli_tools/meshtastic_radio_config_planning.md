# Meshtastic Radio Configuration via CLI — Planning

## Problem

With the CoT bridge as the default operating mode, the meshtastic radio's serial port is owned by `cot-bridge.service` on the Pi. The phone app requires BLE, which means the bridge must be disabled to use it — a chicken-and-egg problem. We need the ability to fully configure meshtastic radios from the CLI without ever touching the phone app.

This covers:
- Setting node names, channels, LoRa parameters, device role, hop limit, tx power, etc.
- Building configs from scratch (no pre-configured "golden radio" required)
- Applying configs to the local radio
- Pushing configs across the fleet

## Meshtastic Config YAML Format

The meshtastic CLI uses a YAML format for both export (`--export-config`) and import (`--configure`). The format is the same in both directions — export produces a YAML, configure consumes one.

### Top-Level Keys

```yaml
# Identity
owner: "Node-0009"              # Long name (displayed in mesh)
owner_short: "0009"             # Short name (4 chars max)

# Channels + LoRa (encoded together as a protobuf URL)
channel_url: "https://meshtastic.org/e/#CgMSAf..."

# Device config sections
config:
  bluetooth: { ... }
  device: { ... }
  display: { ... }
  lora: { ... }
  network: { ... }
  position: { ... }
  power: { ... }
  security: { ... }

# Module config sections
module_config:
  telemetry: { ... }
  mqtt: { ... }
  serial: { ... }
  external_notification: { ... }
  neighbor_info: { ... }
  audio: { ... }
  # ... others

# Optional
location:
  lat: 37.4154
  lon: -77.635
  alt: 50

canned_messages: "Copy|Wilco|Negative|En Route"
ringtone: "..."
```

### Config Sections Relevant to Nucleus

**`config.lora`** — LoRa radio parameters (must match across fleet)

| Field | Type | Natak Value | Notes |
|-------|------|-------------|-------|
| `region` | enum | `US` | Must be set correctly for legal operation. |
| `usePreset` | bool | `true` | Use a named modem preset. |
| `modemPreset` | enum | `SHORT_FAST` | Fastest data rate, shortest range. Best for CoT bridging where nodes are within a few km. |
| `hopLimit` | int | `3` | Max hops per packet. Keeps airtime low — 3 is enough for most Natak deployments. |
| `txPower` | int | `30` | Transmit power in dBm. 30 dBm = 1W, max legal for SX1262 on 915 MHz ISM. |
| `txEnabled` | bool | `true` | Must be true for the radio to transmit. |
| `sx126xRxBoostedGain` | bool | `true` | Enable RX boost on SX1262 (RAK4631 uses this chip). Better sensitivity. |

**`config.device`** — Device behavior

| Field | Type | Natak Value | Notes |
|-------|------|-------------|-------|
| `role` | enum | `TAK` | Optimized for ATAK plugin interop. See roles table below. |
| `rebroadcastMode` | enum | `LOCAL_ONLY` | Only rebroadcast packets heard directly (not relayed packets). Reduces airtime. |
| `nodeInfoBroadcastSecs` | int | `10800` | 3 hours. Node info is low priority — no need to spam the mesh. |
| `disableTripleClick` | bool | `true` | Prevents accidental triple-click actions on headless Pi-attached radios. |
| `serialEnabled` | bool | `false` | The meshtastic serial module (not USB serial). Disabled — we use USB serial for CLI/bridge. |

**`config.bluetooth`** — BLE settings

| Field | Type | Natak Value | Notes |
|-------|------|-------------|-------|
| `enabled` | bool | `true` | BLE on by default. When CoT bridge takes serial, BLE still allows phone app pairing. |
| `mode` | enum | `FIXED_PIN` | Predictable pairing for field use. |
| `fixedPin` | int | `123456` | Standard fleet PIN. Change per deployment if needed. |

**`config.position`** — Position broadcasting

| Field | Type | Natak Value | Notes |
|-------|------|-------------|-------|
| `positionBroadcastSecs` | int | `60` | 1 minute. Frequent position updates for ATAK SA. |
| `positionBroadcastSmartEnabled` | bool | `true` | Only broadcast on movement (overrides interval when stationary). |
| `broadcastSmartMinimumDistance` | int | `100` | Meters. Minimum movement before a smart broadcast triggers. |
| `broadcastSmartMinimumIntervalSecs` | int | `60` | Minimum seconds between smart broadcasts. |
| `positionFlags` | int | `777` | Bitmask controlling which position fields to include. |
| `gpsEnabled` | bool | `false` | RAK4631 has no GPS. Position comes from ATAK via the bridge (`LOC_EXTERNAL`). |

**`config.power`** — Power management

| Field | Type | Natak Value | Notes |
|-------|------|-------------|-------|
| `waitBluetoothSecs` | int | `60` | Seconds to wait for BLE connection before entering power save. |
| `sdsSecs` | int | `4294967295` | Super deep sleep timeout — max value = never. Pi keeps radio powered. |
| `lsSecs` | int | `300` | Light sleep timeout (seconds). |
| `minWakeSecs` | int | `10` | Minimum awake time after activity. |
| `isPowerSaving` | bool | `false` | Power saving off — radio should always be awake on Pi power. |

**`config.security`** — Encryption and access

| Field | Type | Natak Value | Notes |
|-------|------|-------------|-------|
| `publicKey` | base64 | (per-node) | Auto-generated. Unique per radio. |
| `privateKey` | base64 | (per-node) | Auto-generated. Never push between nodes. |
| `serialEnabled` | bool | `true` | Allow USB serial access. Required for CLI and bridge. |
| `adminKey` | list[base64] | `[]` | No admin channel keys set. |
| `adminChannelEnabled` | bool | `false` | Admin channel not used. |

### Module Config Relevant to Nucleus

**`module_config.mqtt`** — MQTT bridge (currently disabled)

| Field | Type | Natak Value | Notes |
|-------|------|-------------|-------|
| `enabled` | bool | `false` | MQTT not active. Pre-configured for future use. |
| `address` | string | `100.94.34.37` | Tailscale IP of MQTT broker (TAK Server). |
| `root` | string | `natak` | MQTT topic root. |
| `encryptionEnabled` | bool | `true` | Encrypt MQTT payloads. |
| `proxyToClientEnabled` | bool | `true` | Allow MQTT proxy to connected clients. |

**`module_config.externalNotification`** — LED/buzzer alerts

| Field | Type | Natak Value | Notes |
|-------|------|-------------|-------|
| `enabled` | bool | `true` | External notification active. |
| `output` | int | `36` | GPIO pin for notification output (RAK4631 LED). |
| `outputMs` | int | `1000` | Notification pulse duration in ms. |
| `active` | bool | `true` | Active high output. |
| `alertMessage` | bool | `true` | Alert on incoming messages. |
| `nagTimeout` | int | `60` | Seconds before repeating unacknowledged alert. |

**`module_config.cannedMessage`** — Pre-configured quick messages

| Field | Type | Natak Value | Notes |
|-------|------|-------------|-------|
| `enabled` | bool | `true` | Canned message module active. |

### Device Roles

The role determines how the radio handles mesh traffic:

| Role | Behavior | Use Case |
|------|----------|----------|
| `CLIENT` | Normal node. Sends own packets, forwards others. | General-purpose nodes |
| `CLIENT_MUTE` | Receives but doesn't transmit. | Monitoring/listen-only |
| `ROUTER` | Prioritizes forwarding. Stays awake, doesn't sleep. Always retransmits. | Dedicated relay infrastructure |
| `ROUTER_CLIENT` | Like ROUTER but also participates as a normal client. | Infrastructure + messaging |
| `REPEATER` | Pure relay — no display, no local processing. | Unattended relay sites |
| **`TAK`** | **Optimized for ATAK plugin interop. Handles TAK packets (portnum 257) natively. Reduced overhead for non-TAK traffic. Stays awake.** | **Nucleus fleet nodes running CoT bridge** |

Nucleus nodes use the `TAK` role. This role is purpose-built for nodes that bridge ATAK CoT over LoRa using the meshtastic ATAK plugin protocol (TAKPacketV2, portnum 257 ATAK_FORWARDER). It ensures proper handling of TAK-format packets and interoperability with Android ATAK plugin users on the same mesh.

### The Channel URL

The `channel_url` encodes:
- All channel settings (PRIMARY + SECONDARY): name, PSK (encryption key), uplink/downlink
- LoRa modem config: preset, region, hop limit

This is the **same data** as the phone app's QR code. `--ch-set-url` and `channel_url` in the YAML both call `node.setURL()`, which deserializes the protobuf and writes channels + LoRa config to the radio.

All nodes in a fleet **must share the same channel_url** to communicate. Node names, device role, power settings, etc. can differ per node.

---

## Two Approaches to Building Config

### Approach A: Template-Based (Build from Scratch)

Maintain a Natak template YAML in the repo with all standard fleet settings. Per-node customization (owner name) is applied at deploy time.

**Template file:** `etc/nucleus/meshtastic-config.yaml.template`

```yaml
# Natak Meshtastic Fleet Config Template
# Per-node values filled in by CLI at deploy time:
#   owner, owner_short

channel_url: "CHANNEL_URL_HERE"

config:
  lora:
    region: US
    usePreset: true
    modemPreset: SHORT_FAST
    hopLimit: 3
    txPower: 30
    txEnabled: true
    sx126xRxBoostedGain: true
  device:
    role: TAK
    rebroadcastMode: LOCAL_ONLY
    nodeInfoBroadcastSecs: 10800
    disableTripleClick: true
    serialEnabled: false
  bluetooth:
    enabled: true
    mode: FIXED_PIN
    fixedPin: 123456
  position:
    positionBroadcastSecs: 60
    positionBroadcastSmartEnabled: true
    broadcastSmartMinimumDistance: 100
    broadcastSmartMinimumIntervalSecs: 60
    positionFlags: 777
    gpsEnabled: false
  power:
    waitBluetoothSecs: 60
    sdsSecs: 4294967295
    lsSecs: 300
    minWakeSecs: 10
    isPowerSaving: false
  security:
    serialEnabled: true

module_config:
  mqtt:
    enabled: false
    address: "100.94.34.37"
    root: "natak"
    encryptionEnabled: true
    proxyToClientEnabled: true
  externalNotification:
    enabled: true
    output: 36
    outputMs: 1000
    active: true
    alertMessage: true
    nagTimeout: 60
  cannedMessage:
    enabled: true
```

**Workflow:**
1. Edit the template once with your fleet's LoRa settings
2. Generate a channel URL (from one configured radio, or build manually)
3. CLI menu: "Build config" → prompts for node name → fills template → saves YAML
4. Apply to local radio or push to fleet

**Pros:** No pre-configured radio needed. Reproducible. Version-controlled.
**Cons:** Must manually set the channel_url (either from an existing radio or by constructing it).

### Approach B: Export from Golden Radio

Configure one radio (the "golden" node) using CLI `--set` commands, then export and distribute.

**Workflow:**
1. Set individual fields on one radio: `meshtastic --set lora.region US`, `--set device.role ROUTER`, etc.
2. Set channels: `meshtastic --ch-set-url <url>` or configure channel names/PSK individually
3. Export: `meshtastic --export-config ~/transfer/natak-fleet.yaml`
4. Strip `owner`/`owner_short` for fleet push (preserve per-node names)
5. Push to other nodes

**Pros:** What-you-see-is-what-you-get. Radio validates settings in real time.
**Cons:** Requires one radio to be manually configured first. Export includes everything, some of which you may not want to push (security keys, position).

### Recommendation: Both

Support both approaches in the CLI. Template-based for initial fleet deployment and standardization. Export-based for ongoing config management and cloning.

---

## The `--set` Individual Field Interface

For quick one-off changes without a full YAML:

```bash
meshtastic --set lora.region US
meshtastic --set lora.hop_limit 5
meshtastic --set device.role ROUTER
meshtastic --set bluetooth.enabled false
meshtastic --set-owner "Node-0009"
meshtastic --set-owner-short "0009"
```

Each `--set` command opens a serial connection, writes the setting, and triggers a settings transaction. Multiple `--set` in one command line are supported but "may be less reliable when setting properties from more than one configuration section" (per meshtastic docs). Using `--begin-edit` / `--commit-edit` can batch changes.

For the CLI menu, individual `--set` is useful for:
- Quick field changes during debugging
- Setting node name on a new radio before full config
- Changing a single setting without disturbing everything else

---

## Serial Port Management

### The `mesh_cli_run` Helper

All meshtastic CLI operations go through a single helper that handles bridge stop/start:

```bash
mesh_cli_run() {
    local bridge_was_running=false
    if systemctl is-active --quiet cot-bridge.service; then
        bridge_was_running=true
        printf "  ${DIM}Stopping CoT bridge...${RESET}\n"
        sudo systemctl stop cot-bridge.service
        sleep 2  # Wait for serial release
    fi

    "$@"
    local rc=$?

    if $bridge_was_running; then
        printf "  ${DIM}Restarting CoT bridge...${RESET}\n"
        sudo systemctl start cot-bridge.service
    fi
    return $rc
}
```

**Bridge running:** Stop service → wait for serial release → run command → restart service.
**Bridge not running:** Run command directly. No interference.

The 2-second sleep after stop is needed because the meshtastic SerialInterface takes a moment to fully release the port after the process exits.

### Remote Operations

For push-to-node and fleet push, the same pattern runs on the remote node via SSH:

```bash
remote_mesh_cli_run() {
    local host="$1"; shift
    remote_ssh "$host" "
        bridge_was_running=false
        if systemctl is-active --quiet cot-bridge.service; then
            bridge_was_running=true
            sudo systemctl stop cot-bridge.service
            sleep 2
        fi
        $@
        rc=\$?
        if \$bridge_was_running; then
            sudo systemctl start cot-bridge.service
        fi
        exit \$rc
    "
}
```

### Sudoers

The `natak` user already has passwordless sudo for `systemctl start/stop/enable/disable cot-bridge.service` (in `/etc/sudoers.d/nucleus-config`). No additional sudoers changes needed.

---

## CLI Menu Design

New "Meshtastic" section added to `nucleus-menu.sh`:

```
  Meshtastic
   11) Radio Info
   12) Export Config
   13) Build Config from Template
   14) Apply Config from File
   15) Push Config to Node
   16) Push Config to ALL Nodes
   17) Set Individual Field
   18) Channel URL / QR
```

### 11) Radio Info

```bash
mesh_cli_run meshtastic --info
```

Shows: node name, node ID, firmware version, channels, LoRa settings, known nodes. Quick sanity check.

### 12) Export Config

```bash
mesh_cli_run meshtastic --export-config "$TRANSFER_DIR/natak-mesh.yaml"
printf "  Config saved to ~/transfer/natak-mesh.yaml\n"
```

Dumps the connected radio's full config to the transfer staging directory. Ready for inspection, editing, or push to other nodes.

### 13) Build Config from Template

Interactive flow:
1. Read the template from `etc/nucleus/meshtastic-config.yaml.template`
2. Prompt for node name (long + short)
3. If template has `CHANNEL_URL_HERE` placeholder, prompt for channel URL or offer to read from connected radio
4. Write completed YAML to `~/transfer/<node-name>.yaml`

```bash
do_mesh_build_config() {
    local template="/opt/nucleus/etc/meshtastic-config.yaml.template"
    # ... or wherever we put it
    
    printf "  Node long name (e.g. Node-0009): "
    read -r long_name
    printf "  Node short name (4 chars, e.g. 0009): "
    read -r short_name
    
    # Read template, inject owner fields
    # If channel_url is placeholder, prompt or read from radio
    # Write to ~/transfer/
}
```

### 14) Apply Config from File

```bash
pick_file "$TRANSFER_DIR" "Config file to apply"
# Prompt: "This will overwrite radio config. Continue? (y/N)"
# Prompt: "Apply node name from file? (y/N)" — if no, strip owner fields
mesh_cli_run meshtastic --configure "$PICKED_FILE"
```

Shows what's about to be applied (at minimum the filename). Asks for confirmation. Optionally strips owner/owner_short to preserve the existing node name.

### 15) Push Config to Node

Interactive flow:
1. Pick a config file from `~/transfer/` (or export first)
2. `pick_node` to select target
3. Prompt: "Preserve target's node name? (Y/n)"
4. If preserving, strip owner/owner_short from a temp copy
5. SCP the YAML to target's `~/transfer/`
6. SSH to target, stop bridge if running, run `meshtastic --configure`, restart bridge

### 16) Push Config to ALL Nodes

Fleet deployment:
1. Pick a config file from `~/transfer/` (or export first)
2. Prompt: push mode
   ```
     1) Settings + channels (preserve node names)  [default]
     2) Full config (overwrite node names)
     3) Channel URL only (fastest — channels + LoRa only)
   ```
3. Enumerate Babel mesh peers
4. For each peer: SCP + SSH apply
5. Report success/failure per node

For mode 1 (default): strip `owner`/`owner_short` from the YAML before pushing.
For mode 3: extract just the `channel_url` from the YAML, use `meshtastic --ch-set-url` on each node.

### 17) Set Individual Field

Interactive wrapper around `meshtastic --set`:

```bash
do_mesh_set_field() {
    echo ""
    printf "  ${BOLD}Common fields:${RESET}\n"
    printf "   ${CYAN}1${RESET}  lora.region\n"
    printf "   ${CYAN}2${RESET}  lora.modem_preset\n"
    printf "   ${CYAN}3${RESET}  lora.hop_limit\n"
    printf "   ${CYAN}4${RESET}  device.role\n"
    printf "   ${CYAN}5${RESET}  bluetooth.enabled\n"
    printf "   ${CYAN}6${RESET}  Node name (owner + owner_short)\n"
    printf "   ${CYAN}7${RESET}  Custom field\n"
    echo ""
    printf "  Select: "
    read -r field_choice
    
    # For each choice, prompt for value, run meshtastic --set
}
```

Provides shortcuts for the most common settings. Option 7 lets the user type any `section.field value` pair directly.

### 18) Channel URL / QR

```bash
mesh_cli_run meshtastic --qr-all
```

Displays the shareable channel URL(s) and terminal QR code. For verifying all nodes match or sharing with phone app users who still need BLE access.

---

## Fleet Config Workflow

### Initial Deployment (Zero to Fleet)

**Step 1: Create the fleet config**

Option A — Template:
```
Menu → 13) Build Config from Template
  Node long name: Node-0009
  Node short name: 0009
  Channel URL: (paste URL or "read from radio")
  → Saved to ~/transfer/Node-0009.yaml
```

Option B — Golden radio:
```
# Configure one radio manually
Menu → 17) Set Individual Field → set region, role, hop limit, etc.
Menu → 12) Export Config
  → Saved to ~/transfer/natak-mesh.yaml
```

**Step 2: Apply to local radio**
```
Menu → 14) Apply Config from File
  → Select natak-mesh.yaml
  → Applied. Radio reboots.
```

**Step 3: Push to all other nodes**
```
Menu → 16) Push Config to ALL Nodes
  → Mode: 1 (preserve node names)
  → Pushing to 10.20.1.8... OK
  → Pushing to 10.20.1.10... OK
  → Pushing to 10.20.1.11... OK
  → Fleet config complete.
```

**Step 4: Verify**
```
Menu → 18) Channel URL / QR
  → Verify URL matches on each node
```

### Reconfiguration (Changing Fleet Settings)

When you need to change a fleet-wide setting (e.g., hop limit, modem preset):

**Option A:** Change on one node, export, push to all:
```
Menu → 17) Set Individual Field → lora.hop_limit → 7
Menu → 12) Export Config
Menu → 16) Push Config to ALL Nodes (mode 1)
```

**Option B:** Edit the template, rebuild, push:
```
Edit template → change hop_limit to 7
Menu → 13) Build Config from Template
Menu → 16) Push Config to ALL Nodes (mode 1)
```

---

## Natak Standard Config

Production settings for Nucleus fleet radios (RAK4631 on Pi). These values are taken from a live deployed node (`0022-nucleus`, firmware 2.7.15).

```yaml
config:
  lora:
    region: US
    usePreset: true
    modemPreset: SHORT_FAST        # Fastest data rate — optimized for CoT throughput over range
    hopLimit: 3                    # 3 hops max — keeps airtime low
    txPower: 30                    # 30 dBm = 1W, max legal for 915 MHz ISM
    txEnabled: true
    sx126xRxBoostedGain: true      # Better RX sensitivity on SX1262
  device:
    role: TAK                      # Optimized for ATAK plugin interop (portnum 257)
    rebroadcastMode: LOCAL_ONLY    # Only rebroadcast direct-heard packets
    nodeInfoBroadcastSecs: 10800   # 3 hours — node info is low priority
    disableTripleClick: true       # No accidental actions on headless radios
    serialEnabled: false           # Meshtastic serial module off (USB serial still works)
  bluetooth:
    enabled: true                  # BLE on — allows phone app pairing alongside bridge
    mode: FIXED_PIN
    fixedPin: 123456               # Standard fleet PIN
  position:
    positionBroadcastSecs: 60      # 1 min — frequent updates for ATAK SA
    positionBroadcastSmartEnabled: true
    broadcastSmartMinimumDistance: 100   # Meters before smart broadcast triggers
    broadcastSmartMinimumIntervalSecs: 60
    positionFlags: 777
    gpsEnabled: false              # No GPS on RAK4631 — position from ATAK (LOC_EXTERNAL)
  power:
    waitBluetoothSecs: 60
    sdsSecs: 4294967295            # Never deep sleep — Pi keeps radio powered
    lsSecs: 300
    minWakeSecs: 10
    isPowerSaving: false           # Always awake
  security:
    serialEnabled: true            # USB serial access required for CLI and bridge

module_config:
  mqtt:
    enabled: false                 # Pre-configured but not active
    address: "100.94.34.37"        # Tailscale IP of MQTT broker
    root: "natak"
    encryptionEnabled: true
    proxyToClientEnabled: true
  externalNotification:
    enabled: true
    output: 36                     # RAK4631 LED GPIO
    outputMs: 1000
    active: true
    alertMessage: true
    nagTimeout: 60
  cannedMessage:
    enabled: true
```

### Channel Config

Primary channel: `natak` with PSK encryption and `positionPrecision: 32`.

```
Channel URL: https://meshtastic.org/e/#Ci0SIHwnHCE2Bak8zZ4DAUTDF673K6UMm5v0JBHXGOlEycoWGgVuYXRhazoCCCASDggBEAY4AUADSAFQHmgB
```

All fleet nodes must share this channel URL. It encodes the channel name, PSK, LoRa modem preset, region, and hop limit.

---

## Timing and Radio Reboots

- `--configure` triggers a radio reboot via `commitSettingsTransaction`. Budget 5-10 seconds per node.
- `--set` also triggers a config write + reboot for most settings.
- `--ch-set-url` writes channels + LoRa config and reboots.
- After reboot, the serial port reappears in 2-3 seconds. The bridge service (if restarted) will reconnect automatically.
- For fleet push, the serial stop/configure/restart cycle per node takes roughly 15-20 seconds. A 6-node fleet push takes about 2 minutes.

## YAML Manipulation

For stripping owner fields and extracting channel URLs, we use simple tools already available:

```bash
# Strip owner/owner_short from YAML (for fleet push preserving names)
grep -v "^owner" config.yaml > config-noname.yaml

# Extract channel URL from YAML
grep "channel_url:" config.yaml | awk '{print $2}'
```

For more complex YAML manipulation (template substitution), Python's `pyyaml` is available (installed as a meshtastic dependency).

## Dependencies

All already installed on every Nucleus node:
- `meshtastic` CLI (v2.7.15) — serial config tool
- `sshpass` — node-to-node SSH/SCP
- `pyyaml` — YAML manipulation (meshtastic dependency)
- `curl` — not needed (old API pattern removed)

## Files

### New
```
etc/nucleus/meshtastic-config.yaml.template  # Fleet config template
```

### Modified
```
opt/nucleus/cli/nucleus-menu.sh              # Add Meshtastic menu section
etc/sudoers.d/nucleus-config                 # Already has cot-bridge permissions
```

### Reference
```
docs/cli_tools/meshtastic_config_sharing.md  # Earlier planning (to be superseded by this doc)
docs/cli_tools/meshtastic_full_integration.md # Overall integration status
```
