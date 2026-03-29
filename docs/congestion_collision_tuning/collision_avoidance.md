# Collision Avoidance & Congestion Tuning for Nucleus MANET

## The Problem

Nucleus mesh nodes use 802.11s on a shared 2.4GHz channel (HT20). All nodes on the mesh share the same frequency and can only transmit one at a time — WiFi is half-duplex. With 2 nodes, the built-in channel access mechanism (CSMA/CA) handles turn-taking well. At 3+ nodes, contention for the channel multiplies and performance degrades significantly due to frame collisions and retry storms.

This document covers the two complementary tuning layers available to address this:

- **Layer 2: RTS/CTS** — Prevents frame collisions on the wireless channel
- **Layer 3: Babel RTT Tuning** — Makes routing decisions congestion-aware

---

## Layer 2: RTS/CTS (Request to Send / Clear to Send)

### How 802.11 Channel Access Works (CSMA/CA)

802.11 uses CSMA/CA (Carrier Sense Multiple Access / Collision Avoidance) for channel access:

1. A node wants to transmit
2. It listens — is the channel busy? If yes, wait
3. Channel is clear — wait a random backoff time selected from the Contention Window
4. Still clear after backoff? Transmit
5. Wait for ACK from receiver

With 2 nodes this works well — they take turns and the random backoff rarely collides. With 3 nodes, the math breaks down:

- Node A finishes transmitting
- Nodes B and C were both waiting for the channel to clear
- Both see the channel go idle at nearly the same instant
- Their random backoff times have roughly a 30% chance of overlapping (default minimum contention window is 15 slots)
- Both transmit simultaneously — collision — no ACK received — both back off with larger windows and retry
- This cascades: more retries means more airtime wasted, which means more contention, which means more collisions

### How RTS/CTS Fixes This

RTS/CTS adds a 4-way handshake before data frame transmission:

```
Node A → [RTS]  → All nodes hear "A wants to talk to B for X microseconds"
Node B → [CTS]  → All nodes hear "Go ahead A, channel reserved for X microseconds"
Node A → [DATA] → Node B
Node B → [ACK]  → Node A
```

The critical mechanism: both the RTS and CTS frames contain a **duration field**. When Node C hears either the RTS or the CTS, it sets a **NAV (Network Allocation Vector)** timer — a "do not transmit" countdown for the announced duration. Node C stays silent for the entire exchange.

This converts the probabilistic "hope we don't collide" into a deterministic "I have reserved the channel."

### The Threshold

The RTS/CTS threshold determines which frames get the handshake protection based on frame size in bytes.

- Frames at or below the threshold transmit normally (no RTS/CTS overhead)
- Frames above the threshold use the RTS/CTS handshake first

**Why a threshold instead of always-on?** A collision on a small 40-byte babel hello wastes almost no airtime — the retry is cheap. A collision on a 1400-byte ATAK cursor-on-target update wastes significantly more airtime, and the retry compounds the congestion. The threshold lets you protect the frames where collisions are expensive without taxing every small packet.

**Recommended value: 500 bytes**

| Threshold | Behavior |
|---|---|
| 0 | RTS/CTS on every frame — maximum protection, maximum overhead |
| 250 | Aggressive — catches most data frames, more overhead |
| **500** | **Balanced — protects ATAK/CoT/file data, leaves babel hellos and small control frames alone** |
| 1000 | Conservative — only the largest frames get protected |
| off | No RTS/CTS — current default, fine for 2 nodes |

At 500, most real traffic (ATAK data, CoT messages, image/file transfers) is protected. Most control traffic (babel hellos at ~40-80 bytes, ARP, small pings) passes through without the handshake overhead.

### Overhead Cost

Each RTS/CTS exchange adds roughly 100μs of airtime. On a 2.4GHz HT20 link doing ~30Mbps raw, that translates to approximately 5-8% throughput reduction in exchange for eliminating the collision-retry storms that can destroy 50%+ of effective throughput with 3+ nodes.

### Multicast Limitation

RTS/CTS does not protect multicast or broadcast traffic. Multicast frames in 802.11 are sent without ACK and without RTS/CTS regardless of the threshold setting. If the network has significant multicast traffic (mDNS, SSDP, babel neighbor discovery), those frames can still collide. However, unicast data traffic — which is the bulk of operational traffic — gets full protection.

### Hidden Node Scenario (Field Deployment)

RTS/CTS was originally designed for the hidden node problem, which is common in field deployments:

- Node A can hear Node B
- Node C can hear Node B
- But A and C cannot hear each other

Without RTS/CTS, A and C have no way to know the other is transmitting. Both send to B simultaneously, and B receives garbage from both. With RTS/CTS, A sends RTS to B, B responds with CTS, and C hears the CTS even though it can't hear A. C sets its NAV timer and stays off the channel.

This makes RTS/CTS **more valuable in the field than on the bench**, not less.

---

## Layer 3: Babel RTT Tuning (RFC 9616)

