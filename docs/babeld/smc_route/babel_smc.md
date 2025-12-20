# 802.11s + Babel + smcroute Migration Guide (Concise)

This document summarizes the required steps to migrate from an 802.11s + BATMAN-adv L2 mesh to a clean L3 routed mesh using Babel and smcroute, with systemd-networkd handling all interface configuration.

Why Switch
- BATMAN-adv = constant L2 flooding (OGMs, ARP, DHCP, mDNS, SSDP).
- Babel = unicast neighbor updates → far lower load.
- No giant L2 broadcast domain.
- wlan1 becomes a clean routed interface.
- wlan0/eth0 clients can access the mesh without static routes.
- AP clients and OTG phone connections work automatically.

Final Network Architecture

Interfaces
- wlan1 → 802.11s mesh, static IP, Babel routing
- br-lan → LAN bridge (wlan0 + optionally eth0)
- wlan0 → AP
- eth0 → automatic WAN/LAN (DHCP or fallback static)

Subnets
- wlan1: 10.0.0.x/24 (static per node)
- br-lan: 192.168.50.1/24
- LAN clients: served via networkd DHCP server
- WAN (eth0 plugged into home router): DHCP from router

Required Packages
sudo apt install babeld smcroute hostapd nftables tcpdump

## Current State of the Build

### Service Configuration

1. **Enable systemd-networkd:**
```bash
sudo systemctl enable systemd-networkd
sudo systemctl start systemd-networkd
```

2. **Configure hostapd:**
```bash
sudo systemctl unmask hostapd
sudo systemctl enable hostapd
# Note: hostapd will be started by mesh-start.sh after config generation
```

3. **Disable wpa_supplicant (started by script):**
```bash
sudo systemctl disable wpa_supplicant
sudo systemctl mask wpa_supplicant@.service
# Note: wpa_supplicant will be started by mesh-start.sh for mesh encryption
```

### Deployment Workflow

All development work is done in `~/git` directory and deployed to the system:

1. **Work in git repository:**
   ```bash
   cd ~/git
   # Edit files as needed
   ```

2. **Deploy files to system:**
   ```bash
   ./deploy.sh
   # Copies files from ~/git to their proper system locations
   ```

3. **Edit mesh configuration:**
   ```bash
   sudo nano /etc/nucleus/mesh.conf
   # Configure MESH_NAME, MESH_CHANNEL, MESH_IP, etc.
   ```

4. **Generate config files:**
   ```bash
   sudo /opt/nucleus/bin/config_generation.sh
   # Generates: 10-wlan1.network, hostapd.conf, wpa_supplicant-wlan1-encrypt.conf
   ```

5. **Start the mesh:**
   ```bash
   sudo /opt/nucleus/bin/mesh-start.sh
   # Configures interfaces, starts wpa_supplicant and hostapd
   ```

**Key Points:**
- Scripts are in `/opt/nucleus/bin/`
- Configuration master file: `/etc/nucleus/mesh.conf`
- Generated configs: `/etc/systemd/network/10-wlan1.network`, `/etc/hostapd/hostapd.conf`, `/etc/wpa_supplicant/wpa_supplicant-wlan1-encrypt.conf`
- Keep `deploy.sh` updated when adding new files to the git repository
- Flow: Edit in `~/git` → Run `deploy.sh` → Edit `mesh.conf` → Run `config_generation.sh` → Run `mesh-start.sh`

### To Do

**Current Status:** mesh-start.sh creates a functioning 802.11s mesh network

**Remaining Tasks:**
1. Review and possibly adjust the `mesh_fwding` parameter in mesh-start.sh/wpa_supplicant configuration
2. Implement babeld configuration and integration
3. Implement smcroute configuration for multicast forwarding
4. Test end-to-end routing between mesh nodes

systemd-networkd Configuration

1. wlan1 – Static Mesh IP
/etc/systemd/network/10-wlan1.network:
[Match]
Name=wlan1
[Network]
Address=10.0.0.2/24

2. br-lan Bridge

NetDev:
/etc/systemd/network/20-brlan.netdev:
[NetDev]
Name=br-lan
Kind=bridge

Bridge IP + DHCP Server:
/etc/systemd/network/21-brlan.network:
[Match]
Name=br-lan
[Network]
Address=192.168.50.1/24
DHCPServer=yes

3. wlan0 → Bridge into br-lan
/etc/systemd/network/30-wlan0.network:
[Match]
Name=wlan0
[Network]
Bridge=br-lan

4. eth0 – LAN Bridge

/etc/systemd/network/40-eth0-lan.network:
[Match]
Name=eth0
[Network]
Bridge=br-lan

**Note:** eth0 mode switching is handled by eth0-mode.sh script

Babeld Setup

/etc/babeld.conf:
interface wlan1
interface br-lan
redistribute ip
redistribute local

Enable Babel:
sudo systemctl enable --now babeld

smcroute Setup (example ATAK CoT group 239.2.3.1)

/etc/smcroute.conf:
mgroup from wlan1 group 239.2.3.1
mgroup from br-lan group 239.2.3.1
mroute from wlan1 group 239.2.3.1 to wlan1 br-lan
mroute from br-lan group 239.2.3.1 to wlan1

Enable smcroute:
sudo systemctl enable --now smcroute

NAT for Internet (eth0 as WAN)
/etc/nftables.conf example:
table ip nat {
    chain postrouting {
        type nat hook postrouting priority 100;
        oifname "eth0" masquerade
    }
}

tcpdump Verification

Multicast forwarding test:
tcpdump -n -i wlan1 host 239.2.3.1

Babel traffic test:
tcpdump -n -i wlan1 port 6696

Summary
- wlan1 = static IP, routed by Babel
- br-lan = AP + LAN clients (DHCP via systemd-networkd)
- eth0 = WAN if DHCP works, LAN if fallback static
- smcroute forwards only needed multicast
- No bridging of wlan1
- No static routes needed for users

Filesystem Structure

```
/etc/nucleus/                  # Config files
  ├── mesh.conf               # Mesh settings
  └── web.conf                # Flask settings

/opt/nucleus/                  # Application root
  ├── bin/                     # Executable scripts
  │   ├── config_generation.sh  # Generate config files
  │   ├── eth0-mode.sh         # eth0 mode switching
  │   └── mesh-start.sh        # Mesh establishment
  └── web/                     # Flask app (no venv)
      ├── app.py
      ├── static/
      └── templates/

/etc/hostapd/                  # hostapd configs
  └── hostapd.conf            # Generated by config_generation.sh

/etc/systemd/network/          # systemd-networkd configs
  ├── 10-wlan1.network        # Generated by config_generation.sh
  ├── 20-brlan.netdev
  ├── 21-brlan.network
  ├── 30-wlan0.network
  └── 40-eth0-lan.network

/etc/systemd/system/           # Service files
  └── nucleus-web.service

/etc/wpa_supplicant/           # WPA supplicant configs
  └── wpa_supplicant-wlan1-encrypt.conf  # Generated by config_generation.sh
```

**Notes:**
- No venv required (packages installed with --break-system-packages)
- Flask service uses: `ExecStart=/usr/bin/python3 /opt/nucleus/web/app.py`
- All Nucleus components under /opt/nucleus/ for easy management
