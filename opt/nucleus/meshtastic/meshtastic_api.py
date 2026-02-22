#!/usr/bin/env python3
"""
Meshtastic Flask API
=====================
Standalone Flask server wrapping the MeshtasticManager.
Runs on port 5001 for independent testing before integration.

Phase 3: REST API with persistent connection.

Usage:
    python3 meshtastic_api.py

Test with curl:
    curl -X POST localhost:5001/api/meshtastic/connect
    curl localhost:5001/api/meshtastic/status
    curl -X POST -H "Content-Type: application/json" -d '{"text":"hello"}' localhost:5001/api/meshtastic/send
    curl localhost:5001/api/meshtastic/messages
    curl -X POST localhost:5001/api/meshtastic/disconnect
"""

import sys
import os

# Add parent directory so we can import the manager
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from flask import Flask, jsonify, request
from meshtastic_manager import MeshtasticManager

app = Flask(__name__)

# Single persistent manager instance
mgr = MeshtasticManager()


@app.route('/api/meshtastic/connect', methods=['POST'])
def connect():
    """Take serial control of the meshtastic radio."""
    data = request.get_json(silent=True) or {}
    port = data.get('port', None)

    result = mgr.connect(port=port)
    status_code = 200 if result['success'] else 500
    return jsonify(result), status_code


@app.route('/api/meshtastic/disconnect', methods=['POST'])
def disconnect():
    """Release serial control and reboot radio to restore BLE."""
    data = request.get_json(silent=True) or {}
    reboot = data.get('reboot', True)

    result = mgr.disconnect(reboot_radio=reboot)
    status_code = 200 if result['success'] else 400
    return jsonify(result), status_code


@app.route('/api/meshtastic/status', methods=['GET'])
def status():
    """Get current connection status and node info."""
    return jsonify(mgr.get_status())


@app.route('/api/meshtastic/send', methods=['POST'])
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


@app.route('/api/meshtastic/messages', methods=['GET'])
def messages():
    """Get recent sent and received messages."""
    limit = request.args.get('limit', 50, type=int)
    msgs = mgr.get_messages(limit=limit)
    return jsonify({
        'messages': msgs,
        'count': len(msgs),
        'state': mgr.state,
    })


if __name__ == '__main__':
    print("Meshtastic API server starting on port 5001...")
    print("Endpoints:")
    print("  POST /api/meshtastic/connect")
    print("  POST /api/meshtastic/disconnect")
    print("  GET  /api/meshtastic/status")
    print("  POST /api/meshtastic/send")
    print("  GET  /api/meshtastic/messages")
    print()
    app.run(host='0.0.0.0', port=5001, debug=False)
