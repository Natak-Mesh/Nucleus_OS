#!/bin/bash

# drone-uart-setup.sh — prepare the Pi GPIO UART for the flight controller link
#
# Run once, as root, then reboot:
#     sudo /opt/nucleus/bin/drone-uart-setup.sh
#     sudo reboot
#
# WHAT THIS FIXES
# ---------------
# The Pi has two UARTs that can reach GPIO14/15 (header pins 8 and 10):
#
#   PL011      "full" UART, own clock source, stable at 921600  -> /dev/ttyAMA0
#   mini-UART  clock derived from the VPU core clock, unreliable -> /dev/ttyS0
#
# By default the PL011 is claimed by the on-board Bluetooth controller (the
# hci_uart_bcm driver binds it as serial0-0), so /dev/ttyAMA0 never appears and
# GPIO14/15 get the mini-UART instead. Three separate problems result:
#
#   1. MAVLINK_SERIAL=/dev/ttyAMA0 points at a device that does not exist,
#      so mavlink-router cannot open the port at all.
#   2. The mini-UART's baud rate tracks the VPU core clock. Under CPU load the
#      clock moves and framing breaks, which is fatal at 921600.
#   3. The kernel serial console + a login prompt (serial-getty) run on the
#      same pins at 115200, transmitting console text straight into the FC's
#      RX2 pin and holding the port open.
#
# This script applies all three fixes. Bluetooth is removed entirely — the
# drone build does not use it.
#
# AFTER REBOOT, VERIFY
#   ls -l /dev/ttyAMA0                       # must exist
#   sudo fuser -v /dev/ttyAMA0               # must report no holder
#   python3 /opt/nucleus/drone/fc-link-check.py
#
# See docs/drone/uart-setup.md for the full write-up.

set -e

if [ "$(id -u)" -ne 0 ]; then
    echo "ERROR: must be run as root (use sudo)." >&2
    exit 1
fi

BOOT_CONFIG=/boot/firmware/config.txt
[ -f "$BOOT_CONFIG" ] || BOOT_CONFIG=/boot/config.txt

BOOT_CMDLINE=/boot/firmware/cmdline.txt
[ -f "$BOOT_CMDLINE" ] || BOOT_CMDLINE=/boot/cmdline.txt

if [ ! -f "$BOOT_CONFIG" ] || [ ! -f "$BOOT_CMDLINE" ]; then
    echo "ERROR: cannot locate boot config/cmdline files." >&2
    exit 1
fi

echo "Using boot config:  $BOOT_CONFIG"
echo "Using boot cmdline: $BOOT_CMDLINE"
echo ""

REBOOT_NEEDED=0

# ---------------------------------------------------------------------------
# 1. enable_uart=1 — turns on the GPIO UART at all
# ---------------------------------------------------------------------------
if grep -q '^enable_uart=1' "$BOOT_CONFIG"; then
    echo "[ok]   enable_uart=1 already set"
else
    echo "[fix]  adding enable_uart=1"
    printf '\n# Nucleus drone: enable the GPIO UART for the flight controller link\nenable_uart=1\n' >> "$BOOT_CONFIG"
    REBOOT_NEEDED=1
fi

# ---------------------------------------------------------------------------
# 2. dtoverlay=disable-bt — unbind Bluetooth from the PL011 so it becomes
#    /dev/ttyAMA0 on GPIO14/15. Without this the pins get the mini-UART.
# ---------------------------------------------------------------------------
if grep -q '^dtoverlay=disable-bt' "$BOOT_CONFIG"; then
    echo "[ok]   dtoverlay=disable-bt already set"
else
    echo "[fix]  adding dtoverlay=disable-bt (releases PL011 from Bluetooth)"
    printf '\n# Nucleus drone: release the PL011 UART from the Bluetooth controller so it\n# appears as /dev/ttyAMA0 on GPIO14/15. Bluetooth is not used on the drone.\ndtoverlay=disable-bt\n' >> "$BOOT_CONFIG"
    REBOOT_NEEDED=1
