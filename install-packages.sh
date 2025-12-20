#!/bin/bash

# Nucleus OS - Package Installation Script
# Install all required software packages for a fresh node

set -e

echo "========================================"
echo "  NATAK Nucleus - Package Installation"
echo "========================================"
echo ""

# Update package lists
echo "[1/6] Updating package lists..."
sudo apt update

# Install core system packages
echo "[2/6] Installing core system packages..."
sudo apt install -y \
  git \
  hostapd \
  python3 \
  python3-pip \
  aircrack-ng \
  iperf3 \
  ufw \
  babeld \
  smcroute \
  nftables \
  tcpdump

# Install Python packages
echo "[3/6] Installing Python packages..."
# Reticulum - Cryptographic networking stack
# Note: Must start rns/rnsd at least once to generate config
pip3 install --break-system-packages rns lxmf

# Nomadnet - Off-grid messaging and information sharing
# Note: Update config after starting nomadnet once
pip3 install --break-system-packages nomadnet

# Flask - Web framework for mesh web interface
sudo pip3 install --break-system-packages flask

# Meshtastic CLI - Tools for Meshtastic devices
pip3 install --upgrade --break-system-packages pytap2
pip3 install --upgrade --break-system-packages "meshtastic[cli]"

# Configure environment
echo "[4/6] Configuring environment..."
# Add ~/.local/bin to PATH for Python packages
if ! grep -q 'export PATH="$HOME/.local/bin:$PATH"' ~/.bashrc; then
    echo 'export PATH="$HOME/.local/bin:$PATH"' >> ~/.bashrc
    echo "Added ~/.local/bin to PATH in ~/.bashrc"
fi

# Install Tailscale
echo "[5/7] Installing Tailscale..."
curl -fsSL https://tailscale.com/install.sh | sh

# Install Raspberry Pi Connect
echo "[6/7] Installing Raspberry Pi Connect..."
sudo apt install -y rpi-connect
loginctl enable-linger $USER

# Enable NetworkManager
echo "[7/7] Enabling NetworkManager..."
sudo systemctl enable NetworkManager

echo ""
echo "========================================"
echo "  Core Package Installation Complete!"
echo "========================================"
echo ""
echo "IMPORTANT NOTES:"
echo ""
echo "1. System wpa_supplicant may need to be disabled to avoid conflicts"
echo "   with the one used for wlan1. Don't forget to unmask and enable hostapd."
echo ""
echo "2. First-run configuration required:"
echo "   - Start rns/rnsd at least once to generate Reticulum config"
echo "   - Start nomadnet at least once to generate its config"
echo ""
echo "3. MANUAL INSTALLATION REQUIRED:"
echo ""
echo "   TAKserver (arm64):"
echo "   - Download from https://tak.gov"
echo "   - Install: sudo dpkg -i takserver-*.deb"
echo ""
echo "   MediaMTX (arm64):"
echo "   - Download: wget https://github.com/bluenviron/mediamtx/releases/latest/download/mediamtx_linux_arm64.tar.gz"
echo "   - Extract: tar -xvzf mediamtx_linux_arm64.tar.gz"
echo ""
echo "4. Reload your shell or run: source ~/.bashrc"
echo ""
echo "Next step: Run ./deploy.sh to deploy Nucleus configuration files"
echo ""
