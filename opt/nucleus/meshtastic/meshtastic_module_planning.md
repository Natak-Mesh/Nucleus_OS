# Meshtastic Serial Control Module — Planning Document

## Overview

A meshtastic module for Nucleus OS that can take command of the meshtastic radio over serial, send standard text messages, and release control back to bluetooth/phone app on demand.

**Use case:** Configure the radio via bluetooth and the standard meshtastic app on the phone, then the Nucleus node takes over via serial for programmatic messaging. A button press (or web UI action) releases control back to the app/bluetooth.

## Key Technical Findings

### Meshtastic Python Library Architecture
- `SerialInterface` → `StreamInterface` → `MeshInterface` (inheritance chain)
- `MeshInterface.sendText()` (mesh_interface.py:412) handles text message sending
- Serial connects at **115200 baud** with `exclusive=True` (locks the serial port)
- BLE and serial are **independent interfaces** — they work simultaneously on the meshtastic device
- "Taking control" = opening the serial port; "Releasing" = closing it
- The phone app via BLE works regardless, but the serial connection enables the Nucleus node to send/receive messages programmatically

### Reference Code Location
- Meshtastic Python CLI repo cloned at: `/home/natak/meshtastic-python`
- Key files:
  - `meshtastic/serial_interface.py` — Serial connection handling
  - `meshtastic/stream_interface.py` — Stream base class (reader thread, protobuf framing)
  - `meshtastic/mesh_interface.py` — Core interface (sendText, sendData, node management)
  - `meshtastic/util.py` — Port detection (`findPorts()`)

## Architecture

### File Structure
```
/opt/nucleus/meshtastic/
├── meshtastic_module_planning.md   # This file
├── meshtastic_manager.py           # Core daemon/service
├── meshtastic_api.py               # Flask API endpoints
└── README.md                       # Usage documentation
```

### 1. Core Manager — `meshtastic_manager.py`

The central class that wraps the meshtastic serial interface.

**States:** `DISCONNECTED` → `CONNECTING` → `CONNECTED` → `DISCONNECTING` → `DISCONNECTED`

**Capabilities:**
- **Connect:** Open serial connection to the meshtastic radio (auto-detect port or configurable path)
- **Send text:** Simple `sendText()` wrapper for sending messages to the mesh network
- **Receive:** Subscribe to incoming messages (pub/sub pattern from the meshtastic lib)
- **Disconnect:** Cleanly close serial connection, freeing the port
- **State tracking:** Expose current state + radio info (node ID, long name, short name, etc.)
- **Message log:** Keep a buffer of recent sent/received messages

**Key design points:**
- Thread-safe (the meshtastic lib uses background reader threads)
- Graceful error handling (serial disconnects, device not found, etc.)
- Singleton pattern — one manager instance per radio

### 2. Flask API — `meshtastic_api.py`

REST endpoints that can be integrated into the existing Nucleus web app or run standalone.

| Endpoint | Method | Description |
|---|---|---|
| `/api/meshtastic/connect` | POST | Take serial control of the radio |
| `/api/meshtastic/disconnect` | POST | Release serial control (back to BLE-only) |
| `/api/meshtastic/status` | GET | Current state + radio info + node list |
| `/api/meshtastic/send` | POST | Send a text message `{"text": "...", "to": "^all" or node_id}` |
| `/api/meshtastic/messages` | GET | Recent received/sent messages |

### 3. Web UI Template

Add to existing Nucleus web nav:
- **Connect/Disconnect toggle button** — the "take over" / "give back" control
- **Status display** — connected state, node info, channel info
- **Text message form** — simple send box
- **Message log** — scrolling list of recent messages

### 4. Configuration

Add to `/etc/nucleus/mesh.conf`:
```bash
# Meshtastic Settings
MESHTASTIC_ENABLED="true"
MESHTASTIC_SERIAL_PORT="auto"    # or specific path like /dev/ttyUSB0
```

## Implementation Order — Phased Testing Approach

Each phase is a clean stopping point where we can verify things work before moving on.

### Phase 1: Install & Verify Meshtastic Library
- Install the `meshtastic` pip package
- Test import: `python3 -c "import meshtastic; from meshtastic.serial_interface import SerialInterface; print('import OK')"`
- If a radio is plugged in: `meshtastic --info` to confirm serial detection works
- **Test criteria:** Does the library import? Does it see the radio?

### Phase 2: Build `meshtastic_manager.py` — Core Only, No Web
- Just the manager class with connect/disconnect/send/status
- Include a `if __name__ == "__main__"` block for standalone CLI testing
- Example test flow from the terminal:
  ```bash
  python3 /opt/nucleus/meshtastic/meshtastic_manager.py --connect
  python3 /opt/nucleus/meshtastic/meshtastic_manager.py --send "hello world"
  python3 /opt/nucleus/meshtastic/meshtastic_manager.py --status
  python3 /opt/nucleus/meshtastic/meshtastic_manager.py --disconnect
  ```
- **Test criteria:** Can we connect, send a message, see it on the phone app, and disconnect?

### Phase 3: Build `meshtastic_api.py` — Standalone Flask Test Server
- Small standalone Flask app (not integrated into main web app yet) that wraps the manager
- Runs on a different port (e.g., port 5001)
- Test with curl:
  ```bash
  curl -X POST localhost:5001/api/meshtastic/connect
  curl localhost:5001/api/meshtastic/status
  curl -X POST -H "Content-Type: application/json" -d '{"text":"test"}' localhost:5001/api/meshtastic/send
  curl -X POST localhost:5001/api/meshtastic/disconnect
  ```
- **Test criteria:** Do the API endpoints work correctly?

### Phase 4: Integrate into Main Nucleus Web App
- Import the API blueprint into the existing `app.py`
- Add the web UI template + nav link
- Add config entries to `/etc/nucleus/mesh.conf`
- **Test criteria:** Does the full web interface work end-to-end?

### Future Phases
- Auto-messaging, status broadcasts, integration with mesh network events
- Button/GPIO trigger for connect/disconnect
- Message queue for offline-then-send scenarios

## Progress Tracker

1. ✅ Switch to `meshtastic_CLI` branch
2. ✅ Clone meshtastic python repo for reference
3. ✅ Explore code and create this planning document
4. ✅ Phase 1: Install & verify meshtastic library (v2.7.7 installed, radio at /dev/ttyACM0)
5. ✅ Phase 2: Build meshtastic_manager.py (CLI-testable)
6. [ ] Phase 3: Build meshtastic_api.py (standalone Flask)
7. [ ] Phase 4: Integrate into main Nucleus web app

## Dependencies

- `meshtastic` python package (the library we cloned)
- `pyserial` (dependency of meshtastic)
- `pypubsub` (dependency of meshtastic, for message pub/sub)
- Existing Flask web app infrastructure

## Notes

- The serial connection uses `exclusive=True`, meaning only one process can hold the port at a time
- The meshtastic lib's `SerialInterface` sets HUPCL off to prevent device reboot on connect/disconnect
- Auto-detection uses `meshtastic.util.findPorts()` which scans USB serial devices
- The `StreamInterface` spawns a daemon reader thread that handles incoming protobuf messages
