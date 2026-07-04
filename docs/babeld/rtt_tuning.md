# Babeld RTT Metric Tuning (RFC 9616)

> **STATUS: REMOVED 2026-07-04** — RTT tuning is not currently in use anywhere in
> Nucleus OS. The `BABEL_MAX_RTT_PENALTY` variable was removed from
> `/etc/nucleus/mesh.conf` to debloat the system, and the generated
> `babeld.conf` does not include any RTT parameters. This document is kept for
> reference in case RTT-based rerouting is revisited in the future.
>
> Key considerations if revisiting:
> - Only affects **unicast** routes installed by babel (TAK server traffic,
>   video, ssh). Multicast CoT/discovery/voice goes through smcroute static
>   mroutes + 802.11s L2 forwarding and is unaffected.
> - On a single shared channel, rerouting to 2 hops doubles airtime use — can
>   make things worse when the whole channel (not one link) is saturated.
> - Sparse RTT samples at hello-interval 4s mean slow reaction and possible
>   route flapping; needs field testing before trusting it.

In a Pi-based 802.11s MANET, airtime is the primary bottleneck. Standard hop-count metrics often fail because a "strong" signal can still be slow due to congestion or interference. RTT tuning forces Babel to choose paths based on actual measured latency.

### Core Configuration
Add this to babeld.conf for the mesh interface:

```
interface wlan1
    enable-timestamps true
    rtt-decay 42
    rtt-min 10
    rtt-max 120
    max-rtt-penalty 512
```

### Parameter Analysis

| Parameter | Value | Logic |
| :--- | :--- | :--- |
| enable-timestamps | true | Required. Adds a timestamp to Hello packets to calculate Round Trip Time (RTT). Default is false on non-tunnel interfaces. |
| rtt-decay | 42 | Smoothing factor (units of 1/256). The manpage default. Provides stable RTT estimates that rise steadily under congestion and stay elevated long enough for Babel to commit to a reroute. |
| rtt-min | 10 | Latency Floor (ms). Any RTT below this is considered "perfect" and receives 0 penalty. |
| rtt-max | 120 | Latency Ceiling (ms). The manpage default. Tighter window ensures penalty ramps up faster on local 802.11s links. |
| max-rtt-penalty | 512 | Max cost added when RTT >= rtt-max. With rxcost 256, a congested 1-hop (256+512=768) always loses to a clean 2-hop (512). Default is 0 on non-tunnel interfaces — RTT tuning is inert without this. |

---

### Why this works for Pi 802.11s

* Congestion Detection: 802.11s doesn't always drop packets when congested; it buffers them. This increases RTT. Babel sees this increase and reroutes before significant packet loss occurs.
* Half-Duplex Penalty: Since WiFi cannot send and receive simultaneously, every extra hop naturally increases RTT. These settings ensure Babel accounts for that "invisible" cost of airtime contention.
* Penalty Math: The penalty is linear: `penalty = max-rtt-penalty × (rtt - rtt-min) / (rtt-max - rtt-min)`. At 75ms RTT: `512 × 65/110 ≈ 303`, which exceeds the 256 cost of an extra hop — triggering reroute.

### Verification
To see these penalties being applied in real-time, use the Babel monitor:

```
(echo "dump"; sleep 1) | nc ::1 33123
```
