#!/usr/bin/env python3
"""
Meshtastic Serial Control Manager
==================================
Core module for taking serial control of a meshtastic radio,
sending/receiving text messages, and releasing back to BLE.

Phase 2: Standalone CLI-testable version.

Usage:
    python3 meshtastic_manager.py connect [--port /dev/ttyACM0]
    python3 meshtastic_manager.py status
    python3 meshtastic_manager.py send "hello world" [--to ^all]
    python3 meshtastic_manager.py messages
    python3 meshtastic_manager.py disconnect
"""

import argparse
import json
import logging
import os
import sys
import threading
import time
from collections import deque
from datetime import datetime
from typing import Optional, Dict, List

from pubsub import pub  # pypubsub — used by meshtastic lib

# State file so CLI commands can share state across invocations
STATE_FILE = "/tmp/meshtastic_manager_state.json"
MESSAGE_LOG_FILE = "/tmp/meshtastic_messages.json"
MAX_MESSAGES = 100

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S"
)
logger = logging.getLogger("meshtastic_manager")


class MeshtasticManager:
    """Manages serial connection to a meshtastic radio."""

    def __init__(self):
        self.interface = None
        self.state = "DISCONNECTED"
        self.port = None
        self.node_info = {}
        self.messages: deque = deque(maxlen=MAX_MESSAGES)
        self._load_messages()

    # ── Connection ──────────────────────────────────────────────

    def connect(self, port: Optional[str] = None) -> Dict:
        """Open serial connection to the meshtastic radio.
        
        Args:
            port: Serial port path (e.g. /dev/ttyACM0). 
                  If None, auto-detects.
        
        Returns:
            Dict with status info.
        """
        if self.interface is not None:
            return {"success": False, "error": "Already connected", "state": self.state}

        self.state = "CONNECTING"
        self._save_state()

        try:
            # Subscribe to messages BEFORE connecting
            pub.subscribe(self._on_text_receive, "meshtastic.receive.text")
            pub.subscribe(self._on_connection, "meshtastic.connection.established")
            pub.subscribe(self._on_disconnect, "meshtastic.connection.lost")

            from meshtastic.serial_interface import SerialInterface

            logger.info(f"Connecting to meshtastic radio{' on ' + port if port else ' (auto-detect)'}...")
            self.interface = SerialInterface(devPath=port)
            self.port = port or self.interface.devPath
            self.state = "CONNECTED"

            # Gather node info
            my_info = self.interface.getMyNodeInfo()
            self.node_info = {
                "my_node_num": my_info.get("num") if my_info else None,
                "long_name": self.interface.getLongName(),
                "short_name": self.interface.getShortName(),
                "port": self.port,
                "connected_at": datetime.now().isoformat(),
            }

            self._save_state()
            logger.info(f"Connected! Node: {self.node_info.get('long_name')} on {self.port}")

            return {"success": True, "state": self.state, "node_info": self.node_info}

        except Exception as e:
            self.state = "ERROR"
            self.interface = None
            self._cleanup_pubsub()
            self._save_state()
            logger.error(f"Connection failed: {e}")
            return {"success": False, "error": str(e), "state": self.state}

    def disconnect(self, reboot_radio: bool = True) -> Dict:
        """Close serial connection and optionally reboot radio to restore BLE.
        
        Args:
            reboot_radio: If True, reboot the radio so BLE reinitializes
                          and the phone app can reconnect. Default True.
        """
        if self.interface is None:
            return {"success": False, "error": "Not connected", "state": self.state}

        self.state = "DISCONNECTING"
        logger.info("Disconnecting from meshtastic radio...")

        # Reboot radio to restore BLE for phone app
        if reboot_radio:
            try:
                logger.info("Sending reboot command to radio (2 second delay)...")
                self.interface.localNode.reboot(2)
                time.sleep(0.5)  # Let the reboot command get sent
            except Exception as e:
                logger.warning(f"Could not send reboot command: {e}")

        try:
            self.interface.close()
        except Exception as e:
            logger.warning(f"Error during close: {e}")

        self.interface = None
        self._cleanup_pubsub()
        self.state = "DISCONNECTED"
        self.node_info = {}
        self._save_state()

        if reboot_radio:
            logger.info("Disconnected. Radio rebooting — BLE will be available shortly.")
        else:
            logger.info("Disconnected (no reboot). Radio released.")
        return {"success": True, "state": self.state, "rebooted": reboot_radio}

    # ── Messaging ───────────────────────────────────────────────

    def send_text(self, text: str, destination: str = "^all", channel: int = 0) -> Dict:
        """Send a text message over the mesh.
        
        Args:
            text: The message text.
            destination: Node ID or "^all" for broadcast.
            channel: Channel index (default 0 = primary).
        
        Returns:
            Dict with send result.
        """
        if self.interface is None:
            return {"success": False, "error": "Not connected"}

        try:
            logger.info(f"Sending to {destination}: {text}")
            result = self.interface.sendText(
                text,
                destinationId=destination,
                wantAck=True,
                channelIndex=channel,
            )

            msg = {
                "direction": "sent",
                "text": text,
                "to": destination,
                "channel": channel,
                "timestamp": datetime.now().isoformat(),
                "packet_id": result.id if result else None,
            }
            self.messages.append(msg)
            self._save_messages()

            logger.info(f"Message sent (id: {msg['packet_id']})")
            return {"success": True, "message": msg}

        except Exception as e:
            logger.error(f"Send failed: {e}")
            return {"success": False, "error": str(e)}

    def get_messages(self, limit: int = 50) -> List[Dict]:
        """Return recent messages."""
        return list(self.messages)[-limit:]

    # ── Status ──────────────────────────────────────────────────

    def get_status(self) -> Dict:
        """Get current manager status."""
        status = {
            "state": self.state,
            "node_info": self.node_info,
            "message_count": len(self.messages),
        }

        if self.interface is not None:
            try:
                nodes = self.interface.nodes
                if nodes:
                    status["known_nodes"] = len(nodes)
            except Exception:
                pass

        return status

    # ── Pub/Sub Callbacks ───────────────────────────────────────

    def _resolve_node_name(self, node_id: str, node_num: int = None) -> str:
        """Look up the long name for a node from the node database.
        
        Falls back to node_id if name not found.
        """
        if self.interface is None:
            return node_id or "unknown"
        
        try:
            nodes = self.interface.nodes
            if nodes:
                # Try lookup by node ID string (e.g. "!abcd1234")
                if node_id and node_id in nodes:
                    user = nodes[node_id].get("user", {})
                    name = user.get("longName") or user.get("shortName")
                    if name:
                        return name
                
                # Try lookup by node number
                if node_num:
                    for nid, node_data in nodes.items():
                        if node_data.get("num") == node_num:
                            user = node_data.get("user", {})
                            name = user.get("longName") or user.get("shortName")
                            if name:
                                return name
        except Exception:
            pass
        
        return node_id or "unknown"

    def _on_text_receive(self, packet, interface):
        """Called when a text message is received."""
        try:
            sender_id = packet.get("fromId", "unknown")
            sender_num = packet.get("from")
            sender_name = self._resolve_node_name(sender_id, sender_num)
            text = packet.get("decoded", {}).get("text", "")
            msg = {
                "direction": "received",
                "text": text,
                "from": sender_name,
                "from_id": sender_id,
                "from_num": sender_num,
                "to": packet.get("toId", "unknown"),
                "channel": packet.get("channel", 0),
                "timestamp": datetime.now().isoformat(),
                "packet_id": packet.get("id"),
            }
            self.messages.append(msg)
            self._save_messages()
            logger.info(f"Received from {sender_name}: {text}")
        except Exception as e:
            logger.error(f"Error handling received message: {e}")

    def _on_connection(self, interface, topic=pub.AUTO_TOPIC):
        """Called when connection is established."""
        logger.info("Meshtastic connection established callback fired.")

    def _on_disconnect(self, interface, topic=pub.AUTO_TOPIC):
        """Called when connection is lost."""
        logger.warning("Meshtastic connection lost!")
        self.state = "DISCONNECTED"
        self.interface = None
        self._save_state()

    def _cleanup_pubsub(self):
        """Unsubscribe from all meshtastic topics."""
        try:
            pub.unsubscribe(self._on_text_receive, "meshtastic.receive.text")
        except Exception:
            pass
        try:
            pub.unsubscribe(self._on_connection, "meshtastic.connection.established")
        except Exception:
            pass
        try:
            pub.unsubscribe(self._on_disconnect, "meshtastic.connection.lost")
        except Exception:
            pass

    # ── Persistence (for CLI mode across invocations) ──────────

    def _save_state(self):
        """Save current state to file for CLI access."""
        try:
            data = {
                "state": self.state,
                "port": self.port,
                "node_info": self.node_info,
                "pid": os.getpid(),
            }
            with open(STATE_FILE, "w") as f:
                json.dump(data, f)
        except Exception as e:
            logger.warning(f"Could not save state: {e}")

    def _save_messages(self):
        """Save messages to file."""
        try:
            with open(MESSAGE_LOG_FILE, "w") as f:
                json.dump(list(self.messages), f, indent=2)
        except Exception as e:
            logger.warning(f"Could not save messages: {e}")

    def _load_messages(self):
        """Load messages from file."""
        try:
            if os.path.exists(MESSAGE_LOG_FILE):
                with open(MESSAGE_LOG_FILE, "r") as f:
                    msgs = json.load(f)
                    self.messages = deque(msgs, maxlen=MAX_MESSAGES)
        except Exception:
            pass


