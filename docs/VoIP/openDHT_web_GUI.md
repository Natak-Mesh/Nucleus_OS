# OpenDHT Web GUI Implementation

## Overview
Web interface for monitoring and managing OpenDHT service on Nucleus mesh nodes. This interface helps verify that OpenDHT is running correctly for Jami voice/video support.

## Features
- Container status monitoring (running/stopped)
- DHT peer count (indicates network health)
- Configuration display (Network ID, Bootstrap IPs)
- Jami client connection information
- Container restart capability

## Implementation Components

### 1. Backend API Endpoints

#### GET `/api/opendht/status`
Returns OpenDHT service status and configuration.

**Implementation:**
- Check Docker container status: `docker ps -a --filter name=dhtnode`
- Query DHT peer count: `curl http://127.0.0.1:8000/`
- Read configuration from `/etc/nucleus/mesh.conf`
- Calculate br-lan gateway IP from mesh IP

**Response:**
```json
{
  "container_running": true,
  "peers_connected": 1,
  "network_id": "12345",
  "mesh_ip": "10.20.1.12",
  "br_lan_ip": "10.20.12.1",
  "bootstrap_ips": ["10.20.1.11", "10.20.1.12"],
  "proxy_url": "10.20.12.1:8000"
}
```

#### POST `/api/opendht/restart`
Restarts the OpenDHT container.

**Implementation:**
- Execute: `sudo /opt/nucleus/bin/opendht-start.sh`
- Return success/error status

**Response:**
```json
{
  "success": true,
  "message": "OpenDHT container restarted"
}
```

### 2. Frontend Page

#### Route: `/opendht`
Template: `templates/opendht.html`

**Layout:**
```
Header with Navigation
├─ Status Section
│  ├─ Container Status Card (RUNNING/STOPPED)
│  └─ Peer Count Card (with health indicator)
├─ Configuration Section
│  ├─ Network ID
│  ├─ Mesh IP
│  ├─ Bootstrap IPs
│  └─ Jami Proxy URL
├─ Actions
│  └─ Restart Container Button
└─ Jami Client Help
   └─ Connection instructions
```

**Status Indicators:**
- Container: Green (RUNNING) / Red (STOPPED)
- Peer Count: 
  - Green: ≥1 peers (healthy)
  - Red: 0 peers (no DHT network)

### 3. Navigation Integration

Add "OpenDHT" button to navigation bar in all templates:
- `templates/index.html`
- `templates/config.html`
- `templates/scan.html`
- `templates/remote.html`
- `templates/ethernet.html`

### 4. Styling

Use existing CSS classes from `static/css/style.css`:
- `.node-card` for status cards
- `.nav-btn` for buttons
- `.node-status-label` for status indicators
- Color scheme matches existing dark theme

## Key Data Sources

### Container Status
```bash
docker ps -a --filter name=dhtnode --format "{{.Status}}"
```
Parse for "Up" vs "Exited"

### DHT Peer Count
```bash
curl -s http://127.0.0.1:8000/
```
Parse JSON: `{"good": 1}` - the number indicates connected peers

### Configuration
Read from `/etc/nucleus/mesh.conf`:
- `OPENDHT_NETWORK_ID`
- `MESH_IP`
- `OPENDHT_BOOTSTRAP_IPS`

Calculate br-lan IP:
- Extract node number from MESH_IP (10.20.1.X)
- Format as 10.20.X.1

### Restart Command
```bash
sudo /opt/nucleus/bin/opendht-start.sh
```
Requires sudoers entry for www-data user

## Sudoers Configuration

Add to `/etc/sudoers.d/opendht-web`:
```
www-data ALL=(ALL) NOPASSWD: /opt/nucleus/bin/opendht-start.sh
```

## User Experience

### Manual Refresh
Status updates only when:
- Page loads
- User clicks refresh button
- User performs action (restart)

No auto-polling to reduce system load.

### Jami Client Information
Display the exact values users need:
- **DHT Proxy Address:** `10.20.X.1:8000` (no http:// prefix)
- **Bootstrap:** `10.20.X.1:4222`

Where X is the node number from mesh IP.

## Troubleshooting Display

Show common issues inline:
- If peers = 0: "No DHT peers connected - check bootstrap IPs"
- If container stopped: "Container not running - click Restart"

## Testing Checklist

- [ ] Status API returns correct container state
- [ ] Peer count matches `curl http://127.0.0.1:8000/`
- [ ] Restart button successfully restarts container
- [ ] Br-lan IP calculation is correct
- [ ] Navigation button appears on all pages
- [ ] Status indicators show correct colors
- [ ] Responsive design works on mobile

## Integration Notes

- No changes to existing routes or templates (except navigation)
- No modification to OpenDHT startup script
- Uses existing Flask patterns and styling
- Minimal dependencies (subprocess, json)
