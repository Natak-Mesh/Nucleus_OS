#!/bin/bash

# Deploy Nucleus OS (Drone) files to system locations
# NOTE: Run ./install-packages.sh first to install required software packages
# NOTE: Check IP addresses in babeld.conf, ensure they match your system
# NOTE: Run 'sudo /opt/nucleus/bin/sd-wear-setup.sh' after deploy to minimize SD card wear
# NOTE: UART must be enabled for the FC link (this script checks and warns)
# NOTE: Pass --force-config to overwrite an existing /etc/nucleus/mesh.conf with
#       the repo template. Without it, node identity (MESH_IP etc.) is preserved.

set -e

# Parse flags
FORCE_CONFIG=false
for arg in "$@"; do
    case "$arg" in
        --force-config) FORCE_CONFIG=true ;;
    esac
done

SOURCE_DIR="$(pwd)"

echo "Deploying from $SOURCE_DIR..."

# NOTE: Bluetooth is deliberately NOT unblocked on the drone build. The
# Bluetooth controller claims the PL011 UART, which is the port the flight
# controller needs (/dev/ttyAMA0 on GPIO14/15). See docs/drone/uart-setup.md.

# Copy etc files (only static configs - generated ones are created by config_generation.sh)
sudo mkdir -p /etc/nucleus
if [ ! -f /etc/nucleus/mesh.conf ] || [ "$FORCE_CONFIG" = "true" ]; then
    # Fresh node (or forced): install the repo mesh.conf as-is.
    sudo cp "$SOURCE_DIR/etc/nucleus/mesh.conf" /etc/nucleus/
    sudo chown natak:natak /etc/nucleus/mesh.conf
else
    # Existing node: preserve all current values, only ADD keys that are
    # missing (e.g. keys introduced by new features). The repo mesh.conf is
    # the source of truth for the full set of keys, their defaults, and the
    # comment block that precedes each key. Never edits or deletes existing
    # lines. Idempotent — safe to re-run.
    #
    # This matters because the repo template carries placeholder node identity
    # (MESH_IP, BR_LAN_IP, AP_NAME ...). Copying it over a live node would
    # rewrite that node's address and drop it off the mesh.
    echo "mesh.conf exists — syncing any missing keys (existing values preserved)"
    REPO_CONF="$SOURCE_DIR/etc/nucleus/mesh.conf"
    NODE_CONF="/etc/nucleus/mesh.conf"
    ADDED=0
    buffer=""
    while IFS= read -r line || [ -n "$line" ]; do
        if [[ "$line" =~ ^[A-Za-z_][A-Za-z0-9_]*= ]]; then
            key="${line%%=*}"
            if grep -q "^${key}=" "$NODE_CONF"; then
                buffer=""                      # key present: drop its comments
            else
                { [ -n "$buffer" ] && printf '%s' "$buffer"; printf '%s\n' "$line"; } \
                    | sudo tee -a "$NODE_CONF" > /dev/null
                echo "  + added $key"
                ADDED=$((ADDED+1))
                buffer=""
            fi
        else
            buffer+="$line"$'\n'                # accumulate comments/blank lines
        fi
    done < "$REPO_CONF"
    [ "$ADDED" -eq 0 ] && echo "  mesh.conf already up to date"
fi

sudo mkdir -p /etc/systemd/network
sudo cp "$SOURCE_DIR/etc/systemd/network/20-brlan.netdev" /etc/systemd/network/
sudo cp "$SOURCE_DIR/etc/systemd/network/30-wlan0.network" /etc/systemd/network/
sudo chown natak:natak /etc/systemd/network/20-brlan.netdev
sudo chown natak:natak /etc/systemd/network/30-wlan0.network

sudo mkdir -p /etc/NetworkManager/conf.d
sudo cp "$SOURCE_DIR/etc/NetworkManager/NetworkManager.conf" /etc/NetworkManager/
sudo cp "$SOURCE_DIR/etc/NetworkManager/conf.d/unmanaged-devices.conf" /etc/NetworkManager/conf.d/
sudo cp "$SOURCE_DIR/etc/smcroute.conf" /etc/
sudo cp "$SOURCE_DIR/etc/babeld.conf" /etc/
sudo chown natak:natak /etc/babeld.conf

# Copy sudoers file for privilege escalation
sudo mkdir -p /etc/sudoers.d
sudo cp "$SOURCE_DIR/etc/sudoers.d/nucleus-config" /etc/sudoers.d/
sudo chmod 0440 /etc/sudoers.d/nucleus-config
sudo chown root:root /etc/sudoers.d/nucleus-config

