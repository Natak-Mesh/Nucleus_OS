# ATAK Voice & Video Plugin Configuration

## Voice Plugin

**Recommended Setting:** `udp://239.255.255.12:1024` (channel 1)

### Multicast Groups Used

The ATAK voice plugin uses multiple multicast groups:

- **239.255.255.1** — General voice traffic
- **239.255.255.2** — Contact discovery / presence announcements
- **239.255.255.12** — Voice channel 1 (channels use 239.255.255.11, .12, .13, etc.)
- **UDP Port:** 1024

### Current Status

Voice multicast routes are **enabled** in `/etc/smcroute.conf` as of 2026-10-04. The routes use the same no-echo bridging pattern as CoT and Discovery — smcroute bridges between wlan1 and br-lan, while 802.11s handles multi-hop natively at Layer 2.

A TTL mangle rule in `mesh-start.sh` bumps ATAK's TTL=1 voice packets to `MESH_MCAST_TTL` (currently 8) on br-lan ingress, matching `239.255.255.0/24` to cover all voice groups in a single rule. This is the same mechanism used for CoT (239.2.3.1) and Discovery (224.10.10.1).

UFW is currently inactive on the system. If UFW is enabled in the future, allow rules will be needed for `239.255.255.0/24` on wlan1 and br-lan, plus port 1024/udp.

---

### How Voice Multicast Crosses the Mesh

Voice multicast uses the same forwarding path as ATAK CoT and Discovery. Understanding this path is important because voice was previously broken by a misconfiguration that has since been corrected.

**smcroute's role is bridging, not multi-hop.** smcroute forwards multicast between two interfaces on the same node: wlan1 (the 802.11s mesh) and br-lan (the local LAN where ATAK devices connect). When a local ATAK device transmits voice on br-lan, smcroute forwards it to wlan1 to enter the mesh. When a voice packet arrives from the mesh on wlan1, smcroute forwards it to br-lan for local delivery. That is all smcroute does — one hop, local bridging.

**802.11s handles multi-hop at Layer 2.** Once a multicast frame is on wlan1, the 802.11s mesh networking layer propagates it to other mesh nodes using controlled flooding. Each mesh point that receives the frame checks it against a Recent Multicast Cache (RMC) keyed by source address and mesh sequence number. If the frame has already been seen, it is silently dropped. If it is new, the mesh point delivers it to the local network stack (where smcroute bridges it to br-lan) and then rebroadcasts it once with a decremented mesh TTL. When mesh TTL reaches zero, forwarding stops.

This is the same deduplication principle used by Meshtastic for multi-hop LoRa — every packet carries a unique ID, every node tracks what it has already forwarded, and each packet propagates outward like a wave with each node forwarding exactly once. No amplification, no storms, works with any number of nodes.

The mesh TTL is controlled by `MESH_802_TTL` in `mesh.conf` (applied via `iw dev wlan1 set mesh_param mesh_ttl` in `mesh-start.sh`). The kernel default of 31 is far too high — the current setting of 8 supports 8-hop mesh networks.

**The critical detail: IP TTL is separate from mesh TTL.** The 802.11s Layer 2 forwarding does not touch the IP header at all. A voice packet that traverses 5 mesh hops arrives at every node's wlan1 interface with the same IP TTL it had when it first entered the mesh. IP TTL is only decremented at Layer 3 boundaries — specifically, when smcroute forwards between wlan1 and br-lan. This means a voice packet's IP TTL is decremented exactly twice in its lifetime regardless of hop count: once at the originating node (br-lan → wlan1) and once at each receiving node (wlan1 → br-lan).

---

### TTL Mangle Rule

ATAK sends voice multicast with **TTL=1**. The kernel's multicast router will not forward a packet unless its TTL is strictly greater than the interface's TTL threshold (default 1). Since 1 is not greater than 1, a voice packet with TTL=1 is dropped by the kernel before smcroute can even forward it from br-lan to wlan1. Voice never enters the mesh.

