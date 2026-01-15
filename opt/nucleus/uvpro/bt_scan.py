#!/usr/bin/env python3
"""
bt_scan.py - Bluetooth Device Discovery and Pairing

PURPOSE:
    Scan for nearby UV-Pro radios and initiate Bluetooth pairing.
    Provides a simple command-line interface for discovery and pairing workflow.

FUNCTIONALITY:
    - Scan for discoverable Bluetooth devices
    - Filter/identify UV-Pro radios by device name or characteristics
    - Initiate pairing with selected device
    - List currently paired devices
    - Remove/unpair devices

IMPLEMENTATION:
    Uses subprocess to wrap bluetoothctl commands:
    - bluetoothctl scan on
    - bluetoothctl pair [MAC]
    - bluetoothctl trust [MAC]
    - bluetoothctl devices

USAGE:
    python3 bt_scan.py scan          # Scan for devices
    python3 bt_scan.py list          # List paired devices
    python3 bt_scan.py pair <MAC>    # Pair with specific device
    python3 bt_scan.py remove <MAC>  # Remove/unpair device

NOTES:
    - UV-Pro must be in pairing mode (flashing red/green LED)
    - Requires hci0 adapter to be UP and powered on
    - May need sudo/root depending on BlueZ configuration
"""

import subprocess
import sys
import time
import re
import json


def run_bluetoothctl_command(commands):
    """
    Run bluetoothctl commands and return output
    
    Args:
        commands: List of commands to send to bluetoothctl
    
    Returns:
        tuple: (stdout, stderr, returncode)
    """
    try:
        # Build command string
        cmd_string = '\n'.join(commands) + '\nexit\n'
        
        # Run bluetoothctl in batch mode
        process = subprocess.Popen(
            ['bluetoothctl'],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True
        )
        
        stdout, stderr = process.communicate(input=cmd_string, timeout=30)
        return stdout, stderr, process.returncode
        
    except subprocess.TimeoutExpired:
        process.kill()
        return "", "Command timed out", 1
    except Exception as e:
        return "", str(e), 1


def scan_devices(timeout=10, filter_uvpro=True):
    """
    Scan for Bluetooth devices
    
    Args:
        timeout: Scan duration in seconds
        filter_uvpro: If True, only return UV-Pro devices
    
    Returns:
        list: List of dicts with {mac, name, rssi}
    """
    print(f"Scanning for Bluetooth devices ({timeout}s)...")
    
    # Start scan
    commands = ['power on', 'scan on']
    stdout, stderr, code = run_bluetoothctl_command(commands)
    
    if code != 0:
        print(f"Error starting scan: {stderr}")
        return []
    
    # Let scan run
    time.sleep(timeout)
    
    # Stop scan and get devices
    commands = ['scan off', 'devices']
    stdout, stderr, code = run_bluetoothctl_command(commands)
    
    devices = []
    for line in stdout.split('\n'):
        # Parse: Device 38:D2:00:01:55:C0 UV-PRO
        match = re.match(r'Device\s+([0-9A-F:]+)\s+(.*)', line, re.IGNORECASE)
        if match:
            mac = match.group(1)
            name = match.group(2).strip()
            
            device = {
                'mac': mac,
                'name': name,
                'is_uvpro': is_uvpro(name, mac)
            }
            
            # Filter if requested
            if filter_uvpro and not device['is_uvpro']:
                continue
            
            devices.append(device)
    
    return devices


def list_paired_devices():
    """
    List devices that are already paired
    
    Returns:
        list: List of dicts with {mac, name, paired, connected}
    """
    commands = ['devices Paired']
    stdout, stderr, code = run_bluetoothctl_command(commands)
    
    if code != 0:
        print(f"Error listing paired devices: {stderr}")
        return []
    
    devices = []
    for line in stdout.split('\n'):
        match = re.match(r'Device\s+([0-9A-F:]+)\s+(.*)', line, re.IGNORECASE)
        if match:
            mac = match.group(1)
            name = match.group(2).strip()
            
            # Get device info
            info_commands = [f'info {mac}']
            info_stdout, _, _ = run_bluetoothctl_command(info_commands)
            
            paired = 'Paired: yes' in info_stdout
            connected = 'Connected: yes' in info_stdout
            
            devices.append({
                'mac': mac,
                'name': name,
                'paired': paired,
                'connected': connected,
                'is_uvpro': is_uvpro(name, mac)
            })
    
    return devices


def pair_device(mac, trust=True):
    """
    Pair with a Bluetooth device
    
    Args:
        mac: MAC address of device
        trust: If True, also trust the device for auto-reconnect
    
    Returns:
        bool: True if successful
    """
    print(f"Pairing with {mac}...")
    
    commands = ['power on', f'pair {mac}']
    if trust:
        commands.append(f'trust {mac}')
    
    stdout, stderr, code = run_bluetoothctl_command(commands)
    
    # Check for success indicators
    if 'Pairing successful' in stdout or 'already paired' in stdout.lower():
        print(f"✓ Paired successfully with {mac}")
        if trust and ('trust' in stdout.lower() or 'Changing' in stdout):
            print(f"✓ Trusted {mac}")
        return True
    else:
        print(f"✗ Pairing failed: {stderr}")
        print(f"Output: {stdout}")
        return False


