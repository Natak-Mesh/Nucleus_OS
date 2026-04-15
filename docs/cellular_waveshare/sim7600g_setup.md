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

---

## DNS Wipe Issue (NetworkManager)

### The Problem

When the cellular connection drops and reconnects (which happens periodically — carrier handoffs, signal fluctuation, etc.), NetworkManager rewrites `/etc/resolv.conf`. If NM is running with its default DNS mode (`dns=default`), each connect/disconnect cycle overwrites the file. When the connection drops, NM can leave resolv.conf empty or with only a `# Generated by NetworkManager` header and no nameservers. The result: the cellular data link comes back up and packets flow, but **DNS resolution is broken** — the system can't resolve hostnames, so internet appears down even though `ping 8.8.8.8` would work fine.

This is insidious because `mesh-start.sh` writes DNS at boot (`nameserver 8.8.8.8` / `8.8.4.4`), but only runs once. Any subsequent NM connection cycle wipes those entries.

### The Fix

**1. Set `dns=none` in NetworkManager.conf** — tells NM to never touch `/etc/resolv.conf`:

```
# /etc/NetworkManager/NetworkManager.conf
[main]
plugins=ifupdown,keyfile
dns=none
```

This file is tracked in the repo at `etc/NetworkManager/NetworkManager.conf` and deployed by `deploy.sh`.

**2. Set static DNS on the eiotclub connection** — belt-and-suspenders, ensures the NM connection profile always carries known-good nameservers:

```bash
sudo nmcli connection modify eiotclub ipv4.dns "8.8.8.8 8.8.4.4" ipv4.ignore-auto-dns yes
```

This persists across reboots in `/etc/NetworkManager/system-connections/eiotclub.nmconnection`.

**3. `mesh-start.sh` still writes resolv.conf at boot** as a final safety net (lines 111–112).

### How to Verify

```bash
# Check NM is not managing DNS
grep dns /etc/NetworkManager/NetworkManager.conf
# Should show: dns=none

# Check eiotclub has static DNS
nmcli connection show eiotclub | grep -i "ipv4.dns\|ignore-auto-dns"
# Should show: ipv4.dns: 8.8.8.8,8.8.4.4 and ipv4.ignore-auto-dns: yes

# Check resolv.conf has nameservers
cat /etc/resolv.conf
```

---

## SIM Expiration & Recovery

### Symptoms

When the eIOT Club SIM expires (pay-as-you-go balance runs out or plan lapses), the modem can still see cell towers but the carrier **actively rejects** registration. The rejection errors escalate:

| `mmcli -m 0` field | Value | Meaning |
|---------------------|-------|---------|
| `registration` | `searching` | Modem is trying to register |
| `network rejection error` | `gprs-not-allowed` | Carrier says this SIM can't use data |
| `network rejection error` | `no-cells-in-location-area` | Carrier refuses to serve this SIM entirely |
| `signal quality` | `0%` with `state: searching` | Modem gave up after repeated rejections |

In the journal (`journalctl -u NetworkManager`), you'll see a repeating cycle every ~3 minutes:
```
modem-broadband[cdc-wdm0]: failed to connect modem: Network timeout
device (cdc-wdm0): Activation: failed for connection 'eiotclub'
policy: auto-activating connection 'eiotclub'
```

ModemManager (`journalctl -u ModemManager`) will show:
```
couldn't load operator code: Current operator MCC/MNC is still unknown
registration in network failed: Network timeout
```

### Understanding the Diagnostic Output

The primary diagnostic tool is `mmcli -m 0` (or whatever modem index `mmcli -L` shows). Key fields in the `3GPP` section:

- **`operator id`**: The MCC/MNC of the carrier the modem sees. For Verizon this is **`311480`** (MCC 311 = USA, MNC 480 = Verizon Wireless). This number comes from the modem's cell scan and identifies which carrier's towers are nearby. You use this same number to force manual registration.

- **`registration`**: The modem's current registration state:
  - `home` or `roaming` = successfully registered ✅
  - `searching` = actively trying to register
  - `idle` = gave up searching (bad sign)
  - `denied` = carrier explicitly rejected

- **`packet service state`**: Whether the data bearer is up:
  - `attached` = data service active ✅
  - `detached` = no data service

- **`network rejection error`**: The specific reason the carrier rejected the modem. Common values:
  - `gprs-not-allowed` = SIM doesn't have active data service (expired/suspended)
  - `no-cells-in-location-area` = carrier refuses to serve this SIM at all
  - (empty) = no rejection, modem just hasn't found a tower yet

### Recovery Procedure

**Step 1: Reactivate the SIM**

Log into [eiotclub.com](https://www.eiotclub.com), find the SIM by ICCID, and reactivate/add credit. The ICCID is printed on the SIM card and also readable via `mmcli -i 0` (look for `iccid` field). Note: the modem may report one extra digit at the end — this is a Luhn check digit and is normal.

**Step 2: Toggle the modem radio**

After SIM reactivation, the modem's RF stack may be stuck from repeated rejections. Stop ModemManager, then toggle the radio off and back on via AT commands:

```bash
sudo systemctl stop ModemManager
# Turn radio off, wait, turn back on
sudo bash -c 'echo -e "AT+CFUN=0\r" > /dev/ttyUSB2; sleep 3; echo -e "AT+CFUN=1\r" > /dev/ttyUSB2'
sudo systemctl start ModemManager
```

`AT+CFUN=0` powers down the modem's radio transceiver (the modem stays on but stops transmitting). `AT+CFUN=1` powers it back up, forcing a fresh cell search and clearing any cached rejection state. This is more thorough than a modem reset because it specifically resets the radio/registration state machine.

Wait ~10 seconds, then check if the modem can see the carrier:

```bash
mmcli -m 0 | grep -E "state|registration|signal|operator"
```

You should see `operator id: 311480`, `operator name: Verizon`, and `signal quality` above 0%. If `registration` is still `searching`, proceed to Step 3.

**Step 3: Force manual registration**

NetworkManager's auto-connect loop interferes with manual registration. Disconnect it first, then force registration on Verizon using the operator code:

```bash
# Disconnect NM's connection attempt
sudo nmcli connection down eiotclub

# Force registration on Verizon (311480)
sudo mmcli -m 0 --3gpp-register-in-operator=311480
# Should print: "successfully registered the modem"
```

The `311480` comes from the `operator id` field in `mmcli -m 0` output. If you're on a different carrier (e.g., AT&T = 310410, T-Mobile = 310260), use that carrier's MCC/MNC instead.

**Step 4: Bring up the data connection**

```bash
sudo nmcli connection up eiotclub
# Should print: "Connection successfully activated"
```

**Step 5: Verify**

```bash
# Check for IP on wwan0
ip addr show wwan0 | grep inet

# Ping through cellular
ping -I wwan0 -c 3 8.8.8.8

# Check DNS works
curl -s --max-time 5 -o /dev/null -w "HTTP %{http_code}\n" https://google.com
```

### If It Still Won't Register

If the modem has signal but the carrier keeps rejecting after reactivation, the SIM provisioning may need more time to propagate through the MVNO chain (eIOT Club → Verizon's HLR/HSS → local towers). This can take **5–30 minutes** for MVNOs. Keep the modem powered on and ModemManager running — NM will auto-connect once the carrier accepts registration.

If it's been over an hour, contact eIOT Club support — the reactivation may not have completed on their end.