# Copy systemd service files
sudo cp "$SOURCE_DIR/etc/systemd/system/brlan-setup.service" /etc/systemd/system/
sudo cp "$SOURCE_DIR/etc/systemd/system/mesh-start.service" /etc/systemd/system/
sudo cp "$SOURCE_DIR/etc/systemd/system/mavlink-router.service" /etc/systemd/system/
sudo mkdir -p /etc/systemd/system/babeld.service.d
sudo cp "$SOURCE_DIR/etc/systemd/system/babeld.service.d/override.conf" /etc/systemd/system/babeld.service.d/
sudo systemctl daemon-reload
sudo systemctl enable brlan-setup.service
sudo systemctl enable mesh-start.service
sudo systemctl enable mavlink-router.service

# Copy opt files
sudo mkdir -p /opt/nucleus/bin
sudo cp "$SOURCE_DIR/opt/nucleus/bin/config_generation.sh" /opt/nucleus/bin/
sudo cp "$SOURCE_DIR/opt/nucleus/bin/mesh-start.sh" /opt/nucleus/bin/
sudo cp "$SOURCE_DIR/opt/nucleus/bin/eth0-mode.sh" /opt/nucleus/bin/
sudo cp "$SOURCE_DIR/opt/nucleus/bin/sd-wear-setup.sh" /opt/nucleus/bin/
sudo cp "$SOURCE_DIR/opt/nucleus/bin/iw-wifi-scan.sh" /opt/nucleus/bin/
sudo cp "$SOURCE_DIR/opt/nucleus/bin/drone-uart-setup.sh" /opt/nucleus/bin/
sudo chmod +x /opt/nucleus/bin/drone-uart-setup.sh
sudo chmod +x /opt/nucleus/bin/config_generation.sh
sudo chmod +x /opt/nucleus/bin/mesh-start.sh
sudo chmod +x /opt/nucleus/bin/eth0-mode.sh
sudo chmod +x /opt/nucleus/bin/sd-wear-setup.sh
sudo chmod +x /opt/nucleus/bin/iw-wifi-scan.sh

# Copy drone MAVLink tools
if [ -d "$SOURCE_DIR/opt/nucleus/drone" ]; then
    sudo mkdir -p /opt/nucleus/drone
    sudo cp -r "$SOURCE_DIR/opt/nucleus/drone/"* /opt/nucleus/drone/
    sudo chmod +x /opt/nucleus/drone/*.py
fi

sudo chown -R natak:natak /opt/nucleus/

# Disable wpa_supplicant (conflicts with hostapd)
sudo systemctl disable wpa_supplicant.service
sudo systemctl stop wpa_supplicant.service

# Enable hostapd for wireless AP
sudo systemctl unmask hostapd.service
sudo systemctl enable hostapd.service

# Enable and start routing services (after network setup)
sudo systemctl enable babeld.service
sudo systemctl restart babeld.service
sudo systemctl enable smcroute.service
sudo systemctl restart smcroute.service

# Verify the UART is ready for the flight controller link.
# The Pi's PL011 UART (/dev/ttyAMA0) is claimed by the Bluetooth controller by
# default, and a serial console + login prompt sit on GPIO14/15. All of that
# has to be undone before the FC link works. drone-uart-setup.sh does it.
# See docs/drone/uart-setup.md for the full explanation.
BOOT_CONFIG=/boot/firmware/config.txt
[ -f "$BOOT_CONFIG" ] || BOOT_CONFIG=/boot/config.txt

BOOT_CMDLINE=/boot/firmware/cmdline.txt
[ -f "$BOOT_CMDLINE" ] || BOOT_CMDLINE=/boot/cmdline.txt

UART_WARN=0
if [ -f "$BOOT_CONFIG" ]; then
    grep -q '^enable_uart=1' "$BOOT_CONFIG" || UART_WARN=1
    grep -q '^dtoverlay=disable-bt' "$BOOT_CONFIG" || UART_WARN=1
else
    UART_WARN=1
fi

# A serial console on GPIO14/15 transmits kernel output into the FC's RX pin.
if [ -f "$BOOT_CMDLINE" ] && \
   grep -qE 'console=(serial0|ttyAMA0|ttyS0)' "$BOOT_CMDLINE"; then
    UART_WARN=1
fi

# /dev/ttyAMA0 missing means the PL011 is still bound to Bluetooth.
[ -e /dev/ttyAMA0 ] || UART_WARN=1

if [ "$UART_WARN" -eq 1 ]; then
    echo ""
    echo "=================================================="
    echo "  WARNING: UART not configured for the FC link"
    echo "=================================================="
    echo "  Run:"
    echo "    sudo /opt/nucleus/bin/drone-uart-setup.sh"
    echo "    sudo reboot"
    echo ""
    echo "  Then verify with:"
    echo "    python3 /opt/nucleus/drone/fc-link-check.py"
    echo ""
    echo "  Until this is done, mavlink-router cannot open"
    echo "  /dev/ttyAMA0 and the drone will not be controllable."
    echo "  Details: docs/drone/uart-setup.md"
    echo "=================================================="
    echo ""
fi

echo "Deployment complete."
