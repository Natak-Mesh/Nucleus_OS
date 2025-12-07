# UFW Firewall Settings for Nucleus Mesh + TAK Server

## Overview

This document describes the correct UFW (Uncomplicated Firewall) configuration for running TAK Server alongside the Nucleus mesh routing system (babeld/smcroute). 

**CRITICAL:** The default UFW `deny (routed)` policy will break multicast forwarding between interfaces, preventing ATAK devices from communicating across the mesh.

## The Problem

When UFW is configured with default policies, multicast traffic cannot be forwarded between interfaces (wlan1 ↔ br-lan), even if incoming/outgoing traffic is allowed. This is because:

- UFW default: `deny (incoming), allow (outgoing), deny (routed)`
- **`deny (routed)` blocks smcroute from forwarding multicast** between wlan1 and br-lan
- Result: ATAK EUDs lose contact, multicast CoT data and discovery packets are blocked

### Symptoms:
- Babel routing works (IPv6 link-local)
- Ping works across mesh
- Only see **outgoing** multicast in tcpdump, no incoming multicast from other mesh nodes
- ATAK devices on different mesh nodes cannot see each other

## Required Ports

### TAK Server Ports (TCP):
- **8089** - TAK Server API/Web UI
- **8443** - TAK Server HTTPS
- **8554** - TAK Server streaming
- **6969** - TAK Server CoT data
- **8444** - TAK Server federation
- **9000** - TAK Server management
- **9001** - TAK Server metrics (optional)
- **1935** - RTMP streaming (optional)

### Mesh Routing Requirements:
- **6696/udp** - Babel routing protocol
- **IGMP** - Multicast group management (handled by interface rules)
- **Multicast groups:**
  - 239.2.3.1 - ATAK CoT data
  - 224.10.10.1 - ATAK Discovery
- **Interface forwarding** - Must allow routed traffic between wlan1 and br-lan

## Complete UFW Configuration

### Step-by-Step Setup

```bash
# 1. Set default policies (CRITICAL: must allow routed!)
sudo ufw default deny incoming
sudo ufw default allow outgoing
sudo ufw default allow routed     # ← CRITICAL for multicast forwarding!

# 2. Allow SSH (always keep this!)
sudo ufw allow ssh

# 3. Allow TAK Server ports
sudo ufw allow 8089/tcp
sudo ufw allow 8443/tcp
sudo ufw allow 8554/tcp
sudo ufw allow 6969/tcp
sudo ufw allow 8444/tcp
sudo ufw allow 9000/tcp
sudo ufw allow in on br-lan to any port 4242 #for reticulum UDP interface
sudo ufw allow 9001/tcp    # Optional
sudo ufw allow 1935/tcp    # Optional

# 4. Allow Babel routing protocol
sudo ufw allow 6696/udp

# 5. Allow multicast on mesh interfaces
sudo ufw allow 239.2.3.1 on wlan1
sudo ufw allow 224.10.10.1 on wlan1
sudo ufw allow 239.2.3.1 on br-lan
sudo ufw allow 224.10.10.1 on br-lan

# 6. Allow all traffic on trusted mesh interfaces
sudo ufw allow in on wlan1
sudo ufw allow in on br-lan

# 7. Enable UFW
sudo ufw enable

# 8. Verify configuration
sudo ufw status verbose
```

### Expected Output

```
Status: active
Logging: on (low)
Default: deny (incoming), allow (outgoing), allow (routed)  ← Note: allow (routed)
New profiles: skip

To                         Action      From
--                         ------      ----
22/tcp                     ALLOW IN    Anywhere
8089/tcp                   ALLOW IN    Anywhere
8443/tcp                   ALLOW IN    Anywhere
8554/tcp                   ALLOW IN    Anywhere
6969/tcp                   ALLOW IN    Anywhere
8444/tcp                   ALLOW IN    Anywhere
9000/tcp                   ALLOW IN    Anywhere
9001/tcp                   ALLOW IN    Anywhere
1935/tcp                   ALLOW IN    Anywhere
6696/udp                   ALLOW IN    Anywhere
239.2.3.1 on wlan1         ALLOW IN    Anywhere
224.10.10.1 on wlan1       ALLOW IN    Anywhere
239.2.3.1 on br-lan        ALLOW IN    Anywhere
224.10.10.1 on br-lan      ALLOW IN    Anywhere
Anywhere on wlan1          ALLOW IN    Anywhere
Anywhere on br-lan         ALLOW IN    Anywhere
[... IPv6 entries ...]
```

## Security Considerations

### Why This Configuration is Safe

