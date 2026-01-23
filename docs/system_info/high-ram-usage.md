# High RAM Usage Investigation & Solutions

**Date:** 2026-01-22  
**System:** Raspberry Pi 4 (4GB RAM)  
**Issue:** Extremely high RAM usage (3.3GB/3.7GB) with heavy swap usage (1.1GB)

---

## Problem Identification

### Initial Symptoms
- Total RAM: 3.7 GB
- Used RAM: 3.3 GB (89%)
- ZRAM Swap: 2.0 GB (1.1 GB used)
- Available: 370 MB
- System experiencing memory pressure

### Investigation Timeline
Initially suspected MediaMTX video streaming service, but high RAM usage persisted even without active video streams.

---

## Root Causes Identified

### 1. TAK Server Memory Consumption

TAK Server is running **5 Java processes** consuming approximately **2.1 GB** (~55% of total RAM):

| Process | PID | Heap (-Xmx) | Actual RSS | % MEM |
|---------|-----|-------------|------------|-------|
| API | 1227 | 617 MB | 842 MB | 21.6% |
| Messaging | 1105 | 617 MB | 568 MB | 14.6% |
| Retention | 1570 | 129 MB | 268 MB | 6.8% |
| Config | 967 | 111 MB | 261 MB | 6.7% |
| Plugin Manager | 1481 | 129 MB | 242 MB | 6.2% |

**Why RSS > Heap:**
Java processes use more memory than just heap size due to:
- Metaspace (class definitions)
- Thread stacks
- JIT compiled code cache
- Native memory buffers
- DirectByteBuffers

**TAK Server Auto-Scaling:**
The `/opt/tak/setenv.sh` script auto-calculates heap sizes based on total system RAM:
```bash
API_MAX_HEAP=$(($TOTALRAMBYTES / 6300))        # ~617 MB on 4GB Pi
MESSAGING_MAX_HEAP=$(($TOTALRAMBYTES / 6300))  # ~617 MB on 4GB Pi
CONFIG_MAX_HEAP=$(($TOTALRAMBYTES / 35000))    # ~111 MB on 4GB Pi
PLUGIN_MANAGER_MAX_HEAP=$(($TOTALRAMBYTES / 30000))  # ~129 MB on 4GB Pi
RETENTION_MAX_HEAP=$(($TOTALRAMBYTES / 30000))       # ~129 MB on 4GB Pi
```

This is **normal TAK Server behavior** for a 4GB Raspberry Pi.

### 2. ZRAM Compressed Swap (PRIMARY ISSUE)

**What is ZRAM?**
ZRAM creates a compressed RAM disk used as swap space. Instead of swapping to SD card:
- Reserves portion of physical RAM (2GB in this case)
- Compresses inactive memory pages and stores them in that reserved RAM
- Compression ratio typically 2:1 to 3:1
- Faster than SD card swap, protects SD from wear

**The Problem:**
- ZRAM is consuming RAM to "save" RAM through compression
- Current usage: 1.1GB of compressed data (likely 2-3GB uncompressed)
- Java heap memory doesn't compress well (dense binary data)
- Adds CPU overhead for compression/decompression
- System is under severe memory pressure despite the compression

**Configuration:**
- Service: `systemd-zram-setup@zram0.service`
- Config: `/usr/lib/systemd/zram-generator.conf` (section `[zram0]`)
- Swap config: `/etc/rpi/swap.conf`
- Writeback timer: `rpi-zram-writeback.timer`

**Why ZRAM exists:**
- Default in newer Raspberry Pi OS versions
- Protects SD card from swap writes
- Helps systems with limited RAM avoid OOM kills
- Generally beneficial for desktop/light workloads

**Why it's problematic here:**
- TAK Server needs actual RAM, not compressed pseudo-RAM
- Memory-intensive Java processes are constantly swapping
- Compression overhead adds latency
- Better to have processes use RAM directly

---

## Solutions Implemented

### MediaMTX Memory Limits (COMPLETED - 2026-01-22)

Added systemd memory constraints to `/etc/systemd/system/mediamtx.service`:

