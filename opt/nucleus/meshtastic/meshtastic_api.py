#!/usr/bin/env python3
"""
Meshtastic CoT Bridge API + Radio Configurator
===============================================
Flask Blueprint for controlling the ATAK CoT Bridge service and for
configuring the Meshtastic radio directly from the web UI.

Bridge control: status, enable, disable, logs.
The bridge runs as a systemd service (cot-bridge.service).

Radio configurator: read/apply radio config and share the channel URL
(QR code) without ever needing the phone app. Because the CoT bridge
owns the serial port exclusively, every radio operation uses the
"bridge pause" pattern:

    stop cot-bridge -> wait for serial release -> run meshtastic CLI
    -> restart cot-bridge

See docs/meshtastic/meshtastic_configurator.md for full documentation.

Usage (integrated into main app):
    from meshtastic_api import meshtastic_bp
    app.register_blueprint(meshtastic_bp)
"""

import base64
import glob
import io
import json
import os
import subprocess
import threading
import time
from contextlib import contextmanager

from flask import Blueprint, Response, jsonify, request

MESH_CONF_PATH = "/etc/nucleus/mesh.conf"

# meshtastic CLI invoked as a module — mesh-web.service's PATH does not
# include ~/.local/bin where the `meshtastic` entry point lives.
MESHTASTIC_CMD = ["python3", "-m", "meshtastic"]

# Cached parsed radio config (survives page reloads without touching radio)
CONFIG_CACHE_PATH = "/tmp/meshtastic_config.json"
EXPORT_TMP_PATH = "/tmp/meshtastic_export.yaml"

# Serial release delay after stopping the bridge (SerialInterface takes a
# moment to fully release the port after the process exits)
SERIAL_RELEASE_SECS = 2

# After a config write the radio reboots; wait for it to come back
RADIO_REBOOT_WAIT_SECS = 30

meshtastic_bp = Blueprint('meshtastic', __name__)

# Only one radio config operation at a time (they stop/start the bridge
# and hold the serial port)
_config_lock = threading.Lock()


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
    except Exception:
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


@meshtastic_bp.route('/api/meshtastic/bridge/logs', methods=['GET'])
def bridge_logs():
    """Return last 50 cot-bridge journal lines + health summary."""
    try:
        result = subprocess.run(
            ['journalctl', '-u', 'cot-bridge.service', '-n', '50',
             '--no-pager', '-o', 'cat'],
            capture_output=True, text=True, timeout=5
        )
        lines = result.stdout.strip().split('\n') if result.stdout.strip() else []
    except Exception:
        lines = []

    # Parse health from the lines
    health = 'unknown'
    last_activity = None
    error_msg = None

    import time as _time
    from datetime import datetime as _dt

    now = _time.time()
    for line in reversed(lines):
        # Find last TX or RX line for activity timestamp
        if last_activity is None and ('[INFO]' in line and ('TX →' in line or 'RX ←' in line)):
            try:
                # Parse timestamp from -o cat line: "19:16:34 [INFO] ..."
                ts_str = line.split()[0]
                today = _dt.now()
                ts = _dt.strptime(ts_str, "%H:%M:%S").replace(
                    year=today.year, month=today.month, day=today.day)
                last_activity = int(now - ts.timestamp())
            except Exception:
                pass

        # Find errors/warnings
        if error_msg is None and ('[WARNING]' in line or '[ERROR]' in line):
            try:
                error_msg = line.split(']', 2)[-1].strip()
            except Exception:
                error_msg = line

    if last_activity is not None:
        if last_activity < 120:
            health = 'healthy'
        else:
            health = 'stale'
    elif lines:
        health = 'no_traffic'
    else:
        health = 'no_logs'

    # Override to error if recent warning/error found and no activity since
    if error_msg and (last_activity is None or last_activity > 60):
        health = 'error'

    return jsonify({
        'lines': lines,
        'health': health,
        'last_activity_secs': last_activity,
        'last_error': error_msg,
    })


# ═══════════════════════════════════════════════════════════════
#  RADIO CONFIGURATOR
#  Read/apply radio config + share channel URL, via the
#  bridge-pause pattern. See docs/meshtastic/meshtastic_configurator.md
# ═══════════════════════════════════════════════════════════════