def _read_state() -> Dict:
    """Read saved state from file (for status/messages commands without active connection)."""
    try:
        if os.path.exists(STATE_FILE):
            with open(STATE_FILE, "r") as f:
                return json.load(f)
    except Exception:
        pass
    return {"state": "DISCONNECTED", "port": None, "node_info": {}}


def _read_messages() -> List[Dict]:
    """Read saved messages from file."""
    try:
        if os.path.exists(MESSAGE_LOG_FILE):
            with open(MESSAGE_LOG_FILE, "r") as f:
                return json.load(f)
    except Exception:
        pass
    return []


# ── CLI Interface ───────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Meshtastic Serial Control Manager",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s connect                      # Auto-detect and connect
  %(prog)s connect --port /dev/ttyACM0  # Connect to specific port
  %(prog)s status                       # Check connection status
  %(prog)s send "hello world"           # Broadcast a message
  %(prog)s send "hello" --to '!abcd1234'  # Send to specific node
  %(prog)s messages                     # Show recent messages
  %(prog)s disconnect                   # Release radio back to BLE
  %(prog)s listen                       # Connect and listen for messages
        """
    )

    subparsers = parser.add_subparsers(dest="command", help="Command to run")

    # connect
    connect_p = subparsers.add_parser("connect", help="Connect to meshtastic radio via serial")
    connect_p.add_argument("--port", default=None, help="Serial port (default: auto-detect)")

    # disconnect
    subparsers.add_parser("disconnect", help="Disconnect and release radio back to BLE")

    # status
    subparsers.add_parser("status", help="Show current connection status")

    # send
    send_p = subparsers.add_parser("send", help="Send a text message")
    send_p.add_argument("text", help="Message text to send")
    send_p.add_argument("--to", default="^all", help="Destination (default: ^all broadcast)")
    send_p.add_argument("--channel", type=int, default=0, help="Channel index (default: 0)")

    # messages
    msg_p = subparsers.add_parser("messages", help="Show recent messages")
    msg_p.add_argument("--limit", type=int, default=20, help="Number of messages to show")

    # listen
    listen_p = subparsers.add_parser("listen", help="Connect and listen for incoming messages")
    listen_p.add_argument("--port", default=None, help="Serial port (default: auto-detect)")

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        sys.exit(1)

    if args.command == "status":
        state = _read_state()
        print(json.dumps(state, indent=2))

    elif args.command == "messages":
        msgs = _read_messages()
        limit = args.limit
        for msg in msgs[-limit:]:
            direction = ">>>" if msg["direction"] == "sent" else "<<<"
            who = msg.get("to") if msg["direction"] == "sent" else msg.get("from", "?")
            ts = msg.get("timestamp", "")
            print(f"  {ts}  {direction}  [{who}]  {msg.get('text', '')}")
        if not msgs:
            print("  No messages yet.")

    elif args.command == "connect":
        mgr = MeshtasticManager()
        result = mgr.connect(port=args.port)
        print(json.dumps(result, indent=2))
        if result["success"]:
            print("\nRadio is under serial control. Run 'disconnect' to release.")
            print("Listening for messages... (Ctrl+C to stop, radio stays connected)")
            try:
                while True:
                    time.sleep(1)
            except KeyboardInterrupt:
                print("\nStopping listener. Radio remains connected until 'disconnect' is called.")
                # Note: in CLI mode, disconnect happens when process exits
                # For persistent connection, Phase 3 (daemon/API) handles this
                mgr.disconnect()

    elif args.command == "disconnect":
        # In CLI mode, the connect process holds the connection.
        # This command signals it by removing the state file.
        state = _read_state()
        if state["state"] == "CONNECTED":
            pid = state.get("pid")
            if pid:
                try:
                    os.kill(pid, 15)  # SIGTERM
                    print(f"Sent disconnect signal to PID {pid}")
                except ProcessLookupError:
                    print("Connect process already gone. Cleaning up state.")
                except Exception as e:
                    print(f"Error signaling process: {e}")
            # Clean up state
            if os.path.exists(STATE_FILE):
                os.remove(STATE_FILE)
            print("Radio released back to BLE/app control.")
        else:
            print(f"Not connected (state: {state['state']})")

    elif args.command == "send":
        # For send, we need an active connection.
        # Quick connect → send → disconnect pattern
        state = _read_state()
        if state["state"] == "CONNECTED":
            # There's a running connect process, but we can't send through it in CLI mode.
            # For Phase 2, do a quick connect-send-disconnect
            print("Note: Using quick connect-send-disconnect. Phase 3 API will support persistent connections.")

        mgr = MeshtasticManager()
        result = mgr.connect(port=state.get("port"))
        if result["success"]:
            send_result = mgr.send_text(args.text, destination=args.to, channel=args.channel)
            print(json.dumps(send_result, indent=2))
            time.sleep(2)  # Allow ack to come back
            mgr.disconnect()
        else:
            print(json.dumps(result, indent=2))

    elif args.command == "listen":
        mgr = MeshtasticManager()
        result = mgr.connect(port=args.port)
        if result["success"]:
            print("Listening for messages... (Ctrl+C to disconnect)")
            try:
                while True:
                    time.sleep(1)
            except KeyboardInterrupt:
                print("\nDisconnecting...")
                mgr.disconnect()
        else:
            print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