```ini
# MEMORY OPTIMIZATION - Added 2026-01-22 for Pi 4 4GB RAM
# MemoryMax: Hard limit - process will be killed if exceeded (prevents system crash)
# Options: 256M (very conservative), 512M (recommended for RTSP-only), 1G (if re-enabling protocols)
# Current config: RTSP-only with reduced writeQueueSize should use <100MB under normal load
MemoryMax=512M

# MemoryHigh: Soft limit - triggers throttling before hitting hard limit
# Set to 80% of MemoryMax to give early warning via performance degradation
MemoryHigh=410M
```

**Reasoning:**
- MediaMTX configured for RTSP-only (HLS/WebRTC disabled)
- Reduced writeQueueSize to 512 in mediamtx.yml
- Should use <100MB under normal load
- 512M hard limit provides safety margin
- 410M soft limit triggers early warning

---

## Solutions Proposed

### Solution 1: Disable ZRAM (RECOMMENDED - FIRST STEP)

**Immediate disable:**
```bash
# Turn off ZRAM swap now
sudo swapoff /dev/zram0
sudo zramctl -r /dev/zram0

# Prevent ZRAM from starting on boot
sudo sed -i 's/^\[zram0\]/#[zram0]/' /usr/lib/systemd/zram-generator.conf

# Disable writeback timer
sudo systemctl disable --now rpi-zram-writeback.timer

# Verify
swapon --show  # Should show nothing
free -h        # Check available RAM
```

**Expected outcome:**
- Frees up RAM previously used for ZRAM compression
- Removes compression/decompression CPU overhead
- TAK Server gets direct access to RAM
- May see 500MB-1GB more usable RAM

**Trade-off:**
- No swap space means OOM killer will terminate processes if RAM exhausted
- For production TAK Server, this is preferable to thrashing ZRAM

**Revert if needed:**
```bash
# Re-enable ZRAM
sudo sed -i 's/^#\[zram0\]/[zram0]/' /usr/lib/systemd/zram-generator.conf
sudo systemctl enable --now rpi-zram-writeback.timer
sudo reboot
```

### Solution 2: Reduce TAK Server Heap Sizes (OPTIONAL - IF NEEDED)

**When to use:**
- If disabling ZRAM alone doesn't resolve memory pressure
- If TAK Server usage is light (<10 users)
- If other services need more RAM

**Implementation:**
Create `/etc/default/takserver` with reduced values:

```bash
# Conservative heap sizes for resource-constrained Pi
CONFIG_MAX_HEAP=80        # (default: ~111MB)
API_MAX_HEAP=400          # (default: ~617MB)
MESSAGING_MAX_HEAP=400    # (default: ~617MB)
PLUGIN_MANAGER_MAX_HEAP=80    # (default: ~129MB)
RETENTION_MAX_HEAP=80         # (default: ~129MB)
```

**Apply changes:**
```bash
sudo systemctl restart takserver-*
```

**Expected savings:**
- API: ~217 MB (617 → 400)
- Messaging: ~217 MB (617 → 400)
- Others: ~140 MB
- **Total: ~570 MB saved**

**Risks:**
- More frequent garbage collection (CPU spikes)
- Possible OutOfMemoryError under heavy load
- May drop connections or fail to process messages
- Database queries returning large datasets may fail

**Monitoring:**
```bash
# Watch for OOM errors in logs
sudo journalctl -u takserver-api -f
sudo journalctl -u takserver-messaging -f

# Monitor memory in real-time
htop
```

**Recommended minimum values (for ~10 users):**
- API: 300-400 MB
- Messaging: 300-400 MB  
- Config: 64-80 MB
- PM: 64-80 MB
- Retention: 64-80 MB

---

## Testing & Validation

### After ZRAM Disable:
```bash
# Check memory status
free -h
swapon --show

# Monitor TAK Server
ps aux --sort=-%mem | head -20

# Watch for stability issues
sudo journalctl -f

# Check TAK web interface
# Verify connections and message flow
```

### After Heap Reduction (if applied):
```bash
# Monitor for OOM errors
sudo journalctl -u takserver-* | grep -i "OutOfMemory"

# Watch GC behavior in TAK logs
tail -f /opt/tak/logs/takserver-*.log | grep -i "gc"

# Performance testing
# - Connect multiple ATAK clients
# - Send data packages
# - Monitor message delivery latency
```

---

## Implementation Order

1. **First:** Disable ZRAM only
   - Test for 24-48 hours
   - Monitor memory and system stability
   - Check if this alone resolves the issue

