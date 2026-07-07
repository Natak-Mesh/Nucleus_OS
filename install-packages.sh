#!/bin/bash

# Nucleus OS - Package Installation Script
# Install all required software packages for a fresh node
#
# NOTE: Tailscale is installed but NOT enabled by default
#       To activate: sudo systemctl enable --now tailscaled && sudo tailscale up

set -e

echo "========================================"
echo "  NATAK Nucleus - Package Installation"
echo "========================================"
echo ""

# Update package lists
echo "[1/8] Updating package lists..."
sudo apt update

# Install core system packages
echo "[2/8] Installing core system packages..."
sudo apt install -y \
  git \
  hostapd \
  python3 \
  python3-pip \
  iperf3 \
  ufw \
  babeld \
  smcroute \
  nftables \
  tcpdump \
  uhubctl \
  sshpass \
  btop \
  mtr-tiny \
  ncdu \
  nginx \
  alsa-utils \
  unzip


# Install Python packages
echo "[3/8] Installing Python packages..."
# Reticulum - Cryptographic networking stack
# Note: Must start rns/rnsd at least once to generate config
pip3 install --break-system-packages rns

# Flask - Web framework for mesh web interface
sudo pip3 install --break-system-packages flask

# Meshtastic CLI - Tools for Meshtastic devices
pip3 install --upgrade --break-system-packages pytap2
pip3 install --upgrade --break-system-packages --ignore-installed "meshtastic[cli]"

# NomadNet - TUI mesh messenger/browser over Reticulum
pip3 install --break-system-packages nomadnet

# TAK Protocol libraries for ATAK CoT ↔ Meshtastic bridge
# takproto: TAK Protocol V1 (protobuf) encoding/decoding
pip3 install --break-system-packages "git+https://github.com/Natak-Mesh/takproto.git"
# meshtastic-tak: TAKPacketV2 conversion + zstd dictionary compression
pip3 install --break-system-packages --upgrade "git+https://github.com/meshtastic/TAKPacket-SDK.git#subdirectory=python"

# LoRa Voice→Text (openvlm-voice.py) — offline STT + TTS
# vosk: streaming speech-to-text (transcribes while PTT is held)
# piper-tts: neural text-to-speech (speaks received texts)
# Installed with sudo (system-wide) because the voice daemon runs as root.
sudo pip3 install --break-system-packages vosk piper-tts

# Pin protobuf to major version 6 — MUST run AFTER meshtastic/takproto/TAKPacket-SDK
# installs, since their `pip install --upgrade` pulls whatever protobuf is newest.
#
# The cot-bridge depends on meshtastic_tak, whose generated code (atak_pb2.py) is
# compiled with protobuf gencode 6.x. Protobuf enforces that the runtime and gencode
# share the same MAJOR version, so a runtime of 5.x or 7.x makes cot-bridge crash at
# import with: "Detected mismatched Protobuf Gencode/Runtime major versions ...
# Same major version is required." (seen on node 0034, 2026-06-16).
#
# Range (>=6,<7) instead of an exact pin: allows protobuf 6.x patch/minor updates
# (bug/security fixes) while blocking the major-version jump that actually breaks us.
# Revisit only if meshtastic_tak regenerates against protobuf 7.
pip3 install --break-system-packages "protobuf>=6,<7"


# Download speech models for LoRa Voice→Text (requires internet)
echo "[3b/8] Downloading STT/TTS models for LoRa voice-text..."
# Vosk STT model (~40 MB) -> /opt/nucleus/models/vosk/vosk-model-small-en-us-0.15
VOSK_DIR=/opt/nucleus/models/vosk
if [ ! -d "$VOSK_DIR/vosk-model-small-en-us-0.15" ]; then
    sudo mkdir -p "$VOSK_DIR"
    wget -q --show-progress -O /tmp/vosk-model.zip \
        https://alphacephei.com/vosk/models/vosk-model-small-en-us-0.15.zip
    sudo unzip -q /tmp/vosk-model.zip -d "$VOSK_DIR"
    rm -f /tmp/vosk-model.zip
    echo "Vosk model installed to $VOSK_DIR"
