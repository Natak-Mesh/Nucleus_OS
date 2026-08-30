#!/usr/bin/env python3
"""
Natak Mesh - Web Interface
Simple Flask app for monitoring mesh network connections

ROUTE FILTERING:
The "Gateway to" section in the web interface filters routes to reduce clutter:
- Removes Docker networks (172.16.0.0/12) - internal container networks
- Removes the mesh backbone network (10.20.1.0/24) - redundant since already connected
- Keeps client-facing LAN networks (10.20.x.0/24 where x != 1)
- Keeps internet gateway routes (0.0.0.0/0) if present
"""

from flask import Flask, render_template, jsonify, request
import socket
import subprocess
import re
from datetime import datetime
import threading
import os
import sys
import glob
import time
import ipaddress
import urllib.request as _urlreq
import urllib.error as _urlerr

# Add meshtastic module to path
sys.path.insert(0, '/opt/nucleus/meshtastic')

app = Flask(__name__)

# Register meshtastic API blueprint
try:
    from meshtastic_api import meshtastic_bp
    app.register_blueprint(meshtastic_bp)
except ImportError as e:
    print(f"Warning: Could not load meshtastic module: {e}")

# Configuration
BABELD_HOST = 'localhost'
BABELD_PORT = 33123
REFRESH_INTERVAL = 5  # seconds
REPO_DIR = '/home/natak/Nucleus_OS'  # Nucleus_OS git repo (source of updates)
DISCONNECTED_DISPLAY_TIME = 60  # seconds

# Store node history
node_history = {}

# Channel scanning state
scan_state = {
    'status': 'idle',  # idle, running, complete, error
    'progress': 0,
    'duration': 60,
    'results': None,
    'error': None,
    'process': None,
    'start_time': None
}
scan_lock = threading.Lock()

# Node update state (nucleus-update.sh runs in the background; the web UI polls
# /api/update/progress to stream the live log, mirroring the channel scan flow).
update_state = {
    'status': 'idle',      # idle, running, done, error
    'running': False,
    'returncode': None,
    'message': '',
    'log': [],
    'start_time': None,
}
update_lock = threading.Lock()

# Absolute path to the node update script (installed by deploy.sh).
NUCLEUS_UPDATE_SCRIPT = '/opt/nucleus/bin/nucleus-update.sh'

# Human-readable outcome for each nucleus-update.sh exit code.
UPDATE_EXIT_MESSAGES = {
    0: 'Update applied successfully. A reboot is recommended.',
    1: 'Already up to date - no changes pulled.',
    2: 'Offline - could not reach the git remote.',
    3: 'Local changes present (dirty working tree) - update stopped.',
    4: 'git pull failed.',
    5: 'install-packages.sh failed.',
    6: 'deploy.sh failed.',
    7: 'config_generation.sh failed.',
    8: 'Environment error (repo missing or not a git repo).',
}


def query_babeld():
    """Query babeld monitoring interface"""
    try:
        sock = socket.socket(socket.AF_INET6, socket.SOCK_STREAM)
        sock.settimeout(5)  # 5 second timeout
        sock.connect(('::1', BABELD_PORT))
        
        # Read banner (ends with first "ok\n")
        banner = b''
        while b'ok\n' not in banner:
            banner += sock.recv(1024)
        
        # Send dump command
        sock.sendall(b'dump\n')
        
        # Read dump output (ends with second "ok\n")
        data = b''
        while True:
            chunk = sock.recv(4096)
            if not chunk:
                break
            data += chunk
            # Look for the final "ok\n" at end of dump
            if data.endswith(b'ok\n'):
                break
        
        sock.close()
        return data.decode('utf-8')
    except Exception as e:
        print(f"Error querying babeld: {e}")
        return ""


def get_channel_utilization():
    """Get current channel utilization from iw survey dump for the in-use channel"""
    try:
        result = subprocess.run(['iw', 'dev', 'wlan1', 'survey', 'dump'],
                              capture_output=True, text=True)
        in_use = False
        active_time = 0
        busy_time = 0
        channel_freq = None

        for line in result.stdout.split('\n'):
            line = line.strip()
            if 'frequency:' in line and '[in use]' in line:
                in_use = True
                match = re.search(r'frequency:\s+(\d+)', line)
                if match:
                    channel_freq = int(match.group(1))
            elif in_use:
                if 'channel active time:' in line:
                    match = re.search(r'(\d+)', line)
                    if match:
                        active_time = int(match.group(1))
                elif 'channel busy time:' in line:
                    match = re.search(r'(\d+)', line)
                    if match:
                        busy_time = int(match.group(1))
                elif 'channel transmit time:' in line:
                    # Done parsing this entry
                    break

        if active_time > 0 and channel_freq:
            busy_pct = round((busy_time / active_time) * 100)
            # Convert frequency to channel number (2.4GHz)
            if 2412 <= channel_freq <= 2484:
                channel = (channel_freq - 2407) // 5
            else:
                channel = channel_freq  # fallback to freq

            # Classify quality (inverted - lower busy is better)
            if busy_pct < 30:
                quality = 'excellent'
            elif busy_pct < 50:
                quality = 'good'
            elif busy_pct < 70:
                quality = 'fair'
            else:
                quality = 'poor'

            return {
                'channel': channel,
                'frequency': channel_freq,
                'busy_pct': busy_pct,
                'quality': quality
            }
        return None
    except Exception as e:
        print(f"Error getting channel utilization: {e}")
        return None


def get_ipv6_neighbors():
    """Get IPv6 neighbor cache (link-local to MAC mapping)"""
    try:
        result = subprocess.run(['ip', '-6', 'neigh', 'show', 'dev', 'wlan1'],
                              capture_output=True, text=True)
        neighbors = {}
        for line in result.stdout.strip().split('\n'):
            if not line:
                continue
            match = re.match(r'(\S+)\s+lladdr\s+(\S+)', line)
            if match:
                ipv6, mac = match.groups()
                neighbors[ipv6] = mac
        return neighbors
    except Exception as e:
        print(f"Error getting IPv6 neighbors: {e}")
        return {}


def get_babel_nexthops():
    """Get IPv4 next-hop addresses from Babel routes in kernel routing table"""
    try:
        result = subprocess.run(['ip', 'route', 'show', 'proto', 'babel', 'dev', 'wlan1'],
                              capture_output=True, text=True)
        nexthops = []
        for line in result.stdout.strip().split('\n'):
            if not line:
                continue
            # Parse: 10.20.2.0/24 via 10.20.1.11 dev wlan1 proto babel onlink
            match = re.search(r'via\s+(\S+)', line)
            if match:
                nexthop_ip = match.group(1)
                if nexthop_ip not in nexthops:
                    nexthops.append(nexthop_ip)
        return nexthops
    except Exception as e:
        print(f"Error getting Babel nexthops: {e}")
        return []


def probe_nexthops(nexthop_ips):
    """Send probes to next-hop IPs to populate neighbor cache"""
    for ip in nexthop_ips:
        try:
            # Fire and forget - non-blocking ping
            subprocess.Popen(
                ['ping', '-c', '1', '-W', '1', ip],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL
            )
        except Exception as e:
            print(f"Error probing {ip}: {e}")


def probe_ipv6_neighbors(ipv6_addresses):
    """Send probes to IPv6 link-local addresses to populate neighbor cache"""
    for ipv6 in ipv6_addresses:
        try:
            # Fire and forget - use ping6 with interface specification for link-local
            subprocess.Popen(
                ['ping6', '-c', '1', '-W', '1', '-I', 'wlan1', ipv6],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL
            )
        except Exception as e:
            print(f"Error probing IPv6 {ipv6}: {e}")


def get_ipv4_neighbors():
    """Get IPv4 neighbor cache on wlan1 interface - returns dict {mac: ipv4}
    
    When a MAC has multiple IPv4 entries (e.g. mesh IP + WAN IP from a switch),
    prefer the mesh subnet address (10.20.1.x) for display purposes.
    """
    try:
        result = subprocess.run(['ip', 'neigh', 'show', 'dev', 'wlan1'],
                              capture_output=True, text=True)
        neighbors = {}
        for line in result.stdout.strip().split('\n'):
            if not line:
                continue
            # Parse: 10.20.1.11 lladdr 00:c0:ca:b7:af:be REACHABLE
            match = re.match(r'(\S+)\s+lladdr\s+(\S+)', line)
            if match:
                addr, mac = match.groups()
                # Skip IPv6 addresses (they contain colons)
                if ':' not in addr:
                    mac_lower = mac.lower()
                    existing = neighbors.get(mac_lower)
                    # Prefer mesh subnet (10.20.1.x) over any other IP for same MAC
                    if existing and existing.startswith('10.20.1.'):
                        continue  # keep the mesh IP we already have
                    neighbors[mac_lower] = addr
        return neighbors
    except Exception as e:
        print(f"Error getting IPv4 neighbors: {e}")
        return {}


