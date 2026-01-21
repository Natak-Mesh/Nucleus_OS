# Natak Mesh Web Interface

Flask-based web interface for mesh network monitoring and configuration.

**Access:** `http://<node-ip>:5000`

## Pages

| Route | Page | Description |
|-------|------|-------------|
| `/` | Dashboard | Mesh node monitoring with link quality and WiFi stats |
| `/config` | Configuration | Edit mesh.conf settings, apply and reboot |
| `/scan` | Channel Scan | WiFi channel congestion analysis |
| `/remote` | Remote Access | Tailscale status and profile management |
| `/ethernet` | Ethernet Mode | Switch eth0 between WAN/LAN modes |
| `/opendht` | OpenDHT | VoIP DHT container status and restart |

## Mesh Node Monitoring

### Data Sources

1. **Babeld Monitoring Interface** (port 33123)
   - Neighbor link-local IPv6 addresses
   - Link quality: `cost`, `reach`, `rxcost`, `txcost`
   - Route information (prefixes, metrics, next-hops)

2. **IPv6 Neighbor Cache** (`ip -6 neigh show dev wlan1`)
   - Maps link-local IPv6 to MAC address

3. **IPv4 Neighbor Cache** (`ip neigh show dev wlan1`)
   - Maps MAC address to IPv4 address

4. **WiFi Station Stats** (`iw wlan1 station dump`)
   - Signal strength (dBm)
   - TX/RX bitrates and MCS indices
   - Expected throughput

### IP Correlation Logic

Babeld provides only IPv6 link-local addresses for neighbors. To display IPv4:

```
Babeld neighbor IPv6 (fe80::...) 
    → IPv6 neighbor cache → MAC address
    → IPv4 neighbor cache → IPv4 address
```

The app probes neighbors before queries to ensure caches are populated.

### Route Filtering

Routes displayed in "Gateway to" are filtered to reduce clutter:
- **Removed:** Docker networks (172.16.0.0/12)
- **Removed:** Mesh backbone (10.20.1.0/24) - redundant
- **Kept:** Client LANs (10.20.x.0/24 where x ≠ 1)
- **Kept:** Internet gateway (0.0.0.0/0)

## Channel Scanning

Uses `airmon-ng` and `airodump-ng` to analyze 2.4GHz channel congestion.

**Process:**
1. Stops mesh services
2. Enables monitor mode on wlan1
3. Scans for specified duration (10-300s)
4. Calculates congestion scores per channel
5. Recommends non-overlapping channels (1, 6, 11)
6. Restores mesh services

**Requirements:** `aircrack-ng` package

## Configuration

### mesh.conf Settings

The config page reads/writes `/etc/nucleus/mesh.conf`. After saving, it runs `/opt/nucleus/bin/config_generation.sh` then reboots.

### App Configuration

In `app.py`:
```python
BABELD_PORT = 33123           # Babeld monitoring port
REFRESH_INTERVAL = 5          # Dashboard auto-refresh (seconds)
DISCONNECTED_DISPLAY_TIME = 60  # Keep disconnected nodes visible (seconds)
```

## API Endpoints

### Mesh Monitoring
- `GET /api/nodes` - Current mesh node data with WiFi stats

### Configuration
- `GET /api/config` - Read mesh.conf
- `POST /api/apply_and_reboot` - Save config, regenerate, reboot

### Channel Scan
- `POST /api/channel-scan/start` - Start scan (body: `{"duration": 60}`)
- `GET /api/channel-scan/status` - Scan progress
- `GET /api/channel-scan/results` - Scan results and recommendations

### Tailscale
- `GET /api/tailscale/status` - Connection status, IP, tailnet
- `POST /api/tailscale/up` - Connect
- `POST /api/tailscale/down` - Disconnect
- `GET /api/tailscale/profiles` - List available profiles
- `POST /api/tailscale/switch` - Switch profile (body: `{"profile_id": "..."}`)

### Ethernet Mode
- `GET /api/eth0-mode/status` - Current mode (wan/lan)
- `POST /api/eth0-mode/switch` - Switch mode (body: `{"mode": "wan|lan"}`)

### OpenDHT
- `GET /api/opendht/status` - Container status, peer count, config
- `POST /api/opendht/restart` - Restart DHT container

## File Structure

```
/opt/nucleus/web/
├── app.py                    # Flask application
├── README.md                 # This file
├── templates/
│   ├── index.html           # Dashboard
│   ├── config.html          # Configuration
│   ├── scan.html            # Channel scan
│   ├── remote.html          # Tailscale management
│   ├── ethernet.html        # Ethernet mode
│   └── opendht.html         # OpenDHT status
├── static/
│   ├── css/style.css        # Dark theme styles
│   └── images/
│       └── NatakMeshsecondary-overlay.png
└── scan_results/            # Channel scan output (created at runtime)
```

## Requirements

- Python 3 with Flask (`pip3 install flask`)
- Babeld with monitoring enabled (`local-port 33123` in `/etc/babeld.conf`)
- `aircrack-ng` package (for channel scanning)
- `tailscale` CLI (for remote access features)
- Docker (for OpenDHT container management)

## Running

### Development
```bash
cd /opt/nucleus/web
python3 app.py
```

### Production
Managed by systemd service `mesh-web.service`

## Troubleshooting

**No nodes showing:**
- Verify babeld: `sudo systemctl status babeld`
- Test monitoring: `echo "dump" | nc localhost 33123`
- Check mesh interface: `ip neigh show dev wlan1`

**IPv4 addresses not resolving:**
- Neighbor caches may be stale
- App automatically probes neighbors before each query
- Manual probe: `ping -c1 <neighbor-ip>`

**Channel scan fails:**
- Requires root/sudo for airmon-ng
- Check aircrack-ng installed: `which airodump-ng`
- Monitor mode conflicts: ensure no other process using wlan1

**Tailscale commands fail:**
- Check sudoers allows tailscale commands
- See `/etc/sudoers.d/tailscale-web`
