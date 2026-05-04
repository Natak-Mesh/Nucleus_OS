# Web UI Optimization — Mobile Dashboard

## Goal

Optimize the web interface for mobile phones. The front page should focus on **connectivity** — making the important stuff big and easy to see at a glance on one screen without scrolling. Everything else moves to a collapsible section.

## Design Principles

- **Whole-mesh visibility** — see all connections at once without scrolling
- **Text color for status** — no emoji dots or circles, just colored text (green/yellow/red)
- **Compact rows** — one line per neighbor/node, not individual cards
- **Consolidated nav** — all tool links collapse into a single expandable section

## Final Layout

```
┌─────────────────────────┐
│    [Logo]  10.20.1.11   │  ← Logo + IP on same line
│                         │
│  Mesh Ch6    AP 3 cli   │  ← Green/red text per status
│                         │
│  WIFI MESH              │
│  10.20.1.12  Good (256) │  ← Green text
│  10.20.1.13  Fair (580) │  ← Yellow text
│  10.20.1.14  Poor (1200)│  ← Red text
│                         │
│  MESHTASTIC             │
│  ALPHA          2m ago  │  ← Green text (recent)
│  BRAVO          5m ago  │  ← Green
│  CHARLIE       18m ago  │  ← Yellow text (stale)
│  Radio ✓  Bridge ON     │
│                         │
│  ⚙ Tools & Settings    │  ← Tap to expand
│                         │
│  Updated 7:01 PM        │
└─────────────────────────┘
```

## Data Sources

### WiFi Mesh Neighbors
- **Source:** Babel routing daemon (`babeld`) via socket query on port 33123
- **Metric:** Babel link cost (Good < 400, Fair 400–700, Poor > 700)
- **Already available** in `/api/dashboard` endpoint

### Meshtastic Nodes
- **Problem:** `cot_bridge.py` daemon owns the serial port exclusively — web app can't query radio directly
- **Solution:** Bridge periodically dumps `iface.nodes` to `/tmp/meshtastic_nodes.json`
- **Data:** Node short name, last heard timestamp, SNR
- **Freshness color:** Green < 5 min, Yellow 5–30 min, dim/grey > 30 min

### Node dump file format (`/tmp/meshtastic_nodes.json`)
```json
{
  "timestamp": 1712345678,
  "nodes": [
    {
      "id": "!abcd1234",
      "short_name": "ALPHA",
      "long_name": "Alpha Node",
      "last_heard": 1712345600,
      "snr": 8.5,
      "battery": 85,
      "hops_away": 0
    }
  ]
}
```

## Files Modified

| File | Change |
|------|--------|
| `opt/nucleus/web/templates/nav.html` | Compact layout, meshtastic section, collapsible nav |
| `opt/nucleus/web/static/css/style.css` | Mobile-first compact styles |
| `opt/nucleus/web/app.py` | Add meshtastic node data to `/api/dashboard` |
| `opt/nucleus/meshtastic/cot_bridge.py` | Add periodic node dump to JSON file |

## What Stays the Same

- All secondary pages (monitor, config, scan, remote, etc.) — unchanged
- All existing API endpoints — unchanged
- Auto-refresh (5-second interval) — unchanged
- Existing meshtastic page with bridge toggle and logs — still accessible from nav
