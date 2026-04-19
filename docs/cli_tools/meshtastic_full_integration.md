# Full Meshtastic Integration into Nucleus — Status & Planning

## Goal

Integrate meshtastic fully into Nucleus OS so that **no phone app is needed** for any meshtastic operation: ATAK CoT bridging over LoRa, radio configuration (including fleet-wide sharing), and future messaging. Everything is accessible from the web UI and CLI menu.

## System Context

- **Radios:** RAK4631 (nRF52840 + SX1262 LoRa) — no WiFi/Ethernet on the radio
- **Compute:** Raspberry Pi 4 — each Pi has a RAK4631 connected via USB serial
- **WiFi Mesh:** 802.11s mesh between all Pis (same broadcast domain, 10.20.1.x/24)
- **ATAK:** EUDs connect to Pi via br-lan (WiFi AP or Ethernet), send CoT multicast on 239.2.3.1:6969 and 224.10.10.1:17012

Every Nucleus node is a Pi + RAK4631 pair. The Pis form an 802.11s WiFi mesh for high-bandwidth local networking. The RAK4631 radios form an independent LoRa mesh for long-range, low-bandwidth CoT bridging. The Pi is the bridge between the two networks.

---

## Radio Operating Modes

The meshtastic radio has two mutually exclusive modes, controlled by a single config flag in `/etc/nucleus/mesh.conf`:

| Mode | Config Value | What Happens |
|---|---|---|
| **BLE** (default) | `COT_BRIDGE_ENABLED=false` | Radio left alone. Phone app works via Bluetooth. Nothing touches serial. |
| **Bridge** | `COT_BRIDGE_ENABLED=true` | `cot-bridge.service` runs. ATAK CoT bridges bidirectionally over LoRa. Serial port owned exclusively by the bridge daemon. |

The toggle is available in the web UI (meshtastic page) and takes effect immediately — no reboot required to enable. Disabling triggers a reboot to fully release the radio back to Bluetooth.

---

## What's Built

### ATAK CoT ↔ LoRa Bridge

Fully implemented and tested bidirectionally between two nodes.

| Component | Location |
|-----------|----------|
| CoT bridge daemon (bidirectional TX+RX) | `/opt/nucleus/meshtastic/cot_bridge.py` |
| TakMessage → CoT XML glue function | `/opt/nucleus/meshtastic/takmessage_to_xml.py` |
| Flask API — bridge status/enable/disable | `/opt/nucleus/meshtastic/meshtastic_api.py` |
| Web UI — radio detection, BLE↔Bridge toggle, service status | `/opt/nucleus/web/templates/meshtastic.html` |
| Systemd service | `/etc/systemd/system/cot-bridge.service` |
| Configuration flag | `/etc/nucleus/mesh.conf` (`COT_BRIDGE_ENABLED`) |
| Sudoers for service control | `/etc/sudoers.d/nucleus-config` |
| Udev rules (prevent mtp-probe crash) | `/etc/udev/rules.d/60-meshtastic.rules` |
| ATAK multicast TTL handling | `/opt/nucleus/bin/mesh-start.sh` |

### Other Existing Infrastructure

| Component | Location |
|-----------|----------|
| CLI menu — system monitoring, network testing, file transfer, reticulum | `/opt/nucleus/cli/nucleus-menu.sh` |
| File transfer — scp between nodes via ~/transfer/ | nucleus-menu.sh |

### Not Yet Built

| Component | Notes |
|-----------|-------|
| CLI menu — Meshtastic config section | Planned (see below) |
| Config sharing — export/apply/push via CLI | Planned (see `meshtastic_config_sharing.md`) |
| LoRa text messaging (standalone, non-ATAK) | Shelved (see archived meshtastic_manager.py) |
| Canned messages / quick send | Shelved |
| Codec2 voice notes | Shelved |

---

## Bridge Architecture

### Data Flow

**TX (local ATAK → LoRa):**
```
ATAK EUD → multicast CoT (TAK Protocol V1) → br-lan
  → cot_bridge.py multicast listener (SA 239.2.3.1:6969 + Chat 224.10.10.1:17012)
  → takproto parse_proto() → TakMessage → takmessage_to_xml() → CoT XML
  → meshtastic-tak CotXmlParser.parse() → TAKPacketV2
  → TakCompressor.compress() (zstd dictionary compression)
  → sendData(portNum=257 ATAK_FORWARDER) → LoRa mesh
```

**RX (LoRa → local ATAK):**
```
LoRa mesh → pypubsub callback (portnum ATAK_FORWARDER)
  → TakCompressor.decompress() → TAKPacketV2
  → CotXmlBuilder.build() → CoT XML
  → multicast inject on br-lan (SA or Chat group) → ATAK EUDs
```

### Key Features

- **30s per-UID rate limiting** — prevents LoRa airtime saturation from frequent PLI updates
- **Loop prevention** — tracks recently RX'd UIDs to avoid re-TX back to LoRa
- **Self-packet filtering** — ignores packets originated by this node
- **SA + Chat multicast** — bridges both position/marker traffic and GeoChat
- **Standalone daemon** — owns serial port exclusively, no contention with other processes

