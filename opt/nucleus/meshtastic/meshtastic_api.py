#!/usr/bin/env python3
"""
Meshtastic Flask API
=====================
Flask Blueprint wrapping the MeshtasticManager.
Can run standalone on port 5001 or be registered into the main app.

Usage (standalone):
    python3 meshtastic_api.py

Usage (integrated):
    from meshtastic_api import meshtastic_bp, mgr
    app.register_blueprint(meshtastic_bp)

Test with curl:
    curl -X POST localhost:5001/api/meshtastic/connect
    curl localhost:5001/api/meshtastic/status
    curl -X POST -H "Content-Type: application/json" -d '{"text":"hello"}' localhost:5001/api/meshtastic/send
    curl localhost:5001/api/meshtastic/messages
    curl -X POST localhost:5001/api/meshtastic/disconnect
"""

import sys
import os

# Add meshtastic module directory so we can import the manager
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from flask import Flask, Blueprint, jsonify, request
from meshtastic_manager import MeshtasticManager

# Blueprint for integration into main app
meshtastic_bp = Blueprint('meshtastic', __name__)

# Single persistent manager instance
mgr = MeshtasticManager()


@meshtastic_bp.route('/api/meshtastic/connect', methods=['POST'])
def connect():
    """Take serial control of the meshtastic radio."""
    data = request.get_json(silent=True) or {}
    port = data.get('port', None)

    result = mgr.connect(port=port)
    status_code = 200 if result['success'] else 500
    return jsonify(result), status_code


@meshtastic_bp.route('/api/meshtastic/disconnect', methods=['POST'])
def disconnect():
    """Release serial control and reboot radio to restore BLE."""
    data = request.get_json(silent=True) or {}
    reboot = data.get('reboot', True)

    result = mgr.disconnect(reboot_radio=reboot)
    status_code = 200 if result['success'] else 400
    return jsonify(result), status_code


@meshtastic_bp.route('/api/meshtastic/status', methods=['GET'])
def status():
    """Get current connection status and node info."""
    return jsonify(mgr.get_status())


@meshtastic_bp.route('/api/meshtastic/send', methods=['POST'])
def send():
    """Send a text message.
    
    JSON body:
        text (required): Message text
        to (optional): Destination node ID, default "^all" (broadcast)
        channel (optional): Channel index, default 0
    """
    data = request.get_json(silent=True)
    if not data or 'text' not in data:
        return jsonify({'success': False, 'error': 'Missing "text" in request body'}), 400

    text = data['text']
    destination = data.get('to', '^all')
    channel = data.get('channel', 0)

    result = mgr.send_text(text, destination=destination, channel=channel)
    status_code = 200 if result['success'] else 500
    return jsonify(result), status_code


@meshtastic_bp.route('/api/meshtastic/messages', methods=['GET'])
def messages():
    """Get recent sent and received messages."""
    limit = request.args.get('limit', 50, type=int)
    msgs = mgr.get_messages(limit=limit)
    return jsonify({
        'messages': msgs,
        'count': len(msgs),
        'state': mgr.state,
    })


@meshtastic_bp.route('/api/meshtastic/nodes', methods=['GET'])
def nodes():
    """Get known mesh nodes.

    Returns an empty list gracefully when disconnected (e.g. radio in BLE mode).
    """
    return jsonify(mgr.get_nodes())


@meshtastic_bp.route('/api/meshtastic/clear-messages', methods=['POST'])
def clear_messages():
    """Clear the message log."""
    return jsonify(mgr.clear_messages())


@meshtastic_bp.route('/api/meshtastic/reset-nodedb', methods=['POST'])
def reset_nodedb():
    """Clear the radio's node database."""
    result = mgr.reset_nodedb()
    status_code = 200 if result['success'] else 500
    return jsonify(result), status_code


# ── Standalone mode ────────────────────────────────────────────

if __name__ == '__main__':
    app = Flask(__name__)
    app.register_blueprint(meshtastic_bp)

    print("Meshtastic API server starting on port 5001...")
    print("Endpoints:")
    print("  POST /api/meshtastic/connect")
    print("  POST /api/meshtastic/disconnect")
    print("  GET  /api/meshtastic/status")
    print("  POST /api/meshtastic/send")
    print("  GET  /api/meshtastic/messages")
    print()
    app.run(host='0.0.0.0', port=5001, debug=False)
