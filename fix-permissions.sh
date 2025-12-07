#!/bin/bash

# Fix file permissions for Nucleus OS web interface
# This fixes the "permission denied" error when saving config settings
# Run this on nodes where files were copied as root

echo "Fixing file permissions for natak user..."

# Fix ownership of config files
sudo chown natak:natak /etc/nucleus/mesh.conf
sudo chown natak:natak /etc/babeld.conf

# Fix ownership of systemd network files
sudo chown natak:natak /etc/systemd/network/20-brlan.netdev
sudo chown natak:natak /etc/systemd/network/30-wlan0.network
sudo chown natak:natak /etc/systemd/network/40-eth0-lan.network

# Fix ownership of entire nucleus directory
sudo chown -R natak:natak /opt/nucleus/

echo "Permission fix complete!"
echo "The web interface should now be able to save configuration settings."
