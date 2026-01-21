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
from datetime import datetime, timedelta
import threading
import signal
import csv
import os
import sys
import glob
from collections import defaultdict
import time

app = Flask(__name__)

# Configuration
BABELD_HOST = 'localhost'
BABELD_PORT = 33123
REFRESH_INTERVAL = 5  # seconds
DISCONNECTED_DISPLAY_TIME = 60  # seconds

# Store node history
node_history = {}

# WiFi Channel to Frequency Mapping (2.4 GHz)
WIFI_CHANNELS = {
    1: 2412, 2: 2417, 3: 2422, 4: 2427, 5: 2432, 6: 2437,
    7: 2442, 8: 2447, 9: 2452, 10: 2457, 11: 2462, 12: 2467, 13: 2472, 14: 2484
}

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
    """Get IPv4 neighbor cache on wlan1 interface - returns dict {mac: ipv4}"""
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
                    neighbors[mac.lower()] = addr
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
            
            # Parse tx retries/failed for link quality
            elif 'tx retries:' in line and current_mac:
                match = re.search(r'tx retries:\s+(\d+)', line)
                if match:
                    current_stats['tx_retries'] = int(match.group(1))
            
            elif 'tx failed:' in line and current_mac:
                match = re.search(r'tx failed:\s+(\d+)', line)
                if match:
                    current_stats['tx_failed'] = int(match.group(1))
        
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


