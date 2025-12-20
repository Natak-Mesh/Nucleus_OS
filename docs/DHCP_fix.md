# ===============================
# systemd-networkd AUTO-SWITCH DOC
# eth0 acts as WAN when DHCP exists
# eth0 acts as LAN gateway when no DHCP
# ===============================

# ===============================
# REFERENCE LINKS
# ===============================
# DHCP=                     https://www.freedesktop.org/software/systemd/man/systemd.network.html#DHCP=
# IPv4LL=                   https://www.freedesktop.org/software/systemd/man/systemd.network.html#IPv4LL=
# RouteMetric=              https://www.freedesktop.org/software/systemd/man/systemd.network.html#RouteMetric=
# LinkLocalAddressing=      https://www.freedesktop.org/software/systemd/man/systemd.network.html#LinkLocalAddressing=
# Address=                  https://www.freedesktop.org/software/systemd/man/systemd.network.html#Address=
# DHCPServer=               https://www.freedesktop.org/software/systemd/man/systemd.network.html#DHCPServer=
# [DHCPServer] Options      https://www.freedesktop.org/software/systemd/man/systemd.network.html#%5BDHCPServer%5D%20Section%20Options
# Drop-in files (.network.d) https://www.freedesktop.org/software/systemd/man/systemd.network.html#Drop-in%20files

# ===============================================================
# FILE 1 — /etc/systemd/network/10-eth0-dhcp.network
# PURPOSE: Try DHCP first. If DHCP succeeds → WAN (Internet).
# ===============================================================
[Match]
Name=eth0

[Network]
DHCP=ipv4          # Request DHCP address when plugged into a router
IPv4LL=yes         # Fall back to IPv4LL (169.254.x.x) when DHCP fails
RouteMetric=100    # Preferred when DHCP is successful (WAN)

# ===============================================================
# FILE 2 — /etc/systemd/network/20-eth0-static.network
# PURPOSE: Triggered when eth0 falls into IPv4LL (no DHCP detected).
# eth0 becomes LAN → provides mesh access + DHCP server to clients.
# ===============================================================
[Match]
Name=eth0
LinkLocalAddressing=ipv4   # Match only when interface is in IPv4LL (DHCP failed)

[Network]
Address=10.10.10.1/24      # Static LAN address for mesh gateway mode
DHCPServer=yes             # Turn on systemd’s built-in DHCP server
IPv4Forwarding=yes         # Route traffic between eth0 and mesh
RouteMetric=1000           # Never used as WAN route

# ===============================================================
# FILE 3 — /etc/systemd/network/20-eth0-static.network.d/dhcpserver.conf
# PURPOSE: Configure DHCP server pool used in LAN/mesh mode.
# ===============================================================
[DHCPServer]
PoolOffset=10    # Start issuing leases at 10.10.10.10
PoolSize=100     # Number of available leases
EmitDNS=no       # Downstream devices do not receive DNS by default

# ===============================================================
# HOW AUTO-SWITCHING WORKS
# ===============================================================
# 1. eth0 plugged into Internet router:
#    - Router provides DHCP
#    - 10-eth0-dhcp.network applies
#    - Pi gets Internet
#    - DHCP server stays OFF

# 2. eth0 plugged into device / laptop with no DHCP:
#    - DHCP attempt fails → IPv4LL assigned
#    - 20-eth0-static.network matches LinkLocalAddressing=ipv4
#    - eth0 becomes LAN gateway (10.10.10.1/24)
#    - DHCP server turns ON
#    - Device connected to eth0 joins the mesh automatically

# ===============================================================
# ISSUE WITH ABOVE APPROACH
# ===============================================================
# **CRITICAL PROBLEM:** The above configuration will NOT work as intended.
#
# 1. LinkLocalAddressing=ipv4 is NOT a valid [Match] section parameter
#    - It belongs in [Network] section, not [Match]
#    - Cannot be used to conditionally match interface state
#
# 2. Multiple .network files with same Name=eth0 will ALL apply simultaneously
#    - systemd-networkd applies ALL matching .network files, not just one
#    - Both DHCP config AND static config would be active at the same time
#    - DHCP server would run even in WAN mode → could interfere with existing router
#
# 3. systemd-networkd does not natively support conditional config based on DHCP success/failure

