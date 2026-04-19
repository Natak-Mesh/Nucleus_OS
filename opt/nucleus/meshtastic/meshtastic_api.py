#!/usr/bin/env python3
"""
Meshtastic CoT Bridge API
===========================
Flask Blueprint for controlling the ATAK CoT Bridge service.

Provides status, enable, and disable endpoints.
The bridge runs as a systemd service (cot-bridge.service).

Usage (integrated into main app):
    from meshtastic_api import meshtastic_bp
    app.register_blueprint(meshtastic_bp)
"""

import glob
import os
import subprocess

from flask import Blueprint, jsonify

MESH_CONF_PATH = "/etc/nucleus/mesh.conf"

meshtastic_bp = Blueprint('meshtastic', __name__)


def _service_is_active():
    """Check if cot-bridge.service is currently running."""
    try:
        result = subprocess.run(
            ['sudo', 'systemctl', 'is-active', 'cot-bridge.service'],
            capture_output=True, text=True, timeout=5
        )
        return result.stdout.strip() == 'active'
    except Exception:
        return False


def _service_is_enabled():
    """Check if cot-bridge.service is enabled (starts on boot)."""
    try:
        result = subprocess.run(
            ['systemctl', 'is-enabled', 'cot-bridge.service'],
            capture_output=True, text=True, timeout=5
        )
        return result.stdout.strip() == 'enabled'
    except Exception:
        return False


def _radio_detected():
    """Check if a Meshtastic radio is connected via USB serial."""
    return bool(glob.glob('/dev/ttyACM*'))


def _read_config_flag():
    """Read COT_BRIDGE_ENABLED from mesh.conf."""
    try:
        with open(MESH_CONF_PATH, 'r') as f:
            for line in f:
                line = line.strip()
                if line.startswith('COT_BRIDGE_ENABLED='):
                    val = line.split('=', 1)[1].strip('"').lower()
                    return val in ('true', '1', 'yes')
    except Exception:
        pass
    return False


def _write_config_flag(enabled):
    """Write COT_BRIDGE_ENABLED to mesh.conf."""
    value = 'true' if enabled else 'false'
    try:
        with open(MESH_CONF_PATH, 'r') as f:
            lines = f.readlines()

        new_lines = []
        found = False
        for line in lines:
            if line.strip().startswith('COT_BRIDGE_ENABLED='):
                new_lines.append(f'COT_BRIDGE_ENABLED={value}\n')
                found = True
            else:
                new_lines.append(line)

        if not found:
            new_lines.append(f'COT_BRIDGE_ENABLED={value}\n')

        with open(MESH_CONF_PATH, 'w') as f:
            f.writelines(new_lines)

        return True
    except Exception as e:
        return False


@meshtastic_bp.route('/api/meshtastic/status', methods=['GET'])
def status():
    """Get bridge status: config flag, service state, radio detected."""
    return jsonify({
        'bridge_enabled': _read_config_flag(),
        'service_active': _service_is_active(),
        'service_enabled': _service_is_enabled(),
        'radio_detected': _radio_detected(),
    })


@meshtastic_bp.route('/api/meshtastic/bridge/enable', methods=['POST'])
def bridge_enable():
    """Enable the CoT bridge: write config, enable + start service."""
    if not _write_config_flag(True):
        return jsonify({'success': False, 'error': 'Failed to write config'}), 500

    try:
        subprocess.run(
            ['sudo', 'systemctl', 'enable', 'cot-bridge.service'],
            capture_output=True, text=True, timeout=10
        )
        result = subprocess.run(
            ['sudo', 'systemctl', 'start', 'cot-bridge.service'],
            capture_output=True, text=True, timeout=10
        )
        if result.returncode != 0:
            return jsonify({
                'success': False,
                'error': f'Service start failed: {result.stderr.strip()}'
            }), 500
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

    return jsonify({'success': True, 'message': 'CoT bridge enabled and started'})


@meshtastic_bp.route('/api/meshtastic/bridge/disable', methods=['POST'])
def bridge_disable():
    """Disable the CoT bridge: stop + disable service, write config."""
    try:
        subprocess.run(
            ['sudo', 'systemctl', 'stop', 'cot-bridge.service'],
            capture_output=True, text=True, timeout=10
        )
        subprocess.run(
            ['sudo', 'systemctl', 'disable', 'cot-bridge.service'],
            capture_output=True, text=True, timeout=10
        )
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

    if not _write_config_flag(False):
        return jsonify({'success': False, 'error': 'Failed to write config'}), 500

    # Reboot the node to fully release the radio back to Bluetooth
    subprocess.Popen(['sudo', 'reboot'], close_fds=True)

    return jsonify({'success': True, 'message': 'CoT bridge disabled — node rebooting'})
