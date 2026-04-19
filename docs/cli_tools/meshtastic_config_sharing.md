# Meshtastic Config Sharing via CLI — Planning

## Problem

Configuring meshtastic radios across a fleet of Nucleus nodes currently requires the phone app's QR code / URL channel sharing feature. This creates a dependency on Bluetooth, a phone, and manual per-node interaction — a bottleneck for deployment and reconfiguration in the field.

The Nucleus CLI already has file transfer capability (scp between nodes via `~/transfer/`). If we can export a radio's config to a file, transfer it, and apply it on the target — we eliminate the phone app dependency entirely.

## Discovery: The Meshtastic CLI Already Supports This

The meshtastic Python CLI (v2.7.8, installed on every Nucleus node) has built-in config export/import:

### Export — `--export-config`

```bash
meshtastic --export-config ~/transfer/natak-mesh.yaml
```

Dumps the **entire** radio configuration as YAML:
- `owner` / `owner_short` — node name
- `channel_url` — base64-encoded protobuf `ChannelSet` (same data the QR code encodes: all channel settings + LoRa modem config)
- `config` — all `localConfig` sections: lora, bluetooth, device, display, network, position, power, security
- `module_config` — all module settings: mqtt, serial, external notification, telemetry, canned message, audio, neighbor info, etc.
- `location` — fixed position (lat/lon/alt)
- `canned_messages`, `ringtone`

### Import — `--configure`

```bash
meshtastic --configure ~/transfer/natak-mesh.yaml
```

Reads the YAML and writes every setting to the connected radio. The implementation (in `meshtastic/__main__.py`) processes each section:
1. Opens a settings transaction (`beginSettingsTransaction`)
2. Sets `owner` / `owner_short` if present
3. Applies `channel_url` via `setURL()` — **this is the QR code equivalent**
4. Walks `config` sections and writes each via `writeConfig()`
5. Walks `module_config` sections and writes each via `writeConfig()`
6. Sets `location` (fixed position) if present
7. Commits the transaction (`commitSettingsTransaction`)

### Channel URL Only — `--ch-set-url`

```bash
meshtastic --ch-set-url "https://meshtastic.org/e/#CgMSAf..."
```

If only channel/LoRa sync is needed (not full device config), this applies just the channel URL — identical to scanning a QR code in the phone app.

### Show Channel URL — `--qr`

```bash
meshtastic --qr          # Primary channel URL + QR
meshtastic --qr-all      # All channels URL + QR
```

Outputs the shareable URL (and terminal QR code). Useful for verifying config or sharing with phone app users.

## What the Channel URL Contains

From `node.py:getURL()`, the URL encodes a protobuf `ChannelSet` containing:
- **Channel settings** for all PRIMARY + SECONDARY channels: name, PSK (encryption key), uplink/downlink enabled
- **LoRa config**: modem preset, region, hop limit, tx power, frequency offset, etc.

The URL format is: `https://meshtastic.org/e/#{base64_urlsafe(protobuf_bytes)}`

This is identical to what the phone app's QR code encodes. `--ch-set-url` and the YAML's `channel_url` field both call `node.setURL()`, which deserializes the protobuf and writes each channel + LoRa config to the radio.

## Existing Infrastructure

### CLI File Transfer (nucleus-menu.sh option 8)

Already operational:
- Staging directory: `~/transfer/` on every node
- Send file to another node (SCP via sshpass)
- Receive file from another node
- `pick_node()` helper lists Babel mesh peers for easy node selection
- `remote_ssh()` / `remote_scp_to()` / `remote_scp_from()` helpers for node-to-node operations

### Meshtastic Serial Control (meshtastic_manager.py)

The Nucleus meshtastic module manages serial connection state. The `meshtastic` CLI tool also connects via serial. **Important:** only one process can hold the serial port at a time (`exclusive=True`). The CLI menu operations will need to either:
- Temporarily release serial control (disconnect via web UI / API) before running `meshtastic --configure`
- Or use the Python API directly within `meshtastic_manager.py` (avoids the serial contention issue since the manager already holds the connection)

