#!/bin/bash
# SD Card Wear Minimization Setup Script
# For Raspberry Pi running Nucleus_OS
# Implements: swap disable, noatime, volatile logs, tmpfs /tmp

set -e

# Check if running as root
if [ "$EUID" -ne 0 ]; then 
    echo "Please run as root (sudo)"
    exit 1
fi

echo "=========================================="
echo "SD Card Wear Minimization Setup"
echo "=========================================="
echo ""

# 1. Disable SD-card-based swap (preserve zram which is RAM-only)
echo "[1/4] Disabling SD card swap (keeping zram)..."
if command -v dphys-swapfile &> /dev/null; then
    dphys-swapfile swapoff 2>/dev/null || true
    dphys-swapfile uninstall 2>/dev/null || true
    systemctl disable dphys-swapfile 2>/dev/null || true
    echo "  ✓ dphys-swapfile disabled"
else
    # Only disable file/partition-based swap on SD card, leave zram alone
    for dev in $(swapon --show=NAME --noheadings 2>/dev/null); do
        if [[ "$dev" != /dev/zram* ]]; then
            swapoff "$dev" 2>/dev/null || true
            echo "  ✓ Disabled SD swap: $dev"
        fi
    done
    echo "  ✓ zram swap preserved (RAM-only, no SD writes)"
fi

# 2. Add noatime to fstab
echo "[2/4] Configuring noatime in /etc/fstab..."
if grep -q "noatime" /etc/fstab; then
    echo "  ✓ noatime already present in fstab"
else
    # Add noatime to root partition mount options
    sed -i 's/\(.*\s\/\s.*\)\sdefaults\s/\1 defaults,noatime /' /etc/fstab
    echo "  ✓ noatime added to root partition"
fi

# 3. Add tmpfs for /tmp if not already present
echo "[3/4] Configuring tmpfs for /tmp..."
if grep -q "tmpfs.*\/tmp" /etc/fstab; then
    echo "  ✓ tmpfs for /tmp already configured"
else
    echo "tmpfs /tmp tmpfs defaults,noatime,nosuid,size=50M 0 0" >> /etc/fstab
    echo "  ✓ tmpfs /tmp added to fstab"
fi

# 4. Configure systemd journal for volatile storage
echo "[4/4] Configuring volatile journal..."
mkdir -p /etc/systemd/journald.conf.d
cat > /etc/systemd/journald.conf.d/volatile.conf << 'EOF'
[Journal]
Storage=volatile
RuntimeMaxUse=50M
EOF
echo "  ✓ Journal configured for RAM-only storage"

echo ""
echo "=========================================="
echo "Setup Complete!"
echo "=========================================="
echo ""
echo "Changes applied:"
echo "  • Swap disabled (frees RAM, reduces writes)"
echo "  • noatime enabled (no access time writes)"
echo "  • Logs to RAM only (~50MB)"
echo "  • /tmp in RAM (~50MB)"
echo ""
echo "Total RAM usage: ~100MB"
echo ""
echo "⚠️  REBOOT REQUIRED for changes to take effect"
echo ""
read -p "Reboot now? (y/n) " -n 1 -r
echo
if [[ $REPLY =~ ^[Yy]$ ]]; then
    echo "Rebooting in 5 seconds... (Ctrl+C to cancel)"
    sleep 5
    reboot
else
    echo "Please reboot manually when ready."
fi
