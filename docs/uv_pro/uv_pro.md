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
Development scripts located at `/opt/nucleus/uvpro/` (git-tracked at `opt/nucleus/uvpro/`):

```
/opt/nucleus/uvpro/
├── bt_scan.py       # Bluetooth discovery and pairing ✅ IMPLEMENTED
├── bt_connect.py    # rfcomm serial connection manager
├── serial_test.py   # Raw TNC serial communication test
└── rns_uvpro.py     # Reticulum SerialInterface integration test
```

**File Descriptions:**
- **bt_scan.py**: ✅ Scan for UV-Pro radios, initiate pairing via bluetoothctl wrapper - COMPLETED & TESTED
- **bt_connect.py**: Establish Bluetooth serial port (/dev/rfcomm0), manage connections
- **serial_test.py**: Validate TNC data transmission before Reticulum integration
- **rns_uvpro.py**: Full Reticulum stack test with UV-Pro as SerialInterface

### Implementation Steps

#### Step 1: Activate Bluetooth Adapter
```bash
# Unblock Bluetooth if soft-blocked (important!)
rfkill list
sudo rfkill unblock bluetooth

# Bring adapter up
sudo hciconfig hci0 up
bluetoothctl show  # Verify adapter is powered on
```

**Note:** Bluetooth may be soft-blocked by default. Use `rfkill unblock bluetooth` to enable before use.

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

**Common Pairing Issue (2026-01-16):**
- **Problem:** Stale pairing from previous session prevents new pairing - device shows as paired in bluetoothctl but radio doesn't show pairing on its side
- **Solution:** Remove stale pairing before attempting fresh pair:
  ```bash
  sudo rfcomm release 0
  bluetoothctl remove <MAC>
  ```
  Then follow normal pairing procedure. This clears cached pairing data and allows proper handshake with radio.

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

#### Step 3.5: bt_scan.py Implementation ✅ COMPLETED (2026-01-15)

**Status:** Implemented using subprocess wrapper (Option C) - fully functional and tested.

**Features:**
- `scan` - Scan for UV-Pro devices (filters by name "UV-PRO" or MAC prefix `38:D2:00`)
- `scan-all` - Scan for all Bluetooth devices
- `list` - List paired devices with connection status
- `pair <MAC>` - Pair and trust device in one command
- `trust <MAC>` - Trust device for auto-reconnect
- `remove <MAC>` - Unpair/remove device
- `json scan/list` - JSON output for API integration

**Usage:**
```bash
python3 /opt/nucleus/uvpro/bt_scan.py list
python3 /opt/nucleus/uvpro/bt_scan.py scan
python3 /opt/nucleus/uvpro/bt_scan.py pair 38:D2:00:01:55:C0
python3 /opt/nucleus/uvpro/bt_scan.py remove 38:D2:00:01:55:C0
python3 /opt/nucleus/uvpro/bt_scan.py json list  # For Flask API
```

**Test Results:**
- Successfully detects paired UV-Pro at `38:D2:00:01:55:C0`
- Identifies device as "UV-PRO" with proper filtering
- Shows paired/connected status correctly
- Ready for Flask API integration

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

## Phase 2 Progress: Reticulum Integration (2026-01-16)

### Reticulum Configuration Status: ✅ COMPLETE

**Configuration:**
- Both Pi nodes (0002 and 0003) configured with SerialInterface for UV-Pro
- Interface uses `/dev/rfcomm0` at 9600 baud
- Configuration file: `~/.reticulum/config`

```ini
[[UV-Pro RF]]
type = SerialInterface
enabled = yes
port = /dev/rfcomm0
speed = 9600
databits = 8
parity = none
stopbits = 1
```

**Interface Status:**
```
SerialInterface[UV-Pro RF]
   Status    : Up
   Mode      : Full
   Rate      : 9.60 kbps
```

### Current Issue: RF Link - TX Only, No RX ⚠️

