# BTech UV-Pro Quick Reference
## Bluetooth & Reticulum Integration Guide

This document contains essential information extracted from the UV-Pro manual for integrating the radio with Pi-based MANET nodes via Bluetooth and Reticulum.

---

## Bluetooth Pairing & Connection

### Pairing Procedure

1. **Enable Pairing Mode on Radio**
   - Navigate to: Menu → Pairing
   - When pairing mode is active, the red/green LED on top will flash alternately
   - Or use the programmable button if configured for pairing

2. **From Pi/Device Side**
   - Radio will appear as a Bluetooth device
   - Pair using standard Bluetooth pairing methods (`bluetoothctl` on Linux)
   - Once paired, the device will be listed in "Paired Devices"

### Connection Settings (Menu: Connections)

- **Pairing** - Initiates pairing mode
- **Scanning** - Shows Bluetooth scanning status
- **Paired Devices** - Lists all devices paired with the radio
- **Available Devices** - Shows discoverable Bluetooth devices nearby

### Bluetooth Audio Settings

- **BT Mic Gain** - Set Bluetooth microphone gain (Low/Medium/High)
- **Keep Connected** - Maintain persistent Bluetooth connection
- **Speaker** - Enable/disable speaker output

---

## BSS Mode (Bluetooth Serial Service)

### Critical Information

The UV-Pro has a **built-in TNC with high-speed BSS mode** that provides serial data over Bluetooth.

- **BSS Protocol** - BTech proprietary protocol for Bluetooth serial data
- **Purpose** - Suitable for non-Ham users (no amateur radio license required)
- **Usage** - Provides serial TNC interface over Bluetooth connection
- **Speed** - High-speed data transmission mode

### BSS vs APRS

**BSS (Bluetooth Serial Service)**
- Proprietary BTech protocol
- Does NOT require Amateur Radio license
- Only works between UV-Pro radios
- Ideal for LMR (Land Mobile Radio) applications
- **Recommended for our Reticulum integration**

**APRS**
- Standard Amateur Radio APRS protocol
- Requires Amateur Radio license and call sign
- Compatible with standard APRS infrastructure
- For Ham Radio use only

---

## Digital Mode Configuration

### Menu Path: General Settings → Digital Mode

**Enable**
- Turn digital mode ON/OFF
- Must be enabled for data transmission

**Share Location**
- Set transmission interval (OFF to 1800 seconds)
- When OFF (but Enable is ON), radio only receives data
- When set to interval, radio transmits location at specified rate

**Digital Channel**
- Select which memory channel is used for digital transmissions
- Can use "Current Channel" for dynamic selection
- Important: This channel carries the data packets

**Format**
- **BSS** - Use for non-Ham applications (our use case)
- **APRS** - Use for Amateur Radio applications (requires license)

**Digital Mute**
- When enabled, radio does NOT play data transmission sounds over speaker
- Prevents annoying data tones from being heard
- **Recommended: Enable for Reticulum integration**

---

## GPS & Location Data

### GPS Status (Menu: GPS Status)

- Shows current GPS location (latitude/longitude)
- Displays altitude and speed
- Can switch positioning system or disable GPS
- **Note**: Must be outdoors with clear sky view for GPS lock

### Location Display Screens

The radio can display:
- Your own position, heading, speed, altitude
- Last contact's position and direction from your location
- List of recently received contacts (last 30, cleared on power off)
- Distance to other radios

---

## Serial Connection Details

### For Reticulum Integration

When paired via Bluetooth, the UV-Pro creates a serial port:
- **Linux**: Typically `/dev/rfcomm0` or similar
- **Serial Interface**: KISS TNC mode over Bluetooth
- **Speed**: High-speed BSS mode
- **Configuration**: Set in Reticulum as SerialInterface

### Important Settings for Serial Data

1. **Digital Mode** - Must be enabled
2. **Format** - Set to BSS
3. **Digital Mute** - Recommended ON (silence data tones)
4. **Digital Channel** - Select appropriate RF channel
5. **Bluetooth** - Must be paired and connected

---

## Radio Configuration Settings

### Power Levels

- **Low (L)**: 2W
- **Medium (M)**: 5W  
- **High (H)**: 7W

### Frequency Ranges

- **VHF**: 136-174 MHz
- **UHF**: 400-520 MHz

### Channel Steps

2.5KHz / 5KHz / 6.25KHz / 10KHz / 12.5KHz / 25KHz / 50KHz / 100KHz

### Memory Channels

- 6 Banks of 30 channels each = 180 total channels
- Channel groups for organization
- Scan capability per channel

