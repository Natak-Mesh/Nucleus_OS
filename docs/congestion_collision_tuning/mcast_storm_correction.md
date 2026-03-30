# Multicast Storm Correction — Echo Routing Removal

## Date: 2026-03-29

## Summary

Adding a third mesh node to the wlan1 802.11s mesh causes catastrophic multicast amplification, destroying mesh performance. The root cause is the smcroute "echo routing" pattern that re-injects received multicast back onto wlan1 at Layer 3, bypassing 802.11s native deduplication. The fix is to remove the echo and let 802.11s handle multi-hop multicast forwarding natively, the same way Meshtastic handles multi-hop LoRa — controlled flooding with per-frame deduplication.

---

## The Problem

With nodes 9 and 10 on the mesh, everything works fine. As soon as node 8 joins, the entire mesh degrades with severe lag. This is not a node 8 hardware issue — it is a fundamental architectural problem with the smcroute multicast routing that only manifests at 3+ nodes.

### Evidence from Node 8 (Live System)

**Multicast TX queue in catastrophic failure:**
- 117,684 multicast packets dropped (73% drop rate)
- 538 packets / 200KB currently queued (queue perpetually full)
- Only 43,679 packets successfully transmitted

**Multicast routing cache showing amplification:**
- Traffic from node 10's ATAK device: 439,829 packets (146MB) flowing through node 8
- Traffic from node 9's ATAK device: 9,439 packets (3.1MB)
- Node 8's own local traffic: 7,072 packets with 7,038 RPF failures (kernel correctly rejecting echo-back of own traffic)

**Mesh peer link degraded by saturation:**
- 81% unicast TX retry rate (268 retries out of 330 packets)
- 34,445 receive drops
- The channel is so saturated with multicast that unicast can barely get through

---

## Root Cause: Echo Routing Creates Amplification Without Deduplication

### What Echo Routing Does

The smcroute configuration contains routes like:

> mroute from wlan1 group 239.2.3.1 to **wlan1** br-lan