# Editable field map. To add a new field later:
#   1. Add an entry here (name -> validator)
#   2. Add its CLI args in _build_command_groups()
#   3. Add it to _parse_export() so reads pick it up
#   4. Add an input to the Radio Config panel in meshtastic.html
VALID_MODEM_PRESETS = {
    'LONG_FAST', 'LONG_SLOW', 'LONG_MODERATE',
    'MEDIUM_FAST', 'MEDIUM_SLOW',
    'SHORT_FAST', 'SHORT_SLOW', 'SHORT_TURBO',
}


def _validate_changes(changes):
    """Validate an apply request. Returns error string or None."""
    if not isinstance(changes, dict) or not changes:
        return 'No changes provided'

    allowed = {'owner', 'owner_short', 'modem_preset', 'hop_limit',
               'tx_power', 'channel_name', 'psk_random'}
    unknown = set(changes) - allowed
    if unknown:
        return f'Unknown fields: {", ".join(sorted(unknown))}'

    if 'owner' in changes:
        v = str(changes['owner']).strip()
        if not v or len(v) > 39:
            return 'Long name must be 1-39 characters'
    if 'owner_short' in changes:
        v = str(changes['owner_short']).strip()
        if not v or len(v) > 4:
            return 'Short name must be 1-4 characters'
    if 'modem_preset' in changes:
        if str(changes['modem_preset']) not in VALID_MODEM_PRESETS:
            return f'Invalid modem preset: {changes["modem_preset"]}'
    if 'hop_limit' in changes:
        try:
            v = int(changes['hop_limit'])
        except (TypeError, ValueError):
            return 'Hop limit must be a number'
        if not 1 <= v <= 7:
            return 'Hop limit must be 1-7'
    if 'tx_power' in changes:
        try:
            v = int(changes['tx_power'])
        except (TypeError, ValueError):
            return 'TX power must be a number'
        if not 0 <= v <= 30:
            return 'TX power must be 0-30 dBm'
    if 'channel_name' in changes:
        v = str(changes['channel_name']).strip()
        if not v or len(v) > 11:
            return 'Channel name must be 1-11 characters'
    if 'psk_random' in changes:
        if not isinstance(changes['psk_random'], bool):
            return 'psk_random must be true/false'

    return None


def _build_command_groups(changes):
    """Translate validated changes into meshtastic CLI invocations.

    Returns a list of arg-lists. Groups are run sequentially with a
    radio-reboot wait between them (each config commit reboots the radio).
    Owner + lora settings go in one invocation; channel settings in another
    (mixing --set and --ch-set in one command is unreliable per meshtastic
    docs).
    """
    groups = []

    # Group 1: owner + lora config (--set-owner / --set)
    args = []
    if 'owner' in changes:
        args += ['--set-owner', str(changes['owner']).strip()]
    if 'owner_short' in changes:
        args += ['--set-owner-short', str(changes['owner_short']).strip()]
    if 'modem_preset' in changes:
        args += ['--set', 'lora.modem_preset', str(changes['modem_preset'])]
    if 'hop_limit' in changes:
        args += ['--set', 'lora.hop_limit', str(int(changes['hop_limit']))]
    if 'tx_power' in changes:
        args += ['--set', 'lora.tx_power', str(int(changes['tx_power']))]
    if args:
        groups.append(args)

    # Group 2: primary channel settings (--ch-set ... --ch-index 0)
    args = []
    if 'channel_name' in changes:
        args += ['--ch-set', 'name', str(changes['channel_name']).strip()]
    if changes.get('psk_random'):
        args += ['--ch-set', 'psk', 'random']
    if args:
        groups.append(args + ['--ch-index', '0'])

    return groups


def _run_meshtastic(args, timeout=120):
    """Run a meshtastic CLI command. Returns (returncode, combined_output)."""
    try:
        result = subprocess.run(
            MESHTASTIC_CMD + args,
            capture_output=True, text=True, timeout=timeout
        )
        out = (result.stdout or '') + (result.stderr or '')
        return result.returncode, out.strip()
    except subprocess.TimeoutExpired:
        return -1, f'meshtastic CLI timed out after {timeout}s'
    except Exception as e:
        return -1, str(e)