def trust_device(mac):
    """
    Trust a device for auto-reconnect
    
    Args:
        mac: MAC address of device
    
    Returns:
        bool: True if successful
    """
    print(f"Trusting {mac}...")
    
    commands = [f'trust {mac}']
    stdout, stderr, code = run_bluetoothctl_command(commands)
    
    if code == 0 or 'trust' in stdout.lower():
        print(f"✓ Trusted {mac}")
        return True
    else:
        print(f"✗ Trust failed: {stderr}")
        return False


def remove_device(mac):
    """
    Remove/unpair a device
    
    Args:
        mac: MAC address of device
    
    Returns:
        bool: True if successful
    """
    print(f"Removing {mac}...")
    
    commands = [f'remove {mac}']
    stdout, stderr, code = run_bluetoothctl_command(commands)
    
    if 'Device has been removed' in stdout or code == 0:
        print(f"✓ Removed {mac}")
        return True
    else:
        print(f"✗ Remove failed: {stderr}")
        return False


def is_uvpro(name, mac):
    """
    Identify if device is a UV-Pro radio
    
    Args:
        name: Device name
        mac: MAC address
    
    Returns:
        bool: True if device is UV-Pro
    """
    # Check name contains UV-P or UV-PRO
    if name and ('UV-P' in name.upper() or 'UVPRO' in name.upper()):
        return True
    
    # Check MAC prefix (38:D2:00 is BTech OUI)
    if mac.upper().startswith('38:D2:00'):
        return True
    
    return False


def print_devices(devices, title="Devices"):
    """Pretty print device list"""
    if not devices:
        print(f"\nNo {title.lower()} found.")
        return
    
    print(f"\n{title}:")
    print("-" * 70)
    for dev in devices:
        uvpro_marker = "🔘 UV-Pro" if dev.get('is_uvpro') else ""
        paired_marker = "✓ Paired" if dev.get('paired') else ""
        connected_marker = "⚡ Connected" if dev.get('connected') else ""
        
        status = ' '.join(filter(None, [uvpro_marker, paired_marker, connected_marker]))
        
        print(f"MAC:  {dev['mac']}")
        print(f"Name: {dev['name']}")
        if status:
            print(f"      {status}")
        print("-" * 70)


def main():
    if len(sys.argv) < 2:
        print("Usage:")
        print("  python3 bt_scan.py scan [timeout]     # Scan for UV-Pro devices")
        print("  python3 bt_scan.py scan-all [timeout] # Scan for all devices")
        print("  python3 bt_scan.py list               # List paired devices")
        print("  python3 bt_scan.py pair <MAC>         # Pair with device")
        print("  python3 bt_scan.py trust <MAC>        # Trust device")
        print("  python3 bt_scan.py remove <MAC>       # Remove/unpair device")
        print("  python3 bt_scan.py json scan          # Output scan as JSON")
        print("  python3 bt_scan.py json list          # Output paired as JSON")
        sys.exit(1)
    
    command = sys.argv[1]
    
    if command == 'scan' or command == 'scan-all':
        timeout = int(sys.argv[2]) if len(sys.argv) > 2 else 10
        filter_uvpro = (command == 'scan')
        devices = scan_devices(timeout=timeout, filter_uvpro=filter_uvpro)
        title = "UV-Pro Radios Found" if filter_uvpro else "Bluetooth Devices Found"
        print_devices(devices, title)
        
    elif command == 'list':
        devices = list_paired_devices()
        print_devices(devices, "Paired Devices")
        
    elif command == 'pair':
        if len(sys.argv) < 3:
            print("Error: MAC address required")
            print("Usage: python3 bt_scan.py pair <MAC>")
            sys.exit(1)
        mac = sys.argv[2]
        success = pair_device(mac, trust=True)
        sys.exit(0 if success else 1)
        
    elif command == 'trust':
        if len(sys.argv) < 3:
            print("Error: MAC address required")
            print("Usage: python3 bt_scan.py trust <MAC>")
            sys.exit(1)
        mac = sys.argv[2]
        success = trust_device(mac)
        sys.exit(0 if success else 1)
        
    elif command == 'remove':
        if len(sys.argv) < 3:
            print("Error: MAC address required")
            print("Usage: python3 bt_scan.py remove <MAC>")
            sys.exit(1)
        mac = sys.argv[2]
        success = remove_device(mac)
        sys.exit(0 if success else 1)
        
    elif command == 'json':
        if len(sys.argv) < 3:
            print("Error: subcommand required (scan or list)")
            sys.exit(1)
        
        subcommand = sys.argv[2]
        if subcommand == 'scan':
            devices = scan_devices(timeout=10, filter_uvpro=True)
        elif subcommand == 'list':
            devices = list_paired_devices()
        else:
            print(f"Error: unknown subcommand '{subcommand}'")
            sys.exit(1)
        
        print(json.dumps(devices, indent=2))
        
    else:
        print(f"Error: Unknown command '{command}'")
        sys.exit(1)


if __name__ == '__main__':
    main()
