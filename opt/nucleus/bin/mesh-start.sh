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
#          (with USB hub power cycle)       #
#############################################
#
# mesh-start-2.sh — Variant of mesh-start.sh that power-cycles the USB
# hub before configuring the WiFi mesh. This is a WORKAROUND for a
# node-specific issue where the Meshtastic radio (RAK4631 / nRF52840)
# firmware crashes during boot, leaving it unresponsive on both serial
# and Bluetooth.
#
# The USB hub power cycle resets all devices on hub 1-1 (including the
# WiFi mesh adapter mt76x0u on port 2 and the Meshtastic radio on port 4).
# Because this runs BEFORE any WiFi mesh configuration, no mesh state is
# lost — the WiFi adapter is configured fresh afterward.
#
# Requires: uhubctl (sudo apt install uhubctl)
#
# See: docs/meshtastic/meshtastic_radio_locking_up.md for full investigation.
#


# Source configuration
source /etc/nucleus/mesh.conf

sysctl -w net.ipv4.ip_forward=1

# ─────────────────────────────────────────────────────────────────────
# USB HUB POWER CYCLE — Meshtastic radio lockup workaround
# ─────────────────────────────────────────────────────────────────────
# The RAK4631 Meshtastic radio crashes during the Pi's USB initialization
# on boot. Power-cycling the USB hub (1-1) resets all USB devices,
# recovering the Meshtastic radio. The WiFi adapter also resets, but
# since we haven't configured the mesh yet, nothing is lost.
#
# This must happen BEFORE any wlan1 configuration below.
# ─────────────────────────────────────────────────────────────────────
if command -v uhubctl &> /dev/null; then
    echo "Power-cycling USB hub 1-1 to recover Meshtastic radio..."
    uhubctl -a off -l 1-1
    sleep 3
    uhubctl -a on -l 1-1
    # Wait for USB devices to re-enumerate after power cycle
    sleep 5
    echo "USB hub power cycle complete. Devices re-enumerated."
else
    echo "WARNING: uhubctl not installed — skipping USB hub power cycle."
    echo "Install with: sudo apt install uhubctl"
fi

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
# Detect correct phy dynamically (USB power cycle can change phy number)
MESH_PHY=$(iw dev wlan1 info | grep wiphy | awk '{print "phy"$2}')
if [ "${MESH_RTS_THRESHOLD:-0}" -gt 0 ] && [ -n "$MESH_PHY" ]; then
    iw phy $MESH_PHY set rts $MESH_RTS_THRESHOLD
    echo "RTS/CTS enabled on $MESH_PHY with threshold: ${MESH_RTS_THRESHOLD} bytes"
fi

# Restore DNS configuration
sleep 2
echo "nameserver 8.8.8.8" > /etc/resolv.conf
echo "nameserver 8.8.4.4" >> /etc/resolv.conf

# rnsd is now managed by its own systemd service (rnsd.service)

# Start mediamtx (required for TAKserver video)
# nohup runuser -l natak -c 'cd /opt/nucleus/bin/mediamtx && ./mediamtx' > /var/log/mediamtx.log 2>&1 &
# MEDIAMTX_PID=$!
# echo "Started mediamtx with PID: $MEDIAMTX_PID"

# sleep 2

# Enable NAT for internet gateway sharing (WAN mode default)
# Check if rule exists before adding to avoid duplicates
iptables -t nat -C POSTROUTING -o eth0 -j MASQUERADE 2>/dev/null || \
    iptables -t nat -A POSTROUTING -o eth0 -j MASQUERADE

# Cap multicast TTL to prevent echo storms with 3+ mesh nodes
# Echo routing (wlan1 → wlan1 br-lan) enables multi-hop but each hop costs 2 TTL
# (one for forward, one for echo). Configurable via MESH_MCAST_TTL in mesh.conf.
if [ "${MESH_MCAST_TTL:-0}" -gt 0 ]; then
    iptables -t mangle -C PREROUTING -i br-lan -d 239.2.3.1/32 -j TTL --ttl-set $MESH_MCAST_TTL 2>/dev/null || \
        iptables -t mangle -A PREROUTING -i br-lan -d 239.2.3.1/32 -j TTL --ttl-set $MESH_MCAST_TTL
    iptables -t mangle -C PREROUTING -i br-lan -d 224.10.10.1/32 -j TTL --ttl-set $MESH_MCAST_TTL 2>/dev/null || \
        iptables -t mangle -A PREROUTING -i br-lan -d 224.10.10.1/32 -j TTL --ttl-set $MESH_MCAST_TTL
    echo "Multicast TTL capped to ${MESH_MCAST_TTL} ($((MESH_MCAST_TTL / 2))-hop reach)"
fi

# Restart smcroute so it registers wlan1 as a multicast VIF
# When smcroute.service starts at boot, wlan1 may still be in NO-CARRIER/DORMANT
# state (especially after USB hub power cycle), causing the kernel to reject
# wlan1 as a multicast virtual interface. Without this, ATAK multicast
# (239.2.3.1 CoT, 224.10.10.1 discovery) cannot cross br-lan <-> wlan1.
if systemctl is-active --quiet smcroute; then
    systemctl restart smcroute
    echo "Restarted smcroute — wlan1 registered as multicast VIF"
fi

# Start OpenDHT if enabled
if [ -f /opt/nucleus/bin/opendht-start.sh ]; then
    /opt/nucleus/bin/opendht-start.sh
fi
