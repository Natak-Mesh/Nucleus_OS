# UV-Pro Pairing & Configuration - Session 2026-01-17

## System Setup

**Pi 0002:**
- MAC: 38:D2:00:01:55:C0
- Hostname: 0002-nucleus

**Pi 0003:**
- MAC: 38:D2:00:01:4D:E3  
- Hostname: 0003-nucleus

**Status:** Both UV-Pro radios factory reset and firmware updated prior to this session.

---

## Bluetooth Pairing Procedure

### Pi 0002 - UV-Pro 38:D2:00:01:55:C0

**1. Prepare radio:**
- Put UV-Pro into pairing mode: Menu → Connections → Pairing
- LED should flash red/green alternately

**2. Scan and pair:**
```bash
bluetoothctl
power on
agent on
default-agent
scan on
# Wait for UV-PRO to appear in scan
pair 38:D2:00:01:55:C0   # First attempt fails - expected
pair 38:D2:00:01:55:C0   # Second attempt succeeds
trust 38:D2:00:01:55:C0
connect 38:D2:00:01:55:C0
exit
```

**3. Bind to RFCOMM channel 1:**
```bash
sudo rfcomm release 0
sudo rfcomm bind /dev/rfcomm0 38:D2:00:01:55:C0 1
sudo chmod 666 /dev/rfcomm0
rfcomm -a
```

**CRITICAL:** The `1` at the end is required - without it or with a different number, it doesn't work.

**Expected output:**
```
rfcomm0: 38:D2:00:01:55:C0 channel 1 connected [tty-attached]
```

---

### Pi 0003 - UV-Pro 38:D2:00:01:4D:E3

**1. Prepare radio:**
- Put UV-Pro into pairing mode: Menu → Connections → Pairing
- LED should flash red/green alternately

**2. Scan and pair:**
```bash
bluetoothctl
power on
agent on
default-agent
scan on
# Wait for UV-PRO to appear in scan
pair 38:D2:00:01:4D:E3   # First attempt fails - expected
pair 38:D2:00:01:4D:E3   # Second attempt succeeds
trust 38:D2:00:01:4D:E3
connect 38:D2:00:01:4D:E3
exit
```

**3. Bind to RFCOMM channel 1:**
```bash
sudo rfcomm release 0
sudo rfcomm bind /dev/rfcomm0 38:D2:00:01:4D:E3 1
sudo chmod 666 /dev/rfcomm0
rfcomm -a
```

**CRITICAL:** The `1` at the end is required - without it or with a different number, it doesn't work.

**Expected output:**
```
rfcomm0: 38:D2:00:01:4D:E3 channel 1 connected [tty-attached]
```

---

## UV-Pro Radio Configuration

**Navigate to:** Menu → General Settings

| Setting | Value | Notes |
|---------|-------|-------|
| **Digital Mode** | **OFF** | Critical - prevents radio from intercepting packets |
| **KISS TNC** | **ON** | Enables KISS protocol framing |
| **Upload Message** | **ON** | Enables message upload functionality |
| **TX Delay** | **300ms** | Allows Bluetooth module time to key PTT |

**Both radios must have identical settings.**

---

## Reticulum Configuration

**File:** `~/.reticulum/config`

**Update the UV-RF interface on both Pis:**

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
```

**Key changes from previous attempts:**
- `type = KISSInterface` (was SerialInterface)
- `speed = 115200` (was 9600)
- Binding to **channel 1** explicitly (critical - without it or with a different number, it doesn't work)
- Disabled Bluetooth Headset profile in `/etc/bluetooth/input.conf`

**Restart Reticulum:**
```bash
sudo systemctl restart rnsd
rnstatus
```

---

## Verification Commands

**Check Bluetooth pairing status:**
```bash
bluetoothctl paired-devices
bluetoothctl info 38:D2:00:01:55:C0  # or 38:D2:00:01:4D:E3
```

**Check RFCOMM binding:**
```bash
rfcomm -a
ls -la /dev/rfcomm0
```

**Check Reticulum interface:**
```bash
rnstatus
```

**Expected rnstatus output:**
```
KISSInterface[UV-RF]
   Status    : Up
   Mode      : Full
   Rate      : 115.20 kbps