def get_mesh_nodes():
    """Get current mesh node status"""
    # Query babeld
    dump_data = query_babeld()
    print(f"DEBUG: Babeld dump data length: {len(dump_data)} bytes")
    
    babel_neighbors = parse_babeld_dump(dump_data)
    print(f"DEBUG: Found {len(babel_neighbors)} babel neighbors: {babel_neighbors}")
    
    babel_routes = parse_babeld_routes(dump_data)
    print(f"DEBUG: Found {len(babel_routes)} babel routes: {babel_routes}")
    
    # Probe IPv6 neighbors from Babel to populate IPv6 neighbor cache
    if babel_neighbors:
        ipv6_list = [n['ipv6'] for n in babel_neighbors]
        print(f"DEBUG: Probing IPv6 neighbors: {ipv6_list}")
        probe_ipv6_neighbors(ipv6_list)
        time.sleep(0.5)  # Allow neighbor cache to populate
    
    # Probe Babel next-hops to populate IPv4 neighbor cache
    nexthops = get_babel_nexthops()
    if nexthops:
        print(f"DEBUG: Probing IPv4 nexthops: {nexthops}")
        probe_nexthops(nexthops)
        time.sleep(0.5)  # Allow neighbor cache to populate
    
    # Get all data sources
    ipv6_neighbors = get_ipv6_neighbors()  # {ipv6: mac}
    ipv4_neighbors = get_ipv4_neighbors()  # {mac: ipv4}
    wifi_stats = get_wifi_station_stats()  # {mac: stats}
    
    print(f"DEBUG: IPv6 neighbors: {ipv6_neighbors}")
    print(f"DEBUG: IPv4 neighbors: {ipv4_neighbors}")
    print(f"DEBUG: WiFi stats: {wifi_stats}")
    
    # Group routes by their next-hop IPv6 address
    routes_by_nexthop = {}
    for route in babel_routes:
        nexthop = route['via']
        if nexthop not in routes_by_nexthop:
            routes_by_nexthop[nexthop] = []
        routes_by_nexthop[nexthop].append({
            'prefix': route['prefix'],
            'metric': route['metric'],
            'installed': route.get('installed', False)
        })
    
    # Correlate data using MAC address as the key
    current_time = datetime.now()
    active_nodes = set()
    nodes = []
    
    for babel_neighbor in babel_neighbors:
        babel_ipv6 = babel_neighbor['ipv6']
        
        # Get MAC address from IPv6 neighbor cache
        mac = ipv6_neighbors.get(babel_ipv6)
        if not mac:
            print(f"DEBUG: No MAC found for IPv6 {babel_ipv6}")
            continue
        
        mac = mac.lower()
        
        # Get IPv4 address from IPv4 neighbor cache
        ipv4 = ipv4_neighbors.get(mac)
        print(f"DEBUG: MAC {mac} → IPv4 {ipv4}, babel_ipv6 was {babel_ipv6}")
        if not ipv4:
            print(f"DEBUG: No IPv4 found for MAC {mac}")
            continue
        
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
        
        # Calculate duration
        duration = current_time - node_history[ipv4]['first_seen']
        duration_str = format_duration(duration)
        
        # Classify cost quality
        cost_val = int(babel_neighbor['cost'])
        if cost_val < 400:
            cost_quality = 'good'
        elif cost_val < 700:
            cost_quality = 'fair'
        else:
            cost_quality = 'poor'
        
        # Get routes via this neighbor and apply filtering
        neighbor_routes = routes_by_nexthop.get(babel_ipv6, [])
        neighbor_routes = filter_routes(neighbor_routes)
        
        # Get WiFi stats for this MAC
        wifi = wifi_stats.get(mac, {})
        
        # Classify signal strength
        signal_quality = None
        if 'signal_avg' in wifi:
            sig = wifi['signal_avg']
            if sig >= -50:
                signal_quality = 'excellent'
            elif sig >= -60:
                signal_quality = 'good'
            elif sig >= -70:
                signal_quality = 'fair'
            else:
                signal_quality = 'poor'
        
        node = {
            'ipv4': ipv4,
            'cost': babel_neighbor['cost'],
            'cost_quality': cost_quality,
            'status': 'connected',
            'duration': duration_str,
            'duration_label': 'Connected for',
            'routes': neighbor_routes
        }
        
        # Add WiFi metrics if available
        if wifi:
            node['wifi'] = {
                'signal': wifi.get('signal'),
                'signal_avg': wifi.get('signal_avg'),
                'signal_quality': signal_quality,
                'tx_bitrate': wifi.get('tx_bitrate'),
                'tx_mcs': wifi.get('tx_mcs'),
                'rx_bitrate': wifi.get('rx_bitrate'),
                'rx_mcs': wifi.get('rx_mcs'),
                'expected_throughput': wifi.get('expected_throughput'),
                'tx_retries': wifi.get('tx_retries'),
                'tx_failed': wifi.get('tx_failed')
            }
        
        nodes.append(node)
    
    # Check for recently disconnected nodes
    for ipv4, info in list(node_history.items()):
        if ipv4 not in active_nodes:
            time_since_disconnect = current_time - info['last_seen']
            if time_since_disconnect.total_seconds() <= DISCONNECTED_DISPLAY_TIME:
                duration_str = format_duration(time_since_disconnect)
                nodes.append({
                    'ipv4': ipv4,
                    'cost': 'N/A',
                    'status': 'disconnected',
                    'duration': duration_str,
                    'duration_label': 'Disconnected',
                    'routes': []
                })
            else:
                # Remove from history if too old
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


def parse_scan_csv(csv_file):
    """Parse airodump-ng CSV output and extract channel data"""
    networks = []
    
    if not os.path.exists(csv_file):
        return networks
    
    try:
        with open(csv_file, 'r', encoding='utf-8', errors='ignore') as f:
            content = f.read()
            
        # Split by the station data section - we only want AP data
        sections = content.split('\nStation MAC')
        ap_data = sections[0]
        
        lines = ap_data.strip().split('\n')
        if len(lines) < 2:
            return networks
            
        reader = csv.reader(lines)
        header = next(reader, None)
        
        if not header:
            return networks
        
        # Find column indices
        try:
            bssid_idx = header.index('BSSID')
            pwr_idx = header.index(' Power')
            channel_idx = header.index(' channel')
            essid_idx = header.index(' ESSID')
        except ValueError:
            return networks
        
        for row in reader:
            if len(row) > max(bssid_idx, pwr_idx, channel_idx, essid_idx):
                try:
                    bssid = row[bssid_idx].strip()
                    power = int(row[pwr_idx].strip())
                    channel = row[channel_idx].strip()
                    essid = row[essid_idx].strip()
                    
                    # Skip invalid entries
                    if channel == '-1' or channel == '' or power == -1:
                        continue
                    
                    channel = int(channel)
                    
                    # Only analyze 2.4GHz channels (1-14)
                    if 1 <= channel <= 14:
                        networks.append({
                            'bssid': bssid,
                            'channel': channel,
                            'power': power,
                            'essid': essid
                        })
                        
                except (ValueError, IndexError):
                    continue
                    
    except Exception:
        pass
    
    return networks