def get_wifi_station_stats():
    """Get WiFi statistics for all stations from iw wlan1 station dump - returns dict {mac: stats}"""
    try:
        result = subprocess.run(['iw', 'wlan1', 'station', 'dump'],
                              capture_output=True, text=True)
        stations = {}
        current_mac = None
        current_stats = {}
        
        for line in result.stdout.split('\n'):
            line = line.strip()
            
            # New station entry
            if line.startswith('Station '):
                # Save previous station if exists
                if current_mac and current_stats:
                    stations[current_mac] = current_stats
                
                # Parse MAC from "Station 00:c0:ca:b7:af:be (on wlan1)"
                match = re.match(r'Station\s+(\S+)', line)
                if match:
                    current_mac = match.group(1).lower()
                    current_stats = {}
            
            # Parse signal strength
            elif 'signal:' in line and current_mac:
                match = re.search(r'signal:\s+([-\d]+)', line)
                if match:
                    current_stats['signal'] = int(match.group(1))
            
            # Parse signal average
            elif 'signal avg:' in line and current_mac:
                match = re.search(r'signal avg:\s+([-\d]+)', line)
                if match:
                    current_stats['signal_avg'] = int(match.group(1))
            
            # Parse tx bitrate
            elif 'tx bitrate:' in line and current_mac:
                # Parse "tx bitrate: 72.2 MBit/s MCS 7 short GI"
                match = re.search(r'tx bitrate:\s+([\d.]+)\s+MBit/s(?:\s+MCS\s+(\d+))?', line)
                if match:
                    current_stats['tx_bitrate'] = float(match.group(1))
                    if match.group(2):
                        current_stats['tx_mcs'] = int(match.group(2))
            
            # Parse rx bitrate
            elif 'rx bitrate:' in line and current_mac:
                # Parse "rx bitrate: 43.3 MBit/s MCS 4 short GI"
                match = re.search(r'rx bitrate:\s+([\d.]+)\s+MBit/s(?:\s+MCS\s+(\d+))?', line)
                if match:
                    current_stats['rx_bitrate'] = float(match.group(1))
                    if match.group(2):
                        current_stats['rx_mcs'] = int(match.group(2))
            
            # Parse expected throughput
            elif 'expected throughput:' in line and current_mac:
                # Parse "expected throughput: 28.655Mbps"
                match = re.search(r'expected throughput:\s+([\d.]+)', line)
                if match:
                    current_stats['expected_throughput'] = float(match.group(1))
            
            # Parse mesh airtime link metric (kernel-computed, real-time)
            elif 'mesh airtime link metric:' in line and current_mac:
                match = re.search(r'mesh airtime link metric:\s+(\d+)', line)
                if match:
                    current_stats['airtime_metric'] = int(match.group(1))
        
        # Don't forget the last station
        if current_mac and current_stats:
            stations[current_mac] = current_stats
        
        return stations
    except Exception as e:
        print(f"Error getting WiFi station stats: {e}")
        return {}


def parse_babeld_dump(dump_data):
    """Parse babeld dump output for neighbor information"""
    neighbors = []
    for line in dump_data.split('\n'):
        if line.startswith('add neighbour'):
            # Parse: add neighbour <id> address <ipv6> if <interface> reach <reach> ... cost <cost>
            parts = line.split()
            neighbor = {}
            for i, part in enumerate(parts):
                if part == 'address' and i + 1 < len(parts):
                    neighbor['ipv6'] = parts[i + 1]
                elif part == 'cost' and i + 1 < len(parts):
                    neighbor['cost'] = parts[i + 1]
                elif part == 'reach' and i + 1 < len(parts):
                    neighbor['reach'] = parts[i + 1]
            if 'ipv6' in neighbor and 'cost' in neighbor:
                neighbors.append(neighbor)
    return neighbors


def parse_babeld_routes(dump_data):
    """Parse babeld dump output for route information"""
    routes = []
    for line in dump_data.split('\n'):
        if line.startswith('add route'):
            # Parse: add route <id> prefix <prefix> from <from> installed <yes/no> ... metric <metric> ... via <ipv6> if <interface>
            parts = line.split()
            route = {}
            for i, part in enumerate(parts):
                if part == 'prefix' and i + 1 < len(parts):
                    route['prefix'] = parts[i + 1]
                elif part == 'metric' and i + 1 < len(parts):
                    route['metric'] = parts[i + 1]
                elif part == 'via' and i + 1 < len(parts):
                    route['via'] = parts[i + 1]
                elif part == 'installed' and i + 1 < len(parts):
                    route['installed'] = parts[i + 1] == 'yes'
            # Include all routes with a next-hop (show what neighbor can reach)
            if 'prefix' in route and 'via' in route:
                routes.append(route)
    return routes


def filter_routes(routes):
    """
    Filter routes to show only interesting destinations in the web interface.
    
    Filters out:
    - Docker networks (172.16.0.0/12)
    - Mesh backbone network (10.20.1.0/24)
    
    Keeps:
    - Client-facing LAN networks (e.g., 10.20.x.0/24 where x != 1)
    - Internet gateway routes (0.0.0.0/0)
    - Any other non-internal routes
    """
    filtered = []
    for route in routes:
        prefix = route['prefix']
        
        # Filter out Docker networks (172.16.0.0/12 covers 172.16-31.x.x)
        if prefix.startswith('172.'):
            try:
                second_octet = int(prefix.split('.')[1].split('/')[0])
                if 16 <= second_octet <= 31:
                    continue  # Skip Docker networks
            except (ValueError, IndexError):
                pass
        
        # Filter out mesh backbone network (10.20.1.0/24)
        if prefix == '10.20.1.0/24':
            continue
        
        # Keep everything else (br-lan networks, internet gateways, etc.)
        filtered.append(route)
    
    return filtered


def mac_from_eui64(ipv6_addr):
    """Derive MAC address from an IPv6 link-local EUI-64 address.

    Example: fe80::2c0:caff:feb7:afbe → 00:c0:ca:b7:af:be

    EUI-64 embeds the MAC with ff:fe inserted in the middle and bit 7
    of the first octet flipped.  Returns None if not a valid EUI-64.
    """
    try:
        addr = ipaddress.IPv6Address(ipv6_addr)
        iid = addr.packed[8:]  # interface identifier (last 8 bytes)
        # EUI-64 marker: bytes 3-4 must be ff:fe
        if iid[3] != 0xff or iid[4] != 0xfe:
            return None
        mac = bytearray(6)
        mac[0] = iid[0] ^ 0x02  # flip universal/local bit
        mac[1] = iid[1]
        mac[2] = iid[2]
        mac[3] = iid[5]
        mac[4] = iid[6]
        mac[5] = iid[7]
        return ':'.join(f'{b:02x}' for b in mac)
    except Exception:
        return None


def _get_kernel_babel_routes():
    """Parse kernel routing table for babel routes grouped by next-hop IPv4.

    Returns: {via_ipv4: [{'prefix': '10.20.23.0/24'}, ...]}
    """
    try:
        result = subprocess.run(['ip', 'route', 'show', 'proto', 'babel', 'dev', 'wlan1'],
                              capture_output=True, text=True)
        routes = {}
        for line in result.stdout.strip().split('\n'):
            if not line:
                continue
            via_match = re.search(r'via\s+(\S+)', line)
            prefix_match = re.match(r'(\S+)', line)
            if via_match and prefix_match:
                via_ip = via_match.group(1)
                prefix = prefix_match.group(1)
                routes.setdefault(via_ip, []).append({'prefix': prefix})
        return routes
    except Exception as e:
        print(f"Error getting kernel babel routes: {e}")
        return {}


