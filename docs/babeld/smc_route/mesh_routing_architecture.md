# Mesh Routing Architecture - Babeld and SMCRoute Deep Dive

A comprehensive explanation of how packet routing and addressing works in the Natak Mesh network using wlan1 as the primary mesh interface.

---

## Table of Contents

1. [Overview - The Two-Layer Approach](#overview---the-two-layer-approach)
2. [Layer 3: Babeld - Unicast Routing](#layer-3-babeld---unicast-routing)
3. [Layer 2: SMCRoute - Multicast Forwarding](#layer-2-smcroute---multicast-forwarding)
4. [How wlan1 Carries Both Traffic Types](#how-wlan1-carries-both-traffic-types)
5. [Cross-Subnet Routing Without NAT](#cross-subnet-routing-without-nat)
6. [Multicast Multi-hop and Storm Prevention](#multicast-multi-hop-and-storm-prevention)
7. [Layer 2 vs Layer 3 Multi-hop Explained](#layer-2-vs-layer-3-multi-hop-explained)
8. [Internet Gateway Sharing](#internet-gateway-sharing)
9. [Packet Flow Examples](#packet-flow-examples)

---

## Overview - The Two-Layer Approach

The Natak Mesh uses **two complementary routing protocols** that work together on the wlan1 mesh interface:

### Babeld - Layer 3 Unicast Routing
Discovers mesh topology and installs routes to reach different IP subnets across the mesh. Handles point-to-point traffic like SSH, web browsing, and TAKServer connections.

### SMCRoute - Multicast Forwarding
Forwards multicast packets (like ATAK traffic) between interfaces. Required because multicast doesn't route like normal IP traffic - it needs explicit forwarding rules.

**Key Insight:** Both protocols operate over the same wlan1 mesh interface but handle different types of traffic at different network layers.

---

## Layer 3: Babeld - Unicast Routing

### What It Does

Babeld is a distance-vector routing protocol that:
- Discovers mesh neighbors automatically
- Exchanges routing information about reachable IP subnets
- Calculates optimal paths based on link quality and hop count
- Installs routes directly into the Linux kernel routing table
- Provides automatic failover when links fail

### How Packets Are Addressed and Routed

Each node has a unique IP address on wlan1 (e.g., 10.20.1.12/24 from your MESH_IP configuration). Babeld learns:
- **Who my neighbors are** - directly reachable nodes via wlan1
- **What networks each neighbor can reach** - multi-hop path discovery
- **The cost of each path** - based on link quality, hop count, and interface type

When a packet needs to reach another subnet, Babeld has already installed a route in the kernel routing table pointing to the next-hop neighbor's wlan1 IP address.

### Multi-hop Example

```
Node A (10.20.1.10) wants to reach Node C's br-lan (10.20.12.30)
↓
Babeld on Node A knows: "To reach 10.20.12.0/24, send to next-hop 10.20.1.11"
↓
Kernel routes packet to 10.20.1.11 via wlan1
↓
Node B receives packet, forwards based on its babeld route
↓
Node C receives packet on wlan1, delivers to local br-lan
```

### Configuration Points

- `import-table 254` / `export-table 254` - Babeld reads/writes kernel routing table
- `interface wlan1 type wireless` - Monitor wlan1 for mesh neighbors
- `redistribute ip 10.20.1.0/24 allow` - Announce "I can reach the mesh network"
- `redistribute ip 10.20.12.0/24 allow` - Announce "I can reach my local br-lan subnet"

### Addressing

Standard Layer 3 IP routing: source IP, destination IP, next-hop determined by routing table, MAC address resolved via ARP.

---

## Layer 2: SMCRoute - Multicast Forwarding

### What It Does

SMCRoute (Static Multicast Routing) creates explicit forwarding rules for multicast traffic:
- Joins multicast groups on specified interfaces
- Forwards multicast packets between interfaces
- Enables multi-hop multicast propagation via "echo routing"
- Required because multicast packets don't follow normal routing tables

### How Multicast Packets Are Routed

ATAK and other services use multicast groups (e.g., 239.2.3.1 for CoT data). Without smcroute, these packets would only reach devices on the same local interface. SMCRoute creates rules that say: "When you see multicast group X on interface Y, copy it to interfaces Z."

### Configuration Pattern

Each multicast group requires four lines:
1. `mgroup from wlan1 group <IP>` - Listen for this multicast on mesh interface
2. `mgroup from br-lan group <IP>` - Listen for this multicast on local bridge
3. `mroute from wlan1 group <IP> to wlan1 br-lan` - Forward mesh → mesh + local (echo routing)
4. `mroute from br-lan group <IP> to wlan1` - Forward local → mesh only

### Critical Concept: Echo Routing

The key to multi-hop multicast is **echo routing** - the line `to wlan1 br-lan` includes wlan1 itself. This means:
- Packets received on wlan1 are forwarded to local br-lan (so local devices get them)
- Packets are ALSO forwarded back out wlan1 (so they propagate to the next hop)

Without echo routing, multicast would only work one hop. With echo routing, packets propagate across the entire mesh.

### Addressing

Multicast addressing: source IP, destination multicast group IP (239.x.x.x range), multicast MAC address. All nodes on the mesh receive the multicast frame.

---

## How wlan1 Carries Both Traffic Types

The wlan1 mesh interface simultaneously carries **two types of traffic**:

### Type 1: Unicast (Babeld-managed)
- Normal TCP/IP traffic between specific IPs
- Examples: SSH, web browsing, TAKServer connections, file transfers
- Addressed: Source IP → Destination IP
- Routed: Via Babeld's learned routes through next-hop neighbors

### Type 2: Multicast (SMCRoute-managed)
- One-to-many broadcast to multicast group
- Examples: ATAK CoT, ATAK discovery, voice (when enabled)
- Addressed: Source IP → Multicast Group (239.x.x.x)
- Routed: Via SMCRoute's explicit forwarding rules with echo routing

Both types coexist peacefully because they use different addressing schemes (unicast vs multicast IP addresses) and different forwarding mechanisms (routing table vs multicast routes).

---

## Cross-Subnet Routing Without NAT

### The Question: Can Babeld Route Between Different Subnets Without NAT?

**Yes, absolutely.** Babeld provides true Layer 3 routing between non-overlapping subnets with no NAT required.

### Traditional Router Problem

Normally, if Node A is on 10.20.1.0/24 and Node B is on 10.20.2.0/24, they need a router with NAT or a gateway device between them to communicate.

### Babeld Solution

- Each node announces "I can reach subnet X" to all neighbors
- Babeld installs **direct kernel routes** pointing to next-hop mesh IPs
- Packets flow end-to-end with **original source/destination IPs intact** (no translation)

### How It Works

```
Node A: 10.20.1.10/24 (mesh) + 10.20.12.1/24 (br-lan)
Node C: 10.20.1.30/24 (mesh) + 10.20.12.3/24 (br-lan)

Device on Node A's br-lan (10.20.12.50) pings device on Node C's br-lan (10.20.12.100)
↓
Node A's routing table (installed by Babeld): 10.20.12.0/24 via 10.20.1.30 dev wlan1
↓
Packet sent with:
  Source IP: 10.20.12.50 (original)
  Dest IP: 10.20.12.100 (original)
  Next-hop: 10.20.1.30 (Node C's wlan1)
↓
Node C receives packet, sees destination is its br-lan subnet, delivers it locally
↓
Reply comes back the same way (reversed path)
```

### Why No NAT Is Needed

- All subnets are **non-overlapping** (10.20.1.0/24, 10.20.12.0/24, etc.)
- Babeld creates **symmetric routing** - both directions know how to reach each other
- It's true Layer 3 routing, just like a traditional router, but distributed across all mesh nodes
- Each node acts as both an endpoint and a router simultaneously

---

## Multicast Multi-hop and Storm Prevention

### How Multi-hop Works for Multicast

Echo routing enables multi-hop multicast propagation:

```
Node A (sender) → Node B (relay) → Node C (receiver)

Node A: ATAK sends multicast 239.2.3.1
  ↓ (transmitted on wlan1 mesh)
Node B: Receives on wlan1
  ↓ (SMCRoute rule: wlan1 → wlan1 + br-lan)
  ├─→ br-lan (local devices receive it)
  └─→ wlan1 (re-transmit to mesh for further propagation)
        ↓
Node C: Receives on wlan1
  ↓ (SMCRoute rule: wlan1 → wlan1 + br-lan)
  ├─→ br-lan (local devices receive it) ✓ Multi-hop success!
  └─→ wlan1 (continues propagating...)
```

### The Storm Problem

Without proper controls, echo routing creates infinite loops:

```
Node A ─→ Node B ─→ Node C
  ↑                    ↓
  └────────────────────┘
(packets loop forever = broadcast storm)
```

### Storm Prevention: TTL (Time To Live)

The Linux kernel's TTL mechanism prevents storms:
- Every time a multicast packet is forwarded (including echo), the kernel **decrements the TTL**
- When TTL reaches 0, the packet is dropped
- Even if a packet loops back to the same node, TTL ensures it dies after a limited number of hops

### TTL in Practice

**ATAK CoT (239.2.3.1) - Works Well:**
- ATAK sends CoT with TTL=1-2 by default
- Even with echo routing, packets die quickly after 1-2 propagations
- No storm risk because TTL is already very low

**ATAK Voice (239.255.255.x) - Caused Problems (Now Disabled):**
- Voice had TTL=64 (set via iptables mangle rule for multi-hop capability)
- Echo routing + high TTL = packets could loop 32+ times before dying
- This caused catastrophic channel saturation: 646K dropped packets, 6-8 second latency
- **Solution:** Reduce TTL to 4-8 hops max OR disable voice multicast routing

### Example TTL Countdown

```
Node A sends with TTL=4
  ↓
Node B receives (TTL=3), forwards to wlan1+br-lan
  ↓
Node C receives (TTL=2), forwards to wlan1+br-lan
  ↓
Node B receives again (TTL=1), forwards to wlan1+br-lan
  ↓
Node A receives again (TTL=0, DROPPED - loop prevented)
```

Even though the packet looped back, TTL killed it after 4 total hops, preventing a storm.

---

## Layer 2 vs Layer 3 Multi-hop Explained

### The Confusion: Who Actually Does Multi-hop?

Both 802.11s mesh (Layer 2) and Babeld (Layer 3) perform multi-hop forwarding, but **at different layers**. They work together to create end-to-end connectivity.

### Layer 2: 802.11s Mesh - MAC Frame Forwarding

**What it does:**
- Forms wireless peer relationships between directly adjacent nodes
- Uses Hybrid Wireless Mesh Protocol (HWMP) for path selection at Layer 2
- Forwards **Ethernet frames** based on MAC addresses
- Handles the actual RF transmission between wireless neighbors
- Operates below the IP layer - doesn't understand IP addresses or subnets

**How Layer 2 multi-hop works:**

```
Node A wants to send frame to Node C's MAC address

802.11s builds mesh path: Node A ↔ Node B ↔ Node C (peer links)

Frame forwarding:
  [Frame: Src MAC=A, Dst MAC=C, Payload=IP packet]
  ↓
  Node A transmits frame to Node B (direct wireless peer)
  ↓
  Node B sees Dst MAC=C (not local), forwards frame to Node C wirelessly
  ↓
  Node C receives frame (Dst MAC matches)
```

**Key point:** 802.11s operates on **MAC addresses** and creates a wireless multi-hop Layer 2 network. It's like a wireless Ethernet switch that spans multiple hops.

### Layer 3: Babeld - IP Packet Routing

**What it does:**
- Exchanges routing information about IP subnets
- Calculates best paths based on link quality and hop count
- Installs routes in kernel routing table
- Determines which **next-hop IP address** to send packets to
- Operates above the MAC layer - uses 802.11s as transport

**How Layer 3 multi-hop works:**

```
Node A wants to send IP packet to Node C (10.20.1.30)

Babeld's job:
  - Discovered Node B (10.20.1.20) can reach Node C
  - Installed route: "10.20.1.30/32 via 10.20.1.20 dev wlan1"

Kernel routing:
  - Lookup destination 10.20.1.30 in routing table
  - Route says next-hop is 10.20.1.20
  - ARP to find MAC address of 10.20.1.20
  - Send frame with Dst MAC=B, but IP packet inside has Dst IP=C
```

**Key point:** Babeld operates on **IP addresses/subnets** and tells the kernel which neighbor to forward to. It relies on 802.11s to actually deliver the frames wirelessly.

### How They Work Together - The Complete Stack

```
APPLICATION LAYER:    [SSH from 10.20.1.10 → 10.20.1.30]
                                ↓
LAYER 3 (Babeld):     "Route to 10.20.1.30 via next-hop 10.20.1.20"
                                ↓
KERNEL ROUTING:       "Send packet to 10.20.1.20 on wlan1"
                                ↓
ARP:                  "MAC address of 10.20.1.20 is AA:BB:CC:DD:EE:FF"
                                ↓
LAYER 2 (802.11s):    "Forward frame to MAC AA:BB:CC:DD:EE:FF"
                                ↓
PHYSICAL LAYER:       [RF transmission to Node B]
                                ↓
                      [Node B receives frame]
                                ↓
LAYER 2 (802.11s):    "Frame is for me (MAC matches), pass to IP layer"
                                ↓
LAYER 3 (Babeld):     "IP dest=10.20.1.30, lookup route, forward to next-hop 10.20.1.30"
                                ↓
LAYER 2 (802.11s):    "Forward frame to Node C's MAC"
                                ↓
                      [Node C receives frame]
                                ↓
APPLICATION LAYER:    [SSH daemon on Node C receives packet]
```

### Analogy: Roads vs GPS Navigation

Think of it like driving between cities:

**802.11s mesh = The roads**
- Provides the physical paths between towns (nodes)
- You can drive from Town A → Town B → Town C
- Roads connect neighboring towns directly
- Without roads, you can't get anywhere

**Babeld = GPS navigation**
- Tells you which route to take to reach your destination
- GPS says "To reach Town C, first drive to Town B, then to Town C"
- Calculates the best route based on traffic and road quality
- But you still drive on the actual roads (802.11s provides the transport)

### Concrete Example: 3-Node Chain

```
Node A (10.20.1.10) ↔ Node B (10.20.1.20) ↔ Node C (10.20.1.30)
```

**Ping from Node A to Node C:**

**Babeld's contribution:**
- Node A's routing table: `10.20.1.30/32 via 10.20.1.20 dev wlan1`
- Node B's routing table: `10.20.1.30/32 via 10.20.1.30 dev wlan1` (direct)
- Babeld determined the IP-level path: A → B → C

**802.11s's contribution:**
- Node A has mesh peer link to Node B at MAC layer
- Node B has mesh peer link to Node C at MAC layer
- When Node A sends frame destined for Node B's MAC, 802.11s delivers it wirelessly
- When Node B forwards frame destined for Node C's MAC, 802.11s delivers it wirelessly

**Both are doing multi-hop:**
- **802.11s multi-hop:** Forwarding wireless frames between mesh peers (Layer 2)
- **Babeld multi-hop:** Routing IP packets through intermediate nodes (Layer 3)
- **They work together:** Babeld decides the IP path, 802.11s provides the wireless transport

---

## Internet Gateway Sharing

### The Scenario: Mesh-Wide Internet Access

When you plug a node into a router via eth0, can Babeld provide internet access to all devices on the mesh?

**Answer: Yes, but you need to configure Babeld to redistribute the default route.**

### Current Configuration Gap

Your babeld.conf currently redistributes specific subnets:
- `redistribute ip 10.20.1.0/24 allow` - Mesh network
- `redistribute ip 10.20.12.0/24 allow` - Local br-lan network

**What's missing:** No rule to redistribute the **default route (0.0.0.0/0)** that gets installed when eth0 receives DHCP from a router.

### What Happens When You Plug Into a Router

**Without default route redistribution:**
1. eth0 gets DHCP (e.g., 192.168.1.100/24) and default gateway
2. Kernel installs default route: `0.0.0.0/0 via 192.168.1.1 dev eth0`
3. IPv4Forwarding=yes means this node CAN forward traffic to internet
4. But Babeld doesn't announce the route - other nodes don't know it exists
5. **Result:** Only the connected node has internet, rest of mesh doesn't

**With default route redistribution:**
1. Same as above - eth0 gets DHCP and default route
2. Babeld announces: "I have a route to 0.0.0.0/0 (internet)"
3. Other nodes learn route and install: `0.0.0.0/0 via 10.20.1.10 dev wlan1`
4. **Result:** Entire mesh uses connected node as internet gateway ✓

### The Fix

Add this line to babeld.conf **before** the deny rules:

```conf
redistribute ip 0.0.0.0/0 allow
```

This tells Babeld: "If I have a default route, announce it to the mesh."

### How Gateway Sharing Works

**Node A (Gateway) plugs into router:**
- eth0: 192.168.1.100/24 (DHCP from router)
- wlan1: 10.20.1.10/24 (mesh)
- Kernel route: `0.0.0.0/0 via 192.168.1.1 dev eth0`
- Babeld sees default route, announces to mesh neighbors

**Node B (2-hop away):**
- Babeld receives announcement from Node A
- Installs route: `0.0.0.0/0 via 10.20.1.10 dev wlan1`
- Any internet traffic now goes to Node A via mesh

**Node C's device (laptop on br-lan):**
- Laptop default gateway: 10.20.12.3 (Node C's br-lan IP)
- Laptop tries to reach 8.8.8.8 (Google DNS)
- Packet goes: Laptop → Node C → Node A (via mesh) → Router → Internet
- Reply returns same path in reverse

### Automatic Features

**Automatic Failover:**
- If Node A unplugs from router, default route disappears
- Babeld automatically withdraws the announcement
- Other nodes remove the route
- If Node B now plugs in, it becomes the new gateway automatically

**Multiple Gateways (Load Balancing):**
- If two nodes both have internet connections:
  - Babeld calculates cost to each gateway
  - Nodes closer to Gateway A use Gateway A
  - Nodes closer to Gateway B use Gateway B
  - Natural load balancing based on mesh topology

**Dynamic Adaptation:**
- No manual configuration needed on any node
- Just plug any node into a router, it becomes a gateway
- Unplug it, gateway role is removed
- Plug a different node in, it takes over

### NAT Requirement

The router connected to eth0 must NAT the mesh traffic. Most home routers do this automatically - they see traffic coming from "192.168.1.100" (your eth0 IP), not the mesh IPs behind it.

### Testing Gateway Sharing

**On the gateway node (plugged into router):**
```bash
# Verify default route exists
ip route | grep default

# Check babeld is announcing it
telnet localhost 33123
dump
# Look for: 0.0.0.0/0 from self
```

**On a remote mesh node:**
```bash
# Verify default route learned via mesh
ip route | grep default
# Should show: default via 10.20.1.X dev wlan1 proto babel

# Test internet connectivity
ping 8.8.8.8
curl http://example.com
```

---

## Packet Flow Examples

### Example 1: SSH from Node A to Node C (Unicast - Babeld)

**Topology:** Node A ↔ Node B ↔ Node C

**Flow:**
1. User on Node A runs: `ssh 10.20.1.30` (Node C's wlan1 IP)
2. Node A checks routing table (populated by Babeld)
3. Route found: `10.20.1.30/32 via 10.20.1.20 dev wlan1` (next-hop = Node B)
4. Packet sent to Node B's MAC address via 802.11s mesh
5. Node B receives packet, checks routing table
6. Route found: `10.20.1.30/32 via 10.20.1.30 dev wlan1` (Node C is direct neighbor)
7. Packet sent to Node C's MAC address via 802.11s mesh
8. Node C receives packet on wlan1, destination IP matches local interface
9. Packet delivered to SSH daemon on Node C
10. Reply packet follows reverse path back to Node A

**Key Technologies:**
- Babeld: Determined IP routing path (A → B → C)
- 802.11s: Provided wireless frame delivery between peers
- Kernel routing: Executed forwarding decisions based on Babeld's installed routes

---

### Example 2: ATAK CoT Multicast from Node A (Multicast - SMCRoute)

**Topology:** Node A ↔ Node B ↔ Node C

**Flow:**
1. ATAK client on Node A's br-lan sends CoT packet to 239.2.3.1 (multicast group)
2. Packet arrives at Node A on br-lan interface
3. SMCRoute rule matches: `mroute from br-lan group 239.2.3.1 to wlan1`
4. Packet forwarded to wlan1 and transmitted as multicast (all mesh peers receive)
5. Node B receives multicast packet on wlan1
6. SMCRoute rule matches: `mroute from wlan1 group 239.2.3.1 to wlan1 br-lan`
7. Packet forwarded to:
   - br-lan (local ATAK clients on Node B receive CoT)
   - wlan1 (echo routing - re-transmit to mesh for multi-hop)
8. Node C receives multicast packet on wlan1 (from Node B's echo)
9. SMCRoute rule matches: `mroute from wlan1 group 239.2.3.1 to wlan1 br-lan`
10. Packet forwarded to:
    - br-lan (local ATAK clients on Node C receive CoT) ✓
    - wlan1 (continues propagating, but TTL will soon expire)

**Key Technologies:**
- SMCRoute: Created multicast forwarding rules between interfaces
- Echo routing: Enabled multi-hop multicast propagation by forwarding wlan1 → wlan1
- TTL: Prevented infinite loops by decrementing on each forward, dropping at 0
- 802.11s: Provided wireless multicast frame broadcast to all mesh peers

---

### Example 3: Device on Node A's br-lan Accesses Internet via Node C's Router (Cross-Subnet + Gateway)

**Topology:** 
- Node A (10.20.1.10 mesh, 10.20.12.1 br-lan) ↔ Node B ↔ Node C (10.20.1.30 mesh, 10.20.12.3 br-lan)
- Node C's eth0 connected to router (192.168.1.100/24)

**Setup:**
- Node C has default route: `0.0.0.0/0 via 192.168.1.1 dev eth0`
- Babeld on Node C announces default route to mesh
- Node A installs route: `0.0.0.0/0 via 10.20.1.30 dev wlan1` (via Node C)

**Flow:**
1. Laptop on Node A's br-lan (10.20.12.50) tries to reach Google DNS (8.8.8.8)
2. Laptop default gateway is 10.20.12.1 (Node A's br-lan IP)
3. Packet arrives at Node A with Src=10.20.12.50, Dst=8.8.8.8
4. Node A checks routing table, finds default route via 10.20.1.30 (Node C)
5. Packet routed through mesh: Node A → Node B → Node C (Babeld + 802.11s)
6. Node C receives packet on wlan1, checks routing table
7. Default route points to router: `0.0.0.0/0 via 192.168.1.1 dev eth0`
8. Packet forwarded to router via eth0 (IPv4Forwarding enabled)
9. Router performs NAT: Src=192.168.1.100 (Node C's eth0), Dst=8.8.8.8
10. Router forwards to internet, receives reply
11. Router performs reverse NAT, sends back to Node C (192.168.1.100)
12. Node C forwards reply back through mesh to Node A
13. Node A forwards reply to laptop on br-lan (10.20.12.50)
14. Laptop receives reply from Google DNS ✓

**Key Technologies:**
- Babeld: Propagated default route across mesh, enabled cross-subnet routing (br-lan to internet)
- 802.11s: Provided wireless multi-hop transport for IP packets
- IPv4Forwarding: Allowed Node C to forward between wlan1 and eth0
- Router NAT: Translated mesh IP addresses to public internet IPs
- No NAT needed between mesh nodes - only at internet gateway

---

## Summary

The Natak Mesh routing architecture uses a sophisticated layered approach:

**Layer 2 (802.11s mesh):** Provides wireless multi-hop frame forwarding based on MAC addresses. Creates a virtual wireless "switch" spanning multiple RF hops.

**Layer 3 (Babeld):** Provides intelligent IP routing based on topology discovery and link quality. Enables cross-subnet communication without NAT and automatic internet gateway sharing.

**Multicast Layer (SMCRoute):** Provides explicit multicast forwarding rules with echo routing for multi-hop propagation. TTL prevents broadcast storms.

All three components work together seamlessly over the wlan1 mesh interface to provide:
- Automatic neighbor discovery and route learning
- Multi-hop connectivity for both unicast and multicast traffic
- Transparent cross-subnet routing
- Dynamic internet gateway sharing with automatic failover
- No manual route configuration required on any node

The result is a truly distributed, self-organizing mesh network that adapts automatically to topology changes, link failures, and internet gateway availability.
