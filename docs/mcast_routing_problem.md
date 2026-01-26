# Multicast Routing Problem - smcroute VIF Registration

## Problem

Node 2 could receive ATAK multicast (SA/CoT) from Node 3, but not from Node 4, even though:
- All nodes were mesh-connected (Babel routing working)
- Multicast packets from Node 4 were reaching Node 2's Pi (visible in tcpdump on wlan1)
- Node 4 could receive multicast from all other nodes

## Initial Diagnosis (Incorrect)

First hypothesis was subnet mismatch - Node 4's EUD used 10.20.4.22, while Nodes 2 and 3 used 10.20.1.x. However, this was by design - each node uses a separate br-lan subnet (10.20.2.x, 10.20.3.x, 10.20.4.x), and Babel correctly advertises these routes.

## Root Cause

**smcroute failed to register wlan1 in the kernel's multicast VIF (Virtual Interface) table on Node 2.**

Symptoms:
- `smcroutectl show` displayed template rules correctly
- `cat /proc/net/ip_mr_vif` showed wlan1 was **missing** (only eth0, wlan0, br-lan, tailscale0 present)
- smcroute logs showed "wrong VIF" errors for echo traffic

Why it happened:
- Node 2 had a hardware failure and the SD card was moved to a new Pi
- The new Pi boots faster, causing smcroute to start before mesh-start.sh completes wlan1 configuration
- wlan1 was in `state DORMANT` / `NO-CARRIER` when smcroute initialized
- smcroute couldn't register wlan1 in the kernel's multicast routing table

## Diagnosis Steps

1. **tcpdump on Node 4** - confirmed smcroute was working correctly:
   ```bash
   sudo tcpdump -n -i any host 239.2.3.1 or host 224.10.10.1
   ```
   Showed multicast arriving on wlan1 and being forwarded to br-lan ✓

2. **tcpdump on Node 2** - showed packets arriving but NOT being forwarded:
   ```
   wlan1 M   IP 10.20.4.21 > 239.2.3.1   ← arrives from mesh
   (no br-lan forwarding)                 ✗
   ```

3. **Check smcroute status**:
   ```bash
   systemctl status smcroute  # running, but errors in logs
   sudo smcroutectl show       # template rules present
   cat /proc/net/ip_mr_vif     # wlan1 MISSING!
   ```

## Solution

**Temporary fix (immediate):**
```bash
sudo systemctl restart smcroute
```

After restart, `/proc/net/ip_mr_vif` showed wlan1 registered, and multicast forwarding worked.

**Permanent fix (choose one):**

### Option A: Add smcroute restart to mesh-start.sh
Add at the end of `/opt/nucleus/bin/mesh-start.sh`:
```bash
# Restart smcroute to ensure wlan1 is registered in VIF table
systemctl restart smcroute
```

### Option B: Make smcroute depend on mesh-start (systemd)
```bash
sudo mkdir -p /etc/systemd/system/smcroute.service.d/
sudo tee /etc/systemd/system/smcroute.service.d/override.conf << 'EOF'
[Unit]
After=mesh-start.service
Wants=mesh-start.service
EOF
sudo systemctl daemon-reload
```

**Recommended:** Option A (simpler and more reliable)

## Verification

After fix, tcpdump on Node 2 shows correct forwarding:
```
wlan1 M   IP 10.20.4.21 > 239.2.3.1      ← arrives from mesh
br-lan Out IP 10.20.4.21 > 239.2.3.1    ← forwarded to EUD ✓
```

## Key Takeaways

- smcroute must start **after** mesh-start.sh configures wlan1
- Hardware changes (SD card swap to faster Pi) can alter boot timing
- The kernel VIF table (`/proc/net/ip_mr_vif`) is the authoritative source for multicast routing state
- smcroute template rules alone don't guarantee multicast routing works - interfaces must be registered in VIF table

## Related Files

- `/etc/smcroute.conf` - multicast route definitions
- `/opt/nucleus/bin/mesh-start.sh` - mesh interface initialization
- `/proc/net/ip_mr_vif` - kernel multicast VIF table
- `/proc/net/ip_mr_cache` - kernel multicast routing cache