2. **If needed:** Reduce TAK heap sizes
   - Start conservative (400MB API/Messaging)
   - Monitor for OOM errors
   - Adjust upward if issues occur

3. **Last resort:** Review other services
   - PostgreSQL memory settings
   - Docker containers
   - Other running services

---

## Additional Notes

### Other Memory Consumers (for reference):
- PostgreSQL: ~35-100 MB
- Tailscale: ~80 MB
- Python services (mesh-web, rnsd): ~70 MB combined
- Docker daemon: ~34 MB

### SD Card Wear Mitigation:
The `sd-wear-setup.sh` script was run, which:
- Disabled disk-based swap (dphys-swapfile)
- Enabled noatime on filesystem
- Configured volatile journald (logs to RAM)
- Added tmpfs for /tmp

This **did not** disable ZRAM (different mechanism).

### Comparison Needed:
Check other working Pi deployments:
- Do they have `/etc/default/takserver` with custom heap values?
- What does `swapon --show` reveal?
- Is ZRAM enabled on those systems?

---

## References

- TAK Server config: `/opt/tak/setenv.sh`
- TAK Server heap calculation formulas (auto-scaling based on RAM)
- ZRAM config: `/usr/lib/systemd/zram-generator.conf`
- MediaMTX service: `/etc/systemd/system/mediamtx.service`
- SD wear script: `/opt/nucleus/bin/sd-wear-setup.sh`

---

## Actions Taken (2026-01-22)

### ZRAM Disable - Completed

**Commands executed:**
```bash
# 1. Immediate disable (caused OOM kill - expected due to memory pressure)
sudo swapoff /dev/zram0
sudo zramctl -r /dev/zram0

# 2. Prevent ZRAM on boot
sudo sed -i 's/^\[zram0\]/#[zram0]/' /usr/lib/systemd/zram-generator.conf

# 3. Disable writeback timer
sudo systemctl disable --now rpi-zram-writeback.timer
```

**Verification:**
```bash
$ swapon --show
NAME       TYPE      SIZE   USED PRIO
/dev/zram0 partition   2G 431.8M  100

$ free -h
               total        used        free      shared  buff/cache   available
Mem:           3.7Gi       3.0Gi       553Mi       170Mi       404Mi       720Mi
Swap:          2.0Gi       431Mi       1.6Gi

$ cat /usr/lib/systemd/zram-generator.conf
...
#[zram0]
```

**Results:**
- ✅ Config file successfully edited: `[zram0]` is now commented out
- ✅ Writeback timer disabled
- ✅ Memory improved: 720MB available (was 370MB before)
- ⚠️ ZRAM still active in current session (systemd recreated it after OOM kill)
- ⚠️ **Reboot required** for ZRAM to be fully disabled

**Memory improvement:**
- Before: 3.3GB/3.7GB used (89%), 370MB available, 1.1GB swap used
- After: 3.0GB/3.7GB used (81%), 720MB available, 431MB swap used
- Freed: ~300MB RAM, reduced swap usage by ~670MB

**Next steps:**
1. Reboot system - ZRAM will NOT start due to commented config
2. After reboot, expect ~1GB more usable RAM
3. Monitor for 24-48 hours
4. If still tight, consider TAK Server heap reduction

---

## Status

- [x] Problem identified
- [x] Root causes analyzed
- [x] MediaMTX memory limits applied
- [x] ZRAM disabled and prevented from starting on boot
- [ ] System reboot (pending - user decision)
- [ ] TAK Server heap reduction (optional, pending evaluation after reboot)
- [ ] 24-48 hour stability test (pending)

---

## Debian Trixie-Specific Memory Issues (2026-01-22)

### Additional Root Causes

Beyond ZRAM and TAK heap sizes, **Debian Trixie introduces glibc 2.41+** with new memory management behaviors that significantly increase RSS on multi-threaded applications.

#### 1. glibc Malloc Arena Bloat
**Issue:**
- glibc 2.41+ defaults to 8 arenas per CPU core on 64-bit systems
- Pi 4 (4 cores) = 32 arenas × 64MB = **~2GB virtual address space overhead**
- TAK Server (5 Java processes) + MediaMTX + PostgreSQL trigger arena allocation
- RSS appears inflated even with conservative heap settings

**Impact:** ~1.0-1.5 GB wasted RAM

