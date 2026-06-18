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

# USB hub power cycle (opt-in via USB_HUB_POWER_CYCLE in mesh.conf)
# Recovers a RAK4631 (nRF52840) Meshtastic radio that boots into a HUNG state:
# the device enumerates cleanly on USB (/dev/ttyACM0 appears, no kernel/xhci
# errors) but the firmware never answers the serial handshake, so cot-bridge
# fails with "Timed out waiting for connection completion". A warm reboot does
# NOT clear this — VBUS is never cut — so only a real USB power cycle (which
# drops VBUS and hard-resets the chip) recovers it. Confirmed reproducible on a
# cold boot on affected nodes 2026-06-17. See:
#   docs/meshtastic/meshtastic_radio_locking_up.md
#
# IMPORTANT (ordering): hub 1-1 carries BOTH the radio (1-1.4) and the wifi
# mesh adapter (wlan1 / 1-1.2). This block MUST run BEFORE wlan1 is configured
# below, because the cycle resets wlan1 too — we want it (re)built fresh
# afterward, not torn down after the mesh is already up.
#
# IMPORTANT (no unbind/bind): we do a CLEAN power off/on ONLY. The old code did
# a driver unbind/bind "force re-enumeration" ~4s after power-on, which yanked
# the nRF52840 off the bus while its firmware was still booting and RE-HANGED
# the radio. That step is removed. Instead we settle, then VERIFY the firmware
# actually answers, and re-cycle up to USB_CYCLE_MAX_ATTEMPTS times if not.
if [ "${USB_HUB_POWER_CYCLE}" = "true" ]; then
    if command -v uhubctl &> /dev/null; then
        ACM_DEV=/dev/ttyACM0
        USB_CYCLE_MAX_ATTEMPTS=${USB_CYCLE_MAX_ATTEMPTS:-3}
        USB_CYCLE_SETTLE=${USB_CYCLE_SETTLE:-10}

        radio_responds() {
            # Returns 0 only if the Meshtastic firmware actually answers on the
            # serial port. Device-node existence is NOT sufficient — a hung
            # radio still enumerates and creates /dev/ttyACM0 — so we perform a
            # real handshake via the meshtastic CLI. The port is free here
            # because cot-bridge.service starts After=mesh-start.service.
            [ -e "$ACM_DEV" ] || return 1
            timeout 20 meshtastic --port "$ACM_DEV" --info >/dev/null 2>&1
        }

        radio_ok=false
        for attempt in $(seq 1 "$USB_CYCLE_MAX_ATTEMPTS"); do
            echo "Power-cycling USB hub 1-1 to recover Meshtastic radio (attempt $attempt/$USB_CYCLE_MAX_ATTEMPTS)..."
            uhubctl -a off -l 1-1
            sleep 3
            uhubctl -a on -l 1-1

            # Let the nRF52840 firmware finish booting before probing it.
            echo "Waiting ${USB_CYCLE_SETTLE}s for radio firmware to settle..."
            sleep "$USB_CYCLE_SETTLE"

            if radio_responds; then
                echo "Meshtastic radio responded on $ACM_DEV (attempt $attempt)."
                radio_ok=true
                break
            fi
            echo "Radio did not respond after cycle $attempt — retrying..."
        done

        if [ "$radio_ok" != "true" ]; then
            echo "WARNING: Meshtastic radio still not responding after ${USB_CYCLE_MAX_ATTEMPTS} power cycles."
        fi

        # Ensure wlan1 has re-appeared after the hub power cycle before we
        # continue to mesh configuration below (mt76x0u needs a moment).
        for i in $(seq 1 15); do
            ip link show wlan1 &>/dev/null && break
            echo "Waiting for wlan1... ($i/15)"
            sleep 1
        done
        if ip link show wlan1 &>/dev/null; then
            echo "USB hub power cycle complete. wlan1 present; continuing to mesh setup."
        else
            echo "WARNING: wlan1 did not appear after USB power cycle!"
        fi
    else
        echo "WARNING: uhubctl not installed — skipping USB hub power cycle."
        echo "Install with: sudo apt install uhubctl"
    fi
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
    # USB power cycle can change phy number; detect dynamically when enabled
    if [ "${USB_HUB_POWER_CYCLE}" = "true" ]; then
        MESH_PHY=$(iw dev wlan1 info | grep wiphy | awk '{print "phy"$2}')
    else
        MESH_PHY=phy0
    fi
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

# Cellular NAT (Waveshare SIM7600G-H) — uncomment on nodes with cellular modem
# Required for mesh nodes to route internet traffic through this node's cellular
# connection (wwan0). Without this, outbound packets retain private 10.20.x.x
# source IPs which the carrier will drop. Only enable on cellular-equipped nodes.
# See: docs/cellular_waveshare/sim7600g_setup.md
# iptables -t nat -C POSTROUTING -o wwan0 -j MASQUERADE 2>/dev/null || \
#     iptables -t nat -A POSTROUTING -o wwan0 -j MASQUERADE

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
    # Voice multicast (239.255.255.0/24 covers all voice groups: general, discovery, channels)
    iptables -t mangle -C PREROUTING -i br-lan -d 239.255.255.0/24 -j TTL --ttl-set $MESH_MCAST_TTL 2>/dev/null || \
        iptables -t mangle -A PREROUTING -i br-lan -d 239.255.255.0/24 -j TTL --ttl-set $MESH_MCAST_TTL
    echo "Multicast TTL set to ${MESH_MCAST_TTL} for CoT, Discovery, and Voice on br-lan"
fi

# Restart smcroute after USB hub power cycle so it registers wlan1 as a multicast VIF
# (power cycle delays USB re-enumeration, so smcroute misses wlan1 at boot)
if [ "${USB_HUB_POWER_CYCLE}" = "true" ] && systemctl is-active --quiet smcroute; then
    systemctl restart smcroute
    echo "Restarted smcroute — wlan1 registered as multicast VIF"
fi

# Start OpenDHT if enabled
if [ -f /opt/nucleus/bin/opendht-start.sh ]; then
    /opt/nucleus/bin/opendht-start.sh
fi

# Restart cot-bridge so it detects br-lan subnet for TX source filtering.
# cot-bridge may start before br-lan has an IP (race condition), which disables
# the source filter and causes WiFi→LoRa rebroadcast of other nodes' traffic.
# Backgrounded (&) so it doesn't block mesh-start from completing.
if systemctl is-enabled --quiet cot-bridge 2>/dev/null; then
    ( sleep 5 && systemctl restart cot-bridge ) &
    echo "Scheduled cot-bridge restart in background"
fi