```

---

## Test Results

### Test 1: RFCOMM Channel 4 (Explicit)
**Command:** `sudo rfcomm bind 0 <MAC> 4`

**Result:**
- Both Pis bound successfully to channel 4
- Reticulum KISSInterface status: Up
- Data flow: **NONE** - no TX/RX traffic
- Radio behavior: No PTT key, no TX LED

### Test 2: RFCOMM Auto-Negotiate (2026-01-17 20:06)
**Command:** `sudo rfcomm bind 0 <MAC>` (no channel specified)

**Result:**
- Both Pis auto-negotiated to channel 1
- `rfcomm -a` output: `channel 1 connected [tty-attached]`
- Reticulum KISSInterface status: Up
- Data flow: **NONE** - no TX/RX traffic
- Radio behavior: No PTT key, no TX LED

**Conclusion:** Channel selection (1 vs 4) does not affect outcome. Root cause is not rfcomm channel.

---

## Current Status (2026-01-17 20:10)

**Pairing:** ✅ Both radios successfully paired
**RFCOMM:** ✅ Bound and connected (tested channel 1 and 4)
**Reticulum:** ✅ Interface shows "Up"
**Data Flow:** ❌ Zero bytes TX/RX
**Radio TX:** ❌ No PTT keying, no TX LED, no audio tone

**Issue:** Reticulum sends data to /dev/rfcomm0, but UV-Pro radio does not transmit. No evidence of TNC receiving KISS frames.

---

## Important Notes

1. **Channel 4 is critical** - sdptool shows SPP (Serial Port Profile) on channel 4, not channel 1
2. **First pair attempt always fails** - documented behavior, retry succeeds
3. **Speed must be 115200** - UV-Pro Bluetooth module runs at this baud rate
4. **Factory reset clears pairing** - requires full re-pair if radios are reset
5. **RFCOMM release required** - must release existing binding before re-binding

---

## Next Steps - Bluetooth Headset Profile Interference

### Reference: VR-N76 RFCOMM Solution

A similar radio (VR-N76) had an identical issue on Linux:
- Bluetooth pairing: ✅ Works
- RFCOMM binding: ✅ Works  
- Data flow through serial: ❌ **Fails**

**Root cause:** Linux was detecting the radio as a Bluetooth headset (A2DP/HFP audio profile), which prevented RFCOMM serial communication from working properly.

**Solution:** Globally disable the Bluetooth Headset profile.

### Theory

When the UV-Pro is detected as a headset:
- Linux routes data through audio profiles (A2DP/HFP) instead of serial (RFCOMM)
- The /dev/rfcomm0 device exists and appears connected
- But no actual data flows through the serial channel
- The radio never receives KISS frames, so it never transmits

This matches our symptoms exactly.

### Test Procedure

**1. Disable Bluetooth Headset profile:**
```bash
sudo nano /etc/bluetooth/input.conf
```

Add or modify:
```ini
[General]
Disable=Headset
```

Save and exit (Ctrl+X, Y, Enter)

**2. Restart Bluetooth service:**
```bash
sudo systemctl restart bluetooth
```

**3. Re-pair UV-Pro:**
```bash
# Remove old pairing
bluetoothctl
remove 38:D2:00:01:55:C0  # or 38:D2:00:01:4D:E3
exit

# Put radio in pairing mode, then:
bluetoothctl
power on
agent on
default-agent
scan on
# Wait for UV-PRO to appear
pair <MAC>   # First attempt may fail
pair <MAC>   # Retry succeeds
trust <MAC>
connect <MAC>
exit
```

**4. Re-bind RFCOMM:**
```bash
sudo rfcomm release 0
sudo rfcomm bind /dev/rfcomm0 <MAC> 1
sudo chmod 666 /dev/rfcomm0
rfcomm -a
```

**CRITICAL:** The `1` at the end is required - without it or with a different number, it doesn't work.

**5. Restart Reticulum and test:**
```bash
sudo systemctl restart rnsd
rnstatus
```

**6. Observe for TX activity:**
- Watch radio TX LED
- Listen for PTT key and data tone
- Check `rnstatus` for TX/RX byte counts increasing

### Important Notes

- This must be done on **both Pi 0002 and Pi 0003**
- If you need Bluetooth headset functionality on these machines, UDEV rules may be a better solution
- After disabling headset profile, radios should be detected as serial devices only

---

## Next Test: VR-N76 Solution (2026-01-18 16:38)

Found community post about VR-N76 radio with identical symptoms. Their solution:
- Disable Bluetooth Headset profile: `sudo nano /etc/bluetooth/input.conf` → `Disable=Headset`
- Bind to channel 1 explicitly: `sudo rfcomm bind /dev/rfcomm0 <MAC> 1`

Radio was already paired and trusted after reboot. Need to:
1. Set up rfcomm binding to channel 1
2. Restart rnsd
3. Test if it works

---

**Document Created:** 2026-01-17 19:53 EST  
**Last Updated:** 2026-01-18 16:38 EST
