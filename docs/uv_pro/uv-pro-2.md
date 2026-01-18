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

**3. Bind to RFCOMM channel 4:**
```bash
sudo rfcomm release 0
sudo rfcomm bind 0 38:D2:00:01:55:C0 4
sudo chmod 666 /dev/rfcomm0
rfcomm -a
```

**Expected output:**
```
rfcomm0: 38:D2:00:01:55:C0 channel 4 connected [tty-attached]
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

**3. Bind to RFCOMM channel 4:**
```bash
sudo rfcomm release 0
sudo rfcomm bind 0 38:D2:00:01:4D:E3 4
sudo chmod 666 /dev/rfcomm0
rfcomm -a
```

**Expected output:**
```
rfcomm0: 38:D2:00:01:4D:E3 channel 4 connected [tty-attached]
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
- Binding to **channel 4** (was defaulting to channel 1)

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

**Document Created:** 2026-01-17 19:53 EST  
**Last Updated:** 2026-01-17 19:53 EST