def _wait_for_radio(max_wait=RADIO_REBOOT_WAIT_SECS):
    """Wait for the radio's USB serial port to (re)appear after a reboot.

    The port often stays present through the reboot, so also add a fixed
    settle delay to let the firmware finish booting.
    """
    deadline = time.time() + max_wait
    while time.time() < deadline:
        if _radio_detected():
            break
        time.sleep(1)
    time.sleep(5)  # firmware settle time after the port appears


@contextmanager
def _bridge_paused():
    """Stop the CoT bridge (if running) for the duration of a radio
    operation, then restart it. If the bridge isn't running, no-op."""
    was_active = _service_is_active()
    if was_active:
        subprocess.run(
            ['sudo', 'systemctl', 'stop', 'cot-bridge.service'],
            capture_output=True, text=True, timeout=15
        )
        time.sleep(SERIAL_RELEASE_SECS)
    try:
        yield
    finally:
        if was_active:
            subprocess.run(
                ['sudo', 'systemctl', 'start', 'cot-bridge.service'],
                capture_output=True, text=True, timeout=15
            )


def _decode_channel_url(url):
    """Decode a meshtastic channel URL into channel summaries.

    Returns a list of {index, name, has_psk} dicts, or [] on failure.
    Used both for display and to validate pasted URLs before touching
    the radio.
    """
    try:
        from meshtastic.protobuf import apponly_pb2
        part = url.split('#', 1)[1]
        part += '=' * (-len(part) % 4)
        channel_set = apponly_pb2.ChannelSet()
        channel_set.ParseFromString(base64.urlsafe_b64decode(part))
        channels = []
        for i, s in enumerate(channel_set.settings):
            channels.append({
                'index': i,
                'name': s.name or '(default)',
                'has_psk': bool(s.psk),
            })
        return channels
    except Exception:
        return []


def _parse_export(yaml_text):
    """Parse a --export-config YAML into the key fields the UI edits."""
    import yaml
    data = yaml.safe_load(yaml_text) or {}
    cfg = data.get('config', {}) or {}
    lora = cfg.get('lora', {}) or {}
    device = cfg.get('device', {}) or {}

    channel_url = data.get('channel_url', '') or data.get('channelUrl', '') or ''
    channels = _decode_channel_url(channel_url)

    return {
        'owner': data.get('owner', ''),
        'owner_short': data.get('owner_short', ''),
        'region': lora.get('region', 'UNSET'),
        'modem_preset': lora.get('modemPreset', 'LONG_FAST'),
        'hop_limit': lora.get('hopLimit', 3),
        'tx_power': lora.get('txPower', 0),
        'role': device.get('role', 'CLIENT'),
        'channel_url': channel_url,
        'channels': channels,
        'channel_name': channels[0]['name'] if channels else '',
    }


def _read_config_from_radio():
    """Export config from the radio and parse it. Caller must hold the
    lock and have the bridge paused. Raises RuntimeError on failure."""
    try:
        os.remove(EXPORT_TMP_PATH)
    except OSError:
        pass

    rc, out = _run_meshtastic(['--export-config', EXPORT_TMP_PATH])
    if rc != 0:
        raise RuntimeError(f'Config export failed: {out[-300:]}')

    try:
        with open(EXPORT_TMP_PATH) as f:
            yaml_text = f.read()
    except OSError as e:
        raise RuntimeError(f'Export file not written: {e}')

    parsed = _parse_export(yaml_text)
    parsed['read_at'] = int(time.time())
    _write_cache(parsed)
    return parsed


def _write_cache(parsed):
    """Atomically write the parsed config cache."""
    tmp = CONFIG_CACHE_PATH + '.tmp'
    with open(tmp, 'w') as f:
        json.dump(parsed, f)
    os.replace(tmp, CONFIG_CACHE_PATH)


def _read_cache():
    """Read the parsed config cache, or None if never read."""
    try:
        with open(CONFIG_CACHE_PATH) as f:
            return json.load(f)
    except Exception:
        return None


@meshtastic_bp.route('/api/meshtastic/config', methods=['GET'])
def config_cached():
    """Return the last-read radio config (instant — no radio access)."""
    cached = _read_cache()
    return jsonify({
        'config': cached,
        'busy': _config_lock.locked(),
    })


