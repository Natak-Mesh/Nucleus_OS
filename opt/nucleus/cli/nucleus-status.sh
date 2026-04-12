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
#            System Status Page             #
#############################################

# One-page system summary for Nucleus nodes.
# Shows node identity, resources, interfaces, services, and top memory consumers.

source /etc/nucleus/mesh.conf 2>/dev/null

# --- Colors ---
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[0;33m'
CYAN='\033[0;36m'
BOLD='\033[1m'
DIM='\033[2m'
RESET='\033[0m'

# --- Helper functions ---

# Check if a systemd service is active
service_status() {
    local svc=$1
    local label=${2:-$1}
    if systemctl is-active --quiet "$svc" 2>/dev/null; then
        printf "  ${GREEN}●${RESET} %-18s" "$label"
    else
        printf "  ${RED}○${RESET} %-18s" "$label"
    fi
}

# Get IP for an interface (first IPv4)
iface_ip() {
    ip -4 addr show "$1" 2>/dev/null | grep -oP 'inet \K[0-9.]+' | head -1
}

# Check if interface is up
iface_up() {
    ip link show "$1" 2>/dev/null | grep -q 'state UP\|state DORMANT\|state UNKNOWN'
}

# --- Node Identity ---
HOSTNAME=$(hostname)
SERIAL=$(echo "$HOSTNAME" | grep -oP '^\d+' || echo "?")
MESH_IP_VAL=${MESH_IP:-"not set"}
UPTIME=$(uptime -p 2>/dev/null | sed 's/^up //')

echo ""
printf "${BOLD}═══════════════════════════════════════════${RESET}\n"
printf "${BOLD}   Nucleus OS — ${CYAN}${HOSTNAME}${RESET}\n"
printf "${BOLD}═══════════════════════════════════════════${RESET}\n"
echo ""
printf "  ${DIM}Mesh IP:${RESET}  %-18s  ${DIM}Uptime:${RESET} %s\n" "$MESH_IP_VAL" "$UPTIME"
echo ""

# --- CPU temp (Raspberry Pi) ---
if [ -f /sys/class/thermal/thermal_zone0/temp ]; then
    cpu_temp=$(awk '{printf "%.1f", $1/1000}' /sys/class/thermal/thermal_zone0/temp)
    temp_color="$GREEN"
    temp_int=${cpu_temp%.*}
    [ "$temp_int" -ge 65 ] && temp_color="$YELLOW"
    [ "$temp_int" -ge 80 ] && temp_color="$RED"
    printf "  ${BOLD}Temp${RESET}  ${temp_color}${cpu_temp}°C${RESET}\n"
fi

echo ""

# --- Network Interfaces ---
printf "  ${BOLD}Interfaces${RESET}\n"

for iface in wlan1 br-lan eth0 tailscale0; do
    ip_addr=$(iface_ip "$iface")
    if iface_up "$iface"; then
        if [ -n "$ip_addr" ]; then
            printf "  ${GREEN}▲${RESET} %-12s %s\n" "$iface" "$ip_addr"
        else
            printf "  ${YELLOW}▲${RESET} %-12s ${DIM}no ip${RESET}\n" "$iface"
        fi
    else
        printf "  ${RED}▼${RESET} %-12s ${DIM}down${RESET}\n" "$iface"
    fi
done

# Show mesh peers count if wlan1 is up
if iface_up wlan1; then
    peer_count=$(iw dev wlan1 station dump 2>/dev/null | grep -c "^Station" || echo 0)
    printf "  ${DIM}  └─ %d mesh peer(s)${RESET}\n" "$peer_count"
fi

echo ""

# --- Key Services ---
printf "  ${BOLD}Services${RESET}\n"

service_status "babeld"       "babeld"
service_status "hostapd"      "hostapd"
echo ""
service_status "smcroute"     "smcroute"
service_status "rnsd"         "rnsd"
echo ""
service_status "tailscaled"   "tailscale"
service_status "mesh-web"     "web-ui"
echo ""

# Check OpenDHT via proxy endpoint (avoids docker permission issues)
if curl -s -o /dev/null -w '' --connect-timeout 1 http://127.0.0.1:8000/ 2>/dev/null; then
    printf "  ${GREEN}●${RESET} %-18s" "opendht"
else
    printf "  ${RED}○${RESET} %-18s" "opendht"
fi
echo ""

echo ""

# --- Top RAM Usage (grouped by service) ---
printf "  ${BOLD}Top RAM Usage${RESET}\n"

# Group RSS by command basename, show top 5
ps -eo rss,comm --no-headers 2>/dev/null | \
    awk '{cmd=$2; mem[cmd]+=$1} END {for(c in mem) printf "%d %s\n", mem[c]/1024, c}' | \
    sort -rn | head -5 | \
    while read -r mb name; do
        printf "  %6s MB  %s\n" "$mb" "$name"
    done

echo ""
printf "${DIM}  Press any key to return...${RESET}"
read -rsn1
