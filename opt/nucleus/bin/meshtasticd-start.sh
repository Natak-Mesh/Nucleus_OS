#!/bin/bash

#       ..        .....        ...       
#       ....     ......       ....      
#       .......... ...       .....       
#       ........    ..      ......       
#       ......      ..     .......       
#       .....       ...  .........       
#       ....        .....     ....      
#       ...         ....        ..   

#############################################
#        N A T A K   -   Nucleus OS         #
#                                           #
#           Mesh Networking Radio           #
#############################################

# meshtasticd Startup Script
# Starts meshtasticd Docker container for Meshtastic radio control.
# Auto-detects the radio connection:
#   - USB serial (/dev/ttyACM0): radio connected via USB port
#   - SPI/GPIO (Pi HAT):        RAK6421 LoRa hat on GPIO pins
# Both modes expose the same TCP API on localhost:4403, so the rest of
# the system (cot-bridge, web configurator, CLI) always uses TCP.

# Source configuration
source /etc/nucleus/mesh.conf

# Check if meshtasticd is enabled
if [ "$MESHTASTICD_ENABLED" != "true" ]; then
    echo "meshtasticd is disabled in mesh.conf"
    exit 0
fi

MESHTASTICD_DIR="/home/natak/meshtasticd"
MESHTASTICD_IMAGE="meshtastic/meshtasticd:daily-alpine"
MESHTASTICD_CONTAINER="meshtasticd"
MAC_FILE="${MESHTASTICD_DIR}/.mac_address"
LORA_CONFIG="${MESHTASTICD_LORA_CONFIG:-lora-RAK6421-13302-slot1}"
USB_SERIAL_DEV="/dev/ttyACM0"

# Create config directories
mkdir -p "${MESHTASTICD_DIR}/config.d"

# Generate or load persistent MAC address (unique per node, stable across reboots)
if [ -f "$MAC_FILE" ]; then
    MAC_ADDR=$(cat "$MAC_FILE")
    echo "meshtasticd: using existing MAC ${MAC_ADDR}"
else
    # Generate a locally-administered random MAC address
    MAC_ADDR=$(printf '%02x:%02x:%02x:%02x:%02x:%02x' \
        $(( (RANDOM % 256) | 0x02 & 0xfe )) \
        $((RANDOM % 256)) $((RANDOM % 256)) \
        $((RANDOM % 256)) $((RANDOM % 256)) $((RANDOM % 256)))
    echo "$MAC_ADDR" > "$MAC_FILE"
    echo "meshtasticd: generated new MAC ${MAC_ADDR}"
fi

# ── Auto-detect radio connection mode ────────────────────────────
# USB serial takes priority: if /dev/ttyACM0 exists, assume a USB
# Meshtastic radio is plugged in. Otherwise fall back to SPI/GPIO
# (RAK Pi HAT). Both produce the same TCP API on localhost:4403.

if [ -e "$USB_SERIAL_DEV" ]; then
    # ── USB serial mode ──────────────────────────────────────────
    RADIO_MODE="usb"
    echo "meshtasticd: USB radio detected at ${USB_SERIAL_DEV}"

    cat > "${MESHTASTICD_DIR}/config.yaml" <<EOF
---
Serial:
  Module: ${USB_SERIAL_DEV}

General:
  MACAddress: ${MAC_ADDR}
EOF

    # No LoRa hardware config needed for USB serial (radio has its own firmware)
    rm -f "${MESHTASTICD_DIR}/config.d/"*.yaml 2>/dev/null

    # Docker args: map the USB device (no full --privileged needed)
    DOCKER_EXTRA_ARGS="--device ${USB_SERIAL_DEV}"

    # USB serial needs longer for meshtasticd to handshake with the radio
    API_WAIT_SECS=60
else
    # ── SPI/GPIO mode (Pi HAT) ───────────────────────────────────
    RADIO_MODE="spi"
    echo "meshtasticd: no USB radio found — using SPI/GPIO (Pi HAT)"

    cat > "${MESHTASTICD_DIR}/config.yaml" <<EOF
---
Lora:
  Module: auto

General:
  MACAddress: ${MAC_ADDR}