## Proposed Design: Meshtastic Config Menu

### New Menu Section in `nucleus-menu.sh`

Add a "Meshtastic Config" section to the CLI menu:

```
  Meshtastic Config
   M1) Export radio config to file
   M2) Apply config from file
   M3) Push config to another node
   M4) Push config to ALL mesh nodes
   M5) Show channel URL
```

### M1: Export Radio Config

```bash
# Disconnect meshtastic_manager if running (release serial port)
# Then:
meshtastic --export-config ~/transfer/natak-mesh.yaml
```

Saves full config YAML to the transfer staging directory, ready for transfer.

**Serial port consideration:** If the web app's meshtastic_manager holds the serial port, we need to release it first. Options:
- `curl -X POST localhost:5000/api/meshtastic/disconnect` (if web app is running)
- Or detect if port is locked and warn the user
- After export, user can reconnect via web UI

### M2: Apply Config from File

```bash
# List available config files in ~/transfer/
# User picks one
meshtastic --configure ~/transfer/natak-mesh.yaml
```

Applies a previously-exported (or hand-edited) config to the local radio.

**Per-node customization:** Before applying, the script should warn that `owner`/`owner_short` in the file will overwrite the local node name. Options:
- Strip `owner`/`owner_short` before applying (preserve local names)
- Prompt: "Apply node name from file? (y/N)"
- Or create a "channels-only" mode that extracts just the `channel_url` and uses `--ch-set-url`

### M3: Push Config to Another Node

Interactive flow:
1. Export local config → `~/transfer/natak-mesh.yaml`
2. `pick_node()` — user selects target
3. SCP the YAML to target node's `~/transfer/`
4. SSH to target, run `meshtastic --configure ~/transfer/natak-mesh.yaml`

```bash
# Pseudocode
meshtastic --export-config ~/transfer/natak-mesh.yaml
pick_node "Push config to"
remote_scp_to ~/transfer/natak-mesh.yaml "$PICKED_NODE" ~/transfer/
remote_ssh "$PICKED_NODE" "meshtastic --configure ~/transfer/natak-mesh.yaml"
```

### M4: Push Config to ALL Mesh Nodes

The fleet deployment command:
1. Export local config → `~/transfer/natak-mesh.yaml`
2. Enumerate all Babel mesh peers
3. For each peer: SCP + SSH apply
4. Report success/failure per node

```bash
# Pseudocode
meshtastic --export-config ~/transfer/natak-mesh.yaml
nodes=($(ip route show proto babel | grep -oP 'via \K[0-9.]+' | sort -u))
for node in "${nodes[@]}"; do
    echo "Pushing to $node..."
    remote_scp_to ~/transfer/natak-mesh.yaml "$node" ~/transfer/
    remote_ssh "$node" "meshtastic --configure ~/transfer/natak-mesh.yaml"
done
```

**Owner name handling for fleet push:** When pushing to all nodes, we almost certainly do NOT want to overwrite each node's name. The script should:
1. Load the YAML
2. Strip `owner` and `owner_short` fields
3. Save as a temp file (e.g., `natak-mesh-noname.yaml`)
4. Push the stripped version

Or offer a choice:
```
  Push config to all nodes:
   1) Channels + settings only (preserve node names)
   2) Full config including node names
   3) Channel URL only (fastest, channels + LoRa only)
```

### M5: Show Channel URL

```bash
meshtastic --qr-all
```

Displays the shareable channel URL(s) in the terminal. Useful for:
- Verifying all nodes are on the same channel config
- Sharing with phone app users who need the URL/QR code
- Quick comparison between nodes

## Config File Variants

For flexibility, we could maintain multiple config file types:

| File | Contents | Use Case |
|------|----------|----------|
| `natak-mesh.yaml` | Full export from `--export-config` | Complete radio clone |
| `natak-channels.yaml` | Just `channel_url` field | Channel sync only (like QR) |
| `natak-fleet.yaml` | Full config minus `owner`/`owner_short` | Fleet push (preserves names) |

