#!/usr/bin/env python3
"""
Meshtastic Serial Control Manager
==================================
Core module for taking serial control of a meshtastic radio,
sending/receiving text messages, and releasing back to BLE.

Dual-transport: LoRa serial + WiFi UDP broadcast between Pis.
- LoRa provides range extension via the RAK4631 mesh.
- WiFi UDP provides near-instant delivery between Pis on the 802.11s mesh.
- Deduplication ensures each message appears once regardless of transport.

Phase 2: Standalone CLI-testable version.
Phase 5: UDP broadcast sender.
Phase 6: UDP listener thread + dedup.
Phase 7: Transport tagging.

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
import socket
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
MESH_CONF_PATH = "/etc/nucleus/mesh.conf"

# Dedup settings
DEDUP_EXPIRY_SECONDS = 300  # 5 minutes
DEDUP_CLEANUP_INTERVAL = 60  # Run cleanup every 60 seconds

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S"
)
logger = logging.getLogger("meshtastic_manager")


class MeshtasticManager:
    """Manages serial connection to a meshtastic radio and WiFi UDP relay."""

    def __init__(self):
        self.interface = None
        self.state = "DISCONNECTED"
        self.port = None
        self.node_info = {}
        self.messages: deque = deque(maxlen=MAX_MESSAGES)
        self._load_messages()

        # ── Configuration (from mesh.conf) ──────────────────────
        self._mesh_ip = None
        self._udp_broadcast_addr = None
        self._udp_port = 4403
        self._udp_relay_enabled = False
        self._load_config()

        # ── Deduplication ───────────────────────────────────────
        # Maps packet_id (int) -> timestamp (float) of first arrival.
        # Both LoRa serial and UDP listener check this before logging.
        self._seen_packets: Dict[int, float] = {}
        self._seen_lock = threading.Lock()

        # Start dedup cleanup timer
        self._dedup_cleanup_timer = None
        self._start_dedup_cleanup()

        # ── UDP Listener ────────────────────────────────────────
        # Runs independently of serial connection (graceful degradation).
        # If radio is disconnected, we still receive messages from other Pis.
        self._udp_listener_thread = None
        self._udp_listener_running = False
        self._udp_sock = None
        if self._udp_relay_enabled:
            self._start_udp_listener()

    # ── Configuration ───────────────────────────────────────────

    def _load_config(self):
        """Read mesh.conf for UDP relay settings.

        Extracts MESH_IP, MESHTASTIC_UDP_RELAY, MESHTASTIC_UDP_PORT.
        Derives broadcast address from MESH_IP (replace last octet with 255).
        """
        config = {}
        try:
            if os.path.exists(MESH_CONF_PATH):
                with open(MESH_CONF_PATH, "r") as f:
                    for line in f:
                        line = line.strip()
                        if line and not line.startswith("#") and "=" in line:
                            key, value = line.split("=", 1)
                            config[key.strip()] = value.strip().strip('"')
        except Exception as e:
            logger.warning(f"Could not read {MESH_CONF_PATH}: {e}")

        # MESH_IP → broadcast address
        self._mesh_ip = config.get("MESH_IP")
        if self._mesh_ip:
            try:
                parts = self._mesh_ip.split(".")
                parts[3] = "255"
                self._udp_broadcast_addr = ".".join(parts)
            except (IndexError, ValueError):
                logger.warning(f"Could not derive broadcast address from MESH_IP={self._mesh_ip}")
                self._udp_broadcast_addr = None

        # UDP relay enable/disable
        relay_str = config.get("MESHTASTIC_UDP_RELAY", "false").lower()
        self._udp_relay_enabled = relay_str in ("true", "1", "yes")

        # UDP port
        try:
            self._udp_port = int(config.get("MESHTASTIC_UDP_PORT", "4403"))
        except ValueError:
            self._udp_port = 4403

        if self._udp_relay_enabled:
            logger.info(
                f"UDP relay enabled: broadcast={self._udp_broadcast_addr}:{self._udp_port}"
            )
        else:
            logger.info("UDP relay disabled (MESHTASTIC_UDP_RELAY not set to true)")

    # ── Deduplication ───────────────────────────────────────────

    def _check_dedup(self, packet_id: int) -> bool:
        """Check if a packet has already been seen.

        Returns True if this is a NEW (unseen) packet.
        Returns False if this is a DUPLICATE.

        Thread-safe — called from both LoRa serial callback and UDP listener.
        """
        if packet_id is None:
            # No packet ID means we can't dedup — treat as new
            return True

        now = time.time()
        with self._seen_lock:
            if packet_id in self._seen_packets:
                return False  # Duplicate
            self._seen_packets[packet_id] = now
            return True  # New

    def _cleanup_dedup(self):
        """Remove expired entries from the seen-packets dictionary.

        Runs periodically via a timer thread. Entries older than
        DEDUP_EXPIRY_SECONDS (5 min) are removed.
        """
        now = time.time()
        cutoff = now - DEDUP_EXPIRY_SECONDS
        with self._seen_lock:
            expired = [pid for pid, ts in self._seen_packets.items() if ts < cutoff]
            for pid in expired:
                del self._seen_packets[pid]
            if expired:
                logger.debug(f"Dedup cleanup: removed {len(expired)} expired entries")

        # Reschedule
        self._start_dedup_cleanup()

    def _start_dedup_cleanup(self):
        """Schedule the next dedup cleanup run."""
        self._dedup_cleanup_timer = threading.Timer(
            DEDUP_CLEANUP_INTERVAL, self._cleanup_dedup
        )
        self._dedup_cleanup_timer.daemon = True
        self._dedup_cleanup_timer.start()

    # ── UDP Broadcast Sender ────────────────────────────────────

    def _udp_broadcast(self, payload: dict):
        """Broadcast a JSON message via UDP to the WiFi mesh.

        Args:
            payload: Dict with message data. Must include 'packet_id'.
                     Sent as a JSON-encoded UTF-8 datagram.
        """
        if not self._udp_relay_enabled:
            return
        if not self._udp_broadcast_addr:
            return

        try:
            data = json.dumps(payload).encode("utf-8")
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
            sock.sendto(data, (self._udp_broadcast_addr, self._udp_port))
            sock.close()
            logger.debug(
                f"UDP broadcast sent: packet_id={payload.get('packet_id')} "
                f"to {self._udp_broadcast_addr}:{self._udp_port}"
            )
        except Exception as e:
            logger.warning(f"UDP broadcast failed: {e}")

    def _build_udp_payload(self, msg: dict, origin: str) -> dict:
        """Build the JSON payload for a UDP broadcast.

        Args:
            msg: The message dict (from send_text or _on_text_receive).
            origin: "user_sent" or "lora_received" — prevents re-injection loops.

        Returns:
            Dict ready for JSON serialization and UDP broadcast.
        """
        return {
            "type": "text",
            "packet_id": msg.get("packet_id"),
            "from_name": msg.get("from", msg.get("node_info", {}).get("long_name", "unknown")),
            "from_id": msg.get("from_id", ""),
            "from_num": msg.get("from_num"),
            "text": msg.get("text", ""),
            "to": msg.get("to", "^all"),
            "channel": msg.get("channel", 0),
            "timestamp": msg.get("timestamp", datetime.now().isoformat()),
            "origin": origin,
            "source_ip": self._mesh_ip,
        }

    # ── UDP Listener ────────────────────────────────────────────

    def _start_udp_listener(self):
        """Start the background UDP listener thread.

        Binds to 0.0.0.0:<udp_port> and listens for broadcast datagrams
        from other Pis. Runs independently of serial connection state.
        """
        if self._udp_listener_running:
            return

        try:
            self._udp_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            self._udp_sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
            self._udp_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            self._udp_sock.bind(("0.0.0.0", self._udp_port))
            # Set timeout so the thread can check the running flag periodically
            self._udp_sock.settimeout(2.0)

            self._udp_listener_running = True
            self._udp_listener_thread = threading.Thread(
                target=self._udp_listener_loop, daemon=True
            )
            self._udp_listener_thread.start()
            logger.info(f"UDP listener started on port {self._udp_port}")
        except Exception as e:
            logger.error(f"Failed to start UDP listener: {e}")
            self._udp_listener_running = False

    def _stop_udp_listener(self):
        """Stop the UDP listener thread."""
        self._udp_listener_running = False
        if self._udp_sock:
            try:
                self._udp_sock.close()
            except Exception:
                pass
            self._udp_sock = None
        if self._udp_listener_thread:
            self._udp_listener_thread.join(timeout=5)
            self._udp_listener_thread = None
        logger.info("UDP listener stopped")

    def _udp_listener_loop(self):
        """Main loop for the UDP listener thread.

        Receives JSON datagrams, deduplicates, and adds to the message log.
        Messages received via UDP are NOT forwarded to the local radio.
        """
        logger.info("UDP listener thread running")
        while self._udp_listener_running:
            try:
                data, addr = self._udp_sock.recvfrom(4096)
            except socket.timeout:
                continue
            except OSError:
                # Socket was closed
                if self._udp_listener_running:
                    logger.warning("UDP socket error, listener stopping")
                break

            try:
                payload = json.loads(data.decode("utf-8"))
            except (json.JSONDecodeError, UnicodeDecodeError) as e:
                logger.warning(f"UDP: invalid payload from {addr}: {e}")
                continue

            # Ignore our own broadcasts
            source_ip = payload.get("source_ip")
            if source_ip and source_ip == self._mesh_ip:
                continue

            # Only handle text messages for now
            if payload.get("type") != "text":
                continue

            packet_id = payload.get("packet_id")

            # Dedup check — if we already have this packet (from LoRa or earlier UDP), skip
            if not self._check_dedup(packet_id):
                logger.debug(
                    f"UDP: duplicate packet_id={packet_id} from {addr[0]}, discarding"
                )
                continue

            # Build message for the log
            msg = {
                "direction": "received",
                "text": payload.get("text", ""),
                "from": payload.get("from_name", "unknown"),
                "from_id": payload.get("from_id", ""),
                "from_num": payload.get("from_num"),
                "to": payload.get("to", "^all"),
                "channel": payload.get("channel", 0),
                "timestamp": payload.get("timestamp", datetime.now().isoformat()),
                "packet_id": packet_id,
                "transport": "wifi",
            }
            self.messages.append(msg)
            self._save_messages()
            logger.info(
                f"UDP [{addr[0]}]: {msg['from']}: {msg['text']} "
                f"(packet_id={packet_id}, transport=wifi)"
            )

        logger.info("UDP listener thread exiting")

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
            self.state = "DISCONNECTED"
            # Close any partially-opened interface to release the serial port lock
            if self.interface is not None:
                try:
                    self.interface.close()
                except Exception:
                    pass
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

        Sends via LoRa (serial to radio) AND broadcasts via UDP to WiFi mesh.

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

            packet_id = result.id if result else None

            msg = {
                "direction": "sent",
                "text": text,
                "to": destination,
                "channel": channel,
                "timestamp": datetime.now().isoformat(),
                "packet_id": packet_id,
                "transport": "local",
            }

            # Register in dedup so we don't re-log when it comes back via UDP
            if packet_id is not None:
                self._check_dedup(packet_id)

            self.messages.append(msg)
            self._save_messages()

            # Broadcast via UDP to WiFi mesh
            udp_payload = self._build_udp_payload(msg, origin="user_sent")
            # Add sender info from node_info for the UDP payload
            udp_payload["from_name"] = self.node_info.get("long_name", "unknown")
            udp_payload["from_id"] = ""
            udp_payload["from_num"] = self.node_info.get("my_node_num")
            self._udp_broadcast(udp_payload)

            logger.info(f"Message sent (id: {packet_id}, transport=local+lora+wifi)")
            return {"success": True, "message": msg}

        except Exception as e:
            logger.error(f"Send failed: {e}")
            return {"success": False, "error": str(e)}

    def get_messages(self, limit: int = 50) -> List[Dict]:
        """Return recent messages."""
        return list(self.messages)[-limit:]

    def clear_messages(self) -> Dict:
        """Clear the message log."""
        self.messages.clear()
        self._save_messages()
        return {"success": True, "message": "Message log cleared"}

    def reset_nodedb(self) -> Dict:
        """Reset the radio's node database. Requires active serial connection."""
        if self.interface is None:
            return {"success": False, "error": "Not connected"}
        try:
            self.interface.localNode.resetNodeDb()
            logger.info("Node database reset")
            return {"success": True, "message": "Node database cleared"}
        except Exception as e:
            logger.error(f"Reset nodedb failed: {e}")
            return {"success": False, "error": str(e)}

    # ── Status ──────────────────────────────────────────────────

    def get_status(self) -> Dict:
        """Get current manager status including UDP relay info."""
        status = {
            "state": self.state,
            "node_info": self.node_info,
            "message_count": len(self.messages),
            "udp_relay": {
                "enabled": self._udp_relay_enabled,
                "listener_running": self._udp_listener_running,
                "broadcast_addr": self._udp_broadcast_addr,
                "port": self._udp_port,
            },
        }

        if self.interface is not None:
            try:
                nodes = self.interface.nodes
                if nodes:
                    status["known_nodes"] = len(nodes)
            except Exception:
                pass

        return status

    def get_nodes(self) -> Dict:
        """Get list of known nodes from the mesh radio.

        Returns a clean, safe response regardless of connection state.
        When disconnected (e.g. radio in BLE mode), returns an empty list
        with state info — no errors, no exceptions.

        Returns:
            Dict with 'state', 'nodes' list, and 'count'.
        """
        if self.interface is None:
            return {"state": self.state, "nodes": [], "count": 0}

        try:
            raw_nodes = self.interface.nodesByNum
            if not raw_nodes:
                return {"state": self.state, "nodes": [], "count": 0}

            my_num = None
            try:
                my_info = self.interface.getMyNodeInfo()
                if my_info:
                    my_num = my_info.get("num")
            except Exception:
                pass

            node_list = []
            now = time.time()

            for node_id, node_data in raw_nodes.items():
                try:
                    user = node_data.get("user", {})
                    short_name = user.get("shortName", "?")
                    node_num = node_data.get("num")

                    # Last heard — use best available timestamp
                    # Position packets update position.time but NOT lastHeard,
                    # so check both and use the most recent.
                    last_heard_epoch = node_data.get("lastHeard", 0) or 0
                    pos_time = node_data.get("position", {}).get("time", 0) or 0
                    last_heard_epoch = max(last_heard_epoch, pos_time)
                    if last_heard_epoch and last_heard_epoch > 0:
                        ago = int(now - last_heard_epoch)
                        if ago < 60:
                            last_heard = f"{ago}s ago"
                        elif ago < 3600:
                            last_heard = f"{ago // 60}m ago"
                        elif ago < 86400:
                            last_heard = f"{ago // 3600}h {(ago % 3600) // 60}m ago"
                        else:
                            last_heard = f"{ago // 86400}d ago"
                    else:
                        last_heard = "never"

                    # SNR from the last packet we heard from this node
                    snr = node_data.get("snr")
                    if snr is None:
                        snr_str = "—"
                    else:
                        snr_str = f"{snr:.1f} dB"

                    is_local = (node_num == my_num) if my_num else False

                    # Position (lat/lon rounded to 5 decimals ≈ 1m accuracy)
                    position = node_data.get("position", {})
                    lat = position.get("latitude")
                    lon = position.get("longitude")
                    if lat and lon:
                        pos_str = f"Lat: {lat:.5f}\nLon: {lon:.5f}"
                    else:
                        pos_str = "—"

                    node_list.append({
                        "short_name": short_name,
                        "last_heard": last_heard,
                        "last_heard_epoch": last_heard_epoch or 0,
                        "snr": snr_str,
                        "position": pos_str,
                        "is_local": is_local,
                    })
                except Exception:
                    # Skip any node that can't be parsed — never crash
                    continue

            # Sort: local node first, then by most recently heard
            node_list.sort(key=lambda n: (not n["is_local"], -n["last_heard_epoch"]))

            return {"state": self.state, "nodes": node_list, "count": len(node_list)}

        except Exception as e:
            logger.warning(f"Error reading node list: {e}")
            return {"state": self.state, "nodes": [], "count": 0}

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
        """Called when a text message is received via LoRa serial.

        Deduplicates, logs, and rebroadcasts via UDP to the WiFi mesh.
        """
        try:
            packet_id = packet.get("id")

            # Dedup check — if already seen (via UDP or earlier LoRa), discard
            if not self._check_dedup(packet_id):
                logger.debug(
                    f"LoRa: duplicate packet_id={packet_id}, discarding"
                )
                return

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
                "packet_id": packet_id,
                "transport": "lora",
            }
            self.messages.append(msg)
            self._save_messages()
            logger.info(f"LoRa: {sender_name}: {text} (packet_id={packet_id}, transport=lora)")

            # Rebroadcast via UDP so other Pis get it instantly
            udp_payload = self._build_udp_payload(msg, origin="lora_received")
            self._udp_broadcast(udp_payload)

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
            transport = msg.get("transport", "?")
            print(f"  {ts}  {direction}  [{who}]  ({transport})  {msg.get('text', '')}")
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
