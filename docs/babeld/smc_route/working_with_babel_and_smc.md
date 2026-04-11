# Working with Babeld and SMCRoute

## Configuration Overview

**Babeld** handles Layer 3 routing - discovers mesh topology and installs routes to reach different IP networks across the mesh.

**SMCRoute** handles multicast routing - forwards multicast packets (like ATAK traffic) between interfaces since multicast doesn't route like normal IP traffic.

---

## Optimizations

### Diversity Routing

**What It Does:**
Enables multi-path routing - uses multiple routes simultaneously to the same destination instead of picking only the best path.

**Configuration:**
```conf
interface wlan1 type wireless link-quality true split-horizon false rxcost 256 hello-interval 4 update-interval 16 diversity true diversity-factor 256
```

**How It Works:**
- Babeld calculates cost for all routes to each destination
- Without diversity: uses only lowest-cost route
- With diversity: uses all routes within `diversity-factor` cost units of best route
- Traffic load-balanced across qualifying paths (per-packet round-robin)

**Example:**
```
Routes to Node D from Node A:
- Via Node B: cost 352
- Via Node C: cost 360
Difference: 8 (less than factor 256)
Result: Both paths used simultaneously
```

**Benefits:**
- Instant failover - alternate path already active if primary fails
- Load distribution across multiple next-hops
- Better resilience in dense mesh topologies

**Trade-offs:**
- Packet reordering (different paths = different delays)
- Slight TCP performance impact from out-of-order delivery
- More complex troubleshooting (traffic split across paths)
- Only helps when multiple viable paths exist

**When To Use:**
- Dense mesh with multiple neighbors providing alternate routes
- Scenarios requiring high availability
- Not critical for simple linear/tree topologies

---

## Adding IP Ranges in Babeld

### Why Add IP Ranges:
- New subnet for guest devices (e.g., 10.20.20.0/24)
- VLAN for specific services
- Additional bridge interface

### Configuration Steps:

1. **Add redistribute rule in `/etc/babeld.conf`**
   ```conf
   # Existing rules
   redistribute ip 10.20.1.0/24 allow
   redistribute ip 10.20.12.0/24 allow
   
   # New subnet
   redistribute ip 10.20.20.0/24 allow
   
   # Keep deny rules at end
   redistribute local deny
   redistribute deny
   ```

2. **Rule Order Matters:**
   - Allow rules must come BEFORE deny rules
   - Babeld processes rules top-to-bottom
   - First match wins

3. **Verify:**
   ```bash
   # Check if route is announced
   telnet localhost 33123
   # Type: dump
   # Look for your new subnet in the output
   ```

### What Gets Announced:
Only the network range (e.g., 10.20.20.0/24) - not individual host IPs within that range. Other nodes learn "this node can reach 10.20.20.0/24" and route accordingly.

---

## Adding Multicast Groups in SMCRoute

### Why Add Multicast Groups:
- New service using multicast (Mumble, custom apps)
- Additional ATAK voice channels
- Video streaming services

### Configuration Pattern:

Each multicast group needs 4 lines:

```conf
# Service Name - Multicast Address
mgroup from wlan1 group <MULTICAST_IP>
mgroup from br-lan group <MULTICAST_IP>
mroute from wlan1 group <MULTICAST_IP> to br-lan
mroute from br-lan group <MULTICAST_IP> to wlan1
```

**Line Breakdown:**
1. `mgroup from wlan1` - Listen for this multicast on mesh interface
2. `mgroup from br-lan` - Listen for this multicast on local bridge
3. `mroute from wlan1 ... to br-lan` - Forward mesh traffic to local bridge (deliver to local ATAK devices)
4. `mroute from br-lan ... to wlan1` - Forward local traffic to mesh (inject into 802.11s)

**Important:** Routes from wlan1 must only output to br-lan, NOT back to wlan1. Including wlan1 in the output creates echo routing that bypasses 802.11s deduplication, causing exponential multicast amplification at 3+ nodes. Multi-hop is handled natively by 802.11s at Layer 2. See: `docs/congestion_collision_tuning/mcast_storm_correction.md`

### Example: Adding Mumble Server