def get_mesh_nodes():
    """Get current mesh node status.

    Uses 'ip route show proto babel' as the source of truth for node discovery.
    Babel dump (cost/reach) and WiFi stats (signal) are best-effort enrichment.
    A node is NEVER dropped from the list because an enrichment lookup failed.

    Data pipeline:
      1. ip route show proto babel dev wlan1  → unique via IPs = node list  (reliable)
      2. babeld dump on port 33123            → cost/reach per neighbor     (best-effort)
      3. iw dev wlan1 station dump            → signal/bitrate per peer    (best-effort)

    Babel cost enrichment matches kernel routes to babel routes by shared prefix
    (no MAC/ARP/IPv6 correlation needed).  WiFi signal enrichment uses ARP
    (best-effort).  Neither can cause a node to vanish from the list.
    """
    current_time = datetime.now()

    # ── Step 1: Node discovery from kernel routing table (reliable) ────────
    # ip route show proto babel dev wlan1 → unique via IPv4 addresses
    nexthop_ips = get_babel_nexthops()
    kernel_routes = _get_kernel_babel_routes()  # {via_ipv4: [{prefix}]}

    # Probe nexthops to keep ARP cache warm for enrichment lookups
    if nexthop_ips:
        probe_nexthops(nexthop_ips)
        time.sleep(0.3)

    # ── Step 2: Babel enrichment — cost & reach (best-effort) ──────────────
    dump_data = query_babeld()
    babel_neighbors = parse_babeld_dump(dump_data)
    babel_routes = parse_babeld_routes(dump_data)

    # Index babel routes by prefix for metric lookup
    babel_route_metrics = {}
    for r in babel_routes:
        p = r['prefix']
        # Prefer the installed route when multiple exist for same prefix
        if p not in babel_route_metrics or r.get('installed'):
            babel_route_metrics[p] = r

    # Map babel neighbor data → IPv4 via shared route prefixes (no MAC/ARP needed)
    # Kernel route: prefix X via 10.20.1.23
    # Babel route:  prefix X via fe80::xxx (installed)
    # Babel neighbor: address fe80::xxx cost 256 reach ffff
    # Match on prefix → 10.20.1.23 has cost 256
    babel_nb_by_ipv6 = {bn['ipv6']: bn for bn in babel_neighbors}
    babel_installed_routes = {}  # {prefix: babel_route}
    for r in babel_routes:
        if r.get('installed'):
            babel_installed_routes[r['prefix']] = r

    ipv4_to_babel = {}  # {ipv4: {cost, reach, ipv6}}
    for ipv4, kroutes in kernel_routes.items():
        if ipv4 in ipv4_to_babel:
            continue
        for kr in kroutes:
            babel_r = babel_installed_routes.get(kr['prefix'])
            if babel_r:
                babel_nb = babel_nb_by_ipv6.get(babel_r['via'])
                if babel_nb:
                    ipv4_to_babel[ipv4] = babel_nb
                    break

    # ── Step 3: WiFi enrichment — signal & bitrate (best-effort) ──────────
    ipv4_neighbors = get_ipv4_neighbors()  # {mac_lower: ipv4}
    wifi_stats = get_wifi_station_stats()  # {mac_lower: stats}
    ipv4_to_wifi = {}
    for mac, stats in wifi_stats.items():
        ipv4 = ipv4_neighbors.get(mac.lower())
        if ipv4:
            ipv4_to_wifi[ipv4] = stats

    # ── Step 4: Build node list ────────────────────────────────────────────
    active_nodes = set()
    nodes = []

    for ipv4 in nexthop_ips:
        active_nodes.add(ipv4)

        # Track connection time
        if ipv4 not in node_history:
            node_history[ipv4] = {
                'first_seen': current_time,
                'last_seen': current_time,
                'status': 'connected'
            }
        else:
            node_history[ipv4]['last_seen'] = current_time
            node_history[ipv4]['status'] = 'connected'

        duration = current_time - node_history[ipv4]['first_seen']
        duration_str = format_duration(duration)

        # Babel cost/reach (best-effort — show N/A if enrichment failed)
        babel_info = ipv4_to_babel.get(ipv4)
        if babel_info:
            cost = babel_info['cost']
            try:
                cost_val = int(cost)
            except (ValueError, TypeError):
                cost_val = 9999
            if cost_val < 400:
                cost_quality = 'good'
            elif cost_val < 700:
                cost_quality = 'fair'
            else:
                cost_quality = 'poor'
        else:
            cost = 'N/A'
            cost_quality = 'unknown'

        # Routes via this node (from kernel table, enriched with babel metrics)
        node_routes = []
        for kr in kernel_routes.get(ipv4, []):
            prefix = kr['prefix']
            babel_r = babel_route_metrics.get(prefix)
            node_routes.append({
                'prefix': prefix,
                'metric': babel_r['metric'] if babel_r else 'N/A',
                'installed': True  # present in kernel routing table = installed
            })
        node_routes = filter_routes(node_routes)

        node = {
            'ipv4': ipv4,
            'cost': cost,
            'cost_quality': cost_quality,
            'status': 'connected',
            'duration': duration_str,
            'duration_label': 'Connected for',
            'routes': node_routes,
        }

        # WiFi enrichment (best-effort — never drop node if missing)
        wifi = ipv4_to_wifi.get(ipv4, {})
        if wifi:
            # Link quality from kernel mesh airtime metric (real-time, lower=better)
            airtime = wifi.get('airtime_metric')
            link_quality = None
            link_quality_status = None
            if airtime is not None:
                link_quality = airtime
                if airtime < 300:
                    link_quality_status = 'excellent'
                elif airtime < 500:
                    link_quality_status = 'good'
                elif airtime < 700:
                    link_quality_status = 'fair'
                else:
                    link_quality_status = 'poor'

            # Signal
            signal_quality = None
            sig = wifi.get('signal_avg')
            raw_signal = wifi.get('signal')
            if sig is not None:
                if sig >= -50:
                    signal_quality = 'excellent'
                elif sig >= -60:
                    signal_quality = 'good'
                elif sig >= -70:
                    signal_quality = 'fair'
                else:
                    signal_quality = 'poor'

            node['wifi'] = {
                'signal': raw_signal,
                'signal_avg': sig,
                'signal_quality': signal_quality,
                'tx_bitrate': wifi.get('tx_bitrate'),
                'tx_mcs': wifi.get('tx_mcs'),
                'rx_bitrate': wifi.get('rx_bitrate'),
                'rx_mcs': wifi.get('rx_mcs'),
                'expected_throughput': wifi.get('expected_throughput'),
                'airtime_metric': airtime,
                'link_quality': link_quality,
                'link_quality_status': link_quality_status,
            }

        nodes.append(node)

    # ── Step 5: Recently disconnected nodes ────────────────────────────────
    for ipv4, info in list(node_history.items()):
        if ipv4 not in active_nodes:
            time_since = current_time - info['last_seen']
            if time_since.total_seconds() <= DISCONNECTED_DISPLAY_TIME:
                nodes.append({
                    'ipv4': ipv4,
                    'cost': 'N/A',
                    'cost_quality': 'unknown',
                    'status': 'disconnected',
                    'duration': format_duration(time_since),
                    'duration_label': 'Disconnected',
                    'routes': []
                })
            else:
                del node_history[ipv4]

    return nodes


def format_duration(delta):
    """Format timedelta into human-readable string"""
    total_seconds = int(delta.total_seconds())
    
    if total_seconds < 60:
        return f"{total_seconds}s"
    elif total_seconds < 3600:
        minutes = total_seconds // 60
        seconds = total_seconds % 60
        return f"{minutes}m {seconds}s"
    else:
        hours = total_seconds // 3600
        minutes = (total_seconds % 3600) // 60
        return f"{hours}h {minutes}m"


def run_nucleus_update():
    """Run nucleus-update.sh in the background, streaming its output into
    update_state so the web UI can poll it live (like the channel scan)."""
    global update_state

    with update_lock:
        update_state['status'] = 'running'
        update_state['running'] = True
        update_state['returncode'] = None
        update_state['message'] = ''
        update_state['log'] = []
        update_state['start_time'] = time.time()

    try:
        proc = subprocess.Popen(
            ['sudo', NUCLEUS_UPDATE_SCRIPT],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
        )

        # Stream output line by line into the shared log (capped to avoid
        # unbounded memory growth on a long-running node).
        for line in iter(proc.stdout.readline, ''):
            line = line.rstrip('\n')
            with update_lock:
                update_state['log'].append(line)
                if len(update_state['log']) > 1000:
                    update_state['log'] = update_state['log'][-1000:]
        proc.stdout.close()
        rc = proc.wait()

        message = UPDATE_EXIT_MESSAGES.get(rc, f'Update finished (exit {rc}).')
        with update_lock:
            update_state['status'] = 'done' if rc in (0, 1) else 'error'
            update_state['returncode'] = rc
            update_state['message'] = message
            update_state['running'] = False

    except Exception as e:
        with update_lock:
            update_state['status'] = 'error'
            update_state['returncode'] = -1
            update_state['message'] = f'Failed to run update: {e}'
            update_state['running'] = False