The `to wlan1` output is the "echo" — when a multicast packet arrives on wlan1 from a remote node, smcroute forwards it to br-lan (correct, delivers to local ATAK devices) AND back to wlan1 (the echo). The echo was intended to enable multi-hop propagation: a packet from node A reaches node B, node B echoes it back onto the mesh, and node C (which couldn't hear A directly) picks it up from B's echo.

### Why Echo Worked with 2 Nodes

With two nodes, echo creates a linear ping-pong. Node A sends, Node B echoes, Node A echoes, Node B echoes, and so on. Each round decrements the IP TTL by 1. With TTL=8, that is 8 bounces total — manageable, especially on a lightly loaded link.

### Why Echo Fails with 3+ Nodes

With three nodes where multiple nodes can hear each other, echo creates **branching amplification**. A packet arrives at the mesh. Two nodes receive it. Both echo it. Each echo is received by two nodes. Both echo again. The packet count grows at each TTL level:

- TTL 8: 1 packet (originator)
- TTL 7: 2 echoes (2 receivers)
- TTL 6: up to 4 echoes
- TTL 5: up to 8 echoes
- TTL 4: up to 16 echoes
- ... continuing until TTL reaches 0

A single ATAK CoT update can generate **up to 255 transmissions** across the mesh before TTL expires. Multiply that by the CoT update rate across all ATAK devices on the mesh, and the channel is instantly saturated.

### The Critical Difference: No Deduplication at Layer 3

This is the fundamental issue. When smcroute echoes a multicast packet back onto wlan1, the kernel creates a **new IP packet**. It gets a new Layer 2 frame with a new 802.11s mesh sequence number. Every other node on the mesh treats it as a completely new, never-before-seen packet. There is no mechanism at Layer 3 to detect that this is a duplicate of something already forwarded.

Compare this to Meshtastic, which does 7-hop flooding without storms. Every Meshtastic LoRa packet carries a unique packet ID. Every node maintains a "seen IDs" cache. When a node receives a packet with an ID it has already processed, it silently drops it. Each packet propagates outward like a wave — each node forwards it exactly once. The hop count is just a decrementing counter that determines when to stop.

The smcroute echo approach has no equivalent of Meshtastic's packet ID dedup. That is why it storms.

---

## Why This Worked for Over a Year

Before the MESH_MCAST_TTL iptables mangle rule was added (commit d63abc3, 2026-03-29), there was no TTL manipulation in mesh-start.sh. ATAK multicast entered the mesh with whatever TTL the application set. The smcroute echo routing existed, but:

- With low application TTL values, echoed packets died quickly, limiting amplification
- Most testing and operations used 2-node configurations, where echo amplification is linear and tolerable
- The storm behavior is specific to 3+ nodes with echo routing — a configuration that was not heavily tested before

The MESH_MCAST_TTL=8 mangle rule was added to ensure multicast packets have enough TTL to survive multi-hop forwarding. This is correct in principle, but it gave the echo routing enough fuel to cause storms. The rule itself is not wrong — the echo routing is the problem.

---

## The Fix: Let 802.11s Handle Multi-Hop Natively

### How 802.11s Multicast Forwarding Works

802.11s mesh networking handles multicast forwarding at Layer 2, and it does so with built-in deduplication — the same principle as Meshtastic.

When a mesh point transmits a multicast frame, the 802.11s mesh header includes two critical fields:

1. **Mesh TTL** — A hop counter that decrements at each forwarding mesh point. When it reaches 0, the frame is not forwarded further. This is controlled by the `mesh_ttl` kernel parameter (default: 31, should be set explicitly).

2. **Mesh Sequence Number** — A per-source counter that uniquely identifies each frame. Every mesh point maintains a duplicate detection cache keyed by (source address, mesh sequence number). When a mesh point receives a frame it has already seen, it drops it without forwarding.

The forwarding behavior at each mesh point:

1. Receive multicast frame from the air
2. Check (source, sequence number) against duplicate cache → if seen, drop
3. Add to duplicate cache
4. Deliver frame to the local network stack (this is where smcroute picks it up and forwards to br-lan)
5. If mesh TTL > 0: decrement mesh TTL, rebroadcast once on the mesh

This is controlled flooding with dedup — exactly Meshtastic's model, implemented at the 802.11 MAC layer. A multicast frame propagates outward through the mesh. Each mesh point forwards it exactly once. The mesh TTL limits the maximum reach. No amplification, no storms, works with any number of nodes.

### What Needs to Change

**smcroute.conf:** Remove `wlan1` from the output interface list on routes that receive from wlan1. The echo is no longer needed because 802.11s handles multi-hop. Routes should be:

- From wlan1 → deliver to br-lan only (local delivery to ATAK devices)
- From br-lan → send to wlan1 (inject local ATAK traffic into the mesh)

This applies to all multicast groups: 239.2.3.1 (CoT), 224.10.10.1 (discovery), and any future groups.

**mesh.conf:** Add a configurable 802.11s mesh TTL variable (alongside the existing MESH_MCAST_TTL). This controls the actual multi-hop reach at Layer 2. A value of 8 supports 8-hop mesh networks, matching the current MESH_MCAST_TTL intent. Both values should be in mesh.conf so operators can tune them without editing scripts.

**mesh-start.sh:** After the mesh interface is configured, apply the mesh_ttl parameter from mesh.conf using the `iw dev wlan1 set mesh_param` command. The kernel default of 31 is far too high and should never be left as-is.

**MESH_MCAST_TTL iptables mangle rule:** Keep it. The IP TTL still needs to be high enough to survive Layer 3 forwarding at each hop (the wlan1 → br-lan forward on each node decrements IP TTL). With 8 hops, the packet traverses 8 Layer 3 boundaries, so IP TTL=8 is correct. The mangle rule ensures ATAK's low default TTL does not cause premature drops.

### Why This is Better Than Reducing TTL

Reducing MESH_MCAST_TTL from 8 to 4 (or lower) would reduce the storm severity but not eliminate it. With 3 fully-connected nodes and TTL=4, a single packet still generates up to 15 copies. With 5 nodes, it gets worse again. The echo routing approach fundamentally does not scale — it is a per-packet amplifier with no dedup.

Removing the echo and using 802.11s native forwarding scales to any node count. It is the same multi-hop mechanism that has been proven in mesh networks for decades. The per-frame dedup via mesh sequence numbers prevents amplification regardless of topology or node count.

---

## Interaction with 802.11s mesh_fwding

The `mesh_fwding` kernel parameter (currently 1, enabled) controls whether a mesh point forwards frames for other mesh points at Layer 2. This must remain enabled for multi-hop to work. It applies to both unicast and multicast frames.

With `mesh_fwding=1` and an appropriate `mesh_ttl`, 802.11s provides:
- Multi-hop unicast forwarding (with HWMP path selection)
- Multi-hop multicast forwarding (with controlled flooding + dedup)

Babel operates at Layer 3 on top of this, providing more sophisticated unicast routing based on link quality and RTT. For unicast traffic, babel's routing decisions override HWMP at the IP layer. For multicast, 802.11s native forwarding is the correct mechanism — babel does not handle multicast routing.

---

## Deployment Notes

### All Nodes Must Be Updated

The smcroute.conf change must be deployed to all mesh nodes. If even one node retains the echo routing, it will re-inject duplicates into the mesh that other nodes will forward (since they look like new frames at Layer 2).

### The mesh_ttl Must Be Consistent

All nodes should have the same mesh_ttl value. If one node has mesh_ttl=31 and another has mesh_ttl=8, multicast frames originating from the first node will be forwarded up to 31 hops while frames from the second stop at 8. This is not catastrophic but creates inconsistent behavior.

### Verify After Deployment

After applying the changes, verify:

1. Multicast TX queue drops should stop accumulating (check `iw dev wlan1 info` multicast TXQ stats)
2. The multicast routing cache should show reasonable packet counts (check `/proc/net/ip_mr_cache`)
3. ATAK CoT and discovery should still propagate across all nodes on the mesh
4. Mesh latency should return to normal (sub-10ms between direct peers)

### Rollback

If 802.11s native multicast forwarding does not work as expected (frames not reaching multi-hop nodes), the echo routing can be temporarily re-enabled in smcroute.conf with a reduced MESH_MCAST_TTL (set to 4 instead of 8) as an interim measure while debugging.

---

## Files Affected

| File | Change |
|---|---|
| /etc/smcroute.conf | Remove wlan1 from output of wlan1-ingress mroute rules |
| /etc/nucleus/mesh.conf | Add MESH_802_TTL variable for 802.11s mesh_ttl |
| /opt/nucleus/bin/mesh-start.sh | Apply mesh_ttl from mesh.conf after interface setup |
| config_generation.sh | Generate smcroute.conf without echo routing |
