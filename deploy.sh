#!/bin/bash

# Deploy Nucleus OS files to system locations
# NOTE: Run ./install-packages.sh first to install required software packages
# NOTE: Run ./SSH_fix.sh on the node to optimize SSH settings
# NOTE: Check IP addresses in babeld.conf, ensure they match your system
# NOTE: Run 'sudo /opt/nucleus/bin/sd-wear-setup.sh' after deploy to minimize SD card wear
# NOTE: Run 'sudo /opt/nucleus/bin/ram-optimize.sh' after deploy for TAKServer RAM corrections (Debian Trixie)

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

# Unblock Bluetooth
sudo rfkill unblock bluetooth

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

# Meshtastic udev rule — prevent mtp-probe from crashing RAK4631 firmware on boot
sudo mkdir -p /etc/udev/rules.d
sudo cp "$SOURCE_DIR/etc/udev/rules.d/60-meshtastic.rules" /etc/udev/rules.d/
sudo udevadm control --reload-rules

# Copy sudoers files for web GUI privilege escalation
sudo mkdir -p /etc/sudoers.d
sudo cp "$SOURCE_DIR/etc/sudoers.d/tailscale-web" /etc/sudoers.d/
sudo chmod 0440 /etc/sudoers.d/tailscale-web
sudo chown root:root /etc/sudoers.d/tailscale-web
sudo cp "$SOURCE_DIR/etc/sudoers.d/nucleus-config" /etc/sudoers.d/
sudo chmod 0440 /etc/sudoers.d/nucleus-config
sudo chown root:root /etc/sudoers.d/nucleus-config

# Copy systemd service files
sudo cp "$SOURCE_DIR/etc/systemd/system/brlan-setup.service" /etc/systemd/system/
sudo cp "$SOURCE_DIR/etc/systemd/system/mesh-start.service" /etc/systemd/system/
sudo cp "$SOURCE_DIR/etc/systemd/system/mesh-web.service" /etc/systemd/system/
sudo cp "$SOURCE_DIR/etc/systemd/system/rnsd.service" /etc/systemd/system/
sudo cp "$SOURCE_DIR/etc/systemd/system/cot-bridge.service" /etc/systemd/system/
sudo cp "$SOURCE_DIR/etc/systemd/system/mediamtx.service" /etc/systemd/system/
sudo cp "$SOURCE_DIR/etc/systemd/system/openvlm-voice.service" /etc/systemd/system/
sudo mkdir -p /etc/systemd/system/babeld.service.d
sudo cp "$SOURCE_DIR/etc/systemd/system/babeld.service.d/override.conf" /etc/systemd/system/babeld.service.d/
sudo systemctl daemon-reload
sudo systemctl enable brlan-setup.service
sudo systemctl enable mesh-start.service
sudo systemctl enable mesh-web.service
sudo systemctl enable rnsd.service
sudo systemctl enable openvlm-voice.service
# Restart voice daemon so a deploy picks up new openvlm-voice.py immediately
# (otherwise the old daemon keeps running until reboot — e.g. no WebSocket server)
sudo systemctl restart openvlm-voice.service

# Note: mediamtx.service is copied but not enabled - enable manually on nodes that need video streaming:
#       sudo systemctl enable --now mediamtx.service

# Copy opt files
sudo mkdir -p /opt/nucleus/bin
sudo cp "$SOURCE_DIR/opt/nucleus/bin/config_generation.sh" /opt/nucleus/bin/
sudo cp "$SOURCE_DIR/opt/nucleus/bin/mesh-start.sh" /opt/nucleus/bin/
sudo cp "$SOURCE_DIR/opt/nucleus/bin/eth0-mode.sh" /opt/nucleus/bin/
sudo cp "$SOURCE_DIR/opt/nucleus/bin/opendht-start.sh" /opt/nucleus/bin/
sudo cp "$SOURCE_DIR/opt/nucleus/bin/sd-wear-setup.sh" /opt/nucleus/bin/
sudo cp "$SOURCE_DIR/opt/nucleus/bin/ram-optimize.sh" /opt/nucleus/bin/
sudo cp "$SOURCE_DIR/opt/nucleus/bin/iw-wifi-scan.sh" /opt/nucleus/bin/
sudo cp "$SOURCE_DIR/opt/nucleus/bin/openvlm-voice.py" /opt/nucleus/bin/
sudo cp "$SOURCE_DIR/opt/nucleus/bin/voice" /usr/local/bin/
sudo chmod +x /opt/nucleus/bin/config_generation.sh
sudo chmod +x /opt/nucleus/bin/mesh-start.sh
sudo chmod +x /opt/nucleus/bin/eth0-mode.sh
sudo chmod +x /opt/nucleus/bin/opendht-start.sh
sudo chmod +x /opt/nucleus/bin/sd-wear-setup.sh
sudo chmod +x /opt/nucleus/bin/ram-optimize.sh
sudo chmod +x /opt/nucleus/bin/iw-wifi-scan.sh
sudo chmod +x /opt/nucleus/bin/openvlm-voice.py
sudo chmod +x /usr/local/bin/voice

# Copy meshtastic module if exists
if [ -d "$SOURCE_DIR/opt/nucleus/meshtastic" ]; then
    sudo cp -r "$SOURCE_DIR/opt/nucleus/meshtastic" /opt/nucleus/
fi

# Copy web directory if exists
if [ -d "$SOURCE_DIR/opt/nucleus/web" ]; then
    sudo cp -r "$SOURCE_DIR/opt/nucleus/web" /opt/nucleus/
fi

# Copy CLI tools
if [ -d "$SOURCE_DIR/opt/nucleus/cli" ]; then
    sudo mkdir -p /opt/nucleus/cli
    sudo cp -r "$SOURCE_DIR/opt/nucleus/cli/"* /opt/nucleus/cli/
    sudo chmod +x /opt/nucleus/cli/*.sh
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
