# Monitor Page Rebuild — Node Detection Fix

## Problem

During field testing (string topology: A-B moving together, away from C-D), the **front page monitor** showed node B as dead while the **hop test page** showed B as connected with good signal. One of these was wrong.

Investigation revealed the front page and hop test page use **completely different data pipelines** for determining node status, and the front page's pipeline has a fragile correlation chain that drops nodes when ARP/neighbor caches go stale.

## Root Cause

### Front Page (`get_mesh_nodes()` → `/api/nodes`)

Uses a 4-step correlation chain:

```
babeld dump (IPv6 neighbor) → IPv6 neighbor cache (MAC) → IPv4 neighbor cache (IPv4) → iw station dump (signal)
```

If **any link** in this chain fails — stale ARP entry, missing IPv6 neighbor, timing issue — the node is silently dropped from the results and appears "disconnected" even though it's fully reachable.

### Hop Test Page (`api_hoptest()` → `/api/hoptest`)

Uses two independent, direct queries:

```
1. ip route show proto babel dev wlan1  →  kernel routing table (IPv4 directly)
2. iw dev wlan1 station dump            →  802.11s WiFi peers (MAC + signal)
```

Panel 1 gives IPv4 addresses directly with no correlation needed. Panel 2 still needs MAC→IPv4 resolution for display, but the two panels are independent — a failed MAC lookup doesn't hide the route.

### Why the Front Page Fails

The critical failure point is `get_ipv6_neighbors()` and `get_ipv4_neighbors()`. These read the kernel neighbor cache, which is:
- **Passively populated** — entries only exist if recent traffic used that path
- **Expires quickly** — default GC timeout is 30-60s
- **Not probed proactively** — the front page calls `probe_nexthops()` and `probe_ipv6_neighbors()` but races against cache expiry

Result: node is reachable (Babel has a route, 802.11s has a peer), but the ARP cache entry expired, so the MAC→IPv4 lookup fails, and the node vanishes from the display.

## Fix Plan

### Node Discovery: Use `ip route show proto babel` as Source of Truth

```
ip route show proto babel dev wlan1
```

Output format:
```
10.20.23.0/24 via 10.20.1.23 dev wlan1 proto babel onlink
10.20.1.23/32 via 10.20.1.23 dev wlan1 proto babel onlink
```

- The `via` field is always a mesh IPv4 address (10.20.1.X) — **no MAC correlation needed**
- If Babel has installed a route, the node is reachable (or was very recently)
- Parse unique `via` IPs → that's your neighbor list

**Advantages:**
- Zero correlation chain — IPv4 comes directly from the kernel routing table
- Babel manages route lifecycle (install/withdraw) based on Hello reachability
- Also tells you direct vs relayed: if `10.20.X.0/24 via 10.20.1.Y` where X≠Y, it's relayed through node Y

