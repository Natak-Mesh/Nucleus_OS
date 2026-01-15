# BTech UV-Pro + Pi MANET Integration Plan

## Overview

This document outlines the plan to integrate BTech UV-Pro handheld radios with Pi-based MANET (Mobile Ad-hoc Network) nodes. The UV-Pro radios feature a built-in TNC (Terminal Node Controller) with high-speed BSS (Bluetooth Serial Service) mode, which will be leveraged for seamless integration.

**Primary Goals:**
- Enable wireless RF mesh communication between MANET nodes
- Integrate UV-Pro radio management into existing web GUI
- Support future ATAK (Android Team Awareness Kit) CoT (Cursor on Target) capabilities

---

## Phase 1: Bluetooth Pairing Infrastructure

### Objectives
- Establish reliable Bluetooth pairing between UV-Pro radios and Pi nodes
- Activate and configure UV-Pro BSS mode
- Build web-based pairing interface in Flask GUI

### Key Components
- **Hardware:** Pi Bluetooth adapter, UV-Pro radios
- **Software:** BlueZ/Bluetooth stack on Pi
- **Web GUI:** Bluetooth device discovery, pairing workflow, device management

### Success Criteria
- UV-Pro radios successfully pair with Pi nodes via Bluetooth
- Web interface allows scanning, pairing, and managing Bluetooth connections
- Paired devices persist across reboots

### Current Pi Bluetooth Baseline
- **BlueZ Version:** 5.82 (latest stable)
- **Bluetooth Service:** Active and running
- **Hardware Adapter:** hci0 (UART-based, BD Address: 88:A2:9E:2D:94:9D)
- **Current Status:** Adapter DOWN (needs to be brought up)
- **Libraries Installed:** libbluetooth3, bluez-firmware, pulseaudio-module-bluetooth
- **Python Libraries:** None installed yet (needed for Flask integration)

### Development Directory Structure
Test and development scripts located at `/opt/nucleus/uvpro/` (Pi filesystem only, not in git repo):

```
/opt/nucleus/uvpro/
├── bt_scan.py       # Bluetooth discovery and pairing
├── bt_connect.py    # rfcomm serial connection manager
├── serial_test.py   # Raw TNC serial communication test
└── rns_uvpro.py     # Reticulum SerialInterface integration test
```

**File Descriptions:**
- **bt_scan.py**: Scan for UV-Pro radios, initiate pairing via bluetoothctl wrapper
- **bt_connect.py**: Establish Bluetooth serial port (/dev/rfcomm0), manage connections
- **serial_test.py**: Validate TNC data transmission before Reticulum integration
- **rns_uvpro.py**: Full Reticulum stack test with UV-Pro as SerialInterface

### Implementation Steps

#### Step 1: Activate Bluetooth Adapter
```bash
sudo hciconfig hci0 up
bluetoothctl show  # Verify adapter is powered on
```

#### Step 2: Manual Pairing Test (Proof of Concept) ✅ COMPLETED

**Test Results (2026-01-15):**

1. **Prepare UV-Pro Radio**
   - Enable Bluetooth on UV-Pro: Menu → Connections
   - Enable BSS mode: Menu → General Settings → Digital Mode → Format: BSS
   - Put radio into pairing mode: Menu → Pairing (LED flashes red/green alternately)

2. **Scan and Pair from Pi**
   ```bash
   # Unblock Bluetooth (if blocked)
   rfkill list
   sudo rfkill unblock bluetooth
   
   # Start bluetoothctl interactive session
   bluetoothctl
   > power on
   > agent on
   > default-agent
   > scan on
   
   # Wait for UV-Pro to appear as "UV-PRO" or "UV-P"
   # Identified by device name in scan results:
   # [NEW] Device 38:D2:00:01:55:C0 UV-P
   # [CHG] Device 38:D2:00:01:55:C0 Name: UV-PRO
   
   # Pair with discovered radio (replace MAC with your radio's address)
   > pair 38:D2:00:01:55:C0
   # May fail first attempt - retry if needed
   > trust 38:D2:00:01:55:C0
   > connect 38:D2:00:01:55:C0
   > exit
   ```

3. **Bind Serial Port**
   ```bash
   # Create /dev/rfcomm0 serial port
   sudo rfcomm bind 0 38:D2:00:01:55:C0
   
   # Verify port created
   ls -la /dev/rfcomm0
   # Output: crw-rw---- 1 root dialout 216, 0 Jan 15 04:25 /dev/rfcomm0
   
   # Check connection
   rfcomm show
   ```

4. **Test Serial Communication**
   ```bash
   # Verify pyserial installed
   python3 -c "import serial; print(serial.__version__)"
   
   # Test port open/write
   python3 -c "
   import serial, time
   s = serial.Serial('/dev/rfcomm0', 9600, timeout=2)
   print(f'Port: {s.name}')
   print(f'Open: {s.is_open}')
   s.write(b'TEST\r\n')
   time.sleep(0.5)
   print(f'Bytes waiting: {s.in_waiting}')
   s.close()
   print('Success')
   "
   ```

