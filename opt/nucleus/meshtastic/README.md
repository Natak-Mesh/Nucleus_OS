# ATAK CoT Bridge -- Meshtastic LoRa Module

Bidirectional bridge between ATAK multicast CoT and Meshtastic LoRa. Allows ATAK
end-user devices on the local mesh network to exchange position reports (SA) and
chat messages with remote nodes over long-range LoRa radio via the Meshtastic
ATAK Forwarder protocol (portnum 257).

The bridge runs as a standalone daemon that owns the Meshtastic radio's serial
port exclusively. When the bridge is disabled, the radio reverts to BLE mode for
direct phone app usage.

## File Layout

```
/opt/nucleus/meshtastic/
  cot_bridge.py          Main bridge daemon (TX + RX)
  meshtastic_api.py      Flask Blueprint -- REST API for service control
  takmessage_to_xml.py   TakMessage protobuf -> CoT XML converter
  archive/               Historical planning docs and earlier prototypes
```

Supporting system files:

- `/etc/systemd/system/cot-bridge.service` -- systemd unit
- `/etc/nucleus/mesh.conf` -- `COT_BRIDGE_ENABLED` flag
- `/etc/udev/rules.d/60-meshtastic.rules` -- suppress mtp-probe/ModemManager

## TX Pipeline (Multicast -> LoRa)

Two listener threads run in the daemon, one per multicast group (SA and Chat).
When an ATAK device on the LAN transmits a CoT event via multicast, the TX
pipeline processes it through these steps:

1. **Receive UDP multicast** on br-lan (TAK Protocol V1 wire format).
2. **Parse TAK Protocol V1** using `takproto.parse_proto()` to get a `TakMessage`
   protobuf object.
3. **Convert to CoT XML** using `takmessage_to_xml()`. This reverses the protobuf
   encoding back to the standard CoT XML interchange format that both `takproto`
   and `meshtastic_tak` understand.
4. **Loop prevention check** -- if this CoT UID was recently received from LoRa
   (within 60s), skip it to avoid re-broadcasting back what we just received.
5. **Rate limiting** -- each CoT UID is throttled to one TX every 30 seconds.
   SA reports arrive frequently; most are redundant over a low-bandwidth LoRa link.
6. **Compress to TAKPacketV2** using `meshtastic_tak.CotXmlParser` (parse XML into
   a TAKPacket structure) then `meshtastic_tak.TakCompressor` (compress to wire
   bytes). This is the compact binary format the ATAK Forwarder plugin expects.
7. **MTU check** -- if compressed payload exceeds 237 bytes (LoRa MTU), the packet
   is dropped with a warning.
8. **Send over LoRa** via `iface.sendData()` with `portNum=257`
   (`ATAK_FORWARDER`), `wantAck=False`.

## RX Pipeline (LoRa -> Multicast)

The daemon subscribes to `meshtastic.receive` via pypubsub. When a mesh packet
arrives from the radio:

1. **Filter by portnum** -- only packets with portnum `ATAK_FORWARDER` (257) are
   processed. All other portnums are ignored.
2. **Skip self-originated packets** -- packets from our own node number are
   discarded.
3. **Decompress TAKPacketV2** using `TakCompressor.decompress()` to recover the
   TAKPacket structure.
4. **Build CoT XML** using `CotXmlBuilder.build()` to produce standard CoT XML.
5. **Track UID** -- the received CoT UID is recorded with a timestamp so the TX
   side knows not to re-broadcast it back over LoRa (loop prevention).
6. **Inject to multicast** -- the CoT XML is sent as a UDP datagram to the
   appropriate multicast group on br-lan:
   - Chat events (containing `GeoChat` or type `b-t-f`) go to `224.10.10.1:17012`
   - All other events (SA) go to `239.2.3.1:6969`

ATAK devices on the local LAN receive the injected multicast and display the
remote user's position or chat message natively.

## Loop Prevention and Rate Limiting

The bridge sits between two networks (multicast LAN and LoRa) and must avoid
feedback loops where a packet bounces between them indefinitely.