**Limitations:**
- Routes persist for 30-60s after a neighbor actually disappears (Babel's hold timer)
- No signal strength info (that requires `iw station dump`)

### Signal Strength: Best-Effort Enrichment from `iw station dump`

After building the node list from Babel routes:

1. Run `iw dev wlan1 station dump` → get MAC→signal map
2. Run `ip neigh show dev wlan1` → get MAC→IPv4 map
3. For each known node (from Babel routes), try to match its IPv4 to a MAC and get signal
4. **If the lookup fails, show the node as connected with "signal: N/A"** — never drop it

This inverts the current logic: nodes are discovered by Babel routes (reliable), and WiFi stats are optional enrichment (best-effort).

### Babel Dump: Use for Link Quality Metrics

Query babeld on port 33123 for `add neighbour` lines to get:
- `reach` — bitmask showing recent Hello reception (real-time link quality)
- `cost` — current link cost including RTT penalty

These are valuable for showing link health but should **not** be the gatekeeper for whether a node appears in the list.

## Data Source Summary

| What | Source | Reliability | Notes |
|:---|:---|:---|:---|
| Node exists / is reachable | `ip route show proto babel` | High | No correlation needed, direct IPv4 |
| Direct vs multi-hop | `ip route` via field | High | Compare via IP to destination prefix |
| Signal strength | `iw station dump` + ARP | Medium | Best-effort, show N/A on failure |
| Link cost / quality | `babeld dump` port 33123 | High | Real-time Hello reachability |
| Neighbor reach bitmask | `babeld dump` port 33123 | High | Shows packet loss pattern |

## RTT Tuning — Removed

RTT tuning (`enable-timestamps`, `rtt-decay`, `rtt-min`, `rtt-max`, `max-rtt-penalty`) has been **stripped entirely** from the wlan1 interface configuration.

### Why

RTT tuning solves **congestion-based** rerouting — it detects bufferbloat/latency on a link and penalizes it. Our actual problem is **at-range degradation** (weak signal, packet loss), which is already handled by Babel's `link-quality true` setting. Link-quality tracks Hello packet delivery ratios and inflates the link cost when packets are lost:

```
effective_cost = rxcost / delivery_ratio
```

With `rxcost 256` and 50% packet loss → cost becomes 512 (equivalent to a clean 2-hop path). This naturally reroutes around degraded links without any RTT involvement.

Adding RTT tuning on top introduced unnecessary variables. The manpage default for `max-rtt-penalty` on wireless is **0** (disabled), meaning RTT penalties are not intended for typical wireless mesh use.

### Final wlan1 interface line

```
interface wlan1 type wireless link-quality true split-horizon false rxcost 256 hello-interval 4 update-interval 16
```

All parameters are either manpage defaults or explicitly required for 802.11s mesh operation.

### History

- Commit `1e4d23a`: Added RTT tuning (`max-rtt-penalty 150`) — too low to trigger hopping
- Commit `2a64daf`: Bumped to `max-rtt-penalty 512` — fixed math but wrong approach for at-range problem
- Current: RTT tuning removed entirely — rely on link-quality for at-range degradation

## Implementation Status

**Implemented: 2026-10-05**

### Changes Made

#### `app.py` — `get_mesh_nodes()` rewrite

The old 4-step correlation chain has been replaced with a route-based pipeline:

```
OLD (fragile):
  babeld dump → IPv6 neighbor cache → IPv4 ARP cache → iw station dump
  Any broken link → node silently dropped

NEW (robust):
  Step 1: ip route show proto babel dev wlan1  → node list         (reliable)
  Step 2: babeld dump + EUI-64 + ARP           → cost/reach        (best-effort)
  Step 3: iw station dump + ARP                → signal/bitrate    (best-effort)
  Broken enrichment → node shown with "N/A"    (never dropped)
```

**Key additions:**

- `mac_from_eui64()` — derives MAC address directly from IPv6 link-local EUI-64 address, bypassing the IPv6 neighbor cache entirely
- `_get_kernel_babel_routes()` — parses kernel routing table grouped by next-hop IPv4 for "Gateway to" display
- IPv6 neighbor cache probing (`probe_ipv6_neighbors`) removed from the pipeline — no longer needed
- ARP probing (`probe_nexthops`) kept but sleep reduced from 0.5s to 0.3s since it's enrichment-only
- Route metrics enriched from babel dump by matching prefix, not by IPv6 correlation

#### CSS / Templates

- Added `cost-unknown` class (grey italic) for nodes where babel cost lookup failed
- Added `q-unknown` class in `nav.html` for the front page neighbor list
- Both templates already handled missing WiFi data conditionally — no changes needed

## Signal & Link Quality Fixes — 2026-11-05

### Problem: Bogus Signal Values

The `iw station dump` driver reports signal values near 0 dBm (e.g., `signal avg: 0 [0] dBm`, `signal: -2 [-2] dBm`) when nodes are at extreme close range or the chipset can't report valid RSSI. Real WiFi signals range from -30 dBm (very close) to -90 dBm (barely usable). Values ≥ -10 dBm are physically impossible and should not be displayed.

**Fix:** In `get_mesh_nodes()` WiFi enrichment, any `signal_avg` or `signal` value ≥ -10 dBm is treated as invalid and set to `None`. The template already handles null signal gracefully (hides the signal row).

### Problem: Broken Link Quality Formula

The old formula calculated link quality from cumulative `iw` counters:

```python
retry_rate = (tx_retries / tx_packets) * 100
link_quality = 100 - retry_rate
```

This was fundamentally wrong because:
- `tx_retries` counts every individual retry attempt over the entire session (a single packet can generate up to 7 retries)
- `tx_retries` can exceed `tx_packets`, making `link_quality` go negative
- These are cumulative counters since station association — a link that was great for 8 hours and terrible for 1 hour still looks 99%+

Example from field: `tx_retries: 7554`, `tx_packets: 9226` → showed "18% link quality — Poor" despite `tx_failed: 1` (99.99% delivery rate) and babel cost 256 (perfect).

**Fix:** Replaced the broken formula with the kernel's `mesh airtime link metric` from `iw station dump`. This metric is:
- Computed by the kernel's 802.11s mesh stack in real-time
- Based on current TX bitrate and frame error rate: `airtime = (overhead + frame_size / bitrate) / (1 - frame_error_rate)`
- Lower is better (~100 = perfect, 1000+ = poor)
- The same metric the kernel mesh stack uses for its own path selection

Quality classification:
- `< 300` → excellent
- `< 500` → good
- `< 700` → fair
- `≥ 700` → poor

### Changes

- `get_wifi_station_stats()` — Removed `tx_packets`/`tx_retries`/`tx_failed` parsing; added `mesh airtime link metric` parsing
- `get_mesh_nodes()` WiFi enrichment — Replaced retry-rate calculation with airtime metric classification; added bogus signal filtering (≥ -10 dBm → None)
- `monitor.html` — Link Quality now displays the airtime metric value with quality label instead of a percentage