### Key Settings for Data Operations

**TX Time Limit**
- Limits maximum continuous transmission time
- Range: OFF to 300 seconds
- Important for data transmissions to prevent timeouts

**Squelch Level**
- Range: 0-9
- 0 = Open squelch (receives weak signals)
- 9 = Tight squelch (only strong signals)
- Recommended: 3-5 for data operations

**Tail Elimination**
- Removes end-of-transmission noise
- Enable for cleaner audio between same-brand radios

---

## Programmable Buttons

The UV-Pro has two programmable buttons (PF1, PF2) that can be configured for quick access to functions. Useful options for our integration:

### Relevant Functions

- **Toggle Radio TX Enable** - Quickly disable/enable transmitting
- **Transmit Power Switch** - Cycle through power levels
- **Main-PTT** - Transmit on main channel
- **Sub-PTT** - Transmit on sub channel
- **Send Location** - Manually trigger APRS/BSS location transmission
- **Toggle Monitor** - Turn squelch on/off
- **Toggle Dual CH** - Switch between single and dual watch

**Note**: Programmable buttons can only be configured via the smartphone app, not from the radio menu.

---

## Technical Specifications

### General

- **Frequency Stability**: ±2.5ppm
- **Battery**: 7.4V, 2600mAh
- **Operating Temperature**: -20°C to +60°C
- **Antenna Impedance**: 50Ω
- **Weight**: 312g
- **Dimensions**: 60mm(W) x 40mm(D) x 130mm(H) - not including antenna

### Transmitter

- **RF Output Power**: 2W (L) / 5W (M) / 7W (H)
- **Adjacent Channel Power**: ≤-68dB
- **FM Noise**: 45dB
- **FM Distortion**: ≤3%

### Receiver

- **Sensitivity (12dB SINAD)**: 0.16µV
- **Adjacent Channel Selectivity**: ≥68dB
- **Intermodulation Immunity**: ≥65dB
- **Audio Output Power**: 2W
- **Audio Distortion**: ≤3%

---

## Quick Setup for Reticulum Integration

### Step 1: Enable Bluetooth
1. Menu → Connections → Pairing
2. Pair with Pi node via Bluetooth

### Step 2: Configure Digital Mode
1. Menu → General Settings → Digital Mode
2. Enable: **ON**
3. Format: **BSS**
4. Digital Channel: Select dedicated data channel
5. Digital Mute: **ON** (recommended)
6. Share Location: **OFF** (receive only) or set interval as needed

### Step 3: Note Serial Port
- After pairing, note the serial port created (e.g., `/dev/rfcomm0`)
- This will be used in Reticulum SerialInterface configuration

### Step 4: Optimize RF Settings
1. Set appropriate TX power level (Medium or High recommended)
2. Configure squelch level (3-5 recommended)
3. Select clear RF channel with minimal interference
4. Ensure TX Time Limit is adequate (60-180 seconds recommended)

---

## Important Notes

1. **GPS Required**: For location-based features, GPS must have satellite lock (clear sky view)

2. **Channel Selection**: The "Digital Channel" setting determines which RF frequency is used for data transmission - coordinate with all nodes in your network

3. **BSS Compatibility**: BSS mode only works between UV-Pro radios - all nodes must have UV-Pro radios for mesh to function

4. **Battery Life**: Digital mode transmissions consume battery - enable "Low Power Mode" in Display Settings if needed

5. **Data Tones**: Even with Digital Mute enabled, LED indicators will show TX/RX activity

6. **Bluetooth Range**: Bluetooth range is limited (~10m) - UV-Pro must remain in proximity to paired Pi node

---

## Troubleshooting

### Bluetooth Won't Pair
- Ensure pairing mode is active (flashing LED)
- Check Bluetooth is enabled on Pi
- Try removing old pairing and re-pair
- Verify hci0 adapter is UP on Pi

### No Serial Port Created
- Check paired devices list on both radio and Pi
- Ensure connection is established, not just paired
- Check for `/dev/rfcomm*` or Bluetooth serial port
- May need to manually bind serial port

### Data Not Transmitting
- Verify Digital Mode is **Enabled**
- Check Format is set to **BSS**
- Ensure Digital Channel is configured
- Verify Bluetooth connection is active
- Check TX Time Limit isn't too restrictive

### Poor Range/Reliability
- Increase TX power to Medium or High
- Verify antenna is properly connected
- Check for RF interference on selected channel
- Adjust squelch level (try 3-5)
- Ensure clear line of sight when possible

---

**Last Updated**: 2026-01-14  
**Source**: BTech UV-Pro Instruction Manual Rev3