**RX UID tracking:** When a CoT event arrives from LoRa, its UID is stored in a
dict with a timestamp. UIDs expire after 60 seconds. Before the TX side sends
anything over LoRa, it checks this dict -- if the UID was recently received from
LoRa, the TX is suppressed.

**TX rate limiting:** Each CoT UID is allowed one LoRa transmission per 30-second
window. ATAK sends SA updates every few seconds; the rate limiter prevents
flooding the LoRa channel. Chat messages also pass through this limiter but are
typically infrequent enough that it has no practical effect.

**Periodic cleanup:** The main loop runs every 10 seconds and purges expired
entries from both tracking dicts to prevent unbounded memory growth.

## Multicast Configuration

| Traffic | Group         | Port  |
|---------|---------------|-------|
| SA      | 239.2.3.1     | 6969  |
| Chat    | 224.10.10.1   | 17012 |

All multicast sockets are bound to `br-lan`. The listener sockets join the
multicast group via IGMP on the br-lan interface IP. The send socket sets
`IP_MULTICAST_TTL=32` and `SO_BINDTODEVICE=br-lan`.

## Service Management

### systemd

The bridge runs as `cot-bridge.service`. It starts after `mesh-start.service`,
runs as the `natak` user with `CAP_NET_RAW` (required for raw multicast socket
operations), and restarts on failure with a 10-second delay.

### Troubleshooting: bridge crash-loops with "Failed to open serial interface"

If `cot-bridge.service` repeatedly fails with
`Failed to open serial interface: Timed out waiting for connection completion`
while `/dev/ttyACM0` still exists, the RAK4631 (nRF52840) firmware has booted
into a hung state — it enumerates on USB but won't answer the serial handshake.
A warm reboot or radio-only replug does **not** clear it; only a USB hub VBUS
power cycle does:

```
sudo uhubctl -a cycle -l 1-1
sudo /opt/nucleus/bin/mesh-start.sh   # restore wlan1 (shares hub 1-1 with radio)
```

The boot-time auto-recovery is the `USB_HUB_POWER_CYCLE` flag in `mesh.conf`.
Full incident analysis and root cause:
`docs/meshtastic/meshtastic_radio_locking_up.md`.


### Configuration

`/etc/nucleus/mesh.conf` contains the flag:

```
COT_BRIDGE_ENABLED=false
```

When `true`, the service is enabled and started. When `false`, the service is
stopped and the radio is available for BLE/phone app usage.

### REST API (meshtastic_api.py)

Flask Blueprint registered in the main Nucleus web app. Endpoints:

| Endpoint                          | Method | Description                              |
|-----------------------------------|--------|------------------------------------------|
| `/api/meshtastic/status`          | GET    | Config flag, service active/enabled, radio detected |
| `/api/meshtastic/bridge/enable`   | POST   | Write config, enable + start service     |
| `/api/meshtastic/bridge/disable`  | POST   | Stop + disable service, write config, reboot node |

The disable endpoint triggers a full node reboot to cleanly release the serial
port and return the radio to BLE mode.

Radio detection checks for `/dev/ttyACM*` devices.

## udev Rules

`/etc/udev/rules.d/60-meshtastic.rules` prevents `mtp-probe` (from
`libmtp-runtime`) and `ModemManager` from probing the RAK4631 (vendor `239a`,
product `8029`). Without this rule, the MTP handshake bytes sent during USB
hotplug can crash the nRF52840 Meshtastic firmware, leaving the radio
unresponsive until a hardware reset.

## Dependencies

- `meshtastic` -- Python library for serial interface, sendData, pypubsub callbacks
- `takproto` -- TAK Protocol V1 protobuf parser (`parse_proto()`)
- `meshtastic_tak` -- TAKPacketV2 compression/decompression, CoT XML parsing/building
- `pypubsub` -- event subscription for mesh packet receive and connection callbacks
- `flask` -- REST API (meshtastic_api.py only)

## Stats and Logging

The daemon tracks counters for both TX and RX pipelines (packets received, parsed,
compressed, sent, rate-limited, too-large, errors). Stats are printed to the
journal on shutdown (SIGTERM or KeyboardInterrupt).

Log format is timestamp + level + message, written to stdout (captured by
journald). Use `--debug` flag for verbose output including meshtastic library
debug logs.
