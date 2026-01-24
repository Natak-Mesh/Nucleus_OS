# Reticulum Web Interface Planning

## Overview

Web UI monitoring page for the Nucleus onboard Reticulum transport instance. Provides visibility into interface status, transport statistics, and known destinations.

## Data Sources

### CLI Utilities

| Utility | Flags | Output | Purpose |
|---------|-------|--------|---------|
| `rnstatus` | `-j` | JSON | Interface status, traffic stats, announce counts |
| `rnstatus` | `-A -j` | JSON | Announce statistics per interface |
| `rnpath` | `-t -j` | JSON | Known destination paths, hop counts |
| `systemctl` | `status rnsd` | text | Service status |

### rnstatus JSON Structure (DEPRECATED - see actual output above)

```json
{
  "interfaces": [
    {
      "name": "AutoInterface/wlan1",
      "status": "up",
      "mode": "full",
      "bitrate": 10000000,
      "tx_bytes": 12345,
      "rx_bytes": 67890,
      "announces": 42
    }
  ],
  "transport_enabled": true,
  "transport_identity": "5245a8efe1788c6a1cd36144a270e13b"
}
```

### rnpath JSON Structure (DEPRECATED - see actual output above)

```json
{
  "paths": [
    {
      "destination": "c89b4da064bf66d280f0e4d8abfd9806",
      "hops": 3,
      "interface": "AutoInterface/wlan1"
    }
  ]
}
```

**Note:** JSON structure verified on target system. See actual output examples below.

### Actual rnstatus -j Output Structure

```json
{
  "interfaces": [
    {
      "name": "AutoInterface[Default Interface]",
      "short_name": "Default Interface",
      "hash": "68c7df65c73947617ad1ff5c2b112fb2...",
      "type": "AutoInterface",
      "status": true,
      "mode": 1,
      "bitrate": 10000000,
      "rxb": 1481,
      "txb": 2174,
      "rxs": 0.0,
      "txs": 0.0,
      "peers": 2,
      "incoming_announce_frequency": 0.008208666967192482,
      "outgoing_announce_frequency": 0.012785778435769854,
      "held_announces": 0,
      "announce_queue": 0,
      "ifac_signature": null,
      "ifac_size": null,
      "ifac_netname": null
    }
  ],
  "transport_id": "62bb1479c0835bf1525c685c02c9a58a",
  "network_id": null,
  "transport_uptime": 715.5244679450989,
  "probe_responder": null,
  "rxb": 3541,
  "txb": 3655,
  "rxs": 0.0,
  "txs": 0.0
}
```

**Key fields:**
- Top-level: `transport_id`, `network_id`, `transport_uptime`, `probe_responder`, `rxb`, `txb`
- Interface fields: `name`, `short_name`, `type`, `status`, `mode`, `bitrate`, `rxb`, `txb`, `peers`/`clients`, `announce_queue`, `held_announces`, announce frequencies, IFAC details

### Actual rnpath -t -j Output Structure

```json
[
  {
    "hash": "2dc12cc56b238ae160c6db1d3a32b4d4",
    "timestamp": 1769256737.1755493,
    "via": "83671bbccc115aa6230e96140e9b4a9f",
    "hops": 2,
    "expires": 1769861521.369153,
    "interface": "AutoInterfacePeer[wlan1/fe80::33]"
  }
]
```

**Key fields:** `hash`, `hops`, `via`, `interface`, `timestamp`, `expires`

## Page Components

### 1. Service Status Card

- **rnsd status**: Running/Stopped indicator
- **Transport enabled**: Yes/No
- **Transport Identity**: Hash (if transport enabled)
- **Restart button**: POST to `/api/reticulum/restart`

### 2. Interfaces Table

| Column | Source |
|--------|--------|
| Interface Name | `rnstatus` |
| Status | Up/Down indicator |
| Mode | full/gateway/access_point |
| Bitrate | Formatted (kbps/Mbps) |
| TX | Formatted bytes |
| RX | Formatted bytes |
| Announces | Count |

### 3. Transport Overview Card

- **Known Destinations**: Count from `rnpath -t`
- **Total Interfaces**: Count from `rnstatus`

### 4. Known Destinations (collapsible)

- Destination hash (truncated display, full on hover)
- Hop count
- Via interface
- Limit display to top N entries, "Show all" expander

## API Endpoints

### GET /reticulum

Renders the monitoring page template.

### GET /api/reticulum/status

Returns combined status data:

```json
{
  "service_running": true,
  "transport_enabled": true,
  "transport_identity": "5245a8efe1788c6a1cd36144a270e13b",
  "interfaces": [...],
  "destinations_count": 15,
  "destinations": [...]
}
```

**Implementation**: Run `rnstatus -j` and `rnpath -t -j`, merge results.

### POST /api/reticulum/restart

Restarts the rnsd service via `systemctl restart rnsd`.

**Response:**
```json
{
  "success": true
}
```

## File Changes

| File | Change |
|------|--------|
| `opt/nucleus/web/app.py` | Add routes: `/reticulum`, `/api/reticulum/status`, `/api/reticulum/restart` |
| `opt/nucleus/web/templates/reticulum.html` | New template |
| `opt/nucleus/web/templates/nav.html` | Add navigation link |
| `etc/sudoers.d/` | May need entry for reticulum commands if running as non-root |

## Implementation Approach

### Data Refresh Strategy

**Polling-based:** The web interface will use JavaScript polling (AJAX requests every few seconds) to fetch status updates from the backend API. This matches the existing pattern used in the mesh monitoring page.

- Not event-driven (RNS utilities are designed for polling, not streaming)
- Refresh interval: 5-10 seconds recommended (configurable)
- Status endpoint returns combined data from `rnstatus -j` and `rnpath -t -j`

### Sudoers Configuration Pattern

Follow existing pattern in `etc/sudoers.d/opendht-web`:

```
# Allow www-data to restart rnsd service
www-data ALL=(ALL) NOPASSWD: /usr/bin/systemctl restart rnsd
www-data ALL=(ALL) NOPASSWD: /usr/bin/systemctl status rnsd
```

### Service Status Detection

Use `systemctl status rnsd` to determine if service is running:
- Exit code 0 + "active (running)" = Running
- Otherwise = Stopped/Failed

Restart button calls `sudo systemctl restart rnsd` via subprocess.

## Dependencies

- `rns` Python package (provides `rnstatus`, `rnpath` utilities)
- `rnsd` systemd service running
- `www-data` user needs sudo permissions for systemctl commands (see sudoers config above)

## Security Considerations

- Restart functionality requires appropriate sudoers configuration
- No sensitive data exposed (destination hashes are public by design)

## Future Considerations

- Recent announce activity log (would require more complex monitoring)
- Interface configuration editing (out of scope for monitoring page)
- Path request functionality