EOF

    # Copy LoRa hardware config from the image's available.d if not already present
    CONFIG_FILE="${MESHTASTICD_DIR}/config.d/${LORA_CONFIG}.yaml"
    if [ ! -f "$CONFIG_FILE" ]; then
        echo "meshtasticd: extracting ${LORA_CONFIG}.yaml from image..."
        docker run --rm "${MESHTASTICD_IMAGE}" \
            cat "/etc/meshtasticd/available.d/${LORA_CONFIG}.yaml" > "$CONFIG_FILE" 2>/dev/null
        if [ ! -s "$CONFIG_FILE" ]; then
            echo "WARNING: failed to extract ${LORA_CONFIG}.yaml — file not found in image"
            rm -f "$CONFIG_FILE"
        fi
    fi

    # Docker args: privileged for SPI/GPIO access
    DOCKER_EXTRA_ARGS="--privileged"

    # SPI/GPIO is faster to initialize
    API_WAIT_SECS=30
fi

# Stop existing container if running
if docker ps -a | grep -q "${MESHTASTICD_CONTAINER}"; then
    echo "Stopping existing meshtasticd container..."
    docker stop "${MESHTASTICD_CONTAINER}" 2>/dev/null
    docker rm "${MESHTASTICD_CONTAINER}" 2>/dev/null
fi

# Named volume for persistent radio config (region, channel, PSK, node DB).
# Without this, docker rm + docker run creates a new anonymous volume each
# time, wiping all radio settings on every reboot.
MESHTASTICD_VOLUME="meshtasticd-data"

# Start meshtasticd container
echo "Starting meshtasticd container (${RADIO_MODE} mode)..."
docker run -d \
    --name "${MESHTASTICD_CONTAINER}" \
    ${DOCKER_EXTRA_ARGS} \
    --net=host \
    --restart=unless-stopped \
    -v "${MESHTASTICD_DIR}/config.yaml:/etc/meshtasticd/config.yaml" \
    -v "${MESHTASTICD_DIR}/config.d:/etc/meshtasticd/config.d" \
    -v "${MESHTASTICD_VOLUME}:/var/lib/meshtasticd" \
    "${MESHTASTICD_IMAGE}"

# Wait for the API to come up, then configure the radio
HOSTNAME_FULL=$(hostname)
HOSTNAME_SHORT=$(hostname | cut -c1-4)

echo "Waiting for meshtasticd API (${RADIO_MODE} mode, max ${API_WAIT_SECS}s)..."
API_ATTEMPTS=$(( API_WAIT_SECS / 2 ))
for i in $(seq 1 $API_ATTEMPTS); do
    if meshtastic --host localhost --info >/dev/null 2>&1; then
        echo "meshtasticd API is up"

        # Always set owner name (cheap, no reboot)
        meshtastic --host localhost --set-owner "${HOSTNAME_FULL}" --set-owner-short "${HOSTNAME_SHORT}"
        echo "meshtasticd: node name set to ${HOSTNAME_FULL} (${HOSTNAME_SHORT})"

        # First-boot radio config: set region if still UNSET.
        # Without a region the radio refuses to transmit:
        #   "send - lora tx disabled: Region unset"
        CURRENT_REGION=$(meshtastic --host localhost --get lora.region 2>&1 | grep -oP 'lora\.region:\s*\K\S+' || true)
        if [ -z "$CURRENT_REGION" ] || [ "$CURRENT_REGION" = "UNSET" ] || [ "$CURRENT_REGION" = "0" ]; then
            echo "meshtasticd: region is UNSET — setting to US..."
            meshtastic --host localhost --set lora.region US
            echo "meshtasticd: waiting for radio reboot after region set..."
            sleep 10
            # Wait for radio to come back
            for j in $(seq 1 15); do
                if meshtastic --host localhost --info >/dev/null 2>&1; then
                    echo "meshtasticd: radio back after region set"
                    break
                fi
                sleep 2
            done
        else
            echo "meshtasticd: region already set to ${CURRENT_REGION}"
        fi

        break
    fi
    sleep 2
done

echo "meshtasticd container started (${RADIO_MODE} mode)"
echo "Verify with: meshtastic --host localhost --info"
