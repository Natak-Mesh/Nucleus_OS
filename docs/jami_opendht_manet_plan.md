# Jami on Disconnected MANET - OpenDHT Implementation Plan

## Overview
This document outlines the plan for running Jami voice/video communication on a disconnected MANET (Mobile Ad-hoc Network) using OpenDHT as the distributed hash table backbone.

## The Problem
Jami requires a Distributed Hash Table (DHT) for:
- Account/contact discovery
- Peer-to-peer connection establishment
- Distributed identity management

By default, Jami uses public internet bootstrap servers (`bootstrap.jami.net`), which won't work on a disconnected MANET.

## The Solution
Run local OpenDHT nodes on mesh network nodes using Docker with **multicast peer discovery** enabled, eliminating the need for external bootstrap servers.

---

## Technical Components

### Docker Image
**Image:** `ghcr.io/savoirfairelinux/opendht/opendht-alpine`

**Source:** OpenDHT official documentation (https://github.com/savoirfairelinux/opendht/wiki)

### Network Requirements
- **Port:** 4222/UDP (OpenDHT standard port)
- **Multicast:** Enabled via `-D` flag (specific multicast group/port not documented)
- **Network Mode:** `--network host` (required for multicast to function)

### Key Features Used
- **`-D` flag:** Enables automatic local peer discovery via multicast
- **`-p 4222`:** Binds to standard DHT port
- **`-s` flag:** Runs in service mode (non-forking daemon)

---

## Architecture

### Deployment Model: Run on Every Node
**Decision:** Install and run OpenDHT node on every mesh network node (not just one central node)

**Rationale:**
- **No single point of failure:** If one node goes offline or out of range, DHT remains functional
- **Distributed by design:** DHT merges data across all nodes automatically
- **Network partitions heal:** When isolated mesh segments reconnect, DHT resyncs automatically
- **Reduced latency:** Local nodes provide faster DHT queries for nearby Jami clients

### How It Works
1. **Bootstrap Phase:**
   - Each OpenDHT node starts with `-D` (multicast discovery) enabled
   - Nodes discover each other on the local network via multicast
   - No external bootstrap server needed

2. **DHT Formation:**
   - Discovered nodes connect and form a distributed hash table
   - Routing tables synchronize across all nodes
   - DHT stores identity and routing data redundantly

3. **Jami Integration:**
   - Jami clients on each device connect to localhost:4222 (or any nearby node IP)
   - Jami publishes account info to DHT
   - Jami queries DHT to find contacts and establish peer connections

4. **Voice/Video Communication:**
   - Once peers discover each other via DHT, Jami establishes direct RTP connections
   - Audio/video traffic flows peer-to-peer over mesh network
   - No TURN server needed (all nodes on same LAN segment)

---

## Will This Actually Work Offline?

### YES - With Prerequisites

**Why it works:**
- The `-D` multicast discovery flag is specifically designed for local network operation
- OpenDHT documentation explicitly supports running without internet bootstrap servers
- DHT is a decentralized system - no central authority required
- Jami is designed to work with custom DHT infrastructure

**Critical Prerequisites:**
1. **Docker images must be pre-loaded** while internet is available
   - Pull `ghcr.io/savoirfairelinux/opendht/opendht-alpine` on all nodes before going offline
   - Save image: `docker save` and distribute if needed
   
2. **Multicast must function on mesh network**
   - Verify multicast routing works on your babel/wlan0 setup
   - Firewall must allow multicast traffic
   
3. **All nodes must be on same network segment**
   - Multicast discovery works within broadcast domain
   - May need multicast routing configuration if mesh has multiple subnets

---

## What I Don't Know (Gaps in Documentation)

1. **Multicast Group/Port:** The `-D` flag documentation doesn't specify which multicast group address or port OpenDHT uses
   - May need to inspect OpenDHT source code or packet capture to determine
   - Important for firewall rules and multicast routing config

2. **Jami Client Configuration:** 
   - Exact method to configure Jami to use local DHT nodes instead of default bootstrap servers
   - Whether Jami has its own multicast discovery or requires manual bootstrap node list

3. **Performance/Scaling:**
   - How many DHT nodes are optimal for a small MANET?
   - DHT overhead on limited bandwidth mesh links

---

## High-Level Implementation Steps

### Phase 1: Infrastructure Setup (While Online)
1. Install Docker on all mesh nodes
2. Pull OpenDHT image on all nodes
3. Create systemd service for auto-start
4. Configure firewall rules for port 4222/UDP and multicast

### Phase 2: Testing & Validation
1. Start DHT nodes on multiple mesh nodes
2. Verify multicast peer discovery works
3. Verify DHT network forms correctly
4. Test DHT queries between nodes

### Phase 3: Jami Integration
1. Install Jami on test devices
2. Configure Jami to use local DHT nodes
3. Create test accounts
4. Test account discovery between Jami clients
5. Test voice/video calls

### Phase 4: Production Deployment
1. Deploy to all mesh nodes
2. Document Jami client setup procedure for end users
3. Monitor DHT health and connectivity

---

## References

- **OpenDHT Documentation:** https://github.com/savoirfairelinux/opendht/wiki/Running-a-node-with-dhtnode
- **Docker Image:** https://github.com/savoirfairelinux/opendht/pkgs/container/opendht%2Fopendht-alpine
- **Jami Documentation:** https://jami.net/
