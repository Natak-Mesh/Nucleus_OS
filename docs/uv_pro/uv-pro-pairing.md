# BTech UV-Pro Bluetooth Pairing Guide

## Device Reference

| Node | Hostname | UV-Pro MAC Address |
|------|----------|--------------------|
| 0002 | 0002-nucleus | `38:D2:00:01:55:C0` |
| 0003 | 0003-nucleus | `38:D2:00:01:4D:E3` |

---

## Prerequisites (One-Time Setup)

**Disable Bluetooth Headset Profile** (prevents audio profile interference):

```bash
sudo nano /etc/bluetooth/input.conf
```

Add:
```ini
[General]
Disable=Headset
```

Save and restart Bluetooth:
```bash
sudo systemctl restart bluetooth
```

---

## UV-Pro Radio Settings

Navigate to **Menu → General Settings**:

| Setting | Value |
|---------|-------|
| **Digital Mode** | **OFF** |
| **KISS TNC** | **ON** |
| **TX Delay** | **300ms** |

---

## Bluetooth Pairing

**1. Pair from Pi:**
```bash
bluetoothctl
scan on
```

**2. Enable pairing on radio:**
- Menu → Pairing

Wait for `UV-PRO` to appear in scan, then:

```bash
scan off
pair 38:D2:00:01:55:C0    # Replace with your radio's MAC
trust 38:D2:00:01:55:C0
exit
```

**3. Bind RFCOMM:**
```bash
sudo rfcomm bind /dev/rfcomm0 38:D2:00:01:55:C0 1
```

**4. Restart the radio** (power off/on)

**5. Unbind and rebind:**
```bash
sudo rfcomm release 0
sudo rfcomm bind /dev/rfcomm0 38:D2:00:01:55:C0 1
```

**6. Start Reticulum:**
```bash
sudo systemctl restart rnsd
```

---

## Reticulum Configuration

Edit `~/.reticulum/config`:

### UV-Pro RF Interface
```ini
[[UV-RF]]
type = KISSInterface
enabled = true
port = /dev/rfcomm0
speed = 1200           # Tested speeds: 1200 ✓, 9600 ✓, 115200 (next to test)
databits = 8
parity = none
stopbits = 1
preamble = 150
txtail = 10
persistence = 200
slottime = 20
flow_control = false
```

### TCP Server (for external Sideband devices)
```ini
[[LAN TCP Server]]
type = TCPServerInterface
enabled = true
device = br-lan
listen_port = 4242
```

**Restart Reticulum:**
```bash
sudo systemctl restart rnsd
rnstatus
```

---

## Reconnect Script

If Bluetooth connection drops, use this script to reconnect:

```bash
#!/bin/bash
# Replace MAC with your radio's address
sudo rfcomm release 0
sudo rfcomm bind /dev/rfcomm0 38:D2:00:01:55:C0 1
sudo chmod 666 /dev/rfcomm0
sudo systemctl restart rnsd
```

---

## Verification

**Check pairing:**
```bash
bluetoothctl paired-devices
```

**Check RFCOMM:**
```bash
rfcomm -a
ls -la /dev/rfcomm0
```

**Check Reticulum interface:**
```bash
rnstatus
```

Expected output:
```
KISSInterface[UV-RF]
  Status  : Up
  Mode    : Full
  Rate    : 1.20 kbps
```

---

## Troubleshooting

**Radio doesn't appear in scan:**
- Ensure radio is in pairing mode (LED flashing)
- Radio must be unpaired from phone app first

**Pairing fails:**
- First attempt often fails - retry immediately
- If still fails: `bluetoothctl remove <MAC>` and start over

**No RF transmission:**
- Verify Digital Mode = OFF (critical)
- Verify KISS TNC = ON
- Check `/etc/bluetooth/input.conf` has headset disabled
- Restart both Bluetooth and rnsd
- verify you have a sideband device connected via tcp interface

**Connection lost after reboot:**
- Run reconnect script
- RFCOMM binding doesn't persist across reboots

**Connection issues after congestion/jamming:**
- Clear Reticulum storage: `rm -rf ~/.reticulum/storage/*`
- Reboot the nodes
- Run through the radio connection again (rfcomm bind, restart radio, unbind then rebind)
- Restart rnsd: `sudo systemctl restart rnsd`