**Symptoms:**
- Both Pi nodes show `SerialInterface[UV-Pro RF]` as "Up"
- Both nodes transmitting data (↑1.87 KB on Pi #1, ↑1.41 KB on Pi #2)
- **Neither node receiving data** (↓0 B on both)
- Announces propagating over AutoInterface but not UV-Pro RF

**Verified Configuration:**
- ✅ Both radios on same frequency
- ✅ Digital Mode enabled, Format = BSS on both
- ✅ Digital Channel identical on both radios
- ✅ Squelch adjusted (0-1) - no effect
- ✅ Radios physically close (same room)
- ✅ Antennas attached, radios powered on

**Troubleshooting Steps Attempted:**
1. Squelch adjustment to 0/1 (open squelch) - no change
2. Verified radio configuration matches
3. Confirmed serial port communication (data going out)
4. Checked physical proximity and power

**Next Diagnostics:**
- [x] Implement serial_test.py for raw serial loop test
- [ ] Test direct serial communication bypass Reticulum
- [ ] Verify BSS audio routing (Bluetooth → TNC → Radio TX audio)
- [ ] Check UV-Pro TX audio level settings
- [ ] Monitor radio squelch LED during transmission
- [ ] Test with second set of radios to rule out hardware fault

**Hypothesis:**
TX audio from TNC → radio transmitter working (data sent)
RX audio from radio receiver → TNC not working (no data received)
Likely BSS audio routing or radio RX audio level issue.

**Critical Discovery (2026-01-16 Evening):**

**Bluetooth Channel Discovery (2026-01-16 Evening) - CORRECTED:**

⚠️ **PREVIOUS ERROR CORRECTED (2026-01-16 21:23):** Initial channel mapping was incorrect due to incomplete sdptool output parsing. Channel 1 does not exist. SPP is on channel 4.

**Full sdptool discovery command:**
```bash
sdptool records 38:D2:00:01:55:C0
```

**Complete Output:**
```
Service RecHandle: 0x10000
Service Class ID List:
  "PnP Information" (0x1200)

Service Name: BS AOC
Service RecHandle: 0x10001
Service Class ID List:
  UUID 128: 39144315-32fa-40db-85ed-fbfeba2d86e6
Protocol Descriptor List:
  "L2CAP" (0x0100)
  "RFCOMM" (0x0003)
    Channel: 2
Language Base Attr List:
  code_ISO639: 0x656e
  encoding:    0x6a
  base_offset: 0x100

Service Name: Voice Gateway
Service RecHandle: 0x10002
Service Class ID List:
  "Handsfree Audio Gateway" (0x111f)
  "Generic Audio" (0x1203)
Protocol Descriptor List:
  "L2CAP" (0x0100)
  "RFCOMM" (0x0003)
    Channel: 3
Profile Descriptor List:
  "Handsfree" (0x111e)
    Version: 0x0107

Service Name: SPP Dev
Service RecHandle: 0x10004
Service Class ID List:
  "Serial Port" (0x1101)
Protocol Descriptor List:
  "L2CAP" (0x0100)
  "RFCOMM" (0x0003)
    Channel: 4
Profile Descriptor List:
  "Serial Port" (0x1101)
    Version: 0x0102
```

**CORRECTED Channel Map:**

| Channel | Service Name | Description | UUID |
|---------|--------------|-------------|------|
| (none) | PnP Information | Device info only - no RFCOMM channel | 0x1200 |
| 2 | BS AOC | BTech proprietary BSS protocol | 39144315-32fa-40db-85ed-fbfeba2d86e6 |
| 3 | Voice Gateway | Handsfree Audio Gateway | 0000111f (with 0x1203 Generic Audio) |
| **4** | **SPP Dev** | **Serial Port Profile (Standard)** | 00001101-0000-1000-8000-00805f9b34fb |

**Correct Binding for Serial Communication:**
```bash
sudo rfcomm bind 0 38:D2:00:01:55:C0 4   # Channel 4, not 1!
```

**Troubleshooting Log - Channel Investigation (2026-01-16 Evening):**

## Channel Discovery via sdptool

**Command:** `sdptool records 38:D2:00:01:55:C0 | grep -A 10 "Service Name\|Channel"`

**Results:**
```
Channel 1: SPP Dev (Serial Port Profile - UUID: 00001101-0000-1000-8000-00805f9b34fb)
Channel 2: BS AOC (BTech proprietary - UUID: 39144315-32fa-40db-85ed-fbfeba2d86e6)
Channel 3: Voice Gateway (Handsfree Audio Gateway - UUID: 0000111f-0000-1000-8000-00805f9b34fb)
```

## Attempt 1: Channel 1 (SPP - Serial Port Profile)

**Action:** `sudo rfcomm bind 0 38:D2:00:01:55:C0 1`
- Binding succeeded
- `/dev/rfcomm0` created
- Port opens successfully

**Testing:** `python3 serial_test.py send`
- First write attempt shows port open
- RTS: True, DTR: True, CTS: True, DSR: True
- **ERROR:** I/O error on write after ~365ms
- `OSError: [Errno 5] Input/output error`
- `SerialException: write failed: [Errno 5] Input/output error`

**Status after failure:**
- `rfcomm -a` shows: `rfcomm0: 38:D2:00:01:55:C0 channel 1 closed`
- Connection terminated during write operation

**Troubleshooting attempted:** NONE - immediately moved to channel 2 without proper diagnosis

**What should have been done:**
- Check `dmesg` during write operation
- Monitor Bluetooth connection state
- Verify radio-side connection status
- Test with `rfcomm connect` instead of `rfcomm bind`
- Check for BlueZ profile handlers

## Attempt 2: Channel 2 (BS AOC - BTech Proprietary)

**Action:** `sudo rfcomm bind 0 38:D2:00:01:55:C0 2`
- Binding succeeded
- `/dev/rfcomm0` created
- Port opens successfully
- Port accepts writes without I/O error

**Testing - Pi 0003 receive mode:**
```bash
python3 serial_test.py receive
```

**Results:**
- Receiving thousands of bytes of data continuously
- Data appears to be HDLC-framed (starts with `~` / 0x7E delimiters)
- Data received even when Pi 0002 is NOT sending
- Appears to be BSS protocol traffic (location broadcasts, announcements, etc.)

**Example received data:**
```
~\x00\x9cq\x12\xfe\xec\xdb\xaa\xa9^6\\e\x9b\xe3\x97...
```

**Key observations:**
- Data IS being received on channel 2
- Data is BSS protocol framed, not raw serial
- Our test messages likely wrapped inside BSS frames but not visible
- This matches documentation: "BSS Protocol - BTech proprietary protocol"

**Status:** Channel 2 works for data transfer but uses BSS framing protocol

## Attempt 3: Channel 4 Discovery (2026-01-16 21:23) - THE REAL SPP

**Critical Realization:** The full `sdptool records` output (see corrected table above) reveals **SPP is actually on channel 4, not channel 1**. The grep-filtered output used earlier was incomplete and misleading.

**Interesting Mystery:** Despite channel 1 not existing in sdptool records, `rfcomm bind 0 38:D2:00:01:55:C0 1` DID successfully create `/dev/rfcomm0` and accepted the binding command. However, it failed on write. This suggests:
- rfcomm may allow binding to non-existent channels without immediate error
- The I/O error occurred when actual communication was attempted
- The "channel 1" binding may have defaulted to some fallback behavior

**Next Action Required:**
Test channel 4 (the actual SPP channel) with:
```bash
sudo rfcomm release 0  # Clean up any existing binding
sudo rfcomm bind 0 38:D2:00:01:55:C0 4
python3 serial_test.py send
```

## Current Status & Questions

**What we know:**
1. Channel 1 - Does NOT exist in sdptool records, but rfcomm allowed binding (failed on write with I/O error)
2. Channel 2 (BS AOC) - Works, uses BSS protocol framing
3. Channel 3 (Voice Gateway) - Not tested, likely for BT headset
4. **Channel 4 (SPP Dev)** - **THE REAL SERIAL PORT PROFILE - NOT YET TESTED**

**Critical Next Step:**
Test channel 4 for raw serial communication - this is likely what we need for Reticulum

**If Channel 4 works:**
- Update Reticulum config to use channel 4 binding
- This should provide raw serial without BSS framing

**If Channel 4 also fails:**
- Build BSS protocol bridge for channel 2
- Decode HDLC framing and extract payload
- Create translator daemon between Reticulum and BSS protocol

---

## KISS Interface (2026-01-17)

UV-Pro TNC uses KISS protocol (HDLC framing with 0x7E delimiters).

```ini
[[UV-Pro KISS Interface]]
type = KISSInterface
enabled = yes
port = /dev/rfcomm0
speed = 9600
databits = 8
parity = none
stopbits = 1
```

---

## KISSInterface Testing (2026-01-17 16:00-16:40)

### Configuration
Config updated to use KISSInterface instead of SerialInterface:
```ini
[[UV-RF]]
type = KISSInterface
enabled = yes
port = /dev/rfcomm0
speed = 9600
databits = 8
parity = none
stopbits = 1
preamble = 150
txtail = 10
persistence = 200
slottime = 20
flow_control = false
```

### Test: rfcomm bind without channel number
**Command:** `sudo rfcomm bind 0 <MAC>` (no channel specified)

**Pi 0002:** MAC 38:D2:00:01:55:C0
**Pi 0003:** MAC 38:D2:00:01:4D:E3

**Result:** rfcomm auto-negotiated to channel 1

### Observed Behavior

**rfcomm status:**
- Pi 0003: `rfcomm0: 38:D2:00:01:4D:E3 channel 1 connected [tty-attached]`
- Pi 0002: `rfcomm0: 38:D2:00:01:55:C0 channel 1 closed` (repeated connection failures)

**rnstatus output (when working):**
- Both interfaces showed "Up"
- Both showed traffic ↑0 B ↓0 B (no traffic flow)
- Rate: 1.20 kbps

**rnsd logs (Pi 0002):**
- Repeated crashes: `Main process exited, code=exited, status=255/EXCEPTION`
- Service restarted automatically multiple times
- rfcomm showed "closed" after rnsd attempted to open port

**Serial port test:**
- `echo "test" > /dev/rfcomm0` succeeded without error on both Pis

**Bluetooth connection status:**
- Pi 0002: `bluetoothctl info` showed "Connected: no"
- `bluetoothctl connect 38:D2:00:01:55:C0` failed with "br-connection-profile-unavailable"

### Summary
- KISSInterface brought interfaces to "Up" status
- No Reticulum traffic observed (counters remained at 0)
- rfcomm bind without channel auto-selected channel 1
- Pi 0002 had persistent BT connection issues, rfcomm showed "closed"
- rnsd crashed repeatedly on Pi 0002 when attempting to use the interface

---

**Document Status:** Phase 2 In Progress  
**Last Updated:** 2026-01-17 16:45  
**Next Step:** TBD


# gemini analysis 
BTech UV-Pro Reticulum Configuration1. Radio Settings (On Device)SettingValueWhyDigital ModeOFFStops the radio from intercepting packets for its own internal APRS/BSS functions.KISS TNCONAllows the radio to interpret KISS frames from Reticulum.TX Delay300msGives the slow Bluetooth module time to key the PTT before data starts.2. Linux OS ConfigurationActionDetailWhyRFCOMM BindChannel 4Your sdptool proved SPP is on 4. Defaulting to 1 connects but passes no data.Permissionschmod 666Ensures Reticulum has the rights to read/write to the /dev/rfcomm0 device.3. Reticulum Interface (config)Ini, TOML[[UV-RF]]
type = KISSInterface
enabled = yes
port = /dev/rfcomm0
speed = 115200
preamble = 150
txtail = 30
persistence = 200
slottime = 20
Why these config values?type = KISSInterface: The UV-Pro has a built-in TNC; this tells Reticulum to use that protocol.speed = 115200: The internal Bluetooth module on these radios runs at 115200. Using 9600 results in timed-out or garbled frames.preamble = 150: Works with the radio's TX Delay to ensure the receiver has a stable carrier before the data hits.txtail = 30: Keeps the PTT keyed long enough to ensure the entire Bluetooth buffer is cleared before the radio de-keys.persistence / slottime: Standard packet radio timing to prevent the radio from "stepping" on other transmissions.

# BTech UV-Pro & Reticulum Configuration Guide

### 1. Radio Settings (On Device Menu)
Navigate to **Main Menu > General Settings** and apply these specific changes:

| Setting | Value | Why |
| :--- | :--- | :--- |
| **Digital Mode** | **OFF** | **Critical.** If ON, the radio firmware intercepts packets for internal APRS/BSS logic. OFF forces the radio to act as a transparent pipe for Reticulum. |
| **KISS TNC** | **ON** | Enables the radio’s internal modem to process KISS frames coming from the Pi. |
| **TX Delay** | **300ms** | Compensates for the slow Bluetooth wake-up time. Ensures the PTT is keyed and the carrier is stable before data is sent. |

---

### 2. Linux OS Configuration (Raspberry Pi)
The BTech/Vero firmware advertises the Serial Port Profile (SPP) on **Channel 4**. You must bind specifically to this channel.

* **Command to Bind:** `sudo rfcomm bind 0 38:D2:00:01:55:C0 4`
* **Command for Permissions:** `sudo chmod 666 /dev/rfcomm0`

**Why?** Your `sdptool` results proved the SPP service is on Channel 4. Standard binding defaults to Channel 1, which connects but will never pass data.

---

### 3. Reticulum Interface Configuration
Paste this block into your `~/.reticulum/config` file:

```ini
[[UV-RF]]
  type = KISSInterface
  enabled = yes
  port = /dev/rfcomm0
  speed = 115200
  preamble = 150
  txtail = 30
  persistence = 200
  slottime = 20