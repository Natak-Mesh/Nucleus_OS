# Waveshare SIM7600G-H 4G HAT — Setup Guide

## Overview

This documents the setup and configuration of the Waveshare SIM7600G-H 4G HAT on the Nucleus mesh node (Raspberry Pi). The board connects via USB and provides cellular WAN backhaul.

---

## Hardware Detection

### USB Devices (via `lsusb`)

The Waveshare 4G board exposes three devices through a USB hub:

| Device | USB ID | Description |
|--------|--------|-------------|
| **MediaTek WiFi** | `0e8d:7610` | MT7610U USB WiFi adapter |
| **RAK Meshtastic** | `239a:8029` | Adafruit WisCore RAK4631 Board |
| **SIM7600G-H Cellular** | `1e0e:9001` | Qualcomm / Option SimTech, Incorporated |

### Serial Ports

The SIM7600G-H creates 5 USB serial ports:

| Port | Function |
|------|----------|
| `/dev/ttyUSB0` | Diagnostic |
| `/dev/ttyUSB1` | GPS NMEA output |
| `/dev/ttyUSB2` | **AT command port** (primary control) |
| `/dev/ttyUSB3` | Modem / PPP data |
| `/dev/ttyUSB4` | Audio |

The modem also exposes a QMI/MBIM interface at `/dev/cdc-wdm0` which NetworkManager uses for data connections.

### Network Interface

When a cellular data connection is active, the modem creates the `wwan0` network interface.

---

## SIM Card

### eIOT Club Multi-Carrier MVNO

- **Type**: Triple-play (standard/micro/nano punch-out), pay-as-you-go
- **Carriers**: Roams across Verizon, AT&T, T-Mobile
- **APN**: `altanwifi` (for Americas)
- **Username/Password**: None required
- **Activation**: Must be activated at [eiotclub.com](https://www.eiotclub.com) before use — register with the ICCID printed on the SIM card

In our testing, the SIM registered on **Verizon LTE** via eIOT Club.

---

## ModemManager Conflict

**Important**: ModemManager (PID typically visible as `ModemManager` in `ps`) holds `/dev/ttyUSB2` and `/dev/ttyUSB3`. You **must stop ModemManager** before using minicom to send AT commands directly.

### Check what's holding the port
```bash
sudo fuser /dev/ttyUSB2
# Returns PID, e.g.: /dev/ttyUSB2: 679

ps -p 679 -o comm=
# Returns: ModemManager
```

### Stop ModemManager for minicom access
```bash
sudo systemctl stop ModemManager
```

### Restart ModemManager when done (needed for NetworkManager cellular)
```bash
sudo systemctl start ModemManager
```

---

## AT Commands via Minicom

### Opening minicom
```bash
sudo minicom -D /dev/ttyUSB2
```

**Note**: AT commands must be typed in **UPPERCASE**.

### Exiting minicom
Press **Ctrl+A**, then **X**, then confirm with Enter.

### Essential AT Commands (all read-only / safe)

| Command | Purpose | Expected Response |
|---------|---------|-------------------|
| `AT` | Test communication | `OK` |
| `AT+CPIN?` | Check SIM status | `+CPIN: READY` |
| `AT+CSQ` | Signal strength (0-31, higher=better) | `+CSQ: 23,99` (23=good, 99=BER not available) |
| `AT+COPS?` | Current registered network | `+COPS: 0,0,"Verizon Wirelss EIOTCLUB",7` |
| `AT+CGDCONT?` | Read PDP context / APN config | `+CGDCONT: 1,"IP","altanwifi",...` |
| `AT+CREG?` | Network registration status | `0,1` = registered, `0,2` = searching, `0,3` = denied |
| `AT+CICCID` | Read SIM ICCID | ICCID number (identifies carrier) |
| `AT+CNUM` | Read phone number on SIM | Phone number if available |
| `AT+CPSI?` | Serving cell info (band, technology) | Detailed cell info |

### Signal Strength Reference (AT+CSQ)

| CSQ Value | dBm (approx) | Quality |
|-----------|---------------|---------|
| 0-9 | -113 to -95 | Poor |
| 10-14 | -93 to -83 | Fair |
| 15-19 | -81 to -73 | Good |
| 20-31 | -71 to -51 | Excellent |
| 99 | Unknown | No signal |

### COPS Response — Technology Codes

| Code | Technology |
|------|-----------|
| 0 | GSM |
| 2 | UTRAN (3G) |
| 7 | E-UTRAN (LTE) |

---

## Bringing Up the Data Connection

### Method: NetworkManager + ModemManager

This is the recommended method for persistent, managed cellular connections.

```bash
# 1. Make sure ModemManager is running
sudo systemctl start ModemManager

# 2. Wait ~5 seconds for modem detection, then verify
mmcli -L

# 3. Check NetworkManager sees the modem
nmcli device status
# Should show: cdc-wdm0  gsm  disconnected  --

# 4. Create the GSM connection (one-time setup)
sudo nmcli connection add type gsm ifname cdc-wdm0 con-name "eiotclub" apn "altanwifi"

# 5. Activate
sudo nmcli connection up eiotclub

# 6. Verify — ping through the cellular interface specifically
ping -I wwan0 -c 3 8.8.8.8
```

### Verifying the Interface
```bash
ip addr show wwan0
# Should show an IP address (e.g., 10.139.90.37/30)
```

---

## Data Usage Tracking with vnstat

### Installation
```bash
sudo apt install -y vnstat
# vnstat auto-detects wwan0 and starts tracking
```

### Checking Usage
```bash
vnstat -i wwan0          # Summary
vnstat -i wwan0 -d       # Daily breakdown
vnstat -i wwan0 -m       # Monthly breakdown
vnstat -i wwan0 -h       # Hourly graph
vnstat -i wwan0 -l       # Live real-time monitor
```

A convenience script is available at `/opt/nucleus/bin/cellular/cell-stats.sh`.

### Service
vnstat runs as a systemd service and persists data across reboots:
```bash
sudo systemctl status vnstat
```

---

## Troubleshooting

### "Device or resource busy" on /dev/ttyUSB2
ModemManager is holding the port. Stop it first:
```bash
sudo systemctl stop ModemManager
```

### SIM not detected (AT+CPIN? returns ERROR)
- Check SIM is properly seated in the slot
- Ensure SIM is the correct size for the slot (nano)
- Try reseating the SIM and power-cycling the modem

### No network registration (AT+CREG? returns 0,2 or 0,3)
- `0,2` = searching — wait, may take a minute
- `0,3` = registration denied — SIM may not be activated
- Activate the SIM at eiotclub.com

### No data connection despite registration
- Verify APN is set correctly: `AT+CGDCONT?`
- For eIOT Club: APN should be `altanwifi` (Americas)
- Check signal: `AT+CSQ` — needs to be above ~10

---

## Quick Reference

```
SIM:        eIOT Club (multi-carrier MVNO)
APN:        altanwifi
Auth:       None
Network:    Verizon LTE (auto-selected)
AT Port:    /dev/ttyUSB2
QMI Port:   /dev/cdc-wdm0
Interface:  wwan0
Minicom:    sudo minicom -D /dev/ttyUSB2
Exit:       Ctrl+A, then X
```