fi

# ---------------------------------------------------------------------------
# 3. Remove the serial console from cmdline.txt. Leaving it in place means the
#    kernel prints boot messages onto GPIO14 at 115200, into the FC's RX pin.
#    Matches console=ttyAMA0,<baud> / console=ttyS0,<baud> / console=serial0,<baud>.
# ---------------------------------------------------------------------------
if grep -qE 'console=(serial0|ttyAMA0|ttyS0)[^ ]*' "$BOOT_CMDLINE"; then
    echo "[fix]  removing serial console from $BOOT_CMDLINE"
    cp "$BOOT_CMDLINE" "${BOOT_CMDLINE}.nucleus.bak"
    echo "       backup written to ${BOOT_CMDLINE}.nucleus.bak"
    # cmdline.txt must stay a single line; collapse the extra whitespace left behind.
    sed -i -E 's/console=(serial0|ttyAMA0|ttyS0)[^ ]*[ ]?//g; s/[ ]+/ /g; s/^ //; s/ $//' "$BOOT_CMDLINE"
    REBOOT_NEEDED=1
else
    echo "[ok]   no serial console in $BOOT_CMDLINE"
fi

# ---------------------------------------------------------------------------
# 4. Disable the serial login prompts. Even with the console removed, a getty
#    unit will re-open the port and hold it against mavlink-router.
#    The unit is created by a systemd generator from the console= setting, so
#    it can be active without being "enabled" — stop and mask it explicitly.
# ---------------------------------------------------------------------------
for GETTY in serial-getty@ttyAMA0.service serial-getty@ttyS0.service; do
    echo "[fix]  stopping and masking $GETTY"
    systemctl stop    "$GETTY" >/dev/null 2>&1 || true
    systemctl disable "$GETTY" >/dev/null 2>&1 || true
    systemctl mask    "$GETTY" >/dev/null 2>&1 || true
done

# ---------------------------------------------------------------------------
# 5. Disable the Bluetooth stack. disable-bt removes the hardware binding; this
#    stops the userspace daemon from starting and logging errors afterwards.
#    hciuart only exists on older Raspberry Pi OS images, so ignore if absent.
# ---------------------------------------------------------------------------
for BTUNIT in hciuart.service bluetooth.service; do
    if [ -n "$(systemctl list-unit-files --no-legend "$BTUNIT" 2>/dev/null)" ]; then
        echo "[fix]  disabling $BTUNIT"
        systemctl disable --now "$BTUNIT" >/dev/null 2>&1 || true
    else
        echo "[ok]   $BTUNIT not present on this image"
    fi
done

# Block the radio as well so nothing re-enables it at runtime.
if command -v rfkill >/dev/null 2>&1; then
    echo "[fix]  rfkill block bluetooth"
    rfkill block bluetooth || true
fi

# ---------------------------------------------------------------------------
# 6. Make sure the operating user can open the port without sudo.
# ---------------------------------------------------------------------------
if id -nG natak 2>/dev/null | grep -qw dialout; then
    echo "[ok]   user natak is in the dialout group"
else
    echo "[fix]  adding natak to the dialout group"
    usermod -aG dialout natak
    REBOOT_NEEDED=1
fi

echo ""
echo "=================================================="
if [ "$REBOOT_NEEDED" -eq 1 ]; then
    echo "  UART setup applied - REBOOT REQUIRED"
    echo "=================================================="
    echo "  sudo reboot"
    echo ""
    echo "  After reboot, confirm the port exists and is free:"
    echo "    ls -l /dev/ttyAMA0"
    echo "    sudo fuser -v /dev/ttyAMA0"
    echo "    python3 /opt/nucleus/drone/fc-link-check.py"
else
    echo "  UART already configured - no reboot needed"
    echo "=================================================="
fi
echo ""