### Why Not WiFi UDP Dual-Transport for TAK?

The original planning doc proposed WiFi UDP relay for TAK data (same pattern as the text messaging system). This was **not implemented** because it's unnecessary — ATAK CoT already flows natively over the 802.11s IP mesh via smcroute/babeld multicast routing. The bridge's sole purpose is extending CoT reach beyond WiFi range via LoRa.

### Interoperability

- **Meshtastic ATAK plugin (Android):** Uses the same portnum 257 (ATAK_FORWARDER) and TAKPacketV2 format. Android ATAK plugin users and Nucleus bridge nodes see each other's CoT.
- **Standalone meshtastic radios:** Silently ignore portnum 257 packets — no interference with normal text messaging.

---

## API Endpoints

The meshtastic API (`meshtastic_api.py`) is a Flask Blueprint registered in the main web app:

| Endpoint | Method | Description |
|---|---|---|
| `/api/meshtastic/status` | GET | Bridge enabled (config), service running/enabled, radio detected |
| `/api/meshtastic/bridge/enable` | POST | Write config + enable + start cot-bridge.service |
| `/api/meshtastic/bridge/disable` | POST | Stop + disable cot-bridge.service + write config + reboot |

---

## Dependencies

| Package | Version | Purpose |
|---------|---------|---------|
| `meshtastic` | 2.7.8 | Radio serial interface, sendData, protobuf definitions |
| `takproto` | 3.0.1 | TAK Protocol V1 encoding/decoding (Natak fork) |
| `meshtastic-tak` | 0.1.0 | TAKPacketV2 compression/decompression (Natak fork) |
| `zstandard` | 0.25.0 | Compression backend for TAKPacketV2 |
| `sshpass` | — | Node-to-node SCP/SSH for config push |
| `pyyaml` | — | YAML config file handling (meshtastic dep) |

---

## File Layout

### Active Files

```
opt/nucleus/meshtastic/
├── cot_bridge.py              # Bridge daemon (bidirectional TX+RX)
├── takmessage_to_xml.py       # TakMessage → CoT XML glue function
└── meshtastic_api.py          # Flask API (bridge status/toggle)

opt/nucleus/web/templates/
└── meshtastic.html            # Web UI (radio detect, BLE↔Bridge toggle)

etc/systemd/system/
└── cot-bridge.service         # Systemd unit for bridge daemon

etc/nucleus/
└── mesh.conf                  # COT_BRIDGE_ENABLED flag

etc/sudoers.d/
└── nucleus-config             # Passwordless systemctl for cot-bridge

etc/udev/rules.d/
└── 60-meshtastic.rules        # Prevent mtp-probe crash on RAK4631
```

### Archived Files

```
opt/nucleus/meshtastic/archive/
├── meshtastic_manager.py          # Text messaging manager (shelved)
├── meshtastic_module_planning.md  # Text messaging planning doc
├── cot_bridge_rx.py               # Stage 6 RX-only test
├── rx_diag.py                     # RX diagnostic test
└── tx_test.py                     # TX test script
```

The text messaging + UDP relay feature (`meshtastic_manager.py`) is preserved in the archive for potential future use. It provided LoRa text messaging with WiFi UDP dual-transport, deduplication, and a web UI for send/receive/node management. The old Flask API endpoints (connect/disconnect/send/messages/nodes) are no longer active.

---

## Remaining Work: Config Sharing via CLI

### Purpose

Eliminate the meshtastic phone app for radio configuration. Export, apply, and push radio config between nodes using the meshtastic CLI's `--export-config` and `--configure` commands, combined with the existing file transfer infrastructure.

### Serial Port Consideration

When the bridge is **disabled** (BLE mode), nothing holds the serial port — the meshtastic CLI can connect freely. When the bridge is **enabled**, `cot_bridge.py` owns the serial port exclusively. Config operations would require:
1. Stopping the bridge service temporarily
2. Running the meshtastic CLI command
3. Restarting the bridge service

This is simpler than the old release/reacquire pattern since systemd handles the lifecycle.

### Detailed Design

See `docs/cli_tools/meshtastic_config_sharing.md` for the full design including:
- Export/apply/push/fleet-push operations
- Owner name handling for fleet deployment
- Channel URL sharing
- Serial port contention strategy

---

## Related Documentation

| Document | Contents |
|----------|----------|
| `docs/meshtastic/atak_cot_bridge.md` | Full development history, staged implementation, library details, progress tracker |
| `docs/meshtastic/cot_bridge_integration.md` | Service management, configuration, web UI integration, file layout |
| `docs/cli_tools/meshtastic_config_sharing.md` | Config export/import/push CLI design |
| `docs/meshtastic/meshtastic_cli_integration.md` | Original meshtastic CLI exploration notes |
| `docs/meshtastic/meshtastic_radio_locking_up.md` | RAK4631 USB lockup workaround (uhubctl power cycle) |