### The Problem RTT Tuning Solves

Babel's default route metric uses ETX (Expected Transmission Count), calculated from hello packet loss rates. ETX measures "how many times do I have to send a packet before it gets through."

The blind spot: 802.11 has its own retry mechanism at Layer 2. When the channel is congested, the radio doesn't immediately drop packets — it queues them, retries them at the MAC layer, backs off, retries again. The packet eventually gets delivered. From babel's perspective, the hello packets are still arriving, so ETX looks fine. But actual user experience is terrible because everything is sitting in transmit queues for hundreds of milliseconds.

RTT tuning adds latency measurement to babel's route metric. When congestion causes queuing delays, the measured round-trip time between neighbors increases. Babel detects this and penalizes that link, making alternative paths more attractive.

### How Timestamps Work (No Clock Sync Required)

A common concern for disconnected MANET nodes with no internet access: **babel RTT timestamps do not require synchronized clocks between nodes.**

The mechanism:

1. Node A sends a Hello with its own local timestamp T1 (monotonic clock, not wall time)
2. Node B receives it, notes its own local receive time, holds it, then sends its own Hello back. In that Hello, Node B includes the **processing delay** — how long it held the packet using its own clock
3. Node A receives Node B's Hello at its own local time T4
4. Node A calculates: RTT = (T4 - T1) - processing_delay_reported_by_B

Node A only uses its own clock for the time difference. Node B only reports its own holding time using its own clock. No node ever compares absolute timestamps with another node. This is the same principle as ICMP ping — no clock sync needed.

Even if one node thinks it's January 1970 and another thinks it's March 2026, the RTT measurement is accurate. The only thing that could cause error is if a node's clock runs at the wrong *speed* (significant crystal drift), which is not a concern with Pi4 hardware.

### Parameter Reference

**enable-timestamps** — Piggybacks a timestamp onto babel's regular hello packets. No extra packets, no extra bandwidth. Zero cost to enable.

**rtt-min (recommended: 10ms)** — The "everything is fine" floor. Any RTT below this value receives zero penalty. On a direct 802.11s link, baseline RTT is typically 1-3ms. Setting this at 10ms means normal jitter doesn't trigger penalties — only real congestion does. Setting too high masks real congestion. Setting too low penalizes normal variation.

**rtt-max (recommended: 150ms)** — The "this link is saturated" ceiling. Any RTT at or above this value receives the full maximum penalty. For 802.11s on 2.4GHz, 150ms of RTT indicates serious queuing. Setting too low causes overreaction to normal traffic spikes. Setting too high tolerates unacceptable latency before reacting.

**max-rtt-penalty (recommended: 150)** — The cost added to the route metric when RTT hits rtt-max. Babel's base wireless hop metric is 256 (the configured rxcost). Adding 150 makes a congested direct link (256 + 150 = 406) notably more expensive, but doesn't automatically make a 2-hop uncongested path (256 + 256 = 512) win. This is intentional — you don't want babel to overreact and route through extra hops unless those hops are genuinely better. The penalty scales linearly between rtt-min and rtt-max.

**rtt-decay (recommended: 125)** — Controls how fast the RTT running average reacts to new measurements. Expressed as a fraction of 256. A value of 125 (~48% weight per new sample) is aggressive — babel notices latency spikes within a few hello intervals. The babel default of 42 (~16%) is very smooth and slow-reacting.

| rtt-decay | Behavior | Best for |
|---|---|---|
| 42 | Smooth, slow to react | Mobile nodes with natural jitter from movement |
| 64 | Moderate responsiveness | General field deployment |
| **125** | **Aggressive, fast reaction** | **Stationary nodes, bench testing, stable links** |

If routes "flap" (switch back and forth) under load in the field, lower rtt-decay toward 64 or 42.

### When RTT Tuning Matters Most

RTT tuning shines at **4+ nodes** where babel has genuine routing choices — multiple paths between source and destination through different parts of the network. With only 3 nodes that all have direct connectivity, babel doesn't have many alternative paths to choose from, so the congestion awareness has limited ability to change routing decisions.

However, enabling it at any node count is still recommended because:

1. Zero cost — just a timestamp field in existing hello packets
2. Sets up correctly for larger deployments without reconfiguration
3. Provides diagnostic visibility — babel's state dump shows measured RTT per neighbor, which is valuable troubleshooting data regardless of whether it changes routing

### Verification

To see RTT measurements and penalties in real-time, dump babel's state:

```
(echo "dump"; sleep 1) | nc ::1 33123
```

Look for the `rtt` and `rtt-penalty` fields in neighbor entries.

---

## How The Two Layers Complement Each Other

| Layer | Mechanism | Fixes | Scope |
|---|---|---|---|
| Layer 2: RTS/CTS | Channel reservation handshake | Frame collisions, hidden node problem | Per-hop, immediate |
| Layer 3: Babel RTT | Congestion-aware route metrics | Routing through congested paths | End-to-end, strategic |