def run_channel_scan(duration):
    """Run channel scan using iw-wifi-scan.sh script"""
    global scan_state
    
    try:
        with scan_lock:
            scan_state['status'] = 'running'
            scan_state['start_time'] = time.time()
        
        # Run iw-wifi-scan.sh with JSON output
        result = subprocess.run([
            'sudo', '/opt/nucleus/bin/iw-wifi-scan.sh',
            '--duration', str(duration),
            '--json',
            '--no-confirm'
        ], capture_output=True, text=True, timeout=duration * 15 + 60)
        
        if result.returncode != 0:
            raise Exception(f"Scan script failed: {result.stderr}")
        
        # Parse JSON output
        import json
        scan_data = json.loads(result.stdout)
        
        # Format results for frontend
        results = []
        for channel_data in scan_data['channels']:
            results.append({
                'channel': channel_data['channel'],
                'network_count': 0,  # iw scan doesn't detect individual networks
                'score': channel_data['busy_percent'],
                'status': channel_data['status'],
                'networks': []  # No network details from iw survey
            })
        
        # Sort by score (lower is better)
        results.sort(key=lambda x: x['score'])
        
        with scan_lock:
            scan_state['status'] = 'complete'
            scan_state['results'] = results
            scan_state['process'] = None
        
        # Probe nexthops to populate IPv4 neighbor cache after scan
        try:
            nexthops = get_babel_nexthops()
            if nexthops:
                print(f"DEBUG: Post-scan probing nexthops: {nexthops}")
                probe_nexthops(nexthops)
        except Exception as e:
            print(f"DEBUG: Error probing nexthops: {e}")
        
    except subprocess.TimeoutExpired:
        with scan_lock:
            scan_state['status'] = 'error'
            scan_state['error'] = 'Scan timed out'
            scan_state['process'] = None
    except Exception as e:
        with scan_lock:
            scan_state['status'] = 'error'
            scan_state['error'] = str(e)
            scan_state['process'] = None


def get_wlan1_status():
    """Get wlan1 mesh interface status from iw"""
    try:
        result = subprocess.run(['iw', 'wlan1', 'info'],
                              capture_output=True, text=True, timeout=5)
        if result.returncode != 0:
            return {'active': False, 'channel': None, 'meshid': None}

        output = result.stdout
        active = 'mesh point' in output

        channel = None
        match = re.search(r'channel\s+(\d+)', output)
        if match:
            channel = int(match.group(1))

        meshid = None
        match = re.search(r'meshid\s+(\S+)', output)
        if match:
            meshid = match.group(1)

        return {'active': active, 'channel': channel, 'meshid': meshid}
    except Exception as e:
        print(f"Error getting wlan1 status: {e}")
        return {'active': False, 'channel': None, 'meshid': None}


def get_ap_status():
    """Get wlan0 AP interface status"""
    try:
        result = subprocess.run(['iw', 'wlan0', 'info'],
                              capture_output=True, text=True, timeout=5)

        ap_active = False
        ssid = None
        if result.returncode == 0:
            output = result.stdout
            ap_active = bool(re.search(r'type\s+AP', output))
            match = re.search(r'ssid\s+(.+)', output)
            if match:
                ssid = match.group(1).strip()

        # Count connected clients
        clients = 0
        station_result = subprocess.run(['iw', 'wlan0', 'station', 'dump'],
                                       capture_output=True, text=True, timeout=5)
        if station_result.returncode == 0:
            clients = station_result.stdout.count('Station ')

        return {'active': ap_active, 'ssid': ssid, 'clients': clients}
    except Exception as e:
        print(f"Error getting AP status: {e}")
        return {'active': False, 'ssid': None, 'clients': 0}


@app.route('/')
def index():
    """Main dashboard page"""
    return render_template('nav.html')


@app.route('/monitor')
def monitor():
    """Network monitoring dashboard"""
    return render_template('monitor.html', 
                         refresh_interval=REFRESH_INTERVAL)


def get_meshtastic_nodes():
    """Read meshtastic node data from JSON file dumped by cot_bridge."""
    import json as _json
    try:
        with open('/tmp/meshtastic_nodes.json', 'r') as f:
            data = _json.load(f)
        return data.get('nodes', [])
    except (FileNotFoundError, ValueError):
        return []
    except Exception:
        return []


@app.route('/api/dashboard')
def api_dashboard():
    """Dashboard API - single endpoint for front page status data"""
    # Get mesh IP
    mesh_ip = 'N/A'
    try:
        with open('/etc/nucleus/mesh.conf', 'r') as f:
            for line in f:
                if line.strip().startswith('MESH_IP='):
                    mesh_ip = line.strip().split('=', 1)[1].strip('"')
                    break
    except Exception:
        pass

    # Get interface statuses
    wlan1 = get_wlan1_status()
    ap = get_ap_status()

    # Get neighbors (reuse existing mesh node logic, return simplified)
    nodes = get_mesh_nodes()
    neighbors = []
    for node in nodes:
        wifi = node.get('wifi') or {}
        neighbors.append({
            'ip': node['ipv4'],
            'cost': node['cost'],
            'cost_quality': node.get('cost_quality', 'unknown'),
            'status': node['status'],
            'signal_avg': wifi.get('signal_avg'),
        })

    # Get meshtastic data
    meshtastic_nodes = get_meshtastic_nodes()
    # Use the meshtastic_api helper if available (handles both USB serial
    # and meshtasticd TCP), fall back to the old glob check.
    try:
        from meshtastic_api import _radio_detected
        radio_detected = _radio_detected()
    except ImportError:
        radio_detected = bool(glob.glob('/dev/ttyACM*'))

    # Check bridge config flag and OTS enabled flag
    bridge_enabled = False
    ots_enabled = True  # default to showing the button
    try:
        with open('/etc/nucleus/mesh.conf', 'r') as f:
            for line in f:
                stripped = line.strip()
                if stripped.startswith('COT_BRIDGE_ENABLED='):
                    val = stripped.split('=', 1)[1].strip('"').lower()
                    bridge_enabled = val in ('true', '1', 'yes')
                elif stripped.startswith('OTS_ENABLED='):
                    val = stripped.split('=', 1)[1].strip('"').lower()
                    ots_enabled = val in ('true', '1', 'yes')
    except Exception:
        pass

    # Get channel utilization
    channel_util = get_channel_utilization()

    # Get version from Nucleus_OS git repo
    version = 'unknown'
    for vpath in ['/home/natak/Nucleus_OS/VERSION', os.path.join(os.path.dirname(__file__), '..', '..', '..', 'VERSION')]:
        try:
            with open(vpath, 'r') as f:
                version = f.read().strip()
            break
        except Exception:
            continue

    return jsonify({
        'version': version,
        'mesh_ip': mesh_ip,
        'wlan1': wlan1,
        'ap': ap,
        'neighbors': neighbors,
        'channel_utilization': channel_util,
        'ots_enabled': ots_enabled,
        'meshtastic': {
            'radio_detected': radio_detected,
            'bridge_enabled': bridge_enabled,
            'nodes': meshtastic_nodes,
        },
        'timestamp': datetime.now().isoformat()
    })


@app.route('/api/node-ip')
def get_node_ip():
    """Get node IP address from mesh config"""
    try:
        with open('/etc/nucleus/mesh.conf', 'r') as f:
            for line in f:
                line = line.strip()
                if line.startswith('MESH_IP='):
                    ip = line.split('=', 1)[1].strip('"')
                    return jsonify({'ip': ip})
        return jsonify({'ip': 'N/A'})
    except Exception as e:
        return jsonify({'ip': 'Error', 'error': str(e)}), 500


@app.route('/api/nodes')
def api_nodes():
    """API endpoint for mesh node data"""
    nodes = get_mesh_nodes()
    channel_util = get_channel_utilization()
    return jsonify({
        'nodes': nodes,
        'channel_utilization': channel_util,
        'timestamp': datetime.now().isoformat()
    })


@app.route('/voice')
def voice():
    """OpenVLM mesh PTT voice — soft-PTT web handset (phone mic/speaker)."""
    return render_template('voice.html')


@app.route('/config')
def config():
    """Configuration page"""
    return render_template('config.html')



@app.route('/api/config', methods=['GET'])
def get_config():
    """Read mesh configuration"""
    try:
        config = {}
        with open('/etc/nucleus/mesh.conf', 'r') as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith('#') and '=' in line:
                    key, value = line.split('=', 1)
                    config[key] = value.strip('"')
        return jsonify(config)
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/apply_and_reboot', methods=['POST'])
def apply_and_reboot():
    """Save config, run config generation, and reboot system"""
    try:
        config = request.json
        
        # Step 1: Save configuration to mesh.conf
        with open('/etc/nucleus/mesh.conf', 'r') as f:
            lines = f.readlines()
        
        new_lines = []
        for line in lines:
            if '=' in line and not line.strip().startswith('#'):
                key = line.split('=')[0].strip()
                if key in config:
                    new_lines.append(f'{key}="{config[key]}"\n')
                else:
                    new_lines.append(line)
            else:
                new_lines.append(line)
        
        with open('/etc/nucleus/mesh.conf', 'w') as f:
            f.writelines(new_lines)
        
        # Step 2: Run config generation script (sudo required - writes to /etc/)
        result = subprocess.run(['sudo', '/opt/nucleus/bin/config_generation.sh'],
                              capture_output=True, text=True, timeout=30)
        
        if result.returncode != 0:
            return jsonify({'error': f'Config generation failed: {result.stderr}'}), 500
        
        # Step 3: Reboot system (in background to allow response)
        subprocess.Popen(['sudo', 'reboot'])
        
        return jsonify({'success': True, 'message': 'Configuration applied, system rebooting'})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/scan')
