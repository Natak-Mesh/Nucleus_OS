# Nucleus OS - System Architecture

## Overview
Nucleus OS is a mesh networking operating system for Natak Mesh hardware nodes. It creates a self-healing, multi-hop wireless mesh network using IEEE 802.11s with SAE encryption, Babel routing protocol, and provides multiple network interfaces for client connectivity.

## System Architecture

### Core Components

#### 1. **Mesh Network Layer (wlan1)**
- **Purpose**: Forms the backbone wireless mesh between nodes
- **Technology**: IEEE 802.11s mesh mode with WPA3-SAE encryption
- **Protocol**: Babel routing daemon for dynamic route discovery
- **Configuration**: `mesh-start.sh`, `wpa_supplicant`, `babeld.conf`
- **IP Addressing**: 10.20.1.x/24 (IPv4), fe80::/64 (IPv6 link-local)

#### 2. **Access Point Layer (wlan0)**
- **Purpose**: Provides WiFi access point for client devices
- **Technology**: hostapd with WPA2-PSK
- **Bridge**: Connected to br-lan bridge
- **IP Addressing**: Served from 10.20.12.x/24 subnet via br-lan

#### 3. **Bridge Interface (br-lan)**
- **Purpose**: Aggregates wlan0 (AP) and optionally eth0 for unified client network
- **Services**: DHCP server, DNS forwarding
- **Routes**: Advertised into mesh via Babel
- **IP Addressing**: 10.20.12.1/24 (gateway for clients)

#### 4. **Ethernet Interface (eth0)**
- **Purpose**: Dual-mode WAN/LAN auto-switching
- **WAN Mode**: DHCP client when connected to router with DHCP
- **LAN Mode**: Static IP + DHCP server when direct-connected to device
- **Auto-switch**: networkd-dispatcher scripts detect DHCP availability
- **IP Addressing**: 
  - WAN: DHCP-assigned
  - LAN: 10.10.10.1/24 with DHCP pool

### Routing & Forwarding

#### Babel Routing Daemon
- **Function**: Distance-vector routing protocol optimized for wireless mesh
- **Interfaces**: Monitors wlan1 (wireless, higher cost) and br-lan (wired, lower cost)
- **Metrics**: Link quality, ETX (expected transmission count), hop count
- **Redistribution**: Announces local subnets (10.20.1.x, 10.20.12.x) to mesh
- **API**: Local monitoring interface on port 33123 for web dashboard

#### IP Forwarding & NAT
- **Kernel forwarding**: Enabled between all interfaces
- **Route propagation**: Babel installs routes in kernel table 254
- **Multicast routing**: smcroute daemon enables multicast forwarding for ATAK/TAKserver

### Management & Configuration

#### Configuration System
- **`mesh.conf`**: Central configuration file with all node settings
- **`config_generation.sh`**: Generates service configs from mesh.conf
- **Dynamic configs**: wpa_supplicant, hostapd, babeld, systemd network files
- **Web interface**: Live config editing with apply & reboot

#### Web Dashboard (Flask)
- **Port**: TCP/5000
- **Features**:
  - Real-time mesh node monitoring
  - Link quality metrics (signal, cost, throughput)
  - WiFi channel scanner with congestion analysis
  - Configuration editor
- **Data sources**: Babel API, IPv4/IPv6 neighbor cache, iw station stats
- **Correlation**: Maps IPv6 LL → MAC → IPv4 → Babel metrics

#### Systemd Services
- **brlan-setup.service**: Creates br-lan bridge at boot
- **mesh-start.service**: Configures wlan1 mesh interface, starts encryption, launches rnsd (Reticulum daemon)
- **mesh-web.service**: Runs Flask web dashboard
- **babeld.service**: Routing daemon (with custom override)
- **hostapd.service**: Access point on wlan0
- **smcroute.service**: Multicast routing for ATAK

### Network Topology