The fix is an iptables mangle rule on `PREROUTING -i br-lan` that sets the IP TTL to `MESH_MCAST_TTL` (currently 8, defined in `mesh.conf`). This catches locally-originated voice traffic as it enters the routing stack from br-lan and bumps the TTL before the kernel makes its forwarding decision. The `-i br-lan` match ensures this only applies to traffic from local ATAK devices, not traffic arriving from the mesh on wlan1.

The packet lifecycle with the mangle rule:

1. ATAK device sends voice on br-lan with TTL=1
2. Mangle rule sets TTL=8
3. Kernel multicast router forwards br-lan → wlan1 (TTL decrements to 7)
4. 802.11s propagates the frame across the mesh at Layer 2 — **no IP TTL change** — all mesh nodes receive it with TTL=7
5. At each receiving node, kernel multicast router forwards wlan1 → br-lan (TTL decrements to 6)
6. ATAK on the remote node receives voice with TTL=6

TTL=8 is more than sufficient. Even with a worst-case chain of intermediate nodes that each do a local br-lan delivery (decrementing once per node), the packet survives many hops. There is no echo routing to amplify packets, so high TTL values do not create storms — but there is also no reason to set it higher than needed.

The mangle rule for voice uses the same `MESH_MCAST_TTL` variable and the same mechanism as the existing CoT (239.2.3.1) and Discovery (224.10.10.1) rules in `mesh-start.sh`. It should be added alongside them, matching `239.255.255.0/24` to cover all voice groups in a single rule.

---

### UFW Firewall Rules

The firewall must allow voice multicast on both interfaces and the voice UDP port. Rules for `239.255.255.0/24` on wlan1 and br-lan, plus port 1024/udp.

---

### smcroute Configuration

The voice routes in `/etc/smcroute.conf` follow the same pattern as CoT and Discovery: join the multicast group on both interfaces, route from wlan1 to br-lan (mesh → local delivery), and route from br-lan to wlan1 (local → mesh injection). Three groups need routes: 239.255.255.1 (general voice), 239.255.255.2 (contact discovery), and 239.255.255.12 (channel 1).

**The routes must NOT echo back to the input interface.** Routes that receive from wlan1 must only output to br-lan, not `wlan1 br-lan`. Including wlan1 in the output creates a new IP packet that bypasses 802.11s deduplication, causing exponential multicast amplification. This is what caused the original voice failure. See the history section below and `docs/congestion_collision_tuning/mcast_storm_correction.md` for the full analysis.

---

### History: Why Voice Was Disabled (2025-12-23)

Voice multicast was enabled in December 2025 with smcroute "echo routing" — routes like `mroute from wlan1 group 239.255.255.1 to wlan1 br-lan`. The intent was multi-hop propagation: a voice packet arrives on wlan1, smcroute echoes it back onto wlan1 so nodes further away can pick it up. Combined with TTL=64 set by an iptables mangle rule, this was expected to support deep mesh networks.

The result was catastrophic. With 2+ nodes on the mesh:

- 646,000 dropped multicast packets on the wlan1 TX queue
- Mesh latency increased from sub-1ms to 6–8 seconds
- Video streaming (MediaMTX) completely broken
- All services (web config, TAKServer) became unreachable

The root cause was that each echo created a **new IP packet** with a **new 802.11s mesh sequence number**. The 802.11s RMC dedup, which keys on (source address, mesh sequence number), treated every echo as a never-before-seen frame and forwarded it again. With TTL=64, each packet could bounce between nodes up to 32 times before dying. A single voice PTT generated thousands of transmissions, saturating the wireless channel completely.

This is the same amplification problem that was later identified and fixed for CoT and Discovery multicast (see `docs/congestion_collision_tuning/mcast_storm_correction.md`). The fix was removing the echo — letting smcroute only bridge between interfaces while 802.11s handles multi-hop natively with its built-in dedup. The voice routes were rewritten in the correct no-echo format and re-enabled on 2026-10-04 alongside the TTL mangle rule for `239.255.255.0/24`.

---

### Bandwidth Considerations