def analyze_channels(networks):
    """Calculate congestion scores for each channel"""
    channel_data = defaultdict(lambda: {'networks': [], 'score': 0})
    
    # Group networks by channel
    for network in networks:
        channel = network['channel']
        channel_data[channel]['networks'].append(network)
    
    # Calculate scores for channels 1-14
    for channel in range(1, 15):
        networks_on_channel = channel_data[channel]['networks']
        
        if not networks_on_channel:
            channel_data[channel]['score'] = 0
            continue
        
        # Base score: number of networks * 10
        network_count_score = len(networks_on_channel) * 10
        
        # Signal strength penalty
        power_scores = []
        for network in networks_on_channel:
            power = network['power']
            if power > -30:  # Very strong signal
                power_scores.append(20)
            elif power > -50:  # Strong signal
                power_scores.append(15)
            elif power > -70:  # Medium signal
                power_scores.append(10)
            else:  # Weak signal
                power_scores.append(5)
        
        avg_power_score = sum(power_scores) / len(power_scores) if power_scores else 0
        
        # Adjacent channel interference
        adjacent_penalty = 0
        for adj_channel in range(max(1, channel-2), min(15, channel+3)):
            if adj_channel != channel:
                adj_networks = len(channel_data[adj_channel]['networks'])
                if adj_networks > 0:
                    distance = abs(adj_channel - channel)
                    if distance == 1:
                        adjacent_penalty += adj_networks * 5
                    elif distance == 2:
                        adjacent_penalty += adj_networks * 3
        
        total_score = network_count_score + avg_power_score + adjacent_penalty
        channel_data[channel]['score'] = total_score
    
    return channel_data


