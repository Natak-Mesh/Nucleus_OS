# Minimize SD Card Wear on MANET Nodes

## Goal
Reduce SD card write operations to extend lifespan of Raspberry Pi SD cards without impacting system functionality or using excessive RAM.

## Why This Matters
SD cards wear out from repeated writes. The main culprits are:
- **System logs** - Constantly writing status messages
- **Swap file** - Using SD card as overflow memory
- **File access timestamps** - Recording every time a file is opened
- **Temporary files** - Scratch space that doesn't need to persist

## Strategy
Move high-write operations to RAM (tmpfs) and disable unnecessary write operations. High endurance SD cards + these changes = long node lifespan.

---

## Changes to Implement

### 1. Disable Swap
**What:** Remove the swap file completely
**Why:** Swap writes constantly to SD and actually reduces available RAM
**RAM Impact:** None (actually frees RAM)
**Risk:** None for systems with adequate RAM

### 2. Disable Access Time Tracking (noatime)
**What:** Stop recording "last accessed" timestamp on every file read
**Why:** Eliminates writes every time you read a file
**RAM Impact:** None
**Risk:** None (rarely needed on embedded systems)

### 3. Volatile Logs (RAM Only)
**What:** Keep all system logs in RAM only - they don't persist across reboots
**Why:** Logs are the #1 source of SD writes
**RAM Impact:** ~50MB (configurable)
**Risk:** Can't review logs after a reboot. Fine for live troubleshooting.
**Note:** Logs exist while the system is running - you just lose history after shutdown.

### 4. Temporary Files to RAM
**What:** Move /tmp to RAM-based storage
**Why:** Temp files don't need to persist anyway
**RAM Impact:** ~50MB (configurable)
**Risk:** None (temp files are meant to be temporary)

### 5. Increase Filesystem Commit Interval
**What:** Write cached data to SD every 10 minutes instead of every 5 seconds
**Why:** Batches writes together, reducing total write operations
**RAM Impact:** None
**Risk:** Very small - if power is lost, you might lose up to 10 min of writes

---

## Total RAM Usage
Approximately **100MB** total (adjustable based on Pi model and available RAM)

For a 4GB or 8GB Pi running TAKServer, this is negligible.

---

## What We DON'T Lose
- System functionality remains identical
- Services work normally
- Live troubleshooting with logs works fine
- Configuration persists normally
- System is stable and reliable

## What We DO Lose
- Log history after reboots (can't investigate "what happened yesterday")
- That's it

---

## Implementation Status
- [ ] Disable swap file
- [ ] Add noatime mount option to /etc/fstab
- [ ] Configure systemd journal for volatile storage only
- [ ] Configure tmpfs for /tmp
- [ ] Adjust filesystem commit interval
- [ ] Test and verify all services start correctly
- [ ] Document any RAM usage changes

---

## Future Considerations
If more aggressive SD protection is needed, the full read-only root filesystem approach is documented separately. That requires:
- Separate /data partition for persistent config
- Boot-time config generation
- More complex setup
- Near-zero SD writes

For now, the simple approach above provides excellent protection with minimal complexity.
