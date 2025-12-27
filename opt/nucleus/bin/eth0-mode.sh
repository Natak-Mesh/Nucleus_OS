#!/bin/bash

#############################################
#        N A T A K   -   Nucleus OS         #
#           eth0 Mode Control Script        #
#############################################

NETWORK_FILE="/etc/systemd/network/40-eth0-lan.network"
CONFIG_FILE="/etc/nucleus/eth0-default-mode"

show_usage() {
    cat <<EOF
Usage: $(basename $0) <command>

Commands:
  wan              Switch eth0 to WAN mode (DHCP from router)
  lan              Switch eth0 to LAN mode (bridge to br-lan)
  set-default wan  Set WAN as default mode at boot
  set-default lan  Set LAN as default mode at boot
  status           Show current mode and default setting

Examples:
  $(basename $0) wan              # Switch to WAN mode now
  $(basename $0) set-default lan  # Make LAN the default mode
  $(basename $0) status           # Check current configuration
EOF
}

get_current_mode() {
    if grep -q "Bridge=br-lan" "$NETWORK_FILE" 2>/dev/null; then
        echo "lan"
    else
        echo "wan"
    fi
}

get_default_mode() {
    if [ -f "$CONFIG_FILE" ]; then
        cat "$CONFIG_FILE"
    else
        echo "wan"
    fi
}

switch_to_wan() {
    echo "Switching eth0 to WAN mode (DHCP)..."
    
    # Update network config file - set DHCP
    cat > "$NETWORK_FILE" <<EOF
[Match]
Name=eth0

[Network]
DHCP=ipv4
IPv4Forwarding=yes
EOF
    
    # Apply immediately
    ip link set eth0 nomaster 2>/dev/null
    systemctl restart systemd-networkd
    
    # Wait for DHCP to acquire an address
    echo "Waiting for DHCP address..."
    sleep 5
    
    # Add MASQUERADE for internet gateway sharing
    iptables -t nat -C POSTROUTING -o eth0 -j MASQUERADE 2>/dev/null || \
        iptables -t nat -A POSTROUTING -o eth0 -j MASQUERADE
    
    echo "✓ eth0 is now in WAN mode with NAT enabled"
}

switch_to_lan() {
    echo "Switching eth0 to LAN mode (bridge to br-lan)..."
    
    # Remove MASQUERADE rule if present
    iptables -t nat -D POSTROUTING -o eth0 -j MASQUERADE 2>/dev/null || true
    
    # Update network config file - add Bridge line
    cat > "$NETWORK_FILE" <<EOF
[Match]
Name=eth0

[Network]
Bridge=br-lan
EOF
    
    # Apply immediately
    ip link set eth0 master br-lan 2>/dev/null
    systemctl restart systemd-networkd
    
    echo "✓ eth0 is now in LAN mode (bridged to br-lan)"
}

set_default() {
    local mode=$1
    echo "$mode" > "$CONFIG_FILE"
    echo "✓ Default mode set to: $mode"
    echo "This will take effect on next boot"
}

show_status() {
    local current=$(get_current_mode)
    local default=$(get_default_mode)
    
    echo "eth0 Mode Status"
    echo "================"
    echo "Current mode:  $current"
    echo "Default mode:  $default"
    echo ""
    
    if [ "$current" = "wan" ]; then
        echo "eth0 is currently accepting DHCP from router"
    else
        echo "eth0 is currently bridged to br-lan"
    fi
}

# Main script logic
case "${1:-}" in
    wan)
        switch_to_wan
        ;;
    lan)
        switch_to_lan
        ;;
    set-default)
        if [ "$2" = "wan" ] || [ "$2" = "lan" ]; then
            set_default "$2"
        else
            echo "Error: set-default requires 'wan' or 'lan'"
            echo ""
            show_usage
            exit 1
        fi
        ;;
    status)
        show_status
        ;;
    *)
        show_usage
        exit 1
        ;;
esac
