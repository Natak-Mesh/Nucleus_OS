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


# Source configuration
source /etc/nucleus/mesh.conf

sysctl -w net.ipv4.ip_forward=1



# Set interfaces to not be managed by NetworkManager
nmcli device set eth0 managed no
nmcli device set wlan1 managed no
nmcli device set wlan0 managed no
nmcli device set br-lan managed no

# Configure mesh interface
ifconfig wlan1 down
iw reg set "US"
iw dev wlan1 set type managed
iw dev wlan1 set 4addr on
iw dev wlan1 set type mesh
iw dev wlan1 set meshid $MESH_NAME
iw dev wlan1 set channel $MESH_CHANNEL HT20
ifconfig wlan1 up

# Establish encryption with wpa_supplicant config
wpa_supplicant -B -i wlan1 -c /etc/wpa_supplicant/wpa_supplicant-wlan1-encrypt.conf

# Wait for encryption to be established
sleep 15

# Disable HWMP L2 forwarding — babeld handles all routing at L3
# wpa_supplicant mesh_fwding=0 is set in the config but some drivers ignore it,
# so we force it here after the mesh is joined.
iw dev wlan1 set mesh_param mesh_fwding=0

# Apply IP address manually (systemd-networkd would reset mesh mode)
ip addr add $MESH_IP/24 dev wlan1
ip -6 addr add $MESH_IPV6_LL/64 dev wlan1

# Set 802.11s mesh TTL for multi-hop multicast/broadcast forwarding
# 802.11s handles multi-hop natively at Layer 2 with dedup (RMC in mac80211/rx.c).
# mesh_ttl controls how many hops multicast frames are forwarded by mesh points.
# mesh_element_ttl controls TTL for path selection elements (PREQ/PREP/PERR).
# The kernel default is 31 — far too high. Configurable via MESH_802_TTL in mesh.conf.
# See: docs/congestion_collision_tuning/mcast_storm_correction.md
if [ "${MESH_802_TTL:-0}" -gt 0 ]; then
    iw dev wlan1 set mesh_param mesh_ttl=$MESH_802_TTL
    iw dev wlan1 set mesh_param mesh_element_ttl=$MESH_802_TTL
    echo "802.11s mesh TTL set to ${MESH_802_TTL} (${MESH_802_TTL}-hop multicast reach)"
fi

# Enable RTS/CTS for collision avoidance (helps in congested/hidden node scenarios)
# Configurable via MESH_RTS_THRESHOLD in mesh.conf (0=disabled, 500=recommended for 3+ nodes)
if [ "${MESH_RTS_THRESHOLD:-0}" -gt 0 ]; then
    MESH_PHY=phy0
    iw phy $MESH_PHY set rts $MESH_RTS_THRESHOLD
    echo "RTS/CTS enabled on $MESH_PHY with threshold: ${MESH_RTS_THRESHOLD} bytes"
fi

# Restore DNS configuration
sleep 2
echo "nameserver 8.8.8.8" > /etc/resolv.conf
echo "nameserver 8.8.4.4" >> /etc/resolv.conf

# Enable NAT for internet gateway sharing (WAN mode default)
# Check if rule exists before adding to avoid duplicates
iptables -t nat -C POSTROUTING -o eth0 -j MASQUERADE 2>/dev/null || \
    iptables -t nat -A POSTROUTING -o eth0 -j MASQUERADE


# Bump multicast TTL on locally-originated traffic (br-lan ingress)
# ATAK sends CoT/Discovery/Voice with low TTL (often TTL=1). The kernel won't
# forward multicast unless TTL > threshold (default 1), so TTL=1 packets die
# before smcroute can bridge them from br-lan to wlan1. This mangle rule sets
# TTL to MESH_MCAST_TTL so packets survive the L3 forwards at each node.
# Only applies to br-lan ingress — traffic arriving from the mesh on wlan1
# already has adequate TTL and is not modified.
# Configurable via MESH_MCAST_TTL in mesh.conf.
if [ "${MESH_MCAST_TTL:-0}" -gt 0 ]; then
    iptables -t mangle -C PREROUTING -i br-lan -d 239.2.3.1/32 -j TTL --ttl-set $MESH_MCAST_TTL 2>/dev/null || \
        iptables -t mangle -A PREROUTING -i br-lan -d 239.2.3.1/32 -j TTL --ttl-set $MESH_MCAST_TTL
    iptables -t mangle -C PREROUTING -i br-lan -d 224.10.10.1/32 -j TTL --ttl-set $MESH_MCAST_TTL 2>/dev/null || \
        iptables -t mangle -A PREROUTING -i br-lan -d 224.10.10.1/32 -j TTL --ttl-set $MESH_MCAST_TTL
    echo "Multicast TTL set to ${MESH_MCAST_TTL} for CoT and Discovery on br-lan"
fi




# NOTE: This script is restarted once per boot by mesh-start-retry.service.
# The mesh does not come up on the initial boot run of this script, but a
# restart of mesh-start.service always brings it up. mesh-start-retry waits
# 30s after mesh-start.service finishes, then restarts it once.
# See: /etc/systemd/system/mesh-start-retry.service
