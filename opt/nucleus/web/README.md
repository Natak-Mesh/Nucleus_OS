# Natak Mesh Web Interface

Flask-based web interface for mesh network monitoring and configuration.

**Access:** `http://<node-ip>:5000`

## Pages

| Route | Page | Description |
|-------|------|-------------|
| `/` | Dashboard | Mobile-optimized connectivity overview — WiFi mesh neighbors, meshtastic nodes |
| `/voice` | Voice PTT | Soft-PTT mesh voice handset (phone mic/speaker) — press-to-talk, named channel picker, live talkers. Requires HTTPS for mic access; connects to the voice daemon via `/voice-ws` |
| `/monitor` | Monitor | Detailed node cards with WiFi stats, routes, channel utilization |
| `/config` | Configuration | Edit mesh.conf settings, apply and reboot |
| `/scan` | Channel Scan | WiFi channel congestion analysis |
| `/remote` | Remote Access | Tailscale status and profile management |
| `/ethernet` | Ethernet Mode | Switch eth0 between WAN/LAN modes |
| `/opendht` | OpenDHT | VoIP DHT container status and restart |
| `/meshtastic` | Meshtastic | Radio detection, CoT bridge toggle, bridge logs |
| `/reticulum` | Reticulum | Transport status, interfaces, known destinations |
| `/opentakserver` | OpenTAKServer | Service status, connected clients, video streams |

## Dashboard (Front Page)

The main dashboard is designed for **mobile phones** — compact, one-screen connectivity view:

- **Mesh IP** — large, prominent
- **Mesh status** — channel number, green/red text
- **WiFi mesh neighbors** — one row per neighbor with Babel link cost (Good/Fair/Poor)
- **Meshtastic nodes** — short name + last heard time, color-coded by freshness
- **Tools & Settings** — collapsible section with all sub-page links + shutdown

### WiFi Mesh Data

WiFi neighbors come from the Babel routing daemon, queried every 5 seconds:

| Source | Data |
|--------|------|
| Babeld (port 33123) | Neighbor IPv6, link cost, reach |
| IPv6 neighbor cache | IPv6 → MAC mapping |
| IPv4 neighbor cache | MAC → IPv4 mapping |

Link quality classification (Babel cost — lower is better): Good < 400, Fair 400–700, Poor > 700.

### Meshtastic Node Data

The CoT bridge daemon (`cot_bridge.py`) periodically dumps the radio's node database to `/tmp/meshtastic_nodes.json` every 30 seconds. The dashboard reads this file.

**Node dump includes:** short name, last heard timestamp, SNR, hops away.

**Last heard tracking:** The bridge tracks its own last-seen time per node on every received ATAK packet, merged with the firmware's `lastHeard` (whichever is more recent). This provides near-real-time "last heard" that updates with every RX packet.

**Max age filter:** Nodes not heard within the last hour are excluded from the dump.

**Freshness colors:**
- Green: heard < 5 minutes ago
- Yellow: heard 5–30 minutes ago
- Grey/dim: heard > 30 minutes ago

## Monitor Page

Detailed node cards with full WiFi performance data per neighbor:
- Signal strength (dBm)
- TX/RX bitrates and MCS indices
- Expected throughput
- Link quality (retry rate)
- Route information ("Gateway to" destinations)
- Channel utilization

### Route Filtering

Routes displayed in "Gateway to" are filtered:
- **Removed:** Docker networks (172.16.0.0/12)
- **Removed:** Mesh backbone (10.20.1.0/24)
- **Kept:** Client LANs (10.20.x.0/24 where x ≠ 1)
- **Kept:** Internet gateway (0.0.0.0/0)

## Channel Scanning

Uses `iw-wifi-scan.sh` to analyze 2.4GHz channel congestion via `iw survey dump`.

**Process:**
1. Dwells on each of 11 channels for specified duration
2. Measures busy time percentage per channel
3. Recommends least congested channels
4. Restores mesh operation after scan

## API Endpoints

### Dashboard
- `GET /api/dashboard` — Single endpoint: mesh IP, wlan1 status, AP status, neighbors, meshtastic nodes

### Mesh Monitoring
- `GET /api/nodes` — Detailed mesh node data with WiFi stats and routes
- `GET /api/node-ip` — Node IP from mesh.conf