```
Internet
   ↓
[Router] ← DHCP → (eth0 - WAN mode)
                        ↓
                 [Nucleus Node]
                   ↓  ↓  ↓
    ┌──────────────┼──┴────────┼──────────────┐
    ↓              ↓           ↓              ↓
(wlan1-mesh)   (br-lan)    (wlan0-AP)    (eth0-LAN)
    ↓           10.20.12.1      ↓           10.10.10.1
    ↓              ↓             ↓              ↓
[Other Nodes]  [Bridge]    [WiFi Clients]  [Direct Device]
10.20.1.x         ↓
    ↑             ↓
    └─ Babel ─→ Routes
```

### Component Interactions

#### Startup Sequence
1. **brlan-setup.service** → Creates br-lan, adds wlan0 to bridge
2. **systemd-networkd** → Configures IP addresses on all interfaces
3. **mesh-start.service** → Sets wlan1 to mesh mode, applies encryption, starts rnsd
4. **babeld.service** → Discovers neighbors, builds routing table
5. **hostapd.service** → Enables wlan0 AP for client connections
6. **mesh-web.service** → Starts monitoring dashboard
7. **networkd-dispatcher** → Monitors eth0 for WAN/LAN state changes

#### Configuration Flow
1. User edits config via web UI or direct file edit
2. `config_generation.sh` reads `/etc/nucleus/mesh.conf`
3. Generates service-specific configs (wpa_supplicant, hostapd, babeld, systemd)
4. System reboot or service restart applies changes
5. Mesh reforms with new parameters

#### Mesh Communication Flow
1. Node broadcasts Babel HELLO packets on wlan1
2. Neighbors respond, link quality measured
3. Nodes exchange route tables
4. Best routes installed in kernel
5. Client traffic forwarded through optimal paths
6. Route updates propagated on topology changes

### Installation & Deployment

#### Setup Scripts
- **`install-packages.sh`**: Installs all required system packages
  - Core: hostapd, babeld, smcroute, python3-flask
  - Mesh apps: Reticulum (rnsd), Nomadnet, Meshtastic CLI
  - Optional: Tailscale, TAKserver, MediaMTX
- **`deploy.sh`**: Copies configs from git repo to system locations
  - Installs to /etc, /opt/nucleus, /etc/systemd
  - Sets permissions, enables services
  - Requires root/sudo

#### Utility Scripts
- **`SSH_fix.sh`**: Optimizes SSH settings for mesh networks
- **`eth0-mode.sh`**: Manual WAN/LAN mode switching tool
- **SSH_Diagnosis/**: Scripts to troubleshoot SSH connectivity issues

### Key Configuration Files

#### Generated (by config_generation.sh)
- `/etc/wpa_supplicant/wpa_supplicant-wlan1-encrypt.conf` - Mesh encryption
- `/etc/hostapd/hostapd.conf` - AP configuration
- `/etc/babeld.conf` - Routing daemon config
- `/etc/systemd/network/*.network` - Interface IP configs

#### Static (edited manually or via web UI)
- `/etc/nucleus/mesh.conf` - Master configuration
- `/etc/smcroute.conf` - Multicast routing rules
- `/etc/NetworkManager/conf.d/unmanaged-devices.conf` - Prevents NM interference

### Extensibility

#### Integrated Services
- **Reticulum Network Stack (rnsd)**: Encrypted overlay network for messaging
- **Nomadnet**: Off-grid communication platform
- **Meshtastic**: LoRa integration capability
- **TAKserver**: Tactical situational awareness (optional)
- **MediaMTX**: RTSP video streaming (optional)
- **Tailscale**: WireGuard VPN overlay (optional)

### Documentation
- **docs/**: Technical documentation, manpages, examples
- **DHCP_deployment_instructions.md**: eth0 auto-switch setup
- **UFW_settings.md**: Firewall configuration guide
- Various fix/troubleshooting guides

## System Summary

Nucleus OS orchestrates multiple network interfaces and routing protocols to create a resilient mesh network. The system automatically handles:
- Mesh formation and healing via Babel
- Client connectivity via AP and bridge
- WAN uplink detection and sharing
- Route optimization based on link quality
- Web-based monitoring and configuration

All components are loosely coupled through standard Linux networking, with systemd managing service lifecycle and configuration scripts ensuring consistency.
