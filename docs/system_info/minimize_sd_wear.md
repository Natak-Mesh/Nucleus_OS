# Minimize SD Card Wear on MANET Nodes

## Goal
Reduce SD card write operations to extend lifespan of Raspberry Pi SD cards without impacting system functionality or using excessive RAM.

## Why This Matters
SD cards wear out from repeated writes. The main culprits on a busy MANET node are:
- **System logs** — Constantly writing status messages (babeld, TAK, meshtastic, kernel, etc.)
- **Swap to disk** — Using SD card as overflow memory (traditional swap files)
- **File access timestamps** — Recording every time a file is opened
- **Temporary files** — Scratch space that doesn't need to persist

## Current Status: ✅ All Mitigations Active

All four key SD wear mitigations are in place on Nucleus nodes.

---

## What's Applied

### 1. Volatile Journal (Logs in RAM Only)
**Status:** ✅ Active — provided by Raspberry Pi OS  
**Config:** `/usr/lib/systemd/journald.conf.d/40-rpi-volatile-storage.conf`  
**How it works:**
- `Storage=volatile` tells systemd-journald to write logs only to `/run/log/journal/` (tmpfs/RAM)
- `/var/log/journal/` (on SD card) exists but remains empty — zero log files on disk
- Journal is compressed with zstd, typically ~8MB in RAM
- Logs are available via `journalctl` while the system is running
- Logs are lost on reboot (acceptable for field nodes)

**Verify:**
```bash
# Show where journals are stored
journalctl --header 2>&1 | grep "File path"
# Expected: /run/log/journal/...

# Confirm nothing on SD
find /var/log/journal/ -type f | wc -l
# Expected: 0

# Check effective config
systemd-analyze cat-config systemd/journald.conf | grep Storage
# Expected: Storage=volatile
```

**Note:** This is a vendor-provided RPi OS default, not our custom config. It survives OS updates since it ships with the distro.

### 2. noatime Mount Option
**Status:** ✅ Active — configured in `/etc/fstab`  
**Config:** `PARTUUID=...-02  /  ext4  defaults,noatime  0  1`  
**How it works:**
- Prevents the filesystem from recording "last accessed" timestamps on every file read
- Eliminates a write operation every time any file is read
- Zero RAM cost, zero functionality impact

**Verify:**
```bash
mount | grep "on / "
# Expected: ... (rw,noatime)
```

### 3. tmpfs for /tmp
**Status:** ✅ Active — handled by systemd `tmp.mount`  
**How it works:**
- `/tmp` is mounted as tmpfs (RAM-based filesystem)
- Temporary files never touch the SD card
- Automatically cleaned on reboot

**Verify:**
```bash
mount | grep /tmp
# Expected: tmpfs on /tmp type tmpfs ...

systemctl status tmp.mount
# Expected: active (mounted)
```

### 4. zram Swap (RAM-to-RAM, NOT SD Card)
**Status:** ✅ Active — provided by Raspberry Pi OS  
**How it works:**
- 2GB zram block device compresses memory pages in RAM using zstd
- Acts like swap but **never touches the SD card**
- Effectively increases usable memory (~3x compression ratio typical)
- This is NOT the same as traditional swap (dphys-swapfile) which writes to SD

**Verify:**
```bash
zramctl
# Expected: /dev/zram0  zstd  2G  ...  [SWAP]

swapon --show
# Expected: /dev/zram0  partition  2G  ...
# Should NOT show /var/swap or any mmcblk device
```

**Important:** Do NOT disable zram swap. It helps the system — especially when running TAK Server — by providing overflow memory compression entirely in RAM. The old guidance said "disable swap" but that referred to traditional SD-card-based swap (dphys-swapfile), which is not present on this system.

---

## Total RAM Usage for SD Protection

| Measure | RAM Used | Notes |
|---------|----------|-------|
| Volatile journal | ~8MB | Capped by systemd, rotates automatically |
| tmpfs /tmp | Variable | Only uses RAM for actual temp files present |
| zram swap | ~130MB compressed | Holds ~430MB of data at ~3x compression |
| noatime | 0 | Mount option only |

All negligible on a 4GB Pi.

---

## What We Keep
- Full system functionality
- All services work normally
- Live troubleshooting with `journalctl` works fine
- Configuration changes persist normally to SD
- Database writes persist normally to SD
- System is stable and reliable

## What We Lose
- Log history after reboots (can't investigate "what happened yesterday")
- That's it

---

## Implementation

### For Fresh Installs
The setup script at `opt/nucleus/bin/sd-wear-setup.sh` applies the noatime fstab change and can disable traditional swap if present. Most mitigations are now handled by RPi OS defaults (zram, volatile journal) or systemd (tmp.mount), so the script is mainly needed for the noatime configuration.

### What's Handled Automatically by RPi OS
- Volatile journal (`40-rpi-volatile-storage.conf`)
- zram swap (replaces traditional dphys-swapfile)
- tmpfs for /tmp (systemd `tmp.mount`)

### What We Configure
- noatime in `/etc/fstab` (applied by `sd-wear-setup.sh` or manually)

---

## Future Considerations

### Additional Tuning (Diminishing Returns)
If even more aggressive SD protection is needed:
- **Increase dirty writeback interval** — `vm.dirty_writeback_centisecs` from 500 (5s) to 1500 (15s) to batch more writes together
- **Increase ext4 commit interval** — Add `commit=60` to fstab to batch filesystem journal commits (default is 5s)
- **Rate-limit journal** — Reduce `RateLimitBurst` in journald config if log volume is excessive

### Full Read-Only Root (Nuclear Option)
For near-zero SD writes:
- Mount root filesystem read-only
- Separate `/data` partition for persistent config
- Use overlayfs for runtime changes
- Significantly more complex to maintain
- Probably unnecessary with current mitigations + high-endurance SD cards

### Power Quality
Undervoltage events (visible in `journalctl` as `hwmon hwmon1: Undervoltage detected!`) can corrupt SD cards regardless of write optimization. Use a quality 5V/3A+ power supply with adequate cabling.
