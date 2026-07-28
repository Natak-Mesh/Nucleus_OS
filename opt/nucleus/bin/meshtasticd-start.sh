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
# Starts meshtasticd Docker container when MESHTASTICD_ENABLED=true.
# meshtasticd exposes a TCP API on localhost:4403 for cot_bridge.py.
# When MESHTASTICD_ENABLED=false (USB serial nodes), this script cleans
# up any stale container and exits.

# Source configuration
source /etc/nucleus/mesh.conf

# Helper: stop and remove any existing meshtasticd container so it doesn't
# hold /dev/ttyACM0 via Docker's --restart=unless-stopped policy.
_cleanup_container() {
    if docker ps -a --format '{{.Names}}' 2>/dev/null | grep -q "^meshtasticd$"; then
        echo "meshtasticd: stopping stale container..."
        docker stop meshtasticd 2>/dev/null
        docker rm meshtasticd 2>/dev/null
    fi
}

# Check if meshtasticd is enabled
if [ "$MESHTASTICD_ENABLED" != "true" ]; then
    echo "meshtasticd is disabled in mesh.conf"
    _cleanup_container
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

# Named volume for persistent radio config (region, channel, PSK, node DB).
# Without this, docker rm + docker run creates a new anonymous volume each
# time, wiping all radio settings on every reboot.
MESHTASTICD_VOLUME="meshtasticd-data"

# Start meshtasticd container
echo "Starting meshtasticd container..."
docker run -d \
    --name "${MESHTASTICD_CONTAINER}" \
    --privileged \
    --net=host \
    --restart=unless-stopped \
    -v "${MESHTASTICD_DIR}/config.yaml:/etc/meshtasticd/config.yaml" \
    -v "${MESHTASTICD_DIR}/config.d:/etc/meshtasticd/config.d" \
    -v "${MESHTASTICD_VOLUME}:/var/lib/meshtasticd" \
    "${MESHTASTICD_IMAGE}"

# Wait for the API to come up, then configure the radio
HOSTNAME_FULL=$(hostname)
HOSTNAME_SHORT=$(hostname | cut -c1-4)

echo "Waiting for meshtasticd API..."
for i in $(seq 1 30); do
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

echo "meshtasticd container started"
echo "Verify with: meshtastic --host localhost --info"
