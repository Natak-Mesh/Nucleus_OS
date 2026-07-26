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
# Starts meshtasticd Docker container for RAK Pi HAT LoRa radio
# Follows the same pattern as opendht-start.sh

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

# Write config.yaml with MAC address
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

# Stop existing container if running
if docker ps -a | grep -q "${MESHTASTICD_CONTAINER}"; then
    echo "Stopping existing meshtasticd container..."
    docker stop "${MESHTASTICD_CONTAINER}" 2>/dev/null
    docker rm "${MESHTASTICD_CONTAINER}" 2>/dev/null
fi

# Start meshtasticd container
echo "Starting meshtasticd container..."
docker run -d \
    --name "${MESHTASTICD_CONTAINER}" \
    --privileged \
    --net=host \
    --restart=unless-stopped \
    -v "${MESHTASTICD_DIR}/config.yaml:/etc/meshtasticd/config.yaml" \
    -v "${MESHTASTICD_DIR}/config.d:/etc/meshtasticd/config.d" \
    "${MESHTASTICD_IMAGE}"

# Wait for the API to come up, then set node name from hostname
HOSTNAME_FULL=$(hostname)
HOSTNAME_SHORT=$(hostname | cut -c1-4)

echo "Waiting for meshtasticd API..."
for i in $(seq 1 15); do
    if meshtastic --host localhost --info >/dev/null 2>&1; then
        echo "meshtasticd API is up"
        meshtastic --host localhost --set-owner "${HOSTNAME_FULL}" --set-owner-short "${HOSTNAME_SHORT}"
        echo "meshtasticd: node name set to ${HOSTNAME_FULL} (${HOSTNAME_SHORT})"
        break
    fi
    sleep 2
done

echo "meshtasticd container started"
echo "Verify with: meshtastic --host localhost --info"