else
    echo "Vosk model already installed."
fi
# Piper TTS voice (~60 MB) -> /opt/nucleus/models/piper/en_US-lessac-low.onnx
PIPER_DIR=/opt/nucleus/models/piper
PIPER_BASE="https://huggingface.co/rhasspy/piper-voices/resolve/v1.0.0/en/en_US/lessac/low"
if [ ! -f "$PIPER_DIR/en_US-lessac-low.onnx" ]; then
    sudo mkdir -p "$PIPER_DIR"
    sudo wget -q --show-progress -O "$PIPER_DIR/en_US-lessac-low.onnx" \
        "$PIPER_BASE/en_US-lessac-low.onnx"
    sudo wget -q --show-progress -O "$PIPER_DIR/en_US-lessac-low.onnx.json" \
        "$PIPER_BASE/en_US-lessac-low.onnx.json"
    echo "Piper voice installed to $PIPER_DIR"
else
    echo "Piper voice already installed."
fi

# Configure environment
echo "[4/8] Configuring environment..."
# Add ~/.local/bin to PATH for Python packages
if ! grep -q 'export PATH="$HOME/.local/bin:$PATH"' ~/.bashrc; then
    echo 'export PATH="$HOME/.local/bin:$PATH"' >> ~/.bashrc
    echo "Added ~/.local/bin to PATH in ~/.bashrc"
fi

# Install Docker
echo "[5/8] Installing Docker..."
if ! command -v docker &> /dev/null; then
    curl -fsSL https://get.docker.com | sh
    sudo usermod -aG docker $USER
    echo "Docker installed. You may need to log out and back in for group changes to take effect."
else
    echo "Docker already installed."
fi

# Pull OpenDHT image (while online)
echo "[6/8] Pulling OpenDHT Docker image..."
if docker images | grep -q opendht-alpine; then
    echo "OpenDHT image already exists."
else
    docker pull ghcr.io/savoirfairelinux/opendht/opendht-alpine
    echo "OpenDHT image pulled successfully."
fi

# Install Yggdrasil
echo "[7/8] Installing Yggdrasil overlay network..."
sudo apt-get install -y dirmngr
sudo mkdir -p /usr/local/apt-keys
gpg --fetch-keys https://neilalexander.s3.dualstack.eu-west-2.amazonaws.com/deb/key.txt
gpg --export 1C5162E133015D81A811239D1840CDAC6011C5EA | sudo tee /usr/local/apt-keys/yggdrasil-keyring.gpg > /dev/null
echo 'deb [signed-by=/usr/local/apt-keys/yggdrasil-keyring.gpg] http://neilalexander.s3.dualstack.eu-west-2.amazonaws.com/deb/ debian yggdrasil' | sudo tee /etc/apt/sources.list.d/yggdrasil.list
sudo apt-get update
sudo apt-get install -y yggdrasil
echo "Yggdrasil installed. Configure peers in /etc/yggdrasil/yggdrasil.conf"

# Install Tailscale
echo "[8/8] Installing Tailscale..."
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
echo "2. First-run configuration required:"
echo "   - Start rns/rnsd at least once to generate Reticulum config"
echo ""
echo "3. Yggdrasil overlay network is installed but NOT enabled."
echo "   - Enable: sudo systemctl enable --now yggdrasil"
echo "   - Configure peers in /etc/yggdrasil/yggdrasil.conf"
echo "   - Check status: yggdrasilctl getSelf"
echo ""
echo "4. MANUAL INSTALLATION REQUIRED:"
echo ""
echo "   TAKserver (arm64):"
echo "   - Download from https://tak.gov"
echo "   - Install: sudo dpkg -i takserver-*.deb"
echo ""
echo "   MediaMTX (arm64):"
echo "   - Download: wget https://github.com/bluenviron/mediamtx/releases/latest/download/mediamtx_linux_arm64.tar.gz"
echo "   - Extract: tar -xvzf mediamtx_linux_arm64.tar.gz"
echo ""
echo "5. Reload your shell or run: source ~/.bashrc"
echo ""
echo "Next step: Run ./deploy.sh to deploy Nucleus configuration files"
echo ""