@meshtastic_bp.route('/api/meshtastic/config/read', methods=['POST'])
def config_read():
    """Read fresh config from the radio (pauses the bridge, ~15s)."""
    if not _radio_detected():
        return jsonify({'success': False, 'error': 'No radio detected'}), 400
    if not _config_lock.acquire(blocking=False):
        return jsonify({'success': False,
                        'error': 'Another radio operation is in progress'}), 409
    try:
        with _bridge_paused():
            parsed = _read_config_from_radio()
        return jsonify({'success': True, 'config': parsed})
    except RuntimeError as e:
        return jsonify({'success': False, 'error': str(e)}), 500
    finally:
        _config_lock.release()


@meshtastic_bp.route('/api/meshtastic/config/apply', methods=['POST'])
def config_apply():
    """Apply changed fields to the radio (pauses bridge, radio reboots,
    ~30-60s depending on how many field groups changed)."""
    if not _radio_detected():
        return jsonify({'success': False, 'error': 'No radio detected'}), 400

    body = request.get_json(silent=True) or {}
    changes = body.get('changes', {})
    err = _validate_changes(changes)
    if err:
        return jsonify({'success': False, 'error': err}), 400

    groups = _build_command_groups(changes)
    if not groups:
        return jsonify({'success': False, 'error': 'No changes provided'}), 400

    if not _config_lock.acquire(blocking=False):
        return jsonify({'success': False,
                        'error': 'Another radio operation is in progress'}), 409
    try:
        with _bridge_paused():
            for i, args in enumerate(groups):
                rc, out = _run_meshtastic(args)
                if rc != 0:
                    return jsonify({
                        'success': False,
                        'error': f'Config write failed: {out[-300:]}'
                    }), 500
                # Config commit reboots the radio — wait before next command
                _wait_for_radio()

            # Re-read so the cache/UI reflect what the radio actually has
            parsed = _read_config_from_radio()

        return jsonify({'success': True,
                        'message': 'Config applied — radio rebooted',
                        'config': parsed})
    except RuntimeError as e:
        return jsonify({'success': False, 'error': str(e)}), 500
    finally:
        _config_lock.release()


@meshtastic_bp.route('/api/meshtastic/config/channel-url', methods=['POST'])
def config_channel_url():
    """Apply a pasted channel URL (QR-code equivalent) to the radio.

    This is how config is shared between nodes: copy the URL from one
    node's Share panel, paste it here on another node."""
    if not _radio_detected():
        return jsonify({'success': False, 'error': 'No radio detected'}), 400

    body = request.get_json(silent=True) or {}
    url = str(body.get('url', '')).strip()
    if not url:
        return jsonify({'success': False, 'error': 'No URL provided'}), 400

    # Validate the URL decodes before touching the radio
    channels = _decode_channel_url(url)
    if not channels:
        return jsonify({'success': False,
                        'error': 'Invalid channel URL — could not decode'}), 400

    if not _config_lock.acquire(blocking=False):
        return jsonify({'success': False,
                        'error': 'Another radio operation is in progress'}), 409
    try:
        with _bridge_paused():
            rc, out = _run_meshtastic(['--ch-set-url', url])
            if rc != 0:
                return jsonify({
                    'success': False,
                    'error': f'Channel URL apply failed: {out[-300:]}'
                }), 500
            _wait_for_radio()
            parsed = _read_config_from_radio()

        return jsonify({'success': True,
                        'message': 'Channel URL applied — radio rebooted',
                        'config': parsed})
    except RuntimeError as e:
        return jsonify({'success': False, 'error': str(e)}), 500
    finally:
        _config_lock.release()


@meshtastic_bp.route('/api/meshtastic/config/qr', methods=['GET'])
def config_qr():
    """Render the cached channel URL as an SVG QR code (works offline).

    Scannable by the official Meshtastic app (BLE/handheld users) or any
    camera app (to copy the URL for pasting into another node's web UI).
    """
    cached = _read_cache()
    url = (cached or {}).get('channel_url', '')
    if not url:
        return jsonify({'error': 'No channel URL — read config first'}), 404

    try:
        import qrcode
        import qrcode.image.svg
        img = qrcode.make(url, image_factory=qrcode.image.svg.SvgPathImage,
                          box_size=14, border=2)
        buf = io.BytesIO()
        img.save(buf)
        return Response(buf.getvalue(), mimetype='image/svg+xml',
                        headers={'Cache-Control': 'no-cache'})
    except Exception as e:
        return jsonify({'error': f'QR generation failed: {e}'}), 500