1. **External ports are locked down** - Only SSH and TAK Server ports are exposed
2. **wlan1 is a trusted mesh interface** - Encrypted 802.11s mesh with WPA3
3. **br-lan is internal LAN** - Local clients and AP (wlan0)
4. **Routed traffic is between trusted interfaces** - wlan1 ↔ br-lan only
5. **No promiscuous forwarding** - UFW still controls what enters the system

### Network Topology

```
[Internet] ←→ eth0 (WAN/LAN auto)
                ↓
         [Nucleus Node]
          ↓          ↓
      wlan1       br-lan
   (mesh)      (wlan0 + eth0)
      ↓            ↓
  [Mesh       [Local ATAK
  Neighbors]   Clients]
```

- **wlan1**: Encrypted mesh backhaul, Babel routing, multicast forwarding
- **br-lan**: Bridge for wlan0 (AP) and optionally eth0 (LAN mode)
- **eth0**: Auto-switches between WAN (uplink) and LAN (bridge to br-lan)

## Verification Steps

### 1. Check UFW Status
```bash
sudo ufw status verbose
# Verify: allow (routed) in default policies
```

### 2. Test Babel Routing
```bash
# Should see IPv6 Babel hello/ihu messages
sudo tcpdump -i wlan1 -n udp port 6696
```

### 3. Test Multicast Forwarding
```bash
# Should see BOTH incoming and outgoing multicast
sudo tcpdump -i wlan1 -n host 239.2.3.1
sudo tcpdump -i wlan1 -n host 224.10.10.1
```

### 4. Test All Multicast Traffic
```bash
# Should see Babel (IPv6) and ATAK multicast (IPv4)
sudo tcpdump -i wlan1 -n multicast
```

### 5. Verify smcroute
```bash
# Check service is running
sudo systemctl status smcroute

# Check multicast routes
sudo smcroutectl show

# Should show active (S,G) routes in Kernel MFC Table
```

### 6. Check Kernel Settings
```bash
# Both should return "1"
cat /proc/sys/net/ipv4/ip_forward
cat /proc/sys/net/ipv4/conf/all/mc_forwarding
```

## Troubleshooting

### Problem: ATAK devices can't see each other

**Check:**
1. UFW allows routed traffic: `sudo ufw status verbose` should show `allow (routed)`
2. Multicast forwarding: `sudo tcpdump -i wlan1 -n multicast` shows both directions
3. smcroute is running: `sudo systemctl status smcroute`
4. Routes exist: `sudo smcroutectl show` shows (S,G) entries in Kernel MFC Table

**Fix:**
```bash
sudo ufw default allow routed
sudo ufw reload
```

### Problem: Only see outgoing multicast, no incoming

**Cause:** `deny (routed)` is blocking forwarding between interfaces

**Fix:**
```bash
sudo ufw default allow routed
sudo ufw reload
```

### Problem: Babel not working

**Check:**
1. Port 6696/udp is allowed: `sudo ufw status | grep 6696`
2. Interface rule exists: `sudo ufw status | grep wlan1`

**Fix:**
```bash
sudo ufw allow 6696/udp
sudo ufw allow in on wlan1
sudo ufw reload
```

### Problem: Mesh routing works, but TAK Server inaccessible

**Check:**
1. TAK Server ports are open: `sudo ufw status | grep 8089`
2. TAK Server is running: `sudo systemctl status takserver`

**Fix:**
```bash
# Add any missing TAK Server ports
sudo ufw allow 8089/tcp
sudo ufw allow 8443/tcp
# ... etc
sudo ufw reload
```

## Quick Reference Commands

```bash
# View current firewall status
sudo ufw status verbose

# Reload firewall after changes
sudo ufw reload

# Disable firewall (for testing only!)
sudo ufw disable

# Re-enable firewall
sudo ufw enable

# Delete a rule
sudo ufw delete allow 1935/tcp

# Reset firewall (WARNING: removes all rules!)
sudo ufw reset
```

## Related Services

This configuration works with:
- **babeld** - Babel routing daemon (UDP 6696)
- **smcroute** - Static multicast routing daemon
- **hostapd** - Access Point on wlan0
- **wpa_supplicant** - Encrypted 802.11s mesh on wlan1
- **systemd-networkd** - Network interface management
- **TAK Server** - Team Awareness Kit server

## References

- [Babel routing documentation](docs/babel_smc.md)
- [UFW documentation](https://help.ubuntu.com/community/UFW)
- [smcroute documentation](https://github.com/troglobit/smcroute)

## Change Log

- **2025-12-04**: Initial documentation
  - Identified critical issue with `deny (routed)` blocking multicast forwarding
  - Documented complete UFW configuration for TAK Server + mesh routing
  - Added troubleshooting steps and verification procedures