# ===============================================================
# RECOMMENDED SOLUTION: EVENT-DRIVEN WITH networkd-dispatcher
# ===============================================================

# ===============================
# ARCHITECTURE OVERVIEW
# ===============================
# Use networkd-dispatcher to hook into systemd-networkd state changes
# Scripts trigger automatically when interface state changes
# Clean separation: DHCP server ONLY runs when in LAN gateway mode

# ===============================
# COMPONENT 1: Base systemd-networkd Configuration
# ===============================
# Single /etc/systemd/network/10-eth0.network file:
#   - Enable DHCP=ipv4 for WAN mode
#   - Enable IPv4LL=yes for fallback
#   - Include static Address=10.10.10.1/24 for LAN mode
#   - DHCPServer= controlled externally (disabled by default)
#   - IPv4Forwarding configured by dispatcher scripts

# ===============================
# COMPONENT 2: networkd-dispatcher Hook Scripts
# ===============================
# Package: networkd-dispatcher (lightweight, event-driven)
# Location: /etc/networkd-dispatcher/

# SCRIPT A: routable.d/eth0-wan-mode (DHCP Success)
# Triggers: When eth0 gets routable DHCP address from router
# Actions:
#   - Ensure DHCP server is stopped/disabled
#   - Configure WAN routing/forwarding rules
#   - Set firewall for WAN mode
#   - Log state: "eth0 in WAN mode"

# SCRIPT B: degraded.d/eth0-lan-mode (DHCP Failure)
# Triggers: When eth0 falls back to IPv4LL (169.254.x.x)
# Actions:
#   - Start DHCP server on 10.10.10.1/24
#   - Configure LAN forwarding to mesh
#   - Set firewall for mesh gateway mode
#   - Log state: "eth0 in LAN gateway mode"

# ===============================
# COMPONENT 3: DHCP Server Control
# ===============================
# Option A: Use systemd-networkd built-in DHCPServer
#   - Toggle via networkctl or configuration drop-in
#   - Cleanest integration with networkd
#
# Option B: Use separate dnsmasq/dhcpcd
#   - Controlled by systemd service (started/stopped by scripts)
#   - More configuration flexibility

# ===============================
# STATE TRANSITIONS
# ===============================
# WAN Mode (eth0 connected to router):
#   - DHCP lease acquired
#   - No DHCP server running
#   - Internet access via eth0
#   - Mesh network isolated from WAN
#
# LAN Gateway Mode (eth0 connected to device):
#   - DHCP fails → IPv4LL assigned
#   - DHCP server starts on 10.10.10.1/24
#   - Connected device gets IP from range
#   - Device can access mesh network
#   - Forwarding enabled between eth0 and mesh interfaces

# ===============================
# BENEFITS OF THIS APPROACH
# ===============================
# ✓ True conditional behavior - no config conflicts
# ✓ DHCP server only runs when needed - prevents network interference
# ✓ Event-driven - responds immediately to state changes
# ✓ Clean logging - easy to troubleshoot
# ✓ Separation of concerns - network config vs. state logic

# ===============================
# TESTING PLAN
# ===============================
# Test 1: Plug eth0 into router with DHCP
#   - Verify WAN mode activates
#   - Verify DHCP server is OFF
#   - Verify internet access
#
# Test 2: Plug eth0 into laptop (no DHCP)
#   - Verify LAN mode activates
#   - Verify DHCP server starts
#   - Verify laptop gets 10.10.10.x address
#   - Verify laptop can access mesh
#
# Test 3: Switch between modes
#   - Monitor logs for clean state transitions
#   - Verify no lingering processes/routes