**Documented Findings:**
- **UV-Pro Device Name:** "UV-PRO" or "UV-P" (truncated in initial discovery)
- **MAC Address:** `38:D2:00:01:55:C0` (test radio)
- **MAC Prefix:** `38:D2:00` appears to be BTech's Bluetooth OUI
- **Serial Port:** `/dev/rfcomm0` after binding
- **Serial Profile UUID:** `00001101-0000-1000-8000-00805f9b34fb` (SPP - Serial Port Profile)
- **Pairing:** No PIN required, may need retry if first attempt fails
- **Port Access:** User must be in `dialout` group (verified: natak is member)
- **pyserial Version:** 3.5 (already installed)

**Key Observations:**
- Bluetooth soft-block must be removed via `rfkill unblock bluetooth`
- Radio appears in scan with name "UV-PRO" - use this to identify correct device
- First pairing attempt may fail with "ConnectionAttemptFailed" - retry succeeds
- Port opens successfully but no RX data with single radio (expected - BSS is point-to-point)
- Serial port requires manual `rfcomm bind` command after pairing

#### Step 3: Python Library Options for Flask Integration
Choose one approach for programmatic Bluetooth control:

**Option A: PyBluez**
- Classic Bluetooth library
- Simple API for scanning, pairing, connecting
- Requires: `sudo apt-get install libbluetooth-dev && pip install pybluez`

**Option B: BlueZ D-Bus API**
- Modern approach using D-Bus interface
- More complex but better integration with BlueZ
- Requires: `pip install dbus-python`

**Option C: Subprocess Wrapper**
- Call `bluetoothctl` via subprocess
- Simplest but less elegant
- No additional dependencies

**Recommendation:** Start with Option C for rapid prototyping, migrate to Option B for production

#### Step 4: Development Testing Workflow
Manual testing sequence before GUI integration:

1. **Bluetooth Pairing** (manual via bluetoothctl)
   ```bash
   sudo hciconfig hci0 up
   bluetoothctl
   > power on
   > agent on
   > scan on
   # Wait for UV-Pro to appear
   > pair [MAC]
   > trust [MAC]
   > connect [MAC]
   ```

2. **Serial Connection** (test with bt_connect.py)
   - Verify `/dev/rfcomm0` created
   - Document connection parameters

3. **TNC Communication** (test with serial_test.py)
   - Send/receive test data
   - Validate BSS protocol

4. **Reticulum Integration** (test with rns_uvpro.py)
   - Configure SerialInterface
   - Test packet transmission between nodes

#### Step 5: Flask Web GUI Features
- **Device Scanner:** List nearby Bluetooth devices
- **Pairing Manager:** Initiate pairing with selected device
- **Connection Status:** Real-time status of paired UV-Pro radios
- **Device Management:** Remove/forget devices, reconnect
- **Serial Port Info:** Display `/dev/rfcomm` port assignments

---

## Phase 2: Reticulum Interface Integration

### Objectives
- Configure UV-Pro TNC as a Reticulum network interface
- Prove concept with node-to-node RF communication
- Establish baseline performance metrics

### Key Components
- **Reticulum Configuration:** SerialInterface via Bluetooth serial connection
- **RF Communication:** Utilize UV-Pro TNC for packet transmission
- **Testing:** Multi-node mesh communication validation

### Success Criteria
- Reticulum successfully communicates through UV-Pro TNC
- Messages route between multiple MANET nodes over RF
- Stable, reliable connectivity demonstrated

---

## Phase 3: ATAK CoT Capability (Future)

### Objectives
- Enable ATAK Cursor on Target message routing
- Integrate with TAK ecosystem
- Support tactical situational awareness applications

### Key Components
- **CoT Gateway:** Bridge between ATAK clients and Reticulum mesh
- **TAK Server:** Integration considerations
- **Message Routing:** CoT packet handling and forwarding

### Success Criteria
- ATAK clients can exchange CoT messages via mesh network
- Position and status updates propagate across nodes
- Reliable tactical data exchange

---

## Open Questions / TBD

### Technical Details to Determine
- Specific UV-Pro TNC configuration parameters
- Optimal Reticulum interface settings for BSS mode
- Bluetooth reconnection handling and error recovery
- Web GUI architecture for real-time device status
- Performance benchmarks and optimization targets

### Hardware/Deployment
- Number of nodes in initial deployment
- Radio frequency band and channel configuration
- Antenna and RF considerations
- Power management for mobile operations

### Integration Points
- Existing Flask web GUI structure and API patterns
- Current Reticulum configuration on Pi nodes
- ATAK client deployment methodology

---

## Notes

- Keep implementation modular for easier testing and debugging
- Document configuration steps as we discover best practices
- Consider security implications for Bluetooth pairing and RF communication
- Plan for field testing scenarios

---

**Document Status:** Initial Planning  
**Last Updated:** 2026-01-14  
**Next Steps:** Begin Phase 1 - Bluetooth pairing infrastructure development
