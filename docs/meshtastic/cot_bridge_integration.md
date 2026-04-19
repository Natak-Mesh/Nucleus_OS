# CoT Bridge Integration — Planning Document

## Overview

The ATAK CoT Bridge (`cot_bridge.py`) is a bidirectional daemon that bridges Cursor on Target (CoT) traffic between the local ATAK multicast network and Meshtastic LoRa. It creates a parallel long-range data path alongside the existing 802.11s IP mesh.

This document covers how to integrate the bridge into the Nucleus OS system — service management, serial port coordination with the existing meshtastic text module, web UI, and configuration.

## What Exists Today

### CoT Bridge (`cot_bridge.py`)

Standalone bidirectional daemon. All 7 development stages complete and verified between two nodes.

**TX path:** Listens on ATAK multicast groups (SA `239.2.3.1:6969` + Chat `224.10.10.1:17012`) on br-lan → parses TAK Protocol V1 → converts to CoT XML → compresses to TAKPacketV2 → sends as `ATAK_FORWARDER` (portnum 257) over LoRa.

**RX path:** Receives `ATAK_FORWARDER` packets from LoRa → decompresses TAKPacketV2 → builds CoT XML → converts to TAK Protocol V1 → injects as multicast on br-lan for local ATAK devices.

**Features:**
- 30s per-UID rate limiting (TX)
- Loop prevention (RX UID tracking — won't re-TX packets received from LoRa)
- Self-packet filtering (ignores own node number)
- SA + Chat multicast support
- Stats tracking and clean shutdown

**Owns the serial port exclusively** — opens `SerialInterface` directly.

### Text Messaging Module (`meshtastic_manager.py` + `meshtastic_api.py`)

Flask-integrated module for text messaging over LoRa. Controlled via web UI (meshtastic.html).

**Capabilities:**
- Connect/disconnect serial control via web UI buttons
- Send/receive text messages (LoRa + WiFi UDP dual-transport)
- Node database display
- Message log with transport badges (LoRa/WiFi/local)
- UDP relay for instant Pi-to-Pi delivery over 802.11s

**Also owns the serial port exclusively** when connected.

### Web UI (`meshtastic.html`)

Single page with:
- Status display (connected/disconnected, node info)
- Radio control buttons (Take Control / Release to BLE / Clear Node DB)
- Send message form (visible when connected)
- Known nodes table (visible when connected)
- Message log (always visible — UDP messages arrive even when disconnected)

## The Serial Port Problem

Both `cot_bridge.py` and `meshtastic_manager.py` use `meshtastic.serial_interface.SerialInterface` which opens the serial port with `exclusive=True`. **They cannot run simultaneously.**

Current state:
- `meshtastic_manager.py` is instantiated by the Flask web app (`app.py`) and holds the serial connection when "Take Control" is clicked
- `cot_bridge.py` is a standalone script run manually from the command line
- No systemd service for either — the web app manages the text module lifecycle, the bridge is manual

## Integration Architecture

### Operating Modes

The meshtastic radio can be in one of these states:

| Mode | Serial Owner | What Works |
|---|---|---|
| **BLE (default)** | Nobody | Phone app via Bluetooth. No Pi serial features. |
| **Text mode** | `meshtastic_manager.py` | Text messaging, node DB, web UI. No CoT bridge. |
| **Bridge mode** | `cot_bridge.py` | Bidirectional ATAK CoT ↔ LoRa. No text messaging. |

Only one mode can be active at a time. Switching requires releasing the serial port.

### Service Design

`cot_bridge.py` runs as a systemd service (`cot-bridge.service`) that can be started/stopped independently.

**Key constraint:** The bridge service and the text module's serial connection are mutually exclusive. Starting the bridge while text mode is connected (or vice versa) will fail with a serial port lock error.

### Configuration

Add to `/etc/nucleus/mesh.conf`:
```bash
# ATAK CoT Bridge Configuration
# Bridges ATAK multicast CoT to/from Meshtastic LoRa
COT_BRIDGE_ENABLED=false
```

When `COT_BRIDGE_ENABLED=true`, the bridge service starts at boot and runs continuously. The text module's "Take Control" button should be disabled or warn that the bridge is active.

When `COT_BRIDGE_ENABLED=false` (default), the bridge doesn't run. The radio is available for BLE or text mode as before.

## Current Progress

- [x] Bridge daemon complete and verified (`cot_bridge.py`)
- [x] All 7 stages passed (see `atak_cot_bridge.md`)
- [x] Dependencies installed (takproto, meshtastic-tak, zstandard)
- [ ] Systemd service file (`cot-bridge.service`)
- [ ] `mesh.conf` config knob (`COT_BRIDGE_ENABLED`)
- [ ] `config_generation.sh` integration (enable/disable service based on config)
- [ ] Web UI awareness (show bridge status, prevent conflicts)
- [ ] `mesh-start.sh` or boot integration
- [ ] Deploy script updates

## Open Questions

These are the items to discuss before implementing:

1. **Service lifecycle** — Should the bridge auto-start at boot when enabled, or be manually triggered? (Leaning: auto-start via systemd, controlled by config flag.)

2. **Web UI integration** — How much bridge visibility in the web UI?
   - Minimal: Just a status indicator ("CoT Bridge: Running/Stopped") on the meshtastic page
   - Medium: Status + start/stop buttons + bridge stats (TX/RX counts)
   - Full: Dedicated page or section with rate limit config, log tail, etc.

3. **Mode switching** — If bridge is running and user clicks "Take Control" for text mode:
   - Option A: Block it — show "CoT Bridge is active, stop it first"
   - Option B: Auto-stop bridge, connect text mode, auto-restart bridge on disconnect
   - Option C: Don't worry about it — if they click Take Control while bridge runs, it fails with a clear error

4. **Text messaging during bridge mode** — The bridge doesn't handle text messages. If someone sends a meshtastic text while the bridge owns the serial port, it won't be received/logged. Is this acceptable, or do we want the bridge to also subscribe to text messages?

5. **Rate limit tuning** — Currently hardcoded at 30s. Should this be configurable via `mesh.conf`?

6. **Logging** — Bridge currently logs to stdout. As a systemd service it would go to journald. Any need for a dedicated log file?

7. **Deploy script** — `deploy.sh` needs to know about the new service file and config entries.
