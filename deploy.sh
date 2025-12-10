#!/bin/bash

# Deploy Nucleus OS files to system locations
# NOTE: Run ./install-packages.sh first to install required software packages
# NOTE: Run ./SSH_fix.sh on the node to optimize SSH settings
# NOTE: Check IP addresses in babeld.conf, ensure they match your system

set -e

SOURCE_DIR="$(pwd)"

echo "Deploying from $SOURCE_DIR..."

# Copy etc files (only static configs - generated ones are created by config_generation.sh)
sudo mkdir -p /etc/nucleus
sudo cp "$SOURCE_DIR/etc/nucleus/mesh.conf" /etc/nucleus/
sudo chown natak:natak /etc/nucleus/mesh.conf

sudo mkdir -p /etc/systemd/network
sudo cp "$SOURCE_DIR/etc/systemd/network/20-brlan.netdev" /etc/systemd/network/
sudo cp "$SOURCE_DIR/etc/systemd/network/30-wlan0.network" /etc/systemd/network/
sudo cp "$SOURCE_DIR/etc/systemd/network/40-eth0-lan.network" /etc/systemd/network/
sudo chown natak:natak /etc/systemd/network/20-brlan.netdev
sudo chown natak:natak /etc/systemd/network/30-wlan0.network
sudo chown natak:natak /etc/systemd/network/40-eth0-lan.network

sudo mkdir -p /etc/NetworkManager/conf.d
sudo cp "$SOURCE_DIR/etc/NetworkManager/conf.d/unmanaged-devices.conf" /etc/NetworkManager/conf.d/
sudo cp "$SOURCE_DIR/etc/smcroute.conf" /etc/
sudo cp "$SOURCE_DIR/etc/babeld.conf" /etc/
sudo chown natak:natak /etc/babeld.conf

# Copy networkd-dispatcher scripts
sudo mkdir -p /etc/networkd-dispatcher/degraded.d
sudo mkdir -p /etc/networkd-dispatcher/routable.d
sudo cp "$SOURCE_DIR/etc/networkd-dispatcher/degraded.d/50-eth0-lan-mode" /etc/networkd-dispatcher/degraded.d/
sudo cp "$SOURCE_DIR/etc/networkd-dispatcher/routable.d/50-eth0-wan-mode" /etc/networkd-dispatcher/routable.d/
sudo chmod +x /etc/networkd-dispatcher/degraded.d/50-eth0-lan-mode
sudo chmod +x /etc/networkd-dispatcher/routable.d/50-eth0-wan-mode

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
sudo chmod +x /opt/nucleus/bin/config_generation.sh
sudo chmod +x /opt/nucleus/bin/mesh-start.sh
sudo chmod +x /opt/nucleus/bin/eth0-mode.sh

# Copy web directory if exists
if [ -d "$SOURCE_DIR/opt/nucleus/web" ]; then
    sudo cp -r "$SOURCE_DIR/opt/nucleus/web" /opt/nucleus/
fi

# Fix ownership for web interface to write config files
sudo chown -R natak:natak /opt/nucleus/

# Enable and start routing services (after network setup)
sudo systemctl enable babeld.service
sudo systemctl restart babeld.service
sudo systemctl enable smcroute.service
sudo systemctl restart smcroute.service

echo "Deployment complete."
