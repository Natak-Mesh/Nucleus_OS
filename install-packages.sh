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
pip3 install --break-system-packages "git+https://github.com/meshtastic/TAKPacket-SDK.git@v0.9.1#subdirectory=python"

# LoRa Voice→Text (openvlm-voice.py) — offline STT + TTS
# vosk: streaming speech-to-text (transcribes while PTT is held)
# piper-tts: neural text-to-speech (speaks received texts). Must be >= 1.4:
#   the voice daemon uses the resident PiperVoice Python API (not the CLI)
#   so the model loads once at startup instead of per message — see
#   docs/VoIP/lora_voice/lora_voice_text.md (TTS section).
# webrtc-noise-gain: WebRTC noise suppression for the STT mic tap
#   (VOICE_STT_CLEANUP in mesh.conf). Optional but recommended: without it
#   the daemon falls back to high-pass filtering only.
# NOTE: the sherpa-onnx STT engine was tested and REJECTED on Pi 4
#   (2026-07-07, see docs/VoIP/lora_voice/lora_voice_text.md) — its pip
#   package and model are intentionally NOT installed. To trial it on
#   faster hardware: pip3 install sherpa-onnx + a streaming zipformer
#   model in /opt/nucleus/models/sherpa/, then VOICE_STT_ENGINE=sherpa.
# Installed with sudo (system-wide) because the voice daemon runs as root.
sudo pip3 install --break-system-packages vosk "piper-tts>=1.4" \
    webrtc-noise-gain

# LoRa Voice Streaming (openvlm-voice.py "stream" transport) — live Codec2
# voice over the Meshtastic radio (VOICE_LORA_STREAM_ENABLED in mesh.conf).
# pycodec2: python bindings for the Codec2 speech codec (3200 bps mode);
#   needs the codec2 C library + headers (libcodec2-dev) to build.
# numpy: sample-rate conversion in the voice daemon's stream path.
sudo apt install -y libcodec2-dev
sudo pip3 install --break-system-packages pycodec2 numpy

# Pin protobuf to major version 6 — MUST run AFTER meshtastic/takproto/TAKPacket-SDK
# installs, since their `pip install --upgrade` pulls whatever protobuf is newest.
#
# The cot-bridge depends on meshtastic_tak, whose generated code (atak_pb2.py) is
# compiled with protobuf gencode 6.x. Protobuf enforces TWO version rules and
# cot-bridge crashes at import if either is violated:
#   1. Runtime and gencode must share the same MAJOR version — a 5.x or 7.x
#      runtime fails with "Detected mismatched Protobuf Gencode/Runtime major
#      versions ... Same major version is required." (node 0034, 2026-06-16).
#   2. Runtime must be >= the gencode version, even within the same major —
#      "Runtime version cannot be older than the linked gencode version."
#      (node 0010, 2026-07-09: gencode 6.33.2 vs runtime 6.32.1).
#
# --upgrade is REQUIRED here: without it, an already-installed 6.x runtime
# satisfies ">=6,<7" and pip leaves it alone, so a fresh TAKPacket-SDK install
# (newer gencode) with a stale runtime trips rule 2 above.
#
# Range (>=6,<7) instead of an exact pin: allows protobuf 6.x patch/minor updates
# (bug/security fixes) while blocking the major-version jump that also breaks us.
# Revisit only if meshtastic_tak regenerates against protobuf 7.
pip3 install --break-system-packages --upgrade "protobuf>=6,<7"


# Download speech models for LoRa Voice→Text (requires internet)
echo "[3b/8] Downloading STT/TTS models for LoRa voice-text..."
# Vosk STT model (~40 MB disk, ~100 MB RAM) -> /opt/nucleus/models/vosk/
# The small model is the fielded default: it decodes faster than real-time
# on a Pi 4 so the transcript is ready the moment PTT is released. Larger
# models (e.g. vosk-model-en-us-0.22-lgraph) were tested and REJECTED on
# Pi 4: slower-than-real-time decode = 10+ s latency after release, plus
# ~500-700 MB RAM. For accuracy gains use the opt-in grammar constraint
# (VOICE_STT_GRAMMAR in mesh.conf) instead.
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

# Pull meshtasticd image (for RAK Pi HAT LoRa radio via SPI/GPIO)
echo "[6b/8] Pulling meshtasticd Docker image..."
if docker images | grep -q "meshtastic/meshtasticd"; then
    echo "meshtasticd image already exists."
else
    docker pull meshtastic/meshtasticd:daily-alpine
    echo "meshtasticd image pulled successfully."
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
