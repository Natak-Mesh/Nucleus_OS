#!/bin/bash

# Deploy Nucleus OS files to system locations
# NOTE: Run ./install-packages.sh first to install required software packages
# NOTE: Run ./SSH_fix.sh on the node to optimize SSH settings
# NOTE: Check IP addresses in babeld.conf, ensure they match your system
# NOTE: Run 'sudo /opt/nucleus/bin/sd-wear-setup.sh' after deploy to minimize SD card wear

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
sudo cp "$SOURCE_DIR/etc/NetworkManager/conf.d/unmanaged-devices.conf" /etc/NetworkManager/conf.d/
sudo cp "$SOURCE_DIR/etc/smcroute.conf" /etc/
sudo cp "$SOURCE_DIR/etc/babeld.conf" /etc/
sudo chown natak:natak /etc/babeld.conf

# Copy sudoers file for Tailscale web GUI
sudo mkdir -p /etc/sudoers.d
sudo cp "$SOURCE_DIR/etc/sudoers.d/tailscale-web" /etc/sudoers.d/
sudo chmod 0440 /etc/sudoers.d/tailscale-web
sudo chown root:root /etc/sudoers.d/tailscale-web

# Copy systemd service files
sudo cp "$SOURCE_DIR/etc/systemd/system/brlan-setup.service" /etc/systemd/system/
sudo cp "$SOURCE_DIR/etc/systemd/system/mesh-start.service" /etc/systemd/system/
sudo cp "$SOURCE_DIR/etc/systemd/system/mesh-web.service" /etc/systemd/system/
sudo cp "$SOURCE_DIR/etc/systemd/system/rnsd.service" /etc/systemd/system/
sudo mkdir -p /etc/systemd/system/babeld.service.d
sudo cp "$SOURCE_DIR/etc/systemd/system/babeld.service.d/override.conf" /etc/systemd/system/babeld.service.d/
sudo systemctl daemon-reload
sudo systemctl enable brlan-setup.service
sudo systemctl enable mesh-start.service
sudo systemctl enable mesh-web.service
sudo systemctl enable rnsd.service

# Copy opt files
sudo mkdir -p /opt/nucleus/bin
sudo cp "$SOURCE_DIR/opt/nucleus/bin/config_generation.sh" /opt/nucleus/bin/
sudo cp "$SOURCE_DIR/opt/nucleus/bin/mesh-start.sh" /opt/nucleus/bin/
sudo cp "$SOURCE_DIR/opt/nucleus/bin/eth0-mode.sh" /opt/nucleus/bin/
sudo cp "$SOURCE_DIR/opt/nucleus/bin/opendht-start.sh" /opt/nucleus/bin/
sudo cp "$SOURCE_DIR/opt/nucleus/bin/sd-wear-setup.sh" /opt/nucleus/bin/
sudo chmod +x /opt/nucleus/bin/config_generation.sh
sudo chmod +x /opt/nucleus/bin/mesh-start.sh
sudo chmod +x /opt/nucleus/bin/eth0-mode.sh
sudo chmod +x /opt/nucleus/bin/opendht-start.sh
sudo chmod +x /opt/nucleus/bin/sd-wear-setup.sh

# Copy web directory if exists
if [ -d "$SOURCE_DIR/opt/nucleus/web" ]; then
    sudo cp -r "$SOURCE_DIR/opt/nucleus/web" /opt/nucleus/
fi

# Fix ownership for web interface to write config files
sudo chown -R natak:natak /opt/nucleus/

# Deploy Reticulum config
sudo mkdir -p /home/natak/.reticulum
sudo cp "$SOURCE_DIR/home/natak/.reticulum/config" /home/natak/.reticulum/
sudo chown -R natak:natak /home/natak/.reticulum

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

echo "Deployment complete."