### Configuration
- `GET /api/config` — Read mesh.conf
- `POST /api/apply_and_reboot` — Save config, regenerate, reboot

### Channel Scan
- `POST /api/channel-scan/start` — Start scan (`{"duration": 60}`)
- `GET /api/channel-scan/status` — Scan progress
- `GET /api/channel-scan/results` — Results and recommendations

### Tailscale
- `GET /api/tailscale/status` — Connection status, IP, tailnet
- `POST /api/tailscale/up` — Connect
- `POST /api/tailscale/down` — Disconnect
- `GET /api/tailscale/profiles` — List profiles
- `POST /api/tailscale/switch` — Switch profile (`{"profile_id": "..."}`)

### Ethernet Mode
- `GET /api/eth0-mode/status` — Current mode (wan/lan)
- `POST /api/eth0-mode/switch` — Switch mode (`{"mode": "wan|lan"}`)

### OpenDHT
- `GET /api/opendht/status` — Container status, peer count, config
- `POST /api/opendht/restart` — Restart DHT container

### Meshtastic
- `GET /api/meshtastic/status` — Radio detected, bridge enabled, service status
- `POST /api/meshtastic/bridge/enable` — Enable CoT bridge
- `POST /api/meshtastic/bridge/disable` — Disable CoT bridge (reboots node)
- `GET /api/meshtastic/bridge/logs` — Last 50 log lines + health summary

### Reticulum
- `GET /api/reticulum/status` — Service status, interfaces, destinations
- `POST /api/reticulum/restart` — Restart rnsd service

### OpenTAKServer
- `GET /api/opentakserver/status` — Service status, connected clients, video streams
- `POST /api/opentakserver/restart` — Restart OTS service
- `/ots/*` — Reverse proxy to OTS web UI (bypasses IP whitelist)

### Voice PTT
- `GET /voice` — soft-PTT web handset page
- `/voice-ws` — WebSocket (proxied by nginx to the voice daemon on
  `127.0.0.1:5557`) carrying PTT/channel control + bidirectional 16 kHz audio

### System
- `POST /api/shutdown` — Graceful shutdown (disconnects meshtastic radio first)
- `POST /api/restart-mesh` — Restart Flask application


## File Structure

```
/opt/nucleus/web/
├── app.py                    # Flask application
├── README.md                 # This file
├── templates/
│   ├── nav.html             # Dashboard (mobile-optimized front page)
│   ├── voice.html           # Soft-PTT mesh voice handset (WebSocket to voice daemon)
│   ├── monitor.html         # Detailed node monitoring
│   ├── config.html          # Configuration editor
│   ├── scan.html            # Channel scan
│   ├── remote.html          # Tailscale management
│   ├── ethernet.html        # Ethernet mode
│   ├── opendht.html         # OpenDHT status
│   ├── meshtastic.html      # Meshtastic radio control
│   ├── reticulum.html       # Reticulum network status
│   └── opentakserver.html   # OpenTAKServer management
├── static/
│   ├── css/style.css        # Dark theme styles
│   └── images/
│       └── NatakMeshsecondary-overlay.png
```

## Requirements

- Python 3 with Flask (`pip3 install flask`)
- Babeld with monitoring enabled (`local-port 33123` in `/etc/babeld.conf`)
- `tailscale` CLI (for remote access features)
- Docker (for OpenDHT container management)
- Meshtastic Python library (for CoT bridge / radio control)

## Running

### Development
```bash
cd /opt/nucleus/web
python3 app.py
```

### Production
Managed by systemd service `mesh-web.service`

## Troubleshooting

**No WiFi mesh neighbors showing:**
- Verify babeld: `sudo systemctl status babeld`
- Test monitoring: `echo "dump" | nc ::1 33123`
- Check mesh interface: `ip neigh show dev wlan1`

**IPv4 addresses not resolving:**
- Neighbor caches may be stale
- App automatically probes neighbors before each query

**No meshtastic nodes showing:**
- Check cot-bridge running: `sudo systemctl status cot-bridge`
- Check node dump file: `cat /tmp/meshtastic_nodes.json`
- Nodes older than 1 hour are filtered out
- Bridge must be restarted after code changes to pick up new code

**Tailscale commands fail:**
- Check sudoers: `/etc/sudoers.d/tailscale-web`
