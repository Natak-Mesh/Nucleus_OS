#!/bin/bash

# Nucleus OS (Drone) - Package Installation Script
# Install all required software packages for a fresh drone companion node
#
# NOTE: Tailscale is installed but NOT enabled by default
#       To activate: sudo systemctl enable --now tailscaled && sudo tailscale up

set -e

echo "========================================"
echo "  NATAK Nucleus Drone - Package Install"
echo "========================================"
echo ""

# Update package lists
echo "[1/5] Updating package lists..."
sudo apt update

# Install core system packages
echo "[2/5] Installing core system packages..."
sudo apt install -y \
  git \
  hostapd \
  python3 \
  python3-pip \
  python3-venv \
  iperf3 \
  babeld \
  smcroute \
  tcpdump \
  btop \
  mtr-tiny \
  meson \
  ninja-build \
  pkg-config \
  g++

# Install Python packages
echo "[3/5] Installing Python packages..."
# pymavlink - MAVLink protocol library used by the drone test scripts
pip3 install --break-system-packages pymavlink

# pygame - joystick input for zorro_mavlink_sender.py (ground station only,
# harmless on the drone node)
pip3 install --break-system-packages pygame

# Build and install mavlink-router
# Not packaged for Debian/Raspberry Pi OS, so it is built from source.
# Bridges the FC UART to UDP and fans out to multiple simultaneous GCS.
echo "[4/5] Building mavlink-router from source..."
if command -v mavlink-routerd &> /dev/null; then
    echo "mavlink-routerd already installed."
else
    BUILD_DIR=$(mktemp -d)
    git clone --recursive https://github.com/mavlink-router/mavlink-router.git "$BUILD_DIR/mavlink-router"
    cd "$BUILD_DIR/mavlink-router"
    meson setup build . --buildtype=release
    ninja -C build
    sudo ninja -C build install
    cd - > /dev/null
    rm -rf "$BUILD_DIR"
    echo "mavlink-routerd installed to $(command -v mavlink-routerd || echo /usr/bin/mavlink-routerd)"
fi

# Configure environment
echo "[5/5] Configuring environment..."
# Add ~/.local/bin to PATH for Python packages
if ! grep -q 'export PATH="$HOME/.local/bin:$PATH"' ~/.bashrc; then
    echo 'export PATH="$HOME/.local/bin:$PATH"' >> ~/.bashrc
    echo "Added ~/.local/bin to PATH in ~/.bashrc"
fi

# Install Tailscale
echo "Installing Tailscale..."
curl -fsSL https://tailscale.com/install.sh | sh
# Enable Tailscale daemon (user can configure profiles manually when ready)
sudo systemctl enable tailscaled
sudo systemctl start tailscaled

# Enable services
echo "Enabling services..."
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
echo "2. UART must be enabled for the flight controller link."
echo "   In /boot/firmware/config.txt:"
echo "     enable_uart=1"
echo "     dtoverlay=disable-bt"
echo "   Then: sudo systemctl disable hciuart && sudo reboot"
echo "   deploy.sh checks for this and warns if missing."
echo ""
echo "3. Tailscale is installed but NOT connected."
echo "   - Connect: sudo tailscale up"
echo ""
echo "4. Reload your shell or run: source ~/.bashrc"
echo ""
echo "Next step: Run ./deploy.sh to deploy Nucleus configuration files"
echo ""