Mumble uses multicast for discovery (default: 239.255.0.1)

```conf
# Mumble Server Discovery
mgroup from wlan1 group 239.255.0.1
mgroup from br-lan group 239.255.0.1
mroute from wlan1 group 239.255.0.1 to br-lan
mroute from br-lan group 239.255.0.1 to wlan1
```

### Example: Adding ATAK Voice Channel 2

```conf
# ATAK Voice - channel_2
mgroup from wlan1 group 239.255.255.13
mgroup from br-lan group 239.255.255.13
mroute from wlan1 group 239.255.255.13 to br-lan
mroute from br-lan group 239.255.255.13 to wlan1
```

**Note:** ATAK voice channels use sequential IPs (239.255.255.12, 239.255.255.13, 239.255.255.14, etc.)

### Multicast Address Ranges:

- **224.0.0.0 - 224.0.0.255**: Reserved (link-local, don't route)
- **224.0.1.0 - 238.255.255.255**: Global multicast
- **239.0.0.0 - 239.255.255.255**: Organization-local (use these)

**Best Practice:** Use 239.x.x.x range for custom services to avoid conflicts.

---

## Verification Commands

### Babeld Status:
```bash
# Connect to babeld management port
telnet localhost 33123

# Commands once connected:
dump         # Show all routes
interfaces   # Show interface status
quit         # Exit
```

### SMCRoute Status:
```bash
# Show active multicast routes
sudo smcroutectl show

# Show multicast group memberships
sudo smcroutectl show groups
```

### Test Multicast:
```bash
# Send test multicast packet
echo "test" | nc -u 239.2.3.1 6969

# Listen for multicast (on another node)
nc -u -l 239.2.3.1 6969
```

---

## Common Scenarios

### Scenario 1: Add Guest WiFi on New Subnet

1. Create new subnet (10.20.30.0/24) on additional interface
2. Add to babeld.conf:
   ```conf
   interface br-guest type wired rxcost 96 hello-interval 4
   redistribute ip 10.20.30.0/24 allow
   ```
3. Guest devices can now reach mesh nodes and vice versa

### Scenario 2: Add Custom Multicast Application

Application uses multicast group 239.100.1.1 on port 5000

1. Add to smcroute.conf:
   ```conf
   # Custom App
   mgroup from wlan1 group 239.100.1.1
   mgroup from br-lan group 239.100.1.1
   mroute from wlan1 group 239.100.1.1 to br-lan
   mroute from br-lan group 239.100.1.1 to wlan1
   ```
2. App's multicast traffic now bridges mesh and local network

### Scenario 3: Isolate Traffic (Don't Route Subnet)

Want local-only subnet that doesn't propagate to mesh:

1. Create subnet (10.20.99.0/24) on interface
2. **Don't add to babeld.conf** - no redistribute rule
3. Traffic stays local, not announced to mesh

---

## Troubleshooting

### Route Not Appearing:
- Check babeld service: `systemctl status babeld`
- Verify rule order (allow before deny)
- Check interface has IP in that subnet
- Use `telnet localhost 33123` → `dump` to see what babeld knows

### Multicast Not Working:
- Verify smcroute running: `systemctl status smcroute`
- Check groups: `sudo smcroutectl show groups`
- Ensure both interfaces in routing rules
- Test with `nc` multicast send/receive
- Check firewall isn't blocking multicast

### Performance Issues After Adding Diversity:
- Monitor for packet reordering (check TCP retransmits)
- Reduce diversity-factor to be more selective
- May not be needed if topology is simple
- Test with/without to compare

---

## Quick Reference

### Babeld Rule Order:
```conf
# 1. Interface definitions
interface <name> type <wired|wireless> [options]

# 2. Allow rules (specific networks)
redistribute ip <network> allow

# 3. Deny rules (blocklist)
redistribute local deny

# 4. Default deny (catch-all)
redistribute deny
```

### SMCRoute Pattern:
```conf
# For each multicast group (no echo — 802.11s handles multi-hop):
mgroup from wlan1 group <IP>
mgroup from br-lan group <IP>
mroute from wlan1 group <IP> to br-lan
mroute from br-lan group <IP> to wlan1
```
