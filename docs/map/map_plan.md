# Pi MANET Offline Map Tile Server — Design Document

> **Purpose:** A lightweight, offline-capable map tile server that runs on Raspberry Pi-based MANET nodes, serving map data to connected phones via a local WiFi access point. Designed for disaster response and field operations where internet may be unavailable.

---

## Table of Contents

1. [Problem Statement](#problem-statement)
2. [System Overview](#system-overview)
3. [Hardware & Software Context](#hardware--software-context)
4. [Architecture](#architecture)
5. [Tile Format & Data Source](#tile-format--data-source)
6. [Storage Budget Analysis](#storage-budget-analysis)
7. [Area Selection Strategies](#area-selection-strategies)
8. [GPS Passthrough — Phone to Pi](#gps-passthrough--phone-to-pi)
9. [Tile Download Methods](#tile-download-methods)
10. [Tile Server Component](#tile-server-component)
11. [Web Map Viewer Component](#web-map-viewer-component)
12. [Map Loader CLI Tool](#map-loader-cli-tool)
13. [Deployment Workflows](#deployment-workflows)
14. [Meshtastic Integration](#meshtastic-integration)
15. [Mesh Tile Sharing (Node-to-Node)](#mesh-tile-sharing-node-to-node)
16. [Required Packages & Dependencies](#required-packages--dependencies)
17. [File Structure](#file-structure)
18. [Systemd Service Configuration](#systemd-service-configuration)
19. [Security Considerations](#security-considerations)
20. [Performance & Resource Constraints](#performance--resource-constraints)
21. [Future Enhancements](#future-enhancements)
22. [Reference: How Columba Does It](#reference-how-columba-does-it)

---

## Problem Statement

Raspberry Pi MANET nodes serve as local infrastructure for connected phones in the field. Phones connect via a wlan0 access point and need access to map data for situational awareness. The challenges:

- **No internet in the field** — maps must be stored locally on the Pi
- **Limited storage** — 32GB SD card shared with OS and other services
- **Unpredictable deployment areas** — disaster response means the AO (Area of Operations) is determined at go-time
- **No GPS on the Pi** — the phone has GPS, the Pi does not
- **Multiple transport layers** — Reticulum, Meshtastic (LoRa), and 802.11s mesh are all running
- **Zero phone-side installs** — solution should work with just a web browser

---

## System Overview

The system consists of three main components:

1. **Map Loader** (`map-loader`) — A CLI tool for downloading and managing map tile data
2. **Tile Server** (`tile-server`) — A lightweight HTTP server that serves tiles to connected phones
3. **Web Viewer** (`index.html`) — A browser-based map interface that phones access over the AP

The phone connects to the Pi's wlan0 access point, opens a web page served by the tile server, and gets a fully interactive offline map. The phone's GPS is used for positioning via the browser's Geolocation API — no GPS hardware needed on the Pi.

---

## Hardware & Software Context

### Pi Node Configuration
- **Hardware:** Raspberry Pi (3B+/4/5 or Zero 2W)
- **Storage:** 32GB SD card (~15-20GB usable after OS + services)
- **Network Interfaces:**
  - `wlan0` — WiFi access point for phone connections
  - 802.11s mesh interface (for node-to-node communication)
  - Meshtastic LoRa radio (via serial/USB)
  - Reticulum stack (running over multiple transports)
- **OS:** Raspberry Pi OS Lite or similar minimal Linux

### Phone Configuration
- Connects to Pi's wlan0 AP
- Uses web browser only — no special app required
- Has GPS hardware (used via browser Geolocation API)

---

## Architecture

```
┌──────────────────────────────────────────────────────────────┐
│                      Raspberry Pi Node                       │
│                                                              │
│  ┌──────────────┐   ┌───────────────┐   ┌────────────────┐  │
│  │  map-loader   │   │  tile-server   │   │   MBTiles      │  │
│  │  (CLI tool)   │──▶│  (HTTP:8080)   │◀──│   Storage      │  │
│  │               │   │               │   │                │  │
│  │ Downloads     │   │ Serves:       │   │ /opt/maps/     │  │
│  │ tiles from    │   │  /tile/{z}/   │   │  ├ world.mb    │  │
│  │ OpenFreeMap   │   │    {x}/{y}    │   │  ├ country.mb  │  │
│  │ into MBTiles  │   │  /style.json  │   │  └ ao.mbtiles  │  │
│  │               │   │  /api/*       │   │                │  │
│  └──────────────┘   │  / (web UI)   │   └────────────────┘  │
│                      └───────┬───────┘                       │
│                              │                               │
│           wlan0 AP ──────────┘  (192.168.x.1:8080)           │
│                                                              │
│  ┌──────────────┐   ┌───────────────┐                        │
│  │  Meshtastic   │   │  Reticulum    │  (other services)     │
│  │  (LoRa GPS)   │   │  Stack        │                       │
│  └──────────────┘   └───────────────┘                        │
└──────────────────────────────────────────────────────────────┘
          │
     ┌────┴─────┐
     │   Phone   │
     │  Browser  │  →  http://192.168.x.1:8080/
     │  (GPS ✓)  │      MapLibre GL JS renders vector tiles
     └──────────┘
```

### Data Flow

1. **Pre-deployment:** `map-loader` downloads tiles from OpenFreeMap and writes them to MBTiles files in `/opt/maps/`
2. **In the field:** `tile-server` reads MBTiles files and serves tiles over HTTP on port 8080
3. **Phone access:** Phone connects to AP, opens web page, browser gets GPS position, map renders with tiles from Pi
4. **Location sharing:** Phone's GPS coordinates can be sent to Pi via API, enabling position display for all connected devices

---

## Tile Format & Data Source

### Vector Tiles (Primary — Recommended)

- **Format:** Protobuf (PBF) / Mapbox Vector Tiles (MVT)
- **Source:** [OpenFreeMap](https://openfreemap.org/) — free, open-source, no API key required
- **Schema:** [OpenMapTiles](https://openmaptiles.org/) — open standard based on OpenStreetMap data
- **Style:** "Liberty" style — clean, readable cartography
- **Tile URL pattern:** `https://tiles.openfreemap.org/planet/{version}/{z}/{x}/{y}.pbf`
- **Version discovery:** Fetch TileJSON from `https://tiles.openfreemap.org/planet` to get current version

**Why vector tiles:**
- **5-10x smaller** than raster PNG tiles for the same area and zoom
- **Render at any zoom** — smooth scaling, no pixelation
- **Styleable** — can change colors, show/hide features, dark mode, etc.
- **GPU-rendered** on the phone via MapLibre GL JS

### Raster Tiles (Alternative)

- **Format:** PNG or JPEG
- **Sources:** OpenStreetMap tile servers, Thunderforest, Stamen, etc.
- **Use case:** If vector rendering is too heavy for very old phones
- **Downside:** 5-10x larger storage, fixed style, no dynamic styling

### MBTiles Container Format

Both vector and raster tiles are stored in **MBTiles** format:
- Standard **SQLite database** file (`.mbtiles` extension)
- Tables: `tiles` (zoom_level, tile_column, tile_row, tile_data) and `metadata`
- Uses **TMS tiling scheme** (origin at bottom-left; conversion from XYZ needed)
- Well-supported across the mapping ecosystem
- Single file per region — easy to copy, backup, transfer via USB

### OpenMapTiles Data Layers

The vector tiles from OpenFreeMap contain these data layers:
- `transportation` — roads, highways, railways, paths
- `water` — oceans, lakes, rivers
- `waterway` — streams, canals
- `landcover` — forests, grass, farmland
- `building` — building footprints (zoom 13+)
- `place` — city names, town names, village names
- `boundary` — administrative boundaries
- `poi` — points of interest
- `landuse` — land use classifications
- `transportation_name` — road names/labels

---

## Storage Budget Analysis

### Available Storage

| Item | Size |
|------|------|
| 32GB SD card (actual) | ~29.8 GB |
| Raspberry Pi OS Lite | ~2-3 GB |
| Reticulum + Meshtastic + mesh tools | ~500 MB |
| System overhead / swap | ~1-2 GB |
| **Available for maps** | **~15-20 GB** |
| Recommended map budget (conservative) | **~8-10 GB** |

### Vector Tile Size Estimates

These are approximate sizes for vector tiles from OpenFreeMap:

| Area | Zoom Levels | Approximate Size | Notes |
|------|-------------|-----------------|-------|
| Entire world | 0-6 | ~50 MB | Countries, major cities, coastlines |
| Entire world | 0-8 | ~200 MB | Major highways, large towns |
| Continental US | 7-10 | ~500 MB | County roads, small towns |
| Single US state (avg) | 0-14 | ~1-5 GB | Varies by population density |
| 25 km radius area | 11-14 | ~100-300 MB | Street-level detail |
| 50 km radius area | 11-14 | ~400 MB - 1 GB | Street-level detail |
| 100 km radius area | 11-14 | ~1.5-3 GB | Street-level detail |
| 200 km radius area | 11-14 | ~4-8 GB | Street-level detail |

### Recommended Layered Storage Strategy

```
┌───────────────────────────────────────────────────────────┐
│ Layer 1: World Overview         (zoom 0-6)      ~50 MB   │
│ ─ Always pre-loaded on every node                        │
│ ─ Provides: continents, countries, major cities          │
├───────────────────────────────────────────────────────────┤
│ Layer 2: Country/Region Detail  (zoom 7-10)     ~500 MB  │
│ ─ Pre-loaded for your operating country                  │
│ ─ Provides: highways, towns, county-level detail         │
├───────────────────────────────────────────────────────────┤
│ Layer 3: AO Detail              (zoom 11-14)    ~1-4 GB  │
│ ─ Downloaded at go-time for the deployment area          │
│ ─ Provides: streets, buildings, POIs, full detail        │
├───────────────────────────────────────────────────────────┤
│ TOTAL                                           ~2-5 GB  │
│ REMAINING FREE SPACE                           ~10-15 GB │
└───────────────────────────────────────────────────────────┘
```

### Zoom Level Detail Reference

| Zoom | What You See | Tile Count (50km radius) |
|------|-------------|-------------------------|
| 0 | Whole world | 1 |
| 1-4 | Continents, countries | ~20 |
| 5-6 | Large regions, states | ~100 |
| 7-8 | Counties, major highways | ~500 |
| 9-10 | Towns, secondary roads | ~2,000 |
| 11-12 | Neighborhoods, local roads | ~8,000 |
| 13-14 | Streets, buildings, POIs | ~32,000 |

---

## Area Selection Strategies

This is the critical problem: how to decide what map data to store on each Pi node. Here are all the viable approaches, from simplest to most sophisticated:

### Strategy 1: Manual Coordinate Entry (Simplest)

**How it works:** Operator provides coordinates and radius via CLI or web UI.

**When to use:** You know where you're going. Someone gives you a lat/lon or grid reference.

**CLI usage:**
```
map-loader --lat 29.7604 --lon -95.3698 --radius 50 --zoom 11-14
```

**Pros:** Dead simple, deterministic, fast
**Cons:** Requires knowing coordinates in advance

---

### Strategy 2: Place Name Geocoding

**How it works:** Operator types a place name. The tool geocodes it to coordinates using the Nominatim API (OpenStreetMap's geocoding service), then downloads tiles around that location.

**CLI usage:**
```
map-loader --place "Houston, TX" --radius 75 --zoom 11-14
```

**Requires:** Internet at the time of geocoding (one-time lookup)

**Geocoding source:** Nominatim (`https://nominatim.openstreetmap.org/search`) — free, no API key, rate-limited to 1 req/sec

**Pros:** Intuitive, no need to look up coordinates
**Cons:** Needs internet for the name lookup (tiles also need internet anyway)

---

### Strategy 3: Phone GPS Passthrough (via Web UI)

**How it works:** Phone connects to Pi's AP, opens the map web page. Browser's Geolocation API provides GPS coordinates. User taps "Download Area" button, selects a radius. Pi downloads tiles centered on the phone's GPS position.

**Flow:**
1. Phone opens `http://192.168.x.1:8080/`
2. Browser prompts: "Allow location access?" → User taps Allow
3. JavaScript `navigator.geolocation.getCurrentPosition()` returns coords
4. JS sends GPS to Pi: `POST /api/location` with `{lat, lon, accuracy}`
5. Map centers on position (using base layer tiles)
6. User taps "Download Area" → selects radius → Pi starts downloading

**Requires:** Phone GPS + internet on the Pi at the time of download

**Pros:** Zero manual coordinate entry, uses the phone's accurate GPS
**Cons:** Still needs internet on Pi for the actual tile download

---

### Strategy 4: Pre-Built Region Packs (USB Transfer)

**How it works:** On a preparation machine (laptop/desktop with good internet), pre-download MBTiles files for states, FEMA regions, or other defined areas. Store them on USB drives. At go-time, plug in the USB and copy the relevant file.

**Preparation (on laptop):**
```
map-loader --region texas --zoom 0-14 --output texas_full.mbtiles
map-loader --region florida --zoom 0-14 --output florida_full.mbtiles
```

**Go-time (on Pi):**
```
map-loader --import /mnt/usb/texas_full.mbtiles
```

**Pre-defined regions could include:**
- US states (50 files)
- FEMA regions (10 files)
- Major metro areas (top 50 cities)
- Countries
- Custom-defined regions

**Pros:** Zero internet needed at go-time, instant deployment, predictable sizes
**Cons:** Requires pre-preparation, may include more data than needed, USB logistics

---

### Strategy 5: Map Click/Drag Selection (Web UI)

**How it works:** The web viewer shows the base layer map (zoom 0-10 always available). The operator draws a rectangle or circle on the map to select the area to download.

**Flow:**
1. Open map in browser — base layers show the whole country
2. Navigate to the deployment area using the base tiles
3. Use a "Select Area" tool to draw a box or circle
4. System calculates tile count and estimated size
5. Confirm → Pi downloads the selected area

**Pros:** Visual, intuitive, precise area selection
**Cons:** Requires internet on Pi for download

---

### Strategy 6: Layered Zoom Pyramid (Recommended Default)

**How it works:** Pre-load low zoom levels for broad coverage (world + country), then only download high zoom levels for the specific AO at go-time.

**Pre-deployment (one-time):**
```
map-loader --world --zoom 0-6           # ~50 MB
map-loader --region us --zoom 7-10      # ~500 MB
```

**Go-time:**
```
map-loader --lat 29.76 --lon -95.37 --radius 50 --zoom 11-14  # ~500 MB - 1 GB
```

**Why this is the best default:**
- Low zoom levels cover the entire country — always useful
- You never arrive somewhere with a completely blank map
- Only the expensive high-zoom data needs to be area-specific
- Downloading zoom 11-14 for a 50km radius is fast (~500MB, 5-10 min)

**Pros:** Best balance of coverage and storage, always has something usable
**Cons:** Still needs go-time download for full detail

---

### Strategy 7: Meshtastic Position-Based Auto-Select (Advanced)

**How it works:** The Pi listens to Meshtastic position broadcasts from all devices on the mesh. It aggregates positions to determine the operating area, then automatically downloads tiles for the convex hull of all operator positions plus a configurable buffer.

**Flow:**
1. Meshtastic devices (phones, other nodes) broadcast GPS positions
2. Pi's Meshtastic daemon receives position packets via serial
3. Map server aggregates positions from the last N minutes
4. Calculates bounding box of all positions + buffer (e.g., +25%)
5. Checks if high-zoom tiles exist for that area
6. If internet available, downloads missing tiles automatically
7. If no internet, reports coverage status

**Pros:** Fully automatic, adapts to actual operational footprint, works with existing Meshtastic setup
**Cons:** Complex implementation, requires internet for initial download, positions may be sparse initially

---

### Strategy 8: Multi-Node Cooperative Caching (Most Advanced)

**How it works:** Nodes on the 802.11s mesh share metadata about which tiles they have. If one node has detailed tiles for an area that another node needs, it can transfer them over the mesh.

**Example scenario:**
- Node A was deployed to Houston last week, has Houston zoom 11-14 tiles
- Node B is being deployed to Houston now, connects to the mesh
- Node B discovers Node A has the needed tiles
- Node B requests tiles from Node A over 802.11s (WiFi mesh — decent bandwidth)
- Node B receives and stores the tiles locally

**Transfer protocol:** Simple HTTP between nodes, or a custom sync protocol over the mesh

**Pros:** Tiles propagate through the mesh without internet, leverages existing data across deployments
**Cons:** Most complex to implement, requires mesh connectivity between nodes, bandwidth-intensive

---

## GPS Passthrough — Phone to Pi

Since the Pi has no GPS module, the phone's GPS is used. Here are all the methods, ordered by simplicity:

### Method 1: Browser Geolocation API (Primary — Recommended)

**How it works:**
- Phone opens the map web page served by the Pi
- JavaScript calls `navigator.geolocation.getCurrentPosition()`
- Browser shows the standard "Allow location access?" prompt
- On approval, returns latitude, longitude, accuracy, altitude, heading, speed
- JavaScript sends this to the Pi via `POST /api/location`

**Requirements:**
- HTTPS or `localhost` — Geolocation API requires secure context. Since the phone connects to the Pi's AP at a local IP (e.g., `http://192.168.x.1:8080/`), most browsers will allow geolocation for private IPs. If not, the tile server can serve over HTTPS with a self-signed cert.
- User must tap "Allow" on the location prompt

**Data available from browser:**
| Field | Description | Typical Accuracy |
|-------|-------------|-----------------|
| `latitude` | Decimal degrees | ±3-10m (GPS), ±30m (WiFi) |
| `longitude` | Decimal degrees | ±3-10m (GPS), ±30m (WiFi) |
| `accuracy` | Accuracy radius in meters | Reported by device |
| `altitude` | Meters above sea level | ±10-30m (if available) |
| `heading` | Degrees from true north | If moving |
| `speed` | Meters per second | If moving |
| `timestamp` | Time of fix | Milliseconds |

**Continuous tracking:** Can use `navigator.geolocation.watchPosition()` for continuous updates (useful for moving operators).

**Privacy note:** Location data stays local — it goes from the phone to the Pi over the direct AP connection. Never leaves the local network.

---

### Method 2: Meshtastic Position Packets (Passive — Already Running)

**How it works:**
- Meshtastic on the phone broadcasts GPS position packets over LoRa
- The Pi receives these via its Meshtastic radio (serial/USB)
- The Meshtastic daemon on the Pi can expose position data via its API
- The tile server reads positions from Meshtastic

**Data path:**
```
Phone GPS → Meshtastic App → LoRa Radio → Pi Meshtastic Radio → Serial → meshtastic daemon → tile-server
```

**Available data:**
- Latitude, longitude, altitude
- Node ID (so you can track multiple devices)
- Battery level, SNR, RSSI
- Timestamp

**Meshtastic Python API:** The `meshtastic` Python package provides access to received position data. The tile server can poll or subscribe to position updates.

**Pros:** Completely passive — no user action needed. Works for ALL devices on the mesh, not just the one viewing the map. Enables blue force tracking.
**Cons:** Lower update rate than browser GPS (Meshtastic position broadcasts are typically every 15-900 seconds). Lower precision (LoRa packet size limits coordinate precision). Slight latency.

---

### Method 3: Manual Entry (Fallback)

**How it works:**
- User types coordinates into the web UI or CLI
- Supports multiple formats: decimal degrees, DMS, MGRS, UTM, grid reference
- Also supports place name search (if internet available for geocoding)

**Web UI input options:**
- Lat/Lon decimal: `29.7604, -95.3698`
- DMS: `29°45'37.4"N 95°22'11.3"W`
- MGRS: `15RYN 12345 67890`
- Place name: `Houston Convention Center`
- Click on map to set position

**Pros:** Always works, no GPS dependency
**Cons:** Requires the user to know or look up their position

---

### Method 4: USB GPS Dongle on Pi (Hardware Addition)

**How it works:** Attach a USB GPS receiver (e.g., u-blox 7/8/9, ~$15-30) to the Pi. The Pi then has its own GPS.

**Integration:** The GPS dongle appears as a serial device (`/dev/ttyACM0` or `/dev/ttyUSB0`). Use `gpsd` to parse NMEA sentences and expose position via the `gpsd` socket.

**Recommended dongles:**
- VK-162 USB GPS (u-blox 7) — ~$15
- VK-172 USB GPS (u-blox 7) — ~$12
- BN-880Q USB GPS (u-blox M8) — ~$20
- Any USB GPS that presents as serial and outputs NMEA

**Pros:** Pi has its own position, works without any phone connection
**Cons:** Additional hardware, additional power draw, additional USB port used

---

## Tile Download Methods

### Method A: Direct HTTP Download from OpenFreeMap

**Process:**
1. Fetch TileJSON from `https://tiles.openfreemap.org/planet` to discover current tile version and URL template
2. Calculate which tiles are needed for the requested area + zoom levels
3. Download each tile as a PBF file via HTTP GET
4. Write tiles into an MBTiles SQLite database
5. Handle XYZ-to-TMS coordinate conversion (MBTiles uses TMS scheme)

**Key parameters:**
- Tile URL template: `https://tiles.openfreemap.org/planet/{version}/{z}/{x}/{y}.pbf`
- User-Agent: Should identify the application
- Concurrency: 5-10 parallel downloads (respect rate limits)
- Retry: 3 attempts with exponential backoff
- HTTP 204 = tile not available at this location (ocean, etc.) — skip

**Tile coordinate calculation:**
- Convert lat/lon bounds to tile coordinates using the standard slippy map formula
- For a circular region: calculate bounding box from center + radius, then enumerate all tiles within
- Total tile count = sum of tiles at each zoom level within the bounds

---

### Method B: Pre-Downloaded MBTiles Import (USB)

**Process:**
1. On a preparation machine, download full region packs
2. Copy MBTiles files to USB drive
3. Plug USB into Pi
4. Copy or symlink MBTiles file to `/opt/maps/`
5. Tile server auto-discovers new files

**Pre-pack generation tools:**
- `map-loader` CLI with `--region` flag
- [OpenMapTiles](https://openmaptiles.org/) — can generate MBTiles from raw OSM data
- [Protomaps](https://protomaps.com/) — offers PMTiles format (similar to MBTiles)
- [MapTiler](https://www.maptiler.com/) — commercial tool with free tier for MBTiles export

---

### Method C: Peer Transfer Over 802.11s Mesh

**Process:**
1. Node discovers peers on the 802.11s mesh
2. Queries peers for tile coverage metadata: "What areas/zoom levels do you have?"
3. Identifies needed tiles that peers have
4. Transfers MBTiles file or individual tiles over HTTP between nodes
5. Writes received tiles to local MBTiles storage

**Bandwidth consideration:**
- 802.11s mesh link: typically 10-50 Mbps usable
- A 1 GB MBTiles file would transfer in ~2-8 minutes
- Individual tile requests are fast (~15 KB per tile, ~100 tiles/second)

---

### Method D: Phone-Initiated Download (Bridge Through Phone)

**Process:**
1. Phone has cellular data but Pi doesn't have internet
2. Phone connects to Pi AP AND cellular simultaneously
3. Web UI has a "Download via my phone" option
4. Phone's browser fetches tiles from OpenFreeMap using cellular
5. Forwards tile data to Pi via the AP connection
6. Pi stores tiles in MBTiles

**Implementation:** The web page fetches tiles in JavaScript using `fetch()`, then POSTs the raw tile data to the Pi's API. The Pi writes each tile to MBTiles.

**Pros:** Pi doesn't need its own internet connection
**Cons:** Uses phone's cellular data, slower (each tile goes through the phone), battery-intensive on the phone

---

## Tile Server Component

### Overview

A lightweight HTTP server running on the Pi that:
- Serves map tiles from MBTiles files
- Serves a MapLibre style JSON document
- Serves the web map viewer
- Provides API endpoints for location and management
- Auto-discovers MBTiles files in the map directory

### API Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/` | GET | Serve the web map viewer HTML page |
| `/tile/{z}/{x}/{y}.pbf` | GET | Serve a vector tile from MBTiles |
| `/tile/{z}/{x}/{y}.png` | GET | Serve a raster tile from MBTiles (if raster source) |
| `/style.json` | GET | Serve the MapLibre style JSON |
| `/api/location` | POST | Receive phone GPS location |
| `/api/location` | GET | Get latest known location(s) |
| `/api/locations` | GET | Get all known operator locations (from Meshtastic + phones) |
| `/api/coverage` | GET | Report which areas/zoom levels have tiles available |
| `/api/coverage?lat=X&lon=Y` | GET | Check tile coverage for a specific location |
| `/api/download` | POST | Trigger a tile download for an area (if internet available) |
| `/api/download/status` | GET | Get download progress |
| `/api/regions` | GET | List all MBTiles files and their coverage |
| `/api/regions/{id}` | DELETE | Delete an MBTiles file |
| `/api/health` | GET | Server health check |

### Tile Serving Logic (Cascading Sources)

When a tile is requested, the server checks multiple MBTiles files in priority order:

1. **AO-specific MBTiles** (highest detail, smallest area) — check first
2. **Country/region MBTiles** (medium detail, broad area) — fallback
3. **World MBTiles** (low detail, global) — ultimate fallback
4. **HTTP 404** — no tile available

The server reads the `metadata` table from each MBTiles to determine its bounds and zoom range, then only queries files that could contain the requested tile.

### TMS/XYZ Coordinate Handling

MBTiles uses TMS tiling scheme (origin at bottom-left), but web map libraries typically request tiles in XYZ scheme (origin at top-left). The server must convert:

```
TMS_Y = (2^zoom - 1) - XYZ_Y
```

### Style JSON Generation

The server dynamically generates a MapLibre style JSON that:
- Points tile sources to the local server (`http://192.168.x.1:8080/tile/{z}/{x}/{y}.pbf`)
- Includes all the layer styling (roads, water, buildings, labels, etc.)
- Adapts based on available tile sources (vector vs. raster)
- Can be customized (dark mode for night operations, etc.)

### Recommended Implementation

**Framework:** FastAPI (Python) or Flask (Python)
- FastAPI preferred: async support, automatic OpenAPI docs, lightweight
- Flask alternative: simpler, more widely known, synchronous

**ASGI Server:** Uvicorn (for FastAPI)
- Lightweight, fast enough for tile serving on Pi
- Single worker sufficient for 1-10 connected phones

**SQLite Access:** Python's built-in `sqlite3` module
- No additional dependencies
- Connection pooling for concurrent tile requests
- Read-only mode for safety

---

## Web Map Viewer Component

### Overview

A single HTML file with embedded JavaScript and CSS that provides:
- Full interactive map (pan, zoom, rotate)
- GPS position display (blue dot)
- Operator positions (from Meshtastic)
- Tile coverage visualization
- Area download interface
- Offline-capable (cached after first load)

### Map Rendering Library: MapLibre GL JS

**Why MapLibre GL JS:**
- Open-source, free, no API key
- GPU-accelerated vector tile rendering
- Smooth zooming and rotation
- Rich styling capabilities
- Active community, well-documented
- ~350 KB gzipped — loads fast over local AP

**Alternative for very constrained scenarios:** Leaflet.js (~40 KB) — simpler, raster-focused, works on older phones

### Features

#### GPS Position Display
- Uses `navigator.geolocation.watchPosition()` for continuous tracking
- Shows blue dot with accuracy circle
- Sends position to Pi periodically via `/api/location`
- Works in secure context (HTTPS or private IP)

#### Operator Locations (Blue Force Tracking)
- Polls `/api/locations` for all known positions
- Displays each operator as a marker with name/callsign
- Updates positions in real-time
- Sources: Browser GPS (connected phones) + Meshtastic (all mesh devices)

#### Tile Coverage Overlay
- Visual indicator showing which areas have detailed tiles
- Green: full coverage (zoom 11-14)
- Yellow: partial coverage (zoom 7-10 only)
- Red: minimal coverage (zoom 0-6 only)
- Helps operators decide if they need to download more tiles

#### Download Area Interface
- "Download Area" mode: user draws a circle or rectangle on the map
- Shows estimated tile count and file size
- Progress bar during download
- Radius presets: 10km, 25km, 50km, 100km
- Zoom level selection with size estimates

#### Offline Capability
- The HTML page itself can be cached by the browser
- MapLibre GL JS can be served from the Pi (no CDN dependency)
- All assets served locally — works without any internet

---

## Map Loader CLI Tool

### Overview

A command-line tool for downloading, managing, and importing map tiles. Designed to run on the Pi or on a preparation machine.

### Commands and Options

#### Download by Coordinates
```
map-loader download --lat <LAT> --lon <LON> --radius <KM> [--zoom <MIN>-<MAX>] [--output <FILE>]
```

**Options:**
- `--lat`, `--lon`: Center coordinates (decimal degrees)
- `--radius`: Radius in kilometers (default: 50)
- `--zoom`: Zoom level range (default: 0-14)
- `--output`: Output MBTiles file path (default: auto-generated in /opt/maps/)
- `--source`: Tile source URL (default: OpenFreeMap)
- `--concurrency`: Parallel downloads (default: 8)
- `--resume`: Resume interrupted download

#### Download by Place Name
```
map-loader download --place "<PLACE NAME>" --radius <KM> [--zoom <MIN>-<MAX>]
```

Uses Nominatim API for geocoding.

#### Download by Region
```
map-loader download --region <REGION> [--zoom <MIN>-<MAX>]
```

Pre-defined regions: US states, FEMA regions, countries. Region definitions stored in a JSON config file.

#### Download World Base Layer
```
map-loader download --world --zoom 0-6
```

#### Download Country Layer
```
map-loader download --country us --zoom 7-10
```

#### Import MBTiles File
```
map-loader import <FILE> [--name <NAME>]
```

Copies or symlinks an MBTiles file into the map directory. Validates the file structure.

#### List Downloaded Regions
```
map-loader list
```

Shows all MBTiles files, their coverage areas, zoom levels, and file sizes.

#### Check Coverage
```
map-loader coverage --lat <LAT> --lon <LON>
```

Reports which zoom levels are available for a given location.

#### Estimate Download Size
```
map-loader estimate --lat <LAT> --lon <LON> --radius <KM> --zoom <MIN>-<MAX>
```

Calculates tile count and estimated file size without downloading.

#### Delete Region
```
map-loader delete <REGION_NAME or FILE>
```

Removes an MBTiles file.

#### Merge MBTiles Files
```
map-loader merge <FILE1> <FILE2> [--output <FILE>]
```

Combines multiple MBTiles files into one (useful for merging overlapping regions).

---

## Deployment Workflows

### Workflow 1: Standard Deployment (Internet at Staging)

**Before deployment (at base/HQ, good internet):**
1. Pre-load base layers if not already done:
   ```
   map-loader download --world --zoom 0-6
   map-loader download --country us --zoom 7-10
   ```
2. Receive mission coordinates/area
3. Download AO detail:
   ```
   map-loader download --lat 29.76 --lon -95.37 --radius 50 --zoom 11-14
   ```
4. Verify coverage:
   ```
   map-loader list
   map-loader coverage --lat 29.76 --lon -95.37
   ```

**In the field:**
1. Power on Pi → tile server starts automatically (systemd)
2. Connect phone to Pi AP
3. Open `http://192.168.x.1:8080/` in browser
4. Full map available immediately

---

### Workflow 2: No-Notice Deployment (No Pre-Loading)

**At staging area (may have limited internet):**
1. Power on Pi
2. Connect phone to Pi AP
3. Open map page — base layers show country overview
4. If Pi can reach internet (tethered, satellite, etc.):
   - Phone GPS provides position
   - Tap "Download Area" in web UI
   - Select radius → Pi downloads tiles
5. If no internet:
   - Base layers (zoom 0-10) provide roads, cities, counties
   - Navigate using available detail
   - Download tiles when internet becomes available

---

### Workflow 3: USB Pre-Pack Deployment

**Before deployment (preparation machine):**
1. Download region pack:
   ```
   map-loader download --region texas --zoom 0-14 --output texas.mbtiles
   ```
2. Copy to USB drive

**At staging:**
1. Plug USB into Pi
2. Import:
   ```
   map-loader import /mnt/usb/texas.mbtiles
   ```
3. Deploy

---

### Workflow 4: Mesh-Enhanced Deployment

**Scenario:** Multiple nodes deployed, one has internet briefly.

1. Node A gets internet (cell tether, satellite link)
2. Node A downloads tiles for the AO
3. Node A shares with the mesh: "I have tiles for area X, zoom 0-14"
4. Nodes B and C request tiles from Node A over 802.11s mesh
5. All nodes now have the same tile coverage

---

## Meshtastic Integration

### Position Collection

The tile server can integrate with the Meshtastic daemon to collect GPS positions from all mesh devices:

**Data source:** Meshtastic Python API (`meshtastic` package)
- Connect to local Meshtastic device via serial (`/dev/ttyUSB0` or `/dev/ttyACM0`)
- Subscribe to position packets
- Each packet contains: node ID, lat, lon, altitude, battery, time

**Position storage:**
- In-memory dictionary: `{node_id: {lat, lon, alt, last_seen, name}}`
- Exposed via `/api/locations` endpoint
- Web viewer polls this to display all operators on the map

### Automatic AO Detection

By aggregating Meshtastic positions, the system can automatically determine the area of operations:

1. Collect positions from all nodes over a time window (e.g., last 30 minutes)
2. Calculate bounding box or convex hull of all positions
3. Add buffer (e.g., 25% or configurable)
4. Compare to available tile coverage
5. Alert if coverage is insufficient
6. Offer to download missing tiles (if internet available)

### Node Metadata on Map

Display rich information about each mesh node on the map:
- Position (lat/lon)
- Name/callsign
- Battery level (icon color coding)
- Signal quality (last heard SNR/RSSI)
- Online/offline status (based on last heard time)
- Device type (node vs. phone vs. repeater)

---

## Mesh Tile Sharing (Node-to-Node)

### Concept

When one Pi node has tiles that another needs, they can share over the 802.11s mesh link (WiFi, relatively high bandwidth compared to LoRa).

### Discovery Protocol

Each tile server advertises its coverage via a simple beacon:

- Periodically broadcast (or respond to queries): node ID, list of MBTiles files with bounds and zoom ranges
- Other nodes compare their coverage and identify gaps
- Request missing tiles from peers

### Transfer Options

**Option A: Full MBTiles file transfer**
- Simple HTTP download of the entire MBTiles file between nodes
- Best when receiving node has no tiles for the area
- 802.11s mesh bandwidth: ~10-50 Mbps → 1 GB file in 2-8 minutes

**Option B: Tile-by-tile API**
- Requesting node asks for specific tiles by z/x/y
- Serving node reads from MBTiles and returns the PBF data
- Best when receiving node has partial coverage and needs to fill gaps

**Option C: Differential sync**
- Nodes exchange tile inventories (list of z/x/y coordinates they have)
- Compute the difference
- Transfer only missing tiles
- Most efficient for partially overlapping coverage

---

## Required Packages & Dependencies

### Python Packages (Pi)

| Package | Version | Purpose | Install |
|---------|---------|---------|---------|
| `fastapi` | ≥0.100 | HTTP API framework | `pip install fastapi` |
| `uvicorn` | ≥0.20 | ASGI server for FastAPI | `pip install uvicorn[standard]` |
| `aiofiles` | ≥23.0 | Async file serving | `pip install aiofiles` |
| `aiosqlite` | ≥0.19 | Async SQLite access for tile serving | `pip install aiosqlite` |
| `httpx` | ≥0.24 | HTTP client for tile downloads | `pip install httpx` |
| `click` | ≥8.0 | CLI framework for map-loader | `pip install click` |
| `rich` | ≥13.0 | Terminal progress bars and formatting | `pip install rich` |
| `meshtastic` | ≥2.0 | Meshtastic API integration (optional) | `pip install meshtastic` |

**One-line install:**
```bash
pip install fastapi uvicorn[standard] aiofiles aiosqlite httpx click rich
```

**Optional:**
```bash
pip install meshtastic  # Only if Meshtastic integration desired
```

### System Packages (Pi OS)

| Package | Purpose | Install |
|---------|---------|---------|
| `python3` | Python runtime (usually pre-installed) | `sudo apt install python3` |
| `python3-pip` | Package installer | `sudo apt install python3-pip` |
| `python3-venv` | Virtual environment support | `sudo apt install python3-venv` |
| `sqlite3` | SQLite CLI (for debugging MBTiles) | `sudo apt install sqlite3` |
| `gpsd` | GPS daemon (only if USB GPS dongle used) | `sudo apt install gpsd gpsd-clients` |

**One-line install:**
```bash
sudo apt install -y python3 python3-pip python3-venv sqlite3
```

### Frontend Libraries (Served from Pi, No CDN)

| Library | Version | Size (gzipped) | Purpose |
|---------|---------|----------------|---------|
| MapLibre GL JS | ≥4.0 | ~350 KB | Vector tile map rendering |
| MapLibre GL CSS | ≥4.0 | ~15 KB | Map styles |

These files should be downloaded and stored locally on the Pi so no internet is needed to serve the web viewer:

```bash
# Download MapLibre GL JS for local serving
wget -O /opt/maps/static/maplibre-gl.js https://unpkg.com/maplibre-gl@4.x/dist/maplibre-gl.js
wget -O /opt/maps/static/maplibre-gl.css https://unpkg.com/maplibre-gl@4.x/dist/maplibre-gl.css
```

### Total Additional Storage for Software

| Item | Size |
|------|------|
| Python packages | ~30 MB |
| MapLibre GL JS + CSS | ~1 MB |
| Map server code | ~50 KB |
| **Total** | **~31 MB** |

---

## File Structure

```
/opt/maps/
├── tile-server.py          # HTTP tile server (main application)
├── map-loader.py           # CLI download/management tool
├── config.json             # Server configuration
├── regions.json            # Pre-defined region definitions (states, etc.)
├── static/
│   ├── index.html          # Web map viewer
│   ├── maplibre-gl.js      # MapLibre GL JS (local copy)
│   ├── maplibre-gl.css     # MapLibre GL CSS (local copy)
│   └── style.json          # Generated MapLibre style (or served dynamically)
├── tiles/
│   ├── world_z0-6.mbtiles      # Base layer: world overview
│   ├── us_z7-10.mbtiles        # Country layer: US detail
│   └── ao_houston_z11-14.mbtiles  # AO layer: deployment area
├── logs/
│   └── tile-server.log     # Server logs
└── README.md               # Setup and usage instructions
```

---

## Systemd Service Configuration

The tile server should start automatically on boot.

### Service File: `/etc/systemd/system/tile-server.service`

**Key settings:**
- `Type=simple` — single process
- `ExecStart` — runs uvicorn with the FastAPI app
- `Restart=always` — auto-restart on crash
- `After=network.target` — start after networking is up
- `User=pi` — run as non-root
- `WorkingDirectory=/opt/maps`
- `Environment` — set Python path, config location

### Management Commands

```bash
sudo systemctl enable tile-server    # Enable on boot
sudo systemctl start tile-server     # Start now
sudo systemctl status tile-server    # Check status
sudo systemctl restart tile-server   # Restart
journalctl -u tile-server -f         # View logs
```

---

## Security Considerations

### Network Security
- The tile server listens on the Pi's AP interface only (bind to `192.168.x.1` or `0.0.0.0` depending on needs)
- No authentication by default (trusted local network over AP)
- Optional: basic API key for management endpoints (`/api/download`, `/api/regions/DELETE`)
- Tile serving endpoints (`/tile/*`) should be unauthenticated for performance

### Data Security
- MBTiles files are read-only during serving (opened with `SQLITE_OPEN_READONLY`)
- Download API should validate coordinates to prevent abuse (reasonable lat/lon/radius bounds)
- File import should validate MBTiles structure before accepting

### Location Privacy
- GPS data from phones stays on the local Pi — never transmitted to the internet
- Meshtastic positions are already broadcast on the mesh (inherent to the protocol)
- Consider adding a "privacy mode" that doesn't share position with the tile server

---

## Performance & Resource Constraints

### Pi Resource Usage

| Resource | Expected Usage | Notes |
|----------|---------------|-------|
| CPU | 1-5% idle, 10-20% serving | SQLite reads are efficient |
| RAM | ~50-100 MB | Python process + SQLite cache |
| Disk I/O | Low (read-only serving) | Higher during downloads |
| Network | Minimal per tile (~15 KB) | 802.11n AP handles 10+ phones easily |

### Tile Serving Performance

- **Cold read:** ~5-10 ms per tile (SQLite seek + read)
- **Cached read:** ~1-3 ms per tile (OS page cache)
- **Typical map view:** ~20-40 tiles visible → ~100-200 ms total
- **Concurrent users:** 5-10 phones easily handled by single Pi 4

### Download Performance

- **Tile download speed:** ~50-200 tiles/second (depends on internet speed and concurrency)
- **50 km radius, zoom 11-14:** ~40,000 tiles → ~5-15 minutes on broadband
- **Disk write speed:** Not a bottleneck (SD card write ~10-20 MB/s, tiles are small)

### Optimization Tips

- Use SQLite WAL mode for concurrent reads during writes
- Pre-compute metadata (bounds, zoom ranges) at startup instead of querying each request
- Serve with appropriate `Cache-Control` headers (tiles don't change)
- Use `mmap` for large MBTiles files if available
- Consider `lz4` compression for mesh tile transfers

---

## Future Enhancements

### Phase 2: Enhanced Features
- **Dark mode map style** — for night operations
- **Terrain/elevation overlay** — using Terrain-RGB tiles
- **Custom markers/annotations** — operators can place markers on the map that sync across devices
- **Route planning** — basic A-to-B routing using OpenStreetMap road data
- **Offline geocoding** — search for places without internet (using a local place name database)
- **Print/export** — export map sections as PDF or image for paper backup

### Phase 3: Advanced Mesh Integration
- **Tile gossip protocol** — nodes automatically share tiles with neighbors
- **Priority-based caching** — AO center gets highest zoom, edges get less
- **Incremental updates** — only download changed tiles when a new OpenFreeMap version is released
- **PMTiles support** — alternative to MBTiles, optimized for HTTP range requests
- **Reticulum RMSP** — serve tiles over Reticulum (like Columba does) for extremely low-bandwidth scenarios

### Phase 4: Mission Planning
- **Waypoint management** — create, share, and navigate to waypoints
- **Area of operations overlay** — draw and share AO boundaries
- **Measurement tools** — distance, area, bearing calculations
- **Coordinate conversion** — lat/lon ↔ MGRS ↔ UTM on the map
- **KML/KMZ import** — load external geographic data

---

## Reference: How Columba Does It

Columba (the Reticulum messaging app) implements a similar but Android-focused system. Key learnings from their codebase:

### Their Architecture
1. **MapLibre GL Native** for rendering (Android SDK)
2. **OpenFreeMap** as the default tile source (same as our plan)
3. **Two offline systems:**
   - MapLibre's native `OfflineManager` API (stores tiles in `mbgl-offline.db`)
   - Custom `MBTilesWriter` for direct MBTiles file creation
4. **RMSP (Reticulum Map Service Protocol)** — serves tiles over the Reticulum mesh network

### What We're Borrowing
- OpenFreeMap as the tile source (proven, free, no API key)
- MBTiles format for storage (SQLite, portable, standard)
- Vector tiles in PBF format (small, styleable)
- OpenMapTiles schema and Liberty style layers
- TileJSON resolution for version discovery
- XYZ-to-TMS coordinate conversion logic
- Geohash-based area encoding (for mesh tile requests)

### What We're Doing Differently
- **Pi-based server** instead of Android app
- **HTTP tile serving** to any browser instead of in-app rendering
- **CLI-first** tile management instead of GUI-only
- **Multi-source GPS** (browser API + Meshtastic + manual) instead of device-only GPS
- **802.11s mesh tile sharing** between nodes (Columba uses RMSP over Reticulum)
- **Web-based viewer** — zero-install on the phone

---

*Document version: 1.0*
*Last updated: 2025*
*Target platform: Raspberry Pi 3B+/4/5 with 32GB SD card*