def scan():
    """Wi-Fi channel scan page"""
    return render_template('scan.html')


@app.route('/remote')
def remote():
    """Remote access management page"""
    return render_template('remote.html')


@app.route('/update')
def update_page():
    """Node software update page"""
    return render_template('update.html')


@app.route('/api/update/status', methods=['GET'])
def get_update_status():
    """Report WAN reachability to the git remote so the UI can enable/disable
    the Update button. Checked on page load (not polled)."""
    wan = False
    try:
        result = subprocess.run(
            ['git', 'ls-remote', 'origin'],
            cwd=REPO_DIR,
            capture_output=True, text=True, timeout=20
        )
        wan = result.returncode == 0
    except Exception:
        wan = False

    with update_lock:
        running = update_state['running']

    return jsonify({
        'wan': wan,
        'running': running,
    })


@app.route('/api/update/run', methods=['POST'])
def run_update():
    """Launch nucleus-update.sh in the background (non-blocking)."""
    with update_lock:
        if update_state['running']:
            return jsonify({'error': 'Update already in progress'}), 400

    thread = threading.Thread(target=run_nucleus_update)
    thread.daemon = True
    thread.start()

    return jsonify({
        'success': True,
        'message': 'Update started',
    })


@app.route('/api/update/progress', methods=['GET'])
def get_update_progress():
    """Return the live update status and log (polled while running)."""
    with update_lock:
        return jsonify({
            'status': update_state['status'],
            'running': update_state['running'],
            'returncode': update_state['returncode'],
            'message': update_state['message'],
            'log': list(update_state['log']),
        })


