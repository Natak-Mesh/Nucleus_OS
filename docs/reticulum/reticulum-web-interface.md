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

### rnstatus JSON Structure (expected)

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

### rnpath JSON Structure (expected)

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

**Note:** Verify actual JSON structure by running utilities on target system.

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

## Dependencies

- `rns` Python package (provides `rnstatus`, `rnpath` utilities)
- `rnsd` systemd service running

## Security Considerations

- Restart functionality requires appropriate sudoers configuration
- No sensitive data exposed (destination hashes are public by design)

## Future Considerations

- Recent announce activity log (would require more complex monitoring)
- Interface configuration editing (out of scope for monitoring page)
- Path request functionality