RTS/CTS prevents the collisions from happening in the first place. RTT tuning ensures that when congestion does build up (from legitimate traffic load, not collisions), babel routes around it. Neither replaces the other.

---

## Tuning for Operations at the Limits of WiFi Range

When nodes are deployed at the edge of their radio range, several parameters become more sensitive and may need adjustment from their close-range defaults.

### RTS/CTS Threshold at Range

At maximum range, the radio drops to the lowest modulation scheme (e.g., MCS0, ~6.5Mbps raw). Each frame occupies the channel for much longer than at close range where higher modulation is used. This means a collision at range wastes proportionally more airtime than a collision on a strong link.

**Recommendation:** Consider lowering the RTS/CTS threshold to **250 bytes** for deployments where nodes are consistently at the edge of range. This provides more aggressive collision protection at the cost of slightly more overhead per frame — but since the overall throughput is already lower at range, the absolute overhead cost (in bytes per second) is smaller.

### Babel Hello Interval and Link Quality

The current configuration uses `hello-interval 4` (seconds) and `update-interval 16` (seconds). At range, links are more variable — signal fading, environmental changes (vehicles, people, weather) cause fluctuations.

**hello-interval** — With noisy links, 4 seconds between hellos means babel might take several intervals to detect that a marginal link has degraded. Lowering to 2 seconds would make babel react faster to link changes, but doubles the control traffic. For links at the edge of range where airtime is precious, this tradeoff may not be worth it. The current value of 4 is a reasonable balance. Only lower it if you're seeing babel keep routes through links that have clearly failed.

**update-interval** — Controls how often babel sends full routing updates. At 16 seconds, route convergence after a topology change takes up to 16 seconds worst case. This is usually acceptable. Lowering it increases control traffic on already-constrained links.

### Babel RTT Parameters at Range

At the edge of range, baseline RTT is naturally higher due to lower data rates and more MAC-layer retries. The rtt-min and rtt-max values may need adjustment:

**rtt-min** — On a strong link, baseline RTT is 1-3ms. On a marginal link at range, baseline may be 20-50ms due to slower modulation and more Layer 2 retries. If rtt-min stays at 10ms, these marginal links will always carry some RTT penalty even when they're performing as well as they can. For edge-of-range deployments, consider raising rtt-min to **30-50ms** to avoid penalizing links for being slow when slow is their best-case performance.

**rtt-max** — Similarly, a congested link at range might show 300-500ms RTT rather than the 150ms you'd see on a congested close-range link. Consider raising rtt-max to **300ms** for edge-of-range scenarios so the penalty scales across the actual observed RTT range rather than hitting maximum penalty immediately.

**rtt-decay** — At range, link quality fluctuates more due to environmental factors. An aggressive rtt-decay of 125 may cause route flapping as RTT bounces around. For edge-of-range deployments, lower this to **64** (moderate) or even **42** (smooth) to prevent babel from constantly switching routes based on momentary RTT spikes from a gust of wind or a vehicle passing through the Fresnel zone.

### Summary of Range-Adjusted Values

| Parameter | Close Range / Bench | Edge of Range / Field |
|---|---|---|
| RTS threshold | 500 bytes | 250 bytes |
| hello-interval | 4s | 4s (keep stable) |
| rtt-min | 10ms | 30-50ms |
| rtt-max | 150ms | 300ms |
| rtt-decay | 125 | 42-64 |
| max-rtt-penalty | 150 | 150 (no change) |

These are starting points. Actual tuning should be informed by monitoring babel state dumps and observing real RTT values in the deployment environment.

---

## High-Level Implementation Plan

### 1. Add configurable RTS/CTS threshold to mesh.conf

Add a `MESH_RTS_THRESHOLD` variable to `/etc/nucleus/mesh.conf`. Default to 500 for new deployments. A value of 0 disables RTS/CTS (backward compatible with current behavior).

### 2. Update mesh-start.sh to apply the RTS/CTS setting

Replace the currently commented-out RTS/CTS line in `mesh-start.sh` with conditional logic that reads `MESH_RTS_THRESHOLD` from mesh.conf and applies it via `iw phy` if the value is greater than 0.

### 3. Add RTT tuning to babeld.conf generation

Update `config_generation.sh` to include the RTT timestamp parameters on the wlan1 interface line in the generated `babeld.conf`. This adds `enable-timestamps true`, `rtt-decay`, `rtt-min`, `rtt-max`, and `max-rtt-penalty` to the existing interface configuration.

### Files Affected

| File | Change |
|---|---|
| `/etc/nucleus/mesh.conf` | Add `MESH_RTS_THRESHOLD` variable |
| `/opt/nucleus/bin/mesh-start.sh` | Conditional RTS/CTS application from variable |
| `/opt/nucleus/bin/config_generation.sh` | RTT parameters in babeld.conf wlan1 interface line |
| `/etc/babeld.conf` | Auto-generated — will include RTT params after regeneration |
