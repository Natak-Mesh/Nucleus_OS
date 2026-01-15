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

### Implementation Steps

#### Step 1: Activate Bluetooth Adapter
```bash
sudo hciconfig hci0 up
bluetoothctl show  # Verify adapter is powered on
```

#### Step 2: Manual Pairing Test (Proof of Concept)
Before automating the pairing process, validate the workflow manually:

1. **Prepare UV-Pro Radio**
   - Enable Bluetooth on UV-Pro
   - Activate BSS (Bluetooth Serial Service) mode
   - Put radio into pairing/discoverable mode

2. **Scan and Pair from Pi**
   ```bash
   bluetoothctl
   > power on
   > agent on
   > default-agent
   > scan on
   # Wait for UV-Pro to appear
   > pair [UV-Pro MAC Address]
   > trust [UV-Pro MAC Address]
   > connect [UV-Pro MAC Address]
   ```

3. **Verify Serial Connection**
   - Check if Bluetooth serial port created (e.g., `/dev/rfcomm0`)
   - Test basic serial communication
   - Note any pairing codes or authentication requirements

4. **Document Findings**
   - Record exact pairing procedure
   - Note UV-Pro device name/MAC address format
   - Identify Bluetooth serial port path
   - Test reconnection after power cycle

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

#### Step 4: Flask Web GUI Features
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
