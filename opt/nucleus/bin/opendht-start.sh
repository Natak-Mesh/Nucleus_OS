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

# OpenDHT Startup Script
# Starts OpenDHT container with configuration from mesh.conf

# Source configuration
source /etc/nucleus/mesh.conf

# Check if OpenDHT is enabled
if [ "$OPENDHT_ENABLED" != "true" ]; then
    echo "OpenDHT is disabled in mesh.conf"
    exit 0
fi

# Stop existing container if running
if docker ps -a | grep -q dhtnode; then
    echo "Stopping existing OpenDHT container..."
    docker stop dhtnode 2>/dev/null
    docker rm dhtnode 2>/dev/null
fi

# Build bootstrap argument, excluding own IP
BOOTSTRAP_ARG=""
if [ -n "$OPENDHT_BOOTSTRAP_IPS" ]; then
    # Filter out own MESH_IP from bootstrap list
    FILTERED_IPS=$(echo "$OPENDHT_BOOTSTRAP_IPS" | tr ',' '\n' | grep -v "^$MESH_IP$" | tr '\n' ',' | sed 's/,$//')
    
    if [ -n "$FILTERED_IPS" ]; then
        # Add :4222 port to first IP and use as bootstrap
        FIRST_IP=$(echo "$FILTERED_IPS" | cut -d',' -f1)
        BOOTSTRAP_ARG="-b $FIRST_IP:4222"
    fi
fi

# Start OpenDHT container
echo "Starting OpenDHT container..."
docker run -d --network host --restart=unless-stopped --name dhtnode \
  ghcr.io/savoirfairelinux/opendht/opendht-alpine \
  dhtnode -p 4222 -D -s --proxyserver 8000 -n $OPENDHT_NETWORK_ID $BOOTSTRAP_ARG

echo "OpenDHT container started"
echo "Verify with: curl http://127.0.0.1:8000/"