def run_channel_scan(duration):
    """Run channel scan in background thread"""
    global scan_state
    
    try:
        # Scan directory
        scan_dir = '/opt/nucleus/web/scan_results'
        os.makedirs(scan_dir, exist_ok=True)
        csv_file = os.path.join(scan_dir, 'scan_output-01.csv')
        
        # Remove old scan files
        old_files = glob.glob(os.path.join(scan_dir, 'scan_output*.csv'))
        if old_files:
            subprocess.run(['sudo', 'rm', '-f'] + old_files, capture_output=True)
        
        # Stop mesh services
        subprocess.run(['sudo', 'systemctl', 'stop', 'mesh-start.service'], 
                      capture_output=True)
        subprocess.run(['sudo', 'pkill', 'wpa_supplicant'], 
                      capture_output=True)
        time.sleep(2)
        
        # Enable monitor mode
        monitor_result = subprocess.run(['sudo', 'airmon-ng', 'start', 'wlan1'], 
                                      capture_output=True)
        if monitor_result.returncode != 0:
            raise Exception("Failed to enable monitor mode")
        
        # Start airodump scan
        with scan_lock:
            scan_state['status'] = 'running'
            scan_state['start_time'] = time.time()
        
        process = subprocess.Popen([
            'sudo', 'airodump-ng', 'wlan1mon', '--band', 'bg', 
            '-w', os.path.join(scan_dir, 'scan_output'), 
            '--output-format', 'csv'
        ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        
        with scan_lock:
            scan_state['process'] = process
        
        # Wait for specified duration
        time.sleep(duration)
        
        # Stop scan gracefully
        try:
            process.send_signal(signal.SIGINT)
            process.wait(timeout=5)
        except:
            process.kill()
        
        # Parse results
        time.sleep(1)  # Allow file to be written
        networks = parse_scan_csv(csv_file)
        channel_data = analyze_channels(networks)
        
        # Format results
        results = []
        for channel in range(1, 15):
            data = channel_data[channel]
            network_count = len(data['networks'])
            score = data['score']
            
            # Determine status
            if score == 0:
                status = 'EMPTY'
            elif score < 20:
                status = 'EXCELLENT'
            elif score < 40:
                status = 'GOOD'
            elif score < 60:
                status = 'MODERATE'
            else:
                status = 'CONGESTED'
            
            results.append({
                'channel': channel,
                'network_count': network_count,
                'score': score,
                'status': status,
                'networks': data['networks'][:3]  # Show top 3 networks
            })
        
        # Sort by score (lower is better)
        results.sort(key=lambda x: x['score'])
        
        with scan_lock:
            scan_state['status'] = 'complete'
            scan_state['results'] = results
            scan_state['process'] = None
        
    except Exception as e:
        with scan_lock:
            scan_state['status'] = 'error'
            scan_state['error'] = str(e)
            scan_state['process'] = None
    
    finally:
        # Cleanup - always restore mesh services
        try:
            subprocess.run(['sudo', 'airmon-ng', 'stop', 'wlan1mon'], 
                          capture_output=True)
            subprocess.run(['sudo', 'systemctl', 'start', 'mesh-start.service'], 
                          capture_output=True)
            
            # Wait for mesh to stabilize and Babel to install routes
            time.sleep(10)
            
            # Probe nexthops to populate IPv4 neighbor cache
            nexthops = get_babel_nexthops()
            if nexthops:
                print(f"DEBUG: Post-scan probing nexthops: {nexthops}")
                probe_nexthops(nexthops)
        except:
            pass


@app.route('/')
def index():
    """Main dashboard page"""
    return render_template('index.html', 
                         refresh_interval=REFRESH_INTERVAL)


@app.route('/api/nodes')
def api_nodes():
    """API endpoint for mesh node data"""
    nodes = get_mesh_nodes()
    return jsonify({
        'nodes': nodes,
        'timestamp': datetime.now().isoformat()
    })


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
        
        # Step 2: Run config generation script
        result = subprocess.run(['/opt/nucleus/bin/config_generation.sh'],
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


@app.route('/ethernet')
def ethernet():
    """Ethernet mode control page"""
    return render_template('ethernet.html')


@app.route('/opendht')
def opendht():
    """OpenDHT monitoring page"""
    return render_template('opendht.html')


@app.route('/api/opendht/status', methods=['GET'])
def get_opendht_status():
    """Get OpenDHT container status and configuration"""
    try:
        import json
        
        # Check Docker container status
        container_running = False
        try:
            result = subprocess.run(['sudo', 'docker', 'ps', '--filter', 'name=dhtnode', '--format', '{{.Status}}'],
                                  capture_output=True, text=True, timeout=5)
            container_running = 'Up' in result.stdout
        except Exception as e:
            print(f"Error checking container: {e}")
        
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
            'container_running': container_running,
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
                              capture_output=True, text=True, timeout=30)
        
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
        
        # Reset state
        with scan_lock:
            scan_state['status'] = 'starting'
            scan_state['duration'] = duration
            scan_state['results'] = None
            scan_state['error'] = None
            scan_state['progress'] = 0
        
        # Start scan in background thread
        thread = threading.Thread(target=run_channel_scan, args=(duration,))
        thread.daemon = True
        thread.start()
        
        return jsonify({
            'success': True,
            'message': f'Channel scan started for {duration} seconds',
            'duration': duration
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
        
        # Find best channels (non-overlapping: 1, 6, 11)
        non_overlapping = [1, 6, 11]
        best_channels = []
        
        for result in results:
            if result['channel'] in non_overlapping:
                best_channels.append({
                    'channel': result['channel'],
                    'score': result['score'],
                    'status': result['status'],
                    'network_count': result['network_count'],
                    'recommended': True
                })
        
        # Sort best channels by score
        best_channels.sort(key=lambda x: x['score'])
        
        return jsonify({
            'all_channels': results,
            'best_channels': best_channels[:3],  # Top 3 recommendations
            'total_networks': sum(r['network_count'] for r in results)
        })


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


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)
