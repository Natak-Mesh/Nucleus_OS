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

## What We Learned (Updated)

1. **OpenDHT multicast discovery (`-D` flag):**
   - Uses IPv6 link-local addresses (fe80::)
   - Works automatically across mesh without smcroute configuration
   - Nodes discover each other on wlan1 mesh interface

2. **Jami Android requires DHT PROXY, not direct DHT:**
   - Mobile apps use HTTP-based DHT proxy (TCP port 8000) to save battery
   - Direct DHT mode (UDP 4222) does NOT work with Jami Android
   - Must run: `dhtnode -p 4222 -D -s --proxyserver 8000`

3. **Network topology:**
   - Phones connect to br-lan (e.g., 10.20.12.x on node 12)
   - Phones must use br-lan gateway IP for DHT proxy (10.20.12.1:8000)
   - Mesh IPs (10.20.1.x) may not be directly routable from phones

4. **Jami configuration:**
   - Setting: "DHT Proxy" (NOT "Bootstrap")
   - Format: `10.20.12.1:8000` (hostname:port, not HTTP URL)
   - Disable "Use DHT proxy list" (default internet proxies)

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

## Current Status (2025-12-29)

### What Works
- ✅ Docker containers running on both nodes with DHT proxy enabled
- ✅ Phones successfully connecting to local DHT proxy (port 8000)
- ✅ Bootstrap between nodes works - DHT traffic flowing
- ✅ Network isolation with `-n 12345` prevents connection to public DHT
- ✅ Containers auto-start on boot with `--restart=unless-stopped`
- ✅ **Offline mode verified working** - Jami calls work without internet connection

### Resolved Issues
1. **Multicast discovery (`-D` flag) not working automatically**
   - Solution: Added `-b` bootstrap flag to docker command
   - Each node bootstraps to the other node's mesh IP at startup
   - Nodes now connect automatically without manual intervention

2. **DHT nodes not connecting**
   - Verified: Proxies are operational and nodes communicate
   - Both proxies show `"good":1` - nodes are connected
   - Verified with `curl http://10.20.1.11:8000/` and `curl http://10.20.1.12:8000/`

### All Systems Operational ✅

**Testing Complete (2025-12-29):**
- Offline functionality verified working
- Voice/video calls work without internet connection
- Local DHT is functioning correctly
- Auto-start verified after reboot

### Working Configuration ✅

**Docker command for Node 12:**
```bash
sudo docker run -d --network host --restart=unless-stopped --name dhttest \
  ghcr.io/savoirfairelinux/opendht/opendht-alpine \
  dhtnode -p 4222 -D -s --proxyserver 8000 -n 12345 -b 10.20.1.11:4222
```

**Docker command for Node 11:**
```bash
sudo docker run -d --network host --restart=unless-stopped --name dhttest \
  ghcr.io/savoirfairelinux/opendht/opendht-alpine \
  dhtnode -p 4222 -D -s --proxyserver 8000 -n 12345 -b 10.20.1.12:4222
```

**Key Points:**
- `--restart=unless-stopped` ensures container auto-starts on boot
- Each node bootstraps to the other node's mesh IP (10.20.1.x)
- Network ID `-n 12345` isolates from public DHT
- Port 4222 (DHT) and 8000 (proxy) are exposed via `--network host`

**Jami Android settings:**
- **Bootstrap:** `10.20.XX.1:4222` (local node's br-lan IP)
- **Use DHT proxy:** Enabled
- **DHT Proxy Address:** `10.20.XX.1:8000` (local node's br-lan IP, NO http:// prefix)
- **Enable local peer discovery:** Enabled
- **Use DHT proxy list:** Disabled
- **UPnP:** Disabled
- **TURN server:** Empty/Clear
- **Name server:** Empty/Clear

Where XX = node number (11 or 12). Each phone uses its connected node's br-lan gateway IP.

### Completed Implementation ✅
1. ✅ Document working configuration with bootstrap addresses
2. ✅ Test offline mode - verified Jami calls work without internet
3. ✅ Verified containers auto-start on boot

### Future Enhancements
1. Test roaming between nodes (phone moving from node 11 to node 12)
2. Deploy to additional mesh nodes with proper bootstrap topology
3. Monitor DHT health and performance under load
4. Consider implementing DHT monitoring dashboard

---

## References

- **OpenDHT Documentation:** https://github.com/savoirfairelinux/opendht/wiki/Running-a-node-with-dhtnode
- **Docker Image:** https://github.com/savoirfairelinux/opendht/pkgs/container/opendht%2Fopendht-alpine
- **Jami Documentation:** https://jami.net/