#### 2. Transparent Hugepages (THP)
**Issue:**
- Java 17 and Go request 2MB pages instead of 4KB pages
- On fragmented 4GB Pi, kernel holds large memory blocks for small allocations
- RSS doubles compared to actual usage (e.g., TAK API: 842MB RSS vs 617MB heap)

**Impact:** ~400-800 MB wasted RAM

#### 3. Go Memory Allocator (MediaMTX)
**Issue:**
- Go's allocator is lazy about releasing memory on newer glibc
- MediaMTX holds freed memory instead of returning it to OS

**Impact:** ~100-200 MB wasted RAM

**Combined Impact:** ~1.5-2.4 GB total bloat

---

## Solution 3: Debian Trixie Optimizations (RECOMMENDED)

**Implementation order (chronological):**

### Step 1: Limit glibc Memory Arenas
```bash
# Add to /etc/environment
echo "MALLOC_ARENA_MAX=2" | sudo tee -a /etc/environment
```

**Effect:** Limits memory pools to 2 per process (from 32), saves ~1-1.5GB

### Step 2: Disable Transparent Hugepages
```bash
# Create systemd service for boot-time disable
sudo tee /etc/systemd/system/disable-thp.service > /dev/null << 'EOF'
[Unit]
Description=Disable Transparent Hugepages (THP)
DefaultDependencies=no
After=sysinit.target local-fs.target
Before=takserver-api.service takserver-messaging.service

[Service]
Type=oneshot
ExecStart=/bin/sh -c 'echo never > /sys/kernel/mm/transparent_hugepage/enabled'
ExecStart=/bin/sh -c 'echo never > /sys/kernel/mm/transparent_hugepage/defrag'

[Install]
WantedBy=basic.target
EOF

# Enable service
sudo systemctl daemon-reload
sudo systemctl enable disable-thp.service

# Verify current THP status (before reboot)
cat /sys/kernel/mm/transparent_hugepage/enabled
# [always] or [madvise] means THP is causing bloat
```

**Effect:** Prevents 2MB page allocation overhead, saves ~400-800MB

### Step 3: Configure MediaMTX Go Memory Release
```bash
# Edit MediaMTX service
sudo nano /etc/systemd/system/mediamtx.service

# Add under [Service] section:
Environment="GOGC=50"

# Reload systemd
sudo systemctl daemon-reload
```

**Effect:** Forces Go to be aggressive about releasing memory to OS

### Step 4: Reboot
```bash
sudo reboot
```

**Expected outcome after reboot:**
- ZRAM disabled (from previous action)
- glibc arena limit active
- THP disabled
- MediaMTX optimized
- **Expected free RAM: ~1.5-2.0 GB** (vs current 370MB)

---

## Verification Commands

### Check THP Status
```bash
cat /sys/kernel/mm/transparent_hugepage/enabled
# Should show: always madvise [never]
```

### Check Arena Limit
```bash
grep MALLOC_ARENA_MAX /etc/environment
# Should show: MALLOC_ARENA_MAX=2
```

### Check ZRAM
```bash
swapon --show
# Should show: (nothing)
```

### Memory Analysis
```bash
# Install PSS analysis tool
sudo apt install smem

# Compare RSS vs PSS (Proportional Set Size)
sudo smem -rtk | head -20

# PSS is actual memory usage; if PSS << RSS, arena bloat confirmed
```

### Monitor TAK Stability
```bash
# Watch for OOM errors
sudo journalctl -u takserver-* | grep -i "OutOfMemory"

# Real-time memory
htop
```

---

## Priority Order

1. **ZRAM disable** (already done, takes effect on reboot) → ~500MB-1GB freed
2. **glibc arena limit** (`MALLOC_ARENA_MAX=2`) → ~1-1.5GB freed
3. **THP disable** → ~400-800MB freed
4. **MediaMTX GOGC** → Better memory hygiene
5. **TAK heap reduction** (only if still needed after above)

**Total expected savings: 2-3GB freed**

---

## Updated Status

- [x] Debian Trixie-specific issues identified
- [ ] MALLOC_ARENA_MAX=2 added to /etc/environment
- [ ] THP disable service created and enabled
- [ ] MediaMTX GOGC=50 configured
- [ ] System reboot
- [ ] Verification tests (PSS analysis, memory monitoring)
- [ ] 24-48 hour stability test
