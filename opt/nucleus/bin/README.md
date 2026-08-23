# Nucleus Drone — Scripts

Shell scripts for mesh initialization and configuration on the drone node.

## Scripts

| Script | Purpose | When Run |
|--------|---------|----------|
| `mesh-start.sh` | Initialize mesh interface and services | Boot (via systemd) |
| `config_generation.sh` | Generate system configs from mesh.conf | After config changes |
| `eth0-mode.sh` | Switch eth0 between WAN/LAN modes | Manual |
| `iw-wifi-scan.sh` | Wi-Fi channel survey | Manual |
| `sd-wear-setup.sh` | Minimize SD card writes | One-time setup |

---

## mesh-start.sh

Run by `mesh-start.service` at boot.

**Sequence:**
1. Enable IP forwarding (`net.ipv4.ip_forward=1`)
2. Set interfaces unmanaged by NetworkManager (eth0, wlan0, wlan1, br-lan)
3. Configure wlan1: mesh mode, meshid, channel
4. Start wpa_supplicant for mesh encryption (SAE)
5. Wait 15s for encryption handshake
6. Apply mesh IP addresses (IPv4 + IPv6 link-local)
7. Set 802.11s mesh TTL and RTS/CTS threshold
8. Set DNS resolvers (8.8.8.8, 8.8.4.4)
9. Enable NAT masquerade on eth0
10. Bump multicast TTL on br-lan ingress
11. Restart smcroute so wlan1 registers as a multicast VIF

**Key files used:**
- `/etc/nucleus/mesh.conf` — Configuration variables
- `/etc/wpa_supplicant/wpa_supplicant-wlan1-encrypt.conf` — Mesh encryption

---

## config_generation.sh

Generates all configuration files from `/etc/nucleus/mesh.conf`.

**Generated files:**

| File | Purpose |
|------|---------|
| `/etc/systemd/network/40-eth0-lan.network` | eth0 network config |
| `/etc/systemd/network/10-wlan1.network` | Mesh interface config |
| `/etc/systemd/network/21-brlan.network` | LAN bridge config with DHCP server |
| `/etc/hostapd/hostapd.conf` | Access point config |
| `/etc/wpa_supplicant/wpa_supplicant-wlan1-encrypt.conf` | Mesh encryption (SAE) |
| `/etc/babeld.conf` | Babel routing daemon config |
| `/etc/mavlink-router/main.conf` | FC UART ↔ mesh UDP bridge |

**Usage:**
```bash
sudo /opt/nucleus/bin/config_generation.sh
sudo reboot
```

---

## eth0-mode.sh

Switch eth0 between WAN and LAN operating modes.

| Mode | eth0 Configuration | Use Case |
|------|-------------------|----------|
| WAN | DHCP client + NAT masquerade | eth0 to router for internet / updates |
| LAN | Bridged to br-lan | eth0 to device needing mesh access |

```bash
eth0-mode.sh wan
eth0-mode.sh lan
eth0-mode.sh set-default wan
eth0-mode.sh status
```

---

## sd-wear-setup.sh

One-time setup to minimize SD card writes.

- Disables swap
- Adds `noatime` to root filesystem mount
- Mounts `/tmp` as tmpfs (50MB RAM)
- Configures systemd journal to RAM-only (50MB)

```bash
sudo /opt/nucleus/bin/sd-wear-setup.sh
```

---

## Configuration Variables

All scripts source `/etc/nucleus/mesh.conf`:

| Variable | Used By | Example |
|----------|---------|---------|
| `MESH_NAME` | mesh-start, config_gen | `natak_mesh` |
| `MESH_CHANNEL` | mesh-start, config_gen | `3` |
| `MESH_PASSWORD` | config_gen | `52235223` |
| `MESH_IP` | mesh-start, config_gen | `10.20.1.9` |
| `MESH_IPV6_LL` | mesh-start, config_gen | `fe80::...` |
| `BR_LAN_IP` | config_gen | `10.20.9.1` |
| `BR_LAN_IPV6_LL` | config_gen | `fe80::...` |
| `AP_NAME` | config_gen | `0009-nucleus-ap` |
| `AP_CHANNEL` | config_gen | `36` |
| `AP_PASSWORD` | config_gen | `52235223` |
| `ETH0_STATIC_IP` | config_gen | `10.10.9.1` |
| `MESH_MCAST_TTL` | mesh-start | `8` |
| `MESH_802_TTL` | mesh-start | `8` |
| `MESH_RTS_THRESHOLD` | mesh-start | `500` |
| `MAVLINK_SERIAL` | config_gen | `/dev/ttyAMA0` |
| `MAVLINK_BAUD` | config_gen | `921600` |
| `MAVLINK_UDP_PORT` | config_gen | `14550` |

---

## Systemd Integration

| Service | Script | Description |
|---------|--------|-------------|
| `mesh-start.service` | mesh-start.sh | Main mesh startup |
| `mavlink-router.service` | - | FC UART ↔ mesh UDP |
| `babeld.service` | - | Babel routing daemon |
| `smcroute.service` | - | Multicast routing |
| `hostapd.service` | - | Access point (wlan0) |

**Startup order:**
1. systemd-networkd (bridge setup)
2. mesh-start.service (mesh interface)
3. babeld.service (routing)
4. hostapd.service (AP)
5. mavlink-router.service (FC link)
