# Natak Mesh - Nucleus Scripts

Shell scripts for mesh network initialization and configuration.

## Scripts

| Script | Purpose | When Run |
|--------|---------|----------|
| `mesh-start.sh` | Initialize mesh interface and services | Boot (via systemd) |
| `config_generation.sh` | Generate system configs from mesh.conf | After config changes |
| `eth0-mode.sh` | Switch eth0 between WAN/LAN modes | Manual or web GUI |
| `opendht-start.sh` | Start OpenDHT Docker container | Called by mesh-start |
| `sd-wear-setup.sh` | Minimize SD card writes | One-time setup |
| `openvlm-voice.py` | Mesh PTT voice daemon (OpenVLM headset + phone soft-PTT) | Boot (via systemd) |
| `voice` | User CLI for voice daemon (installed to /usr/local/bin) | Manual |
| `openvlm-monitor.py` | OpenVLM PTT/audio hardware test tool | Manual |


---

## mesh-start.sh

Main mesh startup script, run by `mesh-start.service` at boot.

**Sequence:**
1. Enable IP forwarding (`net.ipv4.ip_forward=1`)
2. Set interfaces unmanaged by NetworkManager (eth0, wlan0, wlan1, br-lan)
3. Configure wlan1: mesh mode, meshid, channel
4. Start wpa_supplicant for mesh encryption (SAE)
5. Wait 15s for encryption handshake
6. Apply mesh IP addresses (IPv4 + IPv6 link-local)
7. Set DNS resolvers (8.8.8.8, 8.8.4.4)
8. Enable NAT masquerade on eth0
9. Start OpenDHT if enabled

**Key files used:**
- `/etc/nucleus/mesh.conf` - Configuration variables
- `/etc/wpa_supplicant/wpa_supplicant-wlan1-encrypt.conf` - Mesh encryption

---

## config_generation.sh

Generates all configuration files from `/etc/nucleus/mesh.conf` variables.

**Generated files:**

| File | Purpose |
|------|---------|
| `/etc/systemd/network/40-eth0-lan.network` | eth0 network config |
| `/etc/systemd/network/10-wlan1.network` | Mesh interface config |
| `/etc/systemd/network/21-brlan.network` | LAN bridge config with DHCP server |
| `/etc/hostapd/hostapd.conf` | Access point config |
| `/etc/wpa_supplicant/wpa_supplicant-wlan1-encrypt.conf` | Mesh encryption (SAE) |
| `/etc/babeld.conf` | Babel routing daemon config |
| `/etc/nginx/sites-available/zzz-nucleus-web` | Web UI `.local` vhost (also proxies `/voice-ws` WSS → voice daemon) + self-signed TLS cert |


**Usage:**
```bash
sudo /opt/nucleus/bin/config_generation.sh
sudo reboot  # Required for changes to take effect
```

---

## eth0-mode.sh

Switch eth0 between WAN and LAN operating modes.

**Modes:**

| Mode | eth0 Configuration | Use Case |
|------|-------------------|----------|
| WAN | DHCP client + NAT masquerade | eth0 connected to router for internet |
| LAN | Bridged to br-lan | eth0 connected to device needing mesh access |

**Commands:**
```bash
eth0-mode.sh wan              # Switch to WAN mode
eth0-mode.sh lan              # Switch to LAN mode
eth0-mode.sh set-default wan  # Set boot default
eth0-mode.sh set-default lan  # Set boot default
eth0-mode.sh status           # Show current mode
```

**What happens on switch:**
- Updates `/etc/systemd/network/40-eth0-lan.network`
- Restarts systemd-networkd
- Flushes neighbor caches
- Restarts babeld
- WAN mode: Adds NAT masquerade rule
- LAN mode: Removes NAT rule, bridges eth0 to br-lan

---

## opendht-start.sh

Starts OpenDHT Docker container for distributed hash table (used by Jami VoIP).