Voice differs from CoT in that it produces a **continuous UDP stream** (~64kbps per active PTT) rather than small bursty updates. On an 802.11s HT20 link this is negligible bandwidth, but it means more sustained multicast frames on the channel. Since RTS/CTS does not protect multicast traffic (only unicast), voice frames can still collide with other transmissions. With RTS/CTS enabled for unicast (via `MESH_RTS_THRESHOLD` in `mesh.conf`) and the multicast storm fix in place, this should be manageable. Monitor wlan1 TX queue stats after enabling voice to verify.

---

### Troubleshooting

**Contacts don't appear in voice plugin:**
- Verify discovery traffic (239.255.255.2) is being routed: check `smcroutectl show` for the group
- Check UFW allows 239.255.255.2 on both interfaces
- Verify the TTL mangle rule exists: `sudo iptables -t mangle -L PREROUTING -n`
- If no mangle rule for `239.255.255.0/24`, voice packets are dying at TTL=1 before entering the mesh

**Garbled or continuous audio after pressing PTT:**
- Check smcroute config — routes from wlan1 must only output to br-lan, not back to wlan1
- If the echo is present, you will see exponential packet amplification on `ip -s link show wlan1`

**Voice traffic not crossing mesh:**
- Verify traffic leaves the local node: `sudo tcpdump -i wlan1 -n -c 5 'net 239.255.255.0/24'`
- Check the TTL on captured packets — should be 7 (MESH_MCAST_TTL minus 1 for the br-lan → wlan1 forward)
- If TTL=0 or no packets appear, the mangle rule is missing or not matching

**Multicast TX drops accumulating on wlan1:**
- Check with `iw dev wlan1 info` or `ip -s link show wlan1`
- If drops are climbing rapidly, check for echo routing in smcroute.conf
- Small numbers of drops under heavy load are normal; thousands per minute indicate amplification

**Voice works locally but not across multiple hops:**
- Verify `MESH_802_TTL` is set in `mesh.conf` and applied (check `iw dev wlan1 get mesh_param mesh_ttl`)
- Verify `mesh_fwding=1` is active (required for 802.11s to forward frames between mesh points)
- All nodes must have the voice routes in smcroute.conf — if even one node is missing them, voice from that node's local devices won't enter the mesh

---

### Files Involved

| File | Role |
|---|---|
| `/etc/smcroute.conf` | Voice multicast routes (enabled, no-echo bridging) |
| `/etc/nucleus/mesh.conf` | `MESH_MCAST_TTL` variable used for the TTL mangle rule |
| `/opt/nucleus/bin/mesh-start.sh` | Applies TTL mangle rules at boot |
| `/etc/ufw/` | Firewall rules for voice multicast groups |

---

## Video Plugin (OpenTAK ICU)

### OpenTAK ICU Plugin Settings

**Stream Settings:**
- **Stream Protocol:** RTSP
- **Stream Address:** 10.20.xx.1 (br-lan IP of node running MediaMTX)
- **Stream Port:** 8554
- **Stream Path:** mystream (configurable, docs assume this path)
- **TCP:** ON

**Video Preferences:**
- **Video Source:** This device's camera
- **Resolution:** 800x600 (configurable)
- **Bitrate:** 1000
- **Adaptive Bitrate:** ON
- **FPS:** 24 (configurable)
- **Codec:** H264

**Audio Settings:**
- **Enable Audio:** ON
- **Bitrate:** 128
- **Sample Rate:** 44100
- **Codec:** AAC
- **Stereo, Echo Canceller, Noise Suppressor:** ON

### TAKServer Feed Settings (Video Tab)
- **Protocol:** RTSP
- **Address:** `<MediaMTX-IP>`
- **Port:** 8554
- **Path:** `mystream` (no leading /)
- **Auth:** Leave blank if no auth required
- **Secure:** Off

### Notes
- Do not prefix path with `/` in TAKServer
- Enable AAC audio in OpenTAK ICU
- Force TCP in MediaMTX to avoid UDP/NAT issues
- Test with: `ffplay rtsp://<MediaMTX-IP>:8554/mystream`
- Workflow: OpenTAK ICU → RTSP → MediaMTX → TAKServer → ATAK Clients
