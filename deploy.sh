#!/bin/bash

# Deploy Nucleus OS (Drone) files to system locations
# NOTE: Run ./install-packages.sh first to install required software packages
# NOTE: Check IP addresses in babeld.conf, ensure they match your system
# NOTE: Run 'sudo /opt/nucleus/bin/sd-wear-setup.sh' after deploy to minimize SD card wear
# NOTE: UART must be enabled for the FC link (this script checks and warns)

set -e

SOURCE_DIR="$(pwd)"

echo "Deploying from $SOURCE_DIR..."

# Unblock Bluetooth
sudo rfkill unblock bluetooth

# Copy etc files (only static configs - generated ones are created by config_generation.sh)
sudo mkdir -p /etc/nucleus
sudo cp "$SOURCE_DIR/etc/nucleus/mesh.conf" /etc/nucleus/
sudo chown natak:natak /etc/nucleus/mesh.conf

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

# Verify UART is enabled for the flight controller link.
# The Pi's PL011 UART (/dev/ttyAMA0) is assigned to Bluetooth by default, so
# it must be released with dtoverlay=disable-bt before the FC can use it.
BOOT_CONFIG=/boot/firmware/config.txt
[ -f "$BOOT_CONFIG" ] || BOOT_CONFIG=/boot/config.txt

UART_WARN=0
if [ -f "$BOOT_CONFIG" ]; then
    grep -q '^enable_uart=1' "$BOOT_CONFIG" || UART_WARN=1
    grep -q '^dtoverlay=disable-bt' "$BOOT_CONFIG" || UART_WARN=1
else
    UART_WARN=1
fi

if [ "$UART_WARN" -eq 1 ]; then
    echo ""
    echo "=================================================="
    echo "  WARNING: UART not configured for the FC link"
    echo "=================================================="
    echo "  Add to $BOOT_CONFIG:"
    echo "    enable_uart=1"
    echo "    dtoverlay=disable-bt"
    echo "  Then run:"
    echo "    sudo systemctl disable hciuart"
    echo "    sudo reboot"
    echo ""
    echo "  Until this is done, mavlink-router cannot open"
    echo "  /dev/ttyAMA0 and the drone will not be controllable."
    echo "=================================================="
    echo ""
fi

echo "Deployment complete."
