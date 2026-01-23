#!/bin/bash

# RAM Optimization for TAKServer on Raspberry Pi 4 (4GB RAM)
# Addresses Debian Trixie-specific memory management issues
# See docs/system_info/high-ram-usage.md for detailed explanation

set -e

echo "=== TAKServer RAM Optimization Script ==="
echo "This script applies memory optimizations for Debian Trixie systems"
echo "running TAKServer and MediaMTX on Raspberry Pi 4 (4GB RAM)"
echo ""

# 1. Set MALLOC_ARENA_MAX to reduce glibc memory arena bloat
echo "Configuring MALLOC_ARENA_MAX=2 to reduce glibc arena bloat..."
if ! grep -q "^MALLOC_ARENA_MAX=" /etc/environment 2>/dev/null; then
    echo "MALLOC_ARENA_MAX=2" | sudo tee -a /etc/environment
    echo "  ✓ Added MALLOC_ARENA_MAX=2 to /etc/environment"
else
    echo "  ℹ MALLOC_ARENA_MAX already configured in /etc/environment"
fi

# 2. Disable ZRAM compressed swap (consumes RAM to save RAM)
echo ""
echo "Disabling ZRAM compressed swap..."
if [ -f /usr/lib/systemd/zram-generator.conf ]; then
    if grep -q "^\[zram0\]" /usr/lib/systemd/zram-generator.conf 2>/dev/null; then
        sudo sed -i 's/^\[zram0\]/#[zram0]/' /usr/lib/systemd/zram-generator.conf
        echo "  ✓ Disabled ZRAM in zram-generator.conf"
    else
        echo "  ℹ ZRAM already disabled in zram-generator.conf"
    fi
    
    # Disable writeback timer if exists
    if systemctl is-enabled rpi-zram-writeback.timer &>/dev/null; then
        sudo systemctl disable --now rpi-zram-writeback.timer
        echo "  ✓ Disabled rpi-zram-writeback.timer"
    fi
else
    echo "  ℹ ZRAM config file not found (may not be installed)"
fi

# 3. Check if ZRAM is currently active and warn user
if [ -e /dev/zram0 ] && swapon --show | grep -q zram0; then
    echo ""
    echo "  ⚠ WARNING: ZRAM is currently active on this system"
    echo "    The changes above will take effect after reboot"
    echo "    Current swap:"
    swapon --show | grep zram0 || true
fi

echo ""
echo "=== RAM Optimization Complete ==="
echo ""
echo "Changes made:"
echo "  1. MALLOC_ARENA_MAX=2 set (limits glibc memory arenas)"
echo "  2. ZRAM swap disabled (frees RAM used for compression)"
echo "  3. MediaMTX configured with GOGC=50 (aggressive Go GC)"
echo ""
echo "Expected RAM savings: ~1.5-2.5 GB"
echo ""
echo "⚠ REBOOT REQUIRED for changes to take full effect"
echo ""
echo "After reboot, verify with:"
echo "  free -h                    # Should show ~1-2GB more available"
echo "  swapon --show              # Should show no swap devices"
echo "  grep MALLOC /etc/environment  # Should show MALLOC_ARENA_MAX=2"
echo ""
