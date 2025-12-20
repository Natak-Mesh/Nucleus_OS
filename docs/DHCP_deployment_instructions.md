# eth0 Auto-Switch Deployment Instructions

## Overview
This deploys the automatic eth0 WAN/LAN switching functionality using networkd-dispatcher.

## Files to Deploy

### 1. Network Configuration
- **Source:** `etc/systemd/network/40-eth0-lan.network`
- **Destination:** `/etc/systemd/network/40-eth0-lan.network`
- **Permissions:** 644 (root:root)

### 2. WAN Mode Dispatcher Script
- **Source:** `etc/networkd-dispatcher/routable.d/50-eth0-wan-mode`
- **Destination:** `/etc/networkd-dispatcher/routable.d/50-eth0-wan-mode`
- **Permissions:** 755 (root:root) - **MUST BE EXECUTABLE**

### 3. LAN Mode Dispatcher Script
- **Source:** `etc/networkd-dispatcher/degraded.d/50-eth0-lan-mode`
- **Destination:** `/etc/networkd-dispatcher/degraded.d/50-eth0-lan-mode`
- **Permissions:** 755 (root:root) - **MUST BE EXECUTABLE**

## Manual Deployment Commands

```bash
# Copy network configuration
sudo cp etc/systemd/network/40-eth0-lan.network /etc/systemd/network/40-eth0-lan.network
sudo chmod 644 /etc/systemd/network/40-eth0-lan.network

# Copy WAN mode script
sudo mkdir -p /etc/networkd-dispatcher/routable.d
sudo cp etc/networkd-dispatcher/routable.d/50-eth0-wan-mode /etc/networkd-dispatcher/routable.d/50-eth0-wan-mode
sudo chmod 755 /etc/networkd-dispatcher/routable.d/50-eth0-wan-mode

# Copy LAN mode script
sudo mkdir -p /etc/networkd-dispatcher/degraded.d
sudo cp etc/networkd-dispatcher/degraded.d/50-eth0-lan-mode /etc/networkd-dispatcher/degraded.d/50-eth0-lan-mode
sudo chmod 755 /etc/networkd-dispatcher/degraded.d/50-eth0-lan-mode

# Restart services to apply changes
sudo systemctl restart systemd-networkd
sudo systemctl restart networkd-dispatcher
```

## WARNING
**Restarting systemd-networkd will briefly disconnect eth0!**
- Your SSH connection will drop temporarily
- eth0 should reconnect and get DHCP again
- Consider running from console or via tmux/screen

## Verification

### Check Current Mode
```bash
# View eth0 status
ip addr show eth0
networkctl status eth0

# Check logs
journalctl -t eth0-wan-mode -n 20
journalctl -t eth0-lan-mode -n 20
```

### Test WAN Mode (eth0 plugged into router)
```bash
# Should see:
# - eth0 has DHCP address (e.g., 192.168.1.x)
# - No DHCP server running on eth0
# - Log message about WAN mode
```

### Test LAN Mode (eth0 plugged into laptop/device)
```bash
# Should see:
# - eth0 has 169.254.x.x (IPv4LL) and 10.10.10.1/24
# - DHCP server active on eth0
# - Connected device gets 10.10.10.10-110 IP
# - Log message about LAN mode
```

## Rollback
If something goes wrong, restore original config:
```bash
# Restore simple DHCP-only config
cat > /etc/systemd/network/40-eth0-lan.network <<EOF
[Match]
Name=eth0

[Network]
DHCP=yes
EOF

# Remove dispatcher scripts
sudo rm -f /etc/networkd-dispatcher/routable.d/50-eth0-wan-mode
sudo rm -f /etc/networkd-dispatcher/degraded.d/50-eth0-lan-mode

# Restart
sudo systemctl restart systemd-networkd
```