**Behavior:**
1. Checks `OPENDHT_ENABLED` in mesh.conf
2. Stops/removes existing container if present
3. Builds bootstrap argument (excludes own IP from bootstrap list)
4. Starts container with:
   - Port 4222 (DHT)
   - Port 8000 (HTTP proxy)
   - Network ID from config

**Container:**
```
ghcr.io/savoirfairelinux/opendht/opendht-alpine
```

**Verify:**
```bash
curl http://127.0.0.1:8000/
```

---

## sd-wear-setup.sh

One-time setup to minimize SD card writes (extends card lifespan).

**Changes applied:**
- Disables swap
- Adds `noatime` to root filesystem mount
- Mounts `/tmp` as tmpfs (50MB RAM)
- Configures systemd journal to RAM-only (50MB)

**RAM usage:** ~100MB total

**Usage:**
```bash
sudo /opt/nucleus/bin/sd-wear-setup.sh
# Prompts for reboot
```

---

## openvlm-voice.py / voice

Real-time mesh PTT voice over wlan1 (UDP multicast, additive mixing). Runs as
`openvlm-voice.service` at boot. The mesh transport is **independent of the
OpenVLM hardware** — two interchangeable PTT front-ends feed the same mesh:

- **Hardware PTT:** tactical headset on the OpenVLM USB card (attaches/detaches
  with the device; the mesh + phone paths run even with no OpenVLM plugged in).
- **Soft PTT:** a phone on the node's Wi-Fi AP using the `/voice` web page
  (phone mic/speaker are the handset, streamed over a WebSocket). Served over
  HTTPS at `https://<serial>-nucleus.local/voice` (mic capture needs HTTPS).

**User commands:**
```bash
voice start|stop|restart   # control the service
voice status               # channel, PTT state, active talkers, hardware
voice channels             # list configured named channels
voice channel N            # switch voice channel live (1-254)
voice log                  # follow daemon log
```

**mesh.conf variables:** `VOICE_CHANNEL`, `VOICE_CHANNELS`, `VOICE_JITTER_MS`,
`VOICE_TX_GAIN`

**Ports:** UDP 5555 (mesh voice), UDP 5556 (control socket / CLI),
TCP 5557 (WebSocket server; nginx proxies `/voice-ws` here).

Full docs: `docs/VoIP/openvlm_voice_plan.md`


---

## Configuration Variables

All scripts source `/etc/nucleus/mesh.conf`:

| Variable | Used By | Example |
|----------|---------|---------|
| `MESH_NAME` | mesh-start, config_gen | `natak_mesh` |
| `MESH_CHANNEL` | mesh-start, config_gen | `11` |
| `MESH_PASSWORD` | config_gen | `52235223` |
| `MESH_IP` | mesh-start, config_gen | `10.20.1.12` |
| `MESH_IPV6_LL` | mesh-start, config_gen | `fe80::12` |
| `BR_LAN_IP` | config_gen | `10.20.12.1` |
| `BR_LAN_IPV6_LL` | config_gen | `fe80::22` |
| `AP_NAME` | config_gen | `0012-nucleus-ap` |
| `AP_CHANNEL` | config_gen | `36` |
| `AP_PASSWORD` | config_gen | `52235223` |
| `ETH0_STATIC_IP` | config_gen | `10.10.10.1` |
| `OPENDHT_ENABLED` | opendht-start | `true` |
| `OPENDHT_NETWORK_ID` | opendht-start | `12345` |
| `OPENDHT_BOOTSTRAP_IPS` | opendht-start | `10.20.1.11,10.20.1.12` |

---

## Systemd Integration

| Service | Script | Description |
|---------|--------|-------------|
| `mesh-start.service` | mesh-start.sh | Main mesh startup |
| `openvlm-voice.service` | openvlm-voice.py | Mesh PTT voice daemon |
| `mesh-web.service` | - | Flask web interface |
| `babeld.service` | - | Babel routing daemon |
| `hostapd.service` | - | Access point (wlan0) |

**Startup order:**
1. systemd-networkd (bridge setup)
2. mesh-start.service (mesh interface)
3. babeld.service (routing)
4. hostapd.service (AP)
5. mesh-web.service (web GUI)
