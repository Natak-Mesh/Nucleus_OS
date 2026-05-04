# Web UI Optimization — Mobile Dashboard

## Goal

Optimize the web interface for mobile phones. The front page should focus on **connectivity** — making the important stuff big and easy to see at a glance. Everything else moves to a secondary page/section.

## Current State

The existing `nav.html` dashboard shows:
- Natak logo + mesh IP (large)
- Mesh (wlan1) and AP (wlan0) status on one line
- Neighbor table (IP, link quality, connection duration)
- 9 navigation pills (Monitor, Config, Wi-Fi Scan, Remote, Ethernet, OpenDHT, Meshtastic, Reticulum, OpenTAKServer)
- Shutdown button

**Problems for mobile:**
- Neighbor table is compact, hard to read on small screens
- Connection duration isn't that useful — link quality matters more
- No meshtastic radio info on the front page
- All 9 nav links + shutdown are always visible, cluttering the view
- No real meshtastic node visibility (the "health" indicator just parses logs, doesn't reflect actual radio connectivity)

## Planned Changes

### 1. Dashboard Layout (nav.html)

**Keep prominent:**
- Natak logo + mesh IP (already big, keep it)
- Mesh status (wlan1) and AP status (wlan0) — make these **two side-by-side status cards** instead of a single text line. Bigger, with colored backgrounds.

**Mesh Neighbors → Large cards:**
- Replace the compact table with **big touch-friendly cards**, one per neighbor
- Show: IP address + link quality (Good/Fair/Poor with color + cost number)
- **Drop connection duration** — not useful enough for the front page
- Empty state: big visible "No mesh neighbors" message

**Add Meshtastic Nodes section:**
- Show nodes heard by the meshtastic radio with **short name** and **last heard time**
- Data source: `cot_bridge.py` periodically dumps `iface.nodes` to `/tmp/meshtastic_nodes.json`
- Color coding: green if heard recently (< 5 min), yellow if stale (5–30 min), red/grey if old
- Also show radio detected (yes/no) and bridge mode (on/off)

**Navigation → Collapsible:**
- All 9 nav pills collapse into a **"Tools & Settings"** expandable section at the bottom
- Shutdown button moves **inside** the collapsed section (dangerous action shouldn't be prominent)

### 2. Meshtastic Node Data Pipeline

**Problem:** The cot_bridge daemon owns the serial port exclusively. The web app cannot open a second connection to query the radio's node database.

**Solution:** Add a periodic task to `cot_bridge.py` that writes `iface.nodes` to a JSON file every 30 seconds.

**File:** `/tmp/meshtastic_nodes.json`

**Format:**
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

**Changes to `cot_bridge.py`:**
- Add a `_dump_nodes()` function that serializes `iface.nodes` to JSON
- Call it every 30 seconds from the main keep-alive loop
- Write atomically (write to `.tmp` then rename) to avoid partial reads

**Changes to `app.py`:**
- `/api/dashboard` endpoint reads `/tmp/meshtastic_nodes.json` and includes the node list
- Also includes radio_detected and bridge_enabled status from existing meshtastic_api functions

### 3. CSS / Mobile Touch Targets (style.css)

- Minimum **44px** tap targets for all interactive elements
- Larger fonts for key data (neighbor IP, link quality)
- More padding on cards
- Ensure no horizontal scrolling on 320px+ screens

### 4. Files to Modify

| File | Change |
|------|--------|
| `opt/nucleus/web/templates/nav.html` | Full redesign — cards, meshtastic section, collapsible nav |
| `opt/nucleus/web/static/css/style.css` | Mobile touch targets, card styles |
| `opt/nucleus/web/app.py` | Add meshtastic data to `/api/dashboard` |
| `opt/nucleus/meshtastic/cot_bridge.py` | Add periodic node dump to JSON file |

### 5. What Stays the Same

- All secondary pages (monitor, config, scan, remote, ethernet, opendht, meshtastic, reticulum, opentakserver) — unchanged
- All existing API endpoints — unchanged
- Auto-refresh (5-second interval) — unchanged
- The existing meshtastic page with bridge toggle, logs, etc. — still accessible from nav

## Mobile Wireframe

```
┌─────────────────────────┐
│      [Natak Logo]       │
│                         │
│      10.20.1.11         │  ← Big mesh IP
│                         │
│  ┌──────────┬──────────┐│
│  │ 🟢 Mesh  │ 🟢 AP    ││  ← Status cards
│  │  Ch 6    │ 3 clients││
│  └──────────┴──────────┘│
│                         │
│  MESH NEIGHBORS         │
│  ┌─────────────────────┐│
│  │ 10.20.1.12          ││  ← Big card
│  │ 🟢 Good (256)       ││
│  └─────────────────────┘│
│  ┌─────────────────────┐│
│  │ 10.20.1.13          ││
│  │ 🟡 Fair (580)       ││
│  └─────────────────────┘│
│                         │
│  MESHTASTIC NODES       │
│  ┌─────────────────────┐│
│  │ 🟢 ALPHA    2m ago  ││  ← From radio node DB
│  │ 🟢 BRAVO    5m ago  ││
│  │ 🟡 CHARLIE  18m ago ││
│  └─────────────────────┘│
│  Radio: ✓  Bridge: ON   │
│                         │
│  ▼ Tools & Settings     │  ← Tap to expand
│  ┌─────────────────────┐│
│  │ Monitor | Config    ││
│  │ Wi-Fi Scan | Remote ││
│  │ Ethernet | OpenDHT  ││
│  │ Meshtastic | Retic. ││
│  │ OpenTAKServer       ││
│  │                     ││
│  │ [Shutdown Node]     ││
│  └─────────────────────┘│
│                         │
│  Updated 7:01:23 PM     │
└─────────────────────────┘
```