The export could generate all three automatically:
```bash
# Full export
meshtastic --export-config ~/transfer/natak-mesh.yaml

# Generate channels-only variant
grep "channel_url:" ~/transfer/natak-mesh.yaml > ~/transfer/natak-channels.yaml

# Generate fleet variant (strip owner fields)
grep -v "^owner" ~/transfer/natak-mesh.yaml > ~/transfer/natak-fleet.yaml
```

## Serial Port Contention Strategy

The meshtastic CLI and `meshtastic_manager.py` both need exclusive serial access. Two approaches:

### Approach A: Release-and-Reacquire (Simple)

1. Before any meshtastic CLI operation, check if the web app's manager holds the port
2. If yes, call the disconnect API: `curl -s -X POST localhost:5000/api/meshtastic/disconnect`
3. Wait for release (1-2 seconds)
4. Run the meshtastic CLI command
5. Optionally reconnect: `curl -s -X POST localhost:5000/api/meshtastic/connect`

Pros: Simple, uses existing infrastructure.
Cons: Briefly interrupts the web UI's serial connection. Messages received during the gap would be missed on LoRa (UDP listener still works).

### Approach B: Python API Integration (Cleaner)

Add export/import methods directly to `meshtastic_manager.py` that operate while the manager holds the connection:

```python
def export_config(self, path: str) -> Dict:
    """Export current radio config to YAML file."""
    if self.interface is None:
        return {"success": False, "error": "Not connected"}
    from meshtastic.__main__ import export_config
    config_txt = export_config(self.interface)
    with open(path, "w") as f:
        f.write(config_txt)
    return {"success": True, "path": path}

def apply_config(self, path: str) -> Dict:
    """Apply a YAML config file to the radio."""
    # Uses the same logic as meshtastic --configure
    # but through the existing serial connection
    ...
```

Pros: No serial port contention, no interruption to messaging.
Cons: More code to write and maintain, duplicates meshtastic CLI logic.

### Recommendation: Start with Approach A

Approach A is immediate and uses proven tools. The serial release/reacquire takes 2-3 seconds and the web app handles reconnection gracefully. Move to Approach B later if the interruption becomes a problem in practice.

## Implementation Order

### Phase 1: Basic Export/Apply (Local Only)
- Add Meshtastic Config section to `nucleus-menu.sh`
- M1: Export config (with serial release/reacquire)
- M2: Apply config from file
- M5: Show channel URL
- **Test:** Export from one radio, apply to another via manual file copy

### Phase 2: Node-to-Node Push
- M3: Push to specific node (export → SCP → SSH apply)
- Handle serial port release on remote node too
- **Test:** Push from node A to node B via the menu

### Phase 3: Fleet Push
- M4: Push to all nodes with owner-name handling
- Progress reporting per node
- Error handling (node unreachable, serial port busy, etc.)
- **Test:** Configure one radio, push to entire mesh in one operation

### Phase 4: Polish
- Config file variants (full / channels-only / fleet)
- Pre-flight comparison: "These settings will change: ..." before applying
- Web UI integration: export/import buttons on the meshtastic page
- API endpoints for remote config operations

## Dependencies

- `meshtastic` CLI (v2.7.8) — ✅ already installed
- `sshpass` — ✅ already installed (used by file transfer)
- `pyyaml` — ✅ already installed (meshtastic dependency)
- `curl` — ✅ already installed (for serial port release via API)
- Serial port access to radio — ✅ (with release/reacquire pattern)

## Notes

- The `--configure` command triggers a radio reboot after writing config (the `commitSettingsTransaction` causes this). Budget 5-10 seconds per node for the radio to come back online after config push.
- The channel URL in the YAML is the **exact same data** as the QR code. There is zero functional difference between scanning a QR code and applying a YAML with `channel_url`.
- Remote node config push (`--dest !nodeId`) is NOT supported for `--export-config` (the meshtastic CLI explicitly checks and rejects this). Config must be applied locally on each node via SSH.
