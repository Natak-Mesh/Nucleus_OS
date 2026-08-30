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

# UFW mesh-fabric setup
#
# UFW defaults to deny (incoming) and deny (routed). Without explicit rules,
# this silently drops ALL traffic on the trusted mesh interfaces — 802.11s
# mesh (wlan1), the local AP/bridge (br-lan), and the EUD client AP (wlan0) —
# which makes the mesh look dead even though the RF link and peers are up.
#
# These nodes fully trust their own mesh fabric, so we allow ALL traffic on
# those interfaces (both incoming and forwarded/routed) rather than
# enumerating ports. That single decision covers every current and future
# mesh service without per-port maintenance:
#   - babeld routing            (UDP 6696)
#   - ATAK CoT multicast        (UDP 6969 -> 239.2.3.1)
#   - OpenDHT / Jami            (UDP 4222, node-to-node)
#   - Reticulum LAN TCP + Auto  (TCP 4242, UDP multicast)
#   - OpenVLM mesh PTT voice    (multicast on wlan1)
#
# Every rule below is ALLOW-only and idempotent (UFW dedupes identical rules),
# so this script can NEVER block existing access and is safe to re-run.
#
# Ports exposed on untrusted/WAN interfaces (eth0, tailscale) — SSH, TAK,
# mediamtx, mumble, etc. — are intentionally NOT managed here; those remain
# per-node/optional and are configured separately.

set -e

if ! command -v ufw >/dev/null 2>&1; then
    echo "ufw not installed — skipping mesh firewall setup"
    exit 0
fi

# Management: never lock ourselves out of SSH (asserted, not assumed)
ufw allow 22/tcp

# EUD access: wlan0 is the client AP; allow its traffic in and forwarded
ufw allow in on wlan0
ufw route allow in on wlan0
ufw route allow out on wlan0

# 802.11s mesh (wlan1) + local bridge (br-lan): the trusted mesh fabric.
# These are the interfaces the default-deny policy was silently dropping.
ufw allow in on wlan1
ufw allow in on br-lan
ufw route allow in on wlan1
ufw route allow in on br-lan
ufw route allow out on wlan1
ufw route allow out on br-lan

ufw reload
echo "ufw mesh fabric rules applied (wlan0/wlan1/br-lan trusted; SSH preserved)"
