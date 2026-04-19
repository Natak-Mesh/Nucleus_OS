# CoT Bridge Integration — Planning Document

## Overview

The ATAK CoT Bridge (`cot_bridge.py`) is a bidirectional daemon that bridges Cursor on Target (CoT) traffic between the local ATAK multicast network and Meshtastic LoRa. It creates a parallel long-range data path alongside the existing 802.11s IP mesh.

This document covers how the bridge is integrated into Nucleus OS — service management, configuration, and web UI.

## Operating Modes

The meshtastic radio has two modes, controlled by a single config flag:

| Mode | Config Value | What Happens |
|---|---|---|
| **BLE** (default) | `COT_BRIDGE_ENABLED=false` | Radio left alone. Phone app works via Bluetooth. Nothing touches serial. |
| **Bridge** | `COT_BRIDGE_ENABLED=true` | `cot-bridge.service` runs. ATAK CoT bridges to/from LoRa. |

Only one mode at a time. The toggle takes effect immediately (no reboot required) and persists across reboots.

## Architecture

### Service

`cot-bridge.service` — systemd unit that runs `cot_bridge.py` as a daemon.

- Starts after `mesh-start.service` (needs br-lan + multicast routing)
- Runs as `natak` user
- `Restart=on-failure` with 10s backoff
- Logs to journald (`journalctl -u cot-bridge -f`)

### Configuration

`/etc/nucleus/mesh.conf`:
```bash
COT_BRIDGE_ENABLED=false
```

### Web UI Toggle

The meshtastic page (`meshtastic.html`) provides:
- Radio detection status (USB serial present)
- Bridge mode toggle switch (BLE ↔ Bridge)
- Service status indicator (Running/Stopped)

The toggle calls the API which:
1. Writes `COT_BRIDGE_ENABLED` to mesh.conf
2. Runs `systemctl enable/disable --now cot-bridge.service`

No reboot needed — the service starts/stops immediately and the enable/disable persists for future boots. `config_generation.sh` also reads this flag, so a full config-gen + reboot flow stays consistent.

### API Endpoints

| Endpoint | Method | Description |
|---|---|---|
| `/api/meshtastic/status` | GET | Bridge enabled (config), service running, radio detected |
| `/api/meshtastic/bridge/enable` | POST | Enable + start bridge service, write config |
| `/api/meshtastic/bridge/disable` | POST | Stop + disable bridge service, write config |

### Sudoers

`/etc/sudoers.d/nucleus-config` grants the `natak` user passwordless access to:
- `systemctl start/stop/enable/disable/is-active cot-bridge.service`

## File Layout

### Active files

```
opt/nucleus/meshtastic/
├── cot_bridge.py           # Bridge daemon (Stage 7)
├── takmessage_to_xml.py    # TakMessage → CoT XML glue function
└── meshtastic_api.py       # Flask API (bridge status/toggle)

etc/systemd/system/
└── cot-bridge.service      # Systemd unit for bridge daemon

etc/nucleus/
└── mesh.conf               # COT_BRIDGE_ENABLED flag
```

### Archived files

```
opt/nucleus/meshtastic/archive/
├── meshtastic_manager.py       # Text messaging manager (shelved)
├── meshtastic_module_planning.md  # Text messaging planning doc
├── cot_bridge_rx.py            # Stage 6 RX-only test
├── rx_diag.py                  # RX diagnostic test
└── tx_test.py                  # TX test script
```

The text messaging + UDP relay feature (`meshtastic_manager.py`) is preserved in the archive for potential future use. It provided LoRa text messaging with WiFi UDP dual-transport and a web UI for send/receive/node management.

## Bridge Details

See `atak_cot_bridge.md` for the full development history and technical details.

**TX:** Multicast CoT (SA `239.2.3.1:6969` + Chat `224.10.10.1:17012`) → TAK Protocol V1 → CoT XML → TAKPacketV2 → compressed → LoRa (portnum 257 ATAK_FORWARDER)

**RX:** LoRa (portnum 257) → decompress → CoT XML → TAK Protocol V1 → multicast inject on br-lan

**Features:** 30s per-UID rate limiting, loop prevention, self-packet filtering, SA + Chat multicast support.

## Dependencies

Installed via pip (from Natak forks):
- `takproto` — TAK Protocol V1 encoding/decoding
- `meshtastic-tak` (TAKPacket SDK) — TAKPacketV2 compression/decompression
- `zstandard` — compression backend
- `meshtastic` — radio serial interface