@app.route('/api/reboot', methods=['POST'])
def reboot_node():
    """Reboot the node (explicit operator action, separate from update)."""
    try:
        def do_reboot():
            time.sleep(1)
            subprocess.Popen(['sudo', 'reboot'])

        threading.Thread(target=do_reboot, daemon=True).start()

        return jsonify({
            'success': True,
            'message': 'Node rebooting...'
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500


def get_interface_ips(interfaces=('eth0', 'br-lan', 'tailscale0')):
    """Get IPv4 addresses for a list of network interfaces.

    Returns: {iface: [ip1, ip2, ...]} — empty list if interface is down or missing.
    """
    result = {}
    for iface in interfaces:
        try:
            r = subprocess.run(
                ['ip', '-4', 'addr', 'show', 'dev', iface],
                capture_output=True, text=True, timeout=5
            )
            addrs = re.findall(r'inet\s+(\d+\.\d+\.\d+\.\d+)', r.stdout)
            result[iface] = addrs
        except Exception:
            result[iface] = []
    return result


@app.route('/api/network/addresses')
def api_network_addresses():
    """Return IPv4 addresses for key interfaces (eth0, br-lan, tailscale0)."""
    return jsonify(get_interface_ips())


@app.route('/network')
@app.route('/ethernet')
def ethernet():
    """Network / Ethernet mode control page"""
    return render_template('ethernet.html')


@app.route('/opendht')
def opendht():
    """OpenDHT monitoring page"""
    return render_template('opendht.html')


@app.route('/meshtastic')
def meshtastic_page():
    """Meshtastic radio control page"""
    return render_template('meshtastic.html')


@app.route('/reticulum')
def reticulum_page():
    """Reticulum network status page"""
    return render_template('reticulum.html')


def _discover_mesh_nodes():
    """Discover mesh node IPs (10.20.1.X) visible to this node.

    Sources:
    - Babel routes: mesh host routes (10.20.1.X/32), br-lan subnets
      (10.20.X.0/24 -> node at 10.20.1.X), and 'via' next-hop addresses
    - ARP/neighbor cache on wlan1 (direct neighbors on the on-link /24)

    Returns (nodes, own_ip): sorted list of mesh IPs excluding this node.
    """
    import re as _re
    own_ip = None
    try:
        with open('/etc/nucleus/mesh.conf', 'r') as f:
            for line in f:
                if line.strip().startswith('MESH_IP='):
                    own_ip = line.strip().split('=', 1)[1].strip('"')
                    break
    except Exception:
        pass

    nodes = set()

    # From babel routes (destinations + via next-hops)
    try:
        r = subprocess.run(['ip', 'route', 'show', 'proto', 'babel'],
                           capture_output=True, text=True, timeout=5)
        for line in r.stdout.strip().split('\n'):
            if not line.strip():
                continue
            prefix_m = _re.match(r'(\S+)', line)
            via_m = _re.search(r'via\s+(\S+)', line)
            if prefix_m:
                dest = prefix_m.group(1).split('/')[0]
                parts = dest.split('.')
                if len(parts) == 4 and parts[0] == '10' and parts[1] == '20':
                    if parts[2] == '1' and parts[3] not in ('0', '255'):
                        nodes.add(dest)                    # mesh host route 10.20.1.X
                    elif parts[3] == '0' and parts[2] != '1':
                        nodes.add('10.20.1.' + parts[2])   # br-lan 10.20.X.0 -> node X
            if via_m and via_m.group(1).startswith('10.20.1.'):
                nodes.add(via_m.group(1))
    except Exception:
        pass

    # From neighbor cache on wlan1 (direct mesh neighbors)
    try:
        r = subprocess.run(['ip', 'neigh', 'show', 'dev', 'wlan1'],
                           capture_output=True, text=True, timeout=5)
        for line in r.stdout.strip().split('\n'):
            m = _re.match(r'(10\.20\.1\.\d+)\s+lladdr', line)
            if m and 'FAILED' not in line:
                nodes.add(m.group(1))
    except Exception:
        pass

    nodes.discard(own_ip)
    nodes.discard(None)
    try:
        node_list = sorted(nodes, key=lambda ip: int(ip.split('.')[3]))
    except Exception:
        node_list = sorted(nodes)
    return node_list, own_ip


@app.route('/pathtrace')
def pathtrace_page():
    """Mesh path trace — active traceroute view for proving multi-hop relay"""
    return render_template('pathtrace.html')


@app.route('/api/pathtrace')
def api_pathtrace():
    """API endpoint returning mesh hop data for the path trace page.

    Returns two data blocks:
    1. Babel routes (ip route show proto babel dev wlan1)
    2. Direct WiFi peers with resolved IPs (iw station dump + ARP cache)
    Plus a summary line and the node's own mesh IP.
    """
    import re as _re

    result = {
        'mesh_ip': None,
        'babel_routes': '',
        'wifi_peers': [],
        'summary': {},
        'timestamp': datetime.now().isoformat(),
    }

    # Read this node's mesh IP
    try:
        with open('/etc/nucleus/mesh.conf', 'r') as f:
            for line in f:
                if line.strip().startswith('MESH_IP='):
                    result['mesh_ip'] = line.strip().split('=', 1)[1].strip('"')
                    break
    except Exception:
        pass

    # 1. Babel routes
    try:
        r = subprocess.run(['ip', 'route', 'show', 'proto', 'babel', 'dev', 'wlan1'],
                           capture_output=True, text=True, timeout=5)
        result['babel_routes'] = r.stdout.strip()
    except Exception as e:
        result['babel_routes'] = f'Error: {e}'

    # 2. Direct WiFi peers (station dump — resolve MAC to IP via ARP cache)
    try:
        # Build MAC→IPv4 lookup from ARP neighbor cache
        arp_r = subprocess.run(['ip', 'neigh', 'show', 'dev', 'wlan1'],
                               capture_output=True, text=True, timeout=5)
        mac_to_ip = {}
        for arp_line in arp_r.stdout.strip().split('\n'):
            if not arp_line:
                continue
            m = _re.match(r'(\S+)\s+lladdr\s+(\S+)', arp_line)
            if m:
                addr, mac_addr = m.groups()
                if ':' not in addr:  # skip IPv6
                    mac_lower = mac_addr.lower()
                    existing = mac_to_ip.get(mac_lower)
                    # Prefer mesh subnet (10.20.1.x) over other IPs for same MAC
                    if existing and existing.startswith('10.20.1.'):
                        continue
                    mac_to_ip[mac_lower] = addr

        r = subprocess.run(['iw', 'dev', 'wlan1', 'station', 'dump'],
                           capture_output=True, text=True, timeout=5)
        peers = []
        current_mac = None
        signal_avg = None
        for line in r.stdout.split('\n'):
            line = line.strip()
            if line.startswith('Station '):
                if current_mac:
                    ip = mac_to_ip.get(current_mac.lower(), 'unknown')
                    peers.append({'ip': ip, 'signal_avg': signal_avg})
                match = _re.match(r'Station\s+(\S+)', line)
                current_mac = match.group(1) if match else None
                signal_avg = None
            elif 'signal avg:' in line and current_mac:
                match = _re.search(r'signal avg:\s+([-\d]+)', line)
                if match:
                    signal_avg = int(match.group(1))
        if current_mac:
            ip = mac_to_ip.get(current_mac.lower(), 'unknown')
            peers.append({'ip': ip, 'signal_avg': signal_avg})
        result['wifi_peers'] = [p for p in peers if p['ip'] != 'unknown']
    except Exception as e:
        result['wifi_peers'] = []

    # Summary counts
    direct_peer_count = len(result['wifi_peers'])
    # Count routes that go via a different node (relayed)
    # In Natak mesh: 10.20.X.0/24 is node X's br-lan, 10.20.1.X is node X's mesh IP
    # A route is relayed when the via node differs from the destination node
    relay_count = 0
    total_routes = 0
    for line in result['babel_routes'].split('\n'):
        if not line.strip():
            continue
        total_routes += 1
        via_match = _re.search(r'via\s+(\S+)', line)
        prefix_match = _re.match(r'(\S+)', line)
        if via_match and prefix_match:
            via_ip = via_match.group(1)
            prefix = prefix_match.group(1)
            dest_ip = prefix.split('/')[0]

            # Extract node identity from each address
            via_parts = via_ip.split('.')
            dest_parts = dest_ip.split('.')

            # For host routes (10.20.1.X/32 via 10.20.1.Y) — relayed if X != Y
            if dest_ip == via_ip:
                pass  # direct
            elif len(via_parts) == 4 and len(dest_parts) == 4:
                via_node = via_parts[3]  # last octet of 10.20.1.Y
                # br-lan subnet: 10.20.X.0/24 → node number is 3rd octet
                # mesh host: 10.20.1.X/32 → node number is 4th octet
                if dest_parts[2] == '1':
                    dest_node = dest_parts[3]  # mesh IP
                else:
                    dest_node = dest_parts[2]  # br-lan subnet
                if via_node != dest_node:
                    relay_count += 1
            elif via_ip != dest_ip:
                relay_count += 1  # fallback for non-standard prefixes

    result['summary'] = {
        'direct_peers': direct_peer_count,
        'total_routes': total_routes,
        'relayed_routes': relay_count,
    }

    # Known mesh nodes (for the path trace target dropdown)
    try:
        node_list, _own = _discover_mesh_nodes()
        result['nodes'] = node_list
    except Exception:
        result['nodes'] = []

    return jsonify(result)


@app.route('/api/pathtrace/run')
def api_pathtrace_run():
    """Run an active traceroute (mtr) to a known mesh node.

    Target must be a 10.20.1.X mesh IP that is currently known to this node
    (discovered via babel routes / neighbor cache). Anything else is rejected.
    mtr runs with a hard timeout so this endpoint can never hang the server.
    """
    import re as _re
    import json as _json

    target = request.args.get('target', '').strip()

    # Strict format check: must be 10.20.1.X
    if not _re.fullmatch(r'10\.20\.1\.\d{1,3}', target):
        return jsonify({'error': 'Invalid target — must be a 10.20.1.X mesh IP'}), 400

    # Must be a currently-known mesh node
    known_nodes, own_ip = _discover_mesh_nodes()
    if target not in known_nodes:
        return jsonify({'error': f'{target} is not a known mesh node'}), 400

    # Run mtr: 2 probes per hop, no DNS, JSON output, hard 15s timeout
    try:
        r = subprocess.run(
            ['mtr', '--json', '--no-dns', '-c', '2', target],
            capture_output=True, text=True, timeout=15
        )
    except subprocess.TimeoutExpired:
        return jsonify({'error': 'Trace timed out (15s)'}), 504
    except Exception as e:
        return jsonify({'error': f'Trace failed: {e}'}), 500

    if r.returncode != 0 or not r.stdout.strip():
        return jsonify({'error': f'mtr failed: {r.stderr.strip() or "no output"}'}), 500

    try:
        report = _json.loads(r.stdout)['report']
        hops = []
        for hub in report.get('hubs', []):
            hops.append({
                'host': hub.get('host', '???'),
                'loss_pct': hub.get('Loss%', 0.0),
                'avg_ms': hub.get('Avg'),
                'best_ms': hub.get('Best'),
                'worst_ms': hub.get('Wrst'),
            })
    except Exception as e:
        return jsonify({'error': f'Could not parse mtr output: {e}'}), 500

    # Verdict: did the trace actually reach the target?
    reached = bool(hops) and hops[-1]['host'] == target
    hop_count = len(hops)
    relays = [h['host'] for h in hops[:-1]] if reached else []

    return jsonify({
        'target': target,
        'source': own_ip,
        'reached': reached,
        'hop_count': hop_count if reached else None,
        'relays': relays,
        'hops': hops,
        'timestamp': datetime.now().isoformat(),
    })



@app.route('/api/reticulum/status', methods=['GET'])
def get_reticulum_status():
    """Get Reticulum network status from rnstatus and rnpath CLI tools"""
    import json

    result_data = {
        'transport_id': None,
        'transport_uptime': None,
        'rxb': 0,
        'txb': 0,
        'interfaces': [],
        'destinations_count': 0,
    }

    # Get interface status from rnstatus -j
    try:
        rs = subprocess.run(
            ['rnstatus', '-j'],
            capture_output=True, text=True, timeout=10
        )
        if rs.returncode == 0 and rs.stdout.strip():
            status = json.loads(rs.stdout)
            result_data['transport_id'] = status.get('transport_id')
            result_data['transport_uptime'] = status.get('transport_uptime')
            result_data['rxb'] = status.get('rxb', 0)
            result_data['txb'] = status.get('txb', 0)
            result_data['interfaces'] = status.get('interfaces', [])
    except Exception as e:
        print(f"Error running rnstatus: {e}")

    # Get destination count from rnpath (count only, not full list)
    try:
        rp = subprocess.run(
            ['rnpath', '-t', '-j'],
            capture_output=True, text=True, timeout=10
        )
        if rp.returncode == 0 and rp.stdout.strip():
            destinations = json.loads(rp.stdout)
            if isinstance(destinations, list):
                result_data['destinations_count'] = len(destinations)
    except Exception as e:
        print(f"Error running rnpath: {e}")

    return jsonify(result_data)


@app.route('/api/reticulum/restart', methods=['POST'])
def restart_reticulum():
    """Restart the rnsd service"""
    try:
        result = subprocess.run(
            ['sudo', 'systemctl', 'restart', 'rnsd'],
            capture_output=True, text=True, timeout=30
        )

        if result.returncode != 0:
            return jsonify({
                'success': False,
                'error': 'Failed to restart rnsd',
                'output': result.stderr or result.stdout
            }), 500

        return jsonify({
            'success': True,
            'message': 'rnsd service restarted'
        })
    except subprocess.TimeoutExpired:
        return jsonify({'error': 'Command timed out'}), 500
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/opendht/status', methods=['GET'])
def get_opendht_status():
    """Get OpenDHT container status and configuration"""
    try:
        import json
        
        # Query DHT peer count
        peers_connected = 0
        try:
            result = subprocess.run(['curl', '-s', 'http://127.0.0.1:8000/'],
                                  capture_output=True, text=True, timeout=5)
            if result.returncode == 0 and result.stdout:
                data = json.loads(result.stdout)
                # DHT response is nested: {"ipv4": {"good": 1}}
                peers_connected = data.get('ipv4', {}).get('good', 0)
        except Exception as e:
            print(f"Error querying DHT peers: {e}")
        
        # Read configuration from mesh.conf
        config = {}
        try:
            with open('/etc/nucleus/mesh.conf', 'r') as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith('#') and '=' in line:
                        key, value = line.split('=', 1)
                        config[key] = value.strip('"')
        except Exception as e:
            print(f"Error reading config: {e}")
        
        # Extract values
        mesh_ip = config.get('MESH_IP', '10.20.1.X')
        network_id = config.get('OPENDHT_NETWORK_ID', 'N/A')
        bootstrap_ips_str = config.get('OPENDHT_BOOTSTRAP_IPS', '')
        bootstrap_ips = [ip.strip() for ip in bootstrap_ips_str.split(',') if ip.strip()]
        
        # Calculate br-lan IP from mesh IP (10.20.1.X -> 10.20.X.1)
        br_lan_ip = 'N/A'
        try:
            parts = mesh_ip.split('.')
            if len(parts) == 4 and parts[0] == '10' and parts[1] == '20' and parts[2] == '1':
                node_num = parts[3]
                br_lan_ip = f'10.20.{node_num}.1'
        except Exception as e:
            print(f"Error calculating br-lan IP: {e}")
        
        proxy_url = f'{br_lan_ip}:8000' if br_lan_ip != 'N/A' else 'N/A'
        
        return jsonify({
            'peers_connected': peers_connected,
            'network_id': network_id,
            'mesh_ip': mesh_ip,
            'br_lan_ip': br_lan_ip,
            'bootstrap_ips': bootstrap_ips,
            'proxy_url': proxy_url
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/opendht/restart', methods=['POST'])
def restart_opendht():
    """Restart OpenDHT container"""
    try:
        result = subprocess.run(['sudo', '/opt/nucleus/bin/opendht-start.sh'],
                              capture_output=True, text=True, timeout=30)
        
        if result.returncode != 0:
            return jsonify({
                'success': False,
                'error': 'Failed to restart OpenDHT',
                'output': result.stderr or result.stdout
            }), 500
        
        return jsonify({
            'success': True,
            'message': 'OpenDHT container restarted'
        })
    except subprocess.TimeoutExpired:
        return jsonify({'error': 'Command timed out'}), 500
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/eth0-mode/status', methods=['GET'])
def get_eth0_status():
    """Get current eth0 mode"""
    try:
        result = subprocess.run(['/opt/nucleus/bin/eth0-mode.sh', 'status'],
                              capture_output=True, text=True)
        
        # Parse the status output
        current_mode = 'wan'  # default
        for line in result.stdout.split('\n'):
            if 'Current mode:' in line:
                if 'lan' in line.lower():
                    current_mode = 'lan'
                elif 'wan' in line.lower():
                    current_mode = 'wan'
        
        return jsonify({
            'current': current_mode,
            'success': True
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/eth0-mode/switch', methods=['POST'])
def switch_eth0_mode():
    """Switch eth0 mode"""
    try:
        data = request.get_json()
        mode = data.get('mode')
        
        if mode not in ['wan', 'lan']:
            return jsonify({'error': 'Invalid mode. Must be "wan" or "lan"'}), 400
        
        # Run the eth0-mode.sh script with sudo
        result = subprocess.run(['sudo', '/opt/nucleus/bin/eth0-mode.sh', mode],
                              capture_output=True, text=True, timeout=45)
        
        if result.returncode != 0:
            return jsonify({
                'success': False,
                'error': f'Failed to switch mode: {result.stderr}'
            }), 500
        
        return jsonify({
            'success': True,
            'message': f'Successfully switched to {mode.upper()} mode',
            'output': result.stdout
        })
    except subprocess.TimeoutExpired:
        return jsonify({'error': 'Command timed out'}), 500
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/tailscale/status', methods=['GET'])
def get_tailscale_status():
    """Get Tailscale status"""
    try:
        result = subprocess.run(['tailscale', 'status', '--json'],
                              capture_output=True, text=True, timeout=5)
        
        if result.returncode != 0:
            return jsonify({
                'connected': False,
                'status': 'Stopped'
            })
        
        import json
        status_data = json.loads(result.stdout)
        
        # Extract self node information
        self_info = status_data.get('Self', {})
        backend_state = status_data.get('BackendState', '')
        
        # Get Tailscale IP
        ip_result = subprocess.run(['tailscale', 'ip', '-4'],
                                  capture_output=True, text=True, timeout=5)
        tailscale_ip = ip_result.stdout.strip() if ip_result.returncode == 0 else 'N/A'
        
        # Get current tailnet name from switch list
        tailnet_name = 'N/A'
        switch_result = subprocess.run(['sudo', 'tailscale', 'switch', '--list'],
                                      capture_output=True, text=True, timeout=5)
        if switch_result.returncode == 0:
            for line in switch_result.stdout.strip().split('\n')[1:]:
                if not line.strip():
                    continue
                parts = line.split()
                if len(parts) >= 3:
                    account = parts[2]
                    if account.endswith('*'):
                        tailnet_name = parts[1]
                        break
        
        # Determine connection status
        connected = backend_state == 'Running'
        
        return jsonify({
            'connected': connected,
            'ip': tailscale_ip if connected else 'N/A',
            'tailnet': tailnet_name if connected else 'N/A',
            'hostname': self_info.get('HostName', 'N/A'),
            'status': backend_state
        })
    except Exception as e:
        return jsonify({
            'connected': False,
            'status': 'Error',
            'error': str(e)
        }), 500


@app.route('/api/tailscale/up', methods=['POST'])
def turn_tailscale_up():
    """Turn on Tailscale"""
    try:
        result = subprocess.run(['sudo', 'tailscale', 'up'],
                              capture_output=True, text=True, timeout=30)
        
        if result.returncode != 0:
            return jsonify({
                'success': False,
                'error': 'Failed to start Tailscale',
                'output': result.stderr or result.stdout
            }), 500
        
        return jsonify({
            'success': True,
            'message': 'Tailscale connected'
        })
    except subprocess.TimeoutExpired:
        return jsonify({'error': 'Command timed out'}), 500
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/tailscale/down', methods=['POST'])
def turn_tailscale_down():
    """Turn off Tailscale"""
    try:
        result = subprocess.run(['sudo', 'tailscale', 'down'],
                              capture_output=True, text=True, timeout=10)
        
        if result.returncode != 0:
            return jsonify({
                'success': False,
                'error': 'Failed to stop Tailscale',
                'output': result.stderr or result.stdout
            }), 500
        
        return jsonify({
            'success': True,
            'message': 'Tailscale disconnected'
        })
    except subprocess.TimeoutExpired:
        return jsonify({'error': 'Command timed out'}), 500
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/tailscale/profiles', methods=['GET'])
def get_tailscale_profiles():
    """Get list of Tailscale profiles"""
    try:
        result = subprocess.run(['sudo', 'tailscale', 'switch', '--list'],
                              capture_output=True, text=True, timeout=5)
        
        if result.returncode != 0:
            return jsonify({'profiles': []})
        
        profiles = []
        lines = result.stdout.strip().split('\n')
        
        # Skip header line (ID    Tailnet    Account)
        for line in lines[1:]:
            if not line.strip():
                continue
            
            # Split by whitespace, handling the * marker for current profile
            parts = line.split()
            if len(parts) >= 3:
                profile_id = parts[0]
                tailnet = parts[1]
                account = parts[2]
                
                # Check if this is the current profile (account ends with *)
                is_current = account.endswith('*')
                if is_current:
                    account = account.rstrip('*')
                
                profiles.append({
                    'id': profile_id,
                    'tailnet': tailnet,
                    'account': account,
                    'current': is_current
                })
        
        return jsonify({'profiles': profiles})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/tailscale/switch', methods=['POST'])
def switch_tailscale_profile():
    """Switch to a different Tailscale profile"""
    try:
        data = request.get_json()
        profile_id = data.get('profile_id')
        
        if not profile_id:
            return jsonify({'error': 'Missing profile_id'}), 400
        
        result = subprocess.run(['sudo', 'tailscale', 'switch', profile_id],
                              capture_output=True, text=True, timeout=30)
        
        if result.returncode != 0:
            return jsonify({
                'success': False,
                'error': 'Failed to switch profile',
                'output': result.stderr or result.stdout
            }), 500
        
        return jsonify({
            'success': True,
            'message': f'Switched to profile {profile_id}'
        })
    except subprocess.TimeoutExpired:
        return jsonify({'error': 'Command timed out'}), 500
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/channel-scan/start', methods=['POST'])
def start_channel_scan():
    """Start channel scan"""
    global scan_state
    
    with scan_lock:
        if scan_state['status'] == 'running':
            return jsonify({'error': 'Scan already in progress'}), 400
    
    try:
        data = request.get_json()
        duration = int(data.get('duration', 60))
        
        # Validate duration
        if duration < 10 or duration > 300:  # 10 seconds to 5 minutes
            return jsonify({'error': 'Duration must be between 10 and 300 seconds'}), 400
        
        # Calculate total scan time: (dwell time * 11 channels) + overhead
        total_duration = (duration * 11) + 20
        
        # Reset state
        with scan_lock:
            scan_state['status'] = 'starting'
            scan_state['duration'] = total_duration  # Use total duration for progress tracking
            scan_state['results'] = None
            scan_state['error'] = None
            scan_state['progress'] = 0
        
        # Start scan in background thread
        thread = threading.Thread(target=run_channel_scan, args=(duration,))
        thread.daemon = True
        thread.start()
        
        return jsonify({
            'success': True,
            'message': f'Channel scan started for {duration} seconds per channel',
            'duration': total_duration
        })
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/channel-scan/status', methods=['GET'])
def get_channel_scan_status():
    """Get channel scan status"""
    with scan_lock:
        status = scan_state['status']
        duration = scan_state['duration']
        start_time = scan_state['start_time']
        error = scan_state['error']
        
        # Calculate progress if running
        progress = 0
        remaining = 0
        if status == 'running' and start_time:
            elapsed = time.time() - start_time
            progress = min(int((elapsed / duration) * 100), 100)
            remaining = max(0, int(duration - elapsed))
    
    return jsonify({
        'status': status,
        'progress': progress,
        'remaining': remaining,
        'duration': duration,
        'error': error
    })


@app.route('/api/channel-scan/results', methods=['GET'])
def get_channel_scan_results():
    """Get channel scan results"""
    with scan_lock:
        if scan_state['status'] != 'complete':
            return jsonify({'error': 'Scan not complete'}), 400
        
        results = scan_state['results']
        
        if not results:
            return jsonify({'error': 'No scan results available'}), 400
        
        # Get the 3 least congested channels (already sorted by score, lower is better)
        best_channels = []
        for result in results[:3]:  # Top 3 least congested
            best_channels.append({
                'channel': result['channel'],
                'score': result['score'],
                'status': result['status']
            })
        
        return jsonify({
            'all_channels': results,
            'best_channels': best_channels,
            'total_networks': 0  # Not applicable for iw scan
        })


@app.route('/api/shutdown', methods=['POST'])
def shutdown_node():
    """Gracefully shut down the node."""
    try:
        # Schedule shutdown after response is sent
        def do_shutdown():
            time.sleep(1)
            subprocess.Popen(['sudo', 'shutdown', '-h', 'now'])

        threading.Thread(target=do_shutdown, daemon=True).start()

        return jsonify({
            'success': True,
            'message': 'Node shutting down...'
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/restart-mesh', methods=['POST'])
def restart_mesh():
    """Restart Flask application"""
    try:
        # Send success response before restart
        response = jsonify({
            'success': True,
            'message': 'Restarting application...'
        })
        
        # Schedule restart after response is sent
        def do_restart():
            time.sleep(0.5)  # Allow response to be sent
            os.execv(sys.executable, ['python3', os.path.abspath(__file__)])
        
        import threading
        restart_thread = threading.Thread(target=do_restart)
        restart_thread.daemon = True
        restart_thread.start()
        
        return response
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500


# --- OpenTAKServer Integration ---
# Reverse proxy OTS web UI through Flask so phone clients on br-lan
# can access it without hitting the OTS_IP_WHITELIST (which only allows 127.0.0.1).
# Flask connects to OTS nginx on localhost, so the whitelist is always satisfied.

OTS_UPSTREAM = 'http://127.0.0.1:8080'


def _proxy_to_ots(subpath):
    """Transparent reverse proxy to OpenTAKServer via nginx.
    
    Rewrites URLs in HTML/JS responses so the OTS SPA works under the /ots/ prefix.
    """
    from flask import Response

    target = f'{OTS_UPSTREAM}/{subpath}'
    qs = request.query_string.decode()
    if qs:
        target += '?' + qs

    # Build proxy request headers (skip hop-by-hop headers)
    skip = {'host', 'content-length', 'transfer-encoding', 'connection'}
    headers = {}
    for key, value in request.headers:
        if key.lower() not in skip:
            headers[key] = value
    headers['Host'] = '127.0.0.1'
    headers['Accept-Encoding'] = 'identity'  # No compression so we can rewrite

    body = None
    if request.method in ('POST', 'PUT', 'PATCH', 'DELETE'):
        body = request.get_data()
        if not body:
            body = None

    req = _urlreq.Request(target, data=body, headers=headers, method=request.method)

    try:
        resp = _urlreq.urlopen(req, timeout=30)
        status = resp.status
    except _urlerr.HTTPError as e:
        resp = e
        status = e.code
    except Exception as e:
        return jsonify({'error': f'OTS proxy error: {e}'}), 502

    data = resp.read()
    content_type = ''
    for k, v in resp.getheaders():
        if k.lower() == 'content-type':
            content_type = v
            break

    # Rewrite URLs in HTML/JS so the SPA works under /ots/ prefix
    if 'text/html' in content_type or 'javascript' in content_type:
        rewrites = [
            (b'"/api/', b'"/ots/api/'),
            (b"'/api/", b"'/ots/api/"),
            (b'`/api/', b'`/ots/api/'),
            (b'"/Marti/', b'"/ots/Marti/'),
            (b"'/Marti/", b"'/ots/Marti/"),
            (b'"/socket.io', b'"/ots/socket.io'),
            (b"'/socket.io", b"'/ots/socket.io"),
            (b'"/oauth/', b'"/ots/oauth/'),
        ]
        for old, new in rewrites:
            data = data.replace(old, new)

    if 'text/html' in content_type:
        # Rewrite asset references in HTML
        html_rewrites = [
            (b'href="/assets/', b'href="/ots/assets/'),
            (b'src="/assets/', b'src="/ots/assets/'),
            (b'href="/favicon', b'href="/ots/favicon'),
            (b'src="/favicon', b'src="/ots/favicon'),
        ]
        for old, new in html_rewrites:
            data = data.replace(old, new)

    if 'text/css' in content_type:
        data = data.replace(b'url(/', b'url(/ots/')
        data = data.replace(b"url('/", b"url('/ots/")
        data = data.replace(b'url("/', b'url("/ots/')

    # Build response headers, excluding hop-by-hop
    excluded = {'transfer-encoding', 'content-encoding', 'content-length', 'connection'}
    resp_headers = []
    for k, v in resp.getheaders():
        if k.lower() not in excluded:
            resp_headers.append((k, v))

    return Response(data, status=status, headers=resp_headers)


@app.route('/opentakserver')
def opentakserver_page():
    """OpenTAKServer status and management page"""
    return render_template('opentakserver.html')


@app.route('/api/opentakserver/status', methods=['GET'])
def get_ots_status():
    """Get OpenTAKServer service status, connected clients, and video streams"""
    import json as _json

    result_data = {
        'service_running': False,
        'clients': 0,
        'video_streams': []
    }

    # Check service status
    try:
        svc = subprocess.run(
            ['systemctl', 'is-active', 'opentakserver'],
            capture_output=True, text=True, timeout=5
        )
        result_data['service_running'] = svc.stdout.strip() == 'active'
    except Exception:
        pass

    # Count connected EUDs by checking TCP connections on OTS streaming ports
    # Port 8088 = unencrypted TCP, Port 8089 = SSL
    try:
        ss_result = subprocess.run(
            ['ss', '-tn', 'state', 'established', '( sport = :8088 or sport = :8089 )'],
            capture_output=True, text=True, timeout=5
        )
        # Count lines minus the header
        lines = [l for l in ss_result.stdout.strip().split('\n') if l.strip()]
        result_data['clients'] = max(0, len(lines) - 1)  # subtract header line
    except Exception as e:
        print(f"Error counting OTS clients: {e}")

    # Get active video streams from MediaMTX API
    try:
        req = _urlreq.Request('http://127.0.0.1:9997/v3/paths/list')
        resp = _urlreq.urlopen(req, timeout=5)
        paths_data = _json.loads(resp.read())
        items = paths_data.get('items', [])
        for item in items:
            if item.get('ready', False):
                result_data['video_streams'].append({
                    'name': item.get('name', 'unknown'),
                    'source': item.get('source', {}).get('type', 'unknown')
                })
    except Exception:
        pass

    return jsonify(result_data)


@app.route('/api/opentakserver/restart', methods=['POST'])
def restart_ots():
    """Restart OpenTAKServer and related services"""
    try:
        result = subprocess.run(
            ['sudo', 'systemctl', 'restart', 'opentakserver'],
            capture_output=True, text=True, timeout=30
        )
        if result.returncode != 0:
            return jsonify({
                'success': False,
                'error': 'Failed to restart OpenTAKServer',
                'output': result.stderr or result.stdout
            }), 500

        return jsonify({
            'success': True,
            'message': 'OpenTAKServer restarted'
        })
    except subprocess.TimeoutExpired:
        return jsonify({'error': 'Command timed out'}), 500
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/ots/')
@app.route('/ots/<path:subpath>', methods=['GET', 'POST', 'PUT', 'DELETE', 'PATCH'])
def ots_proxy(subpath=''):
    """Reverse proxy to OpenTAKServer web UI.
    
    All requests to /ots/... are forwarded to OTS nginx on localhost:8080.
    This bypasses the OTS_IP_WHITELIST since Flask connects from 127.0.0.1.
    """
    return _proxy_to_ots(subpath)


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)
