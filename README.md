# Nucleus OS — Drone Branch

Stripped-down Nucleus build for use as an **ArduPilot companion computer**.

The drone Pi is a full mesh node that also bridges MAVLink between the flight
controller UART and the Wi-Fi mesh. Everything not needed for that role
(Meshtastic/LoRa, Reticulum, OpenDHT/Jami, web UI, CLI menu, MediaMTX,
TAKserver support) has been removed.

## Role

```
Zorro (USB HID) → Ground Pi (MAVProxy) → 802.11s mesh UDP
                                              ↓
                          Drone Pi (mavlink-router) → FC UART → ArduPilot
```

- Control: MAVLink `RC_CHANNELS_OVERRIDE`, ground → drone
- Telemetry: MAVLink HEARTBEAT / ATTITUDE / SYS_STATUS, drone → ground
- Single protocol end to end, no translation

## What's kept

| Component | Purpose |
|---|---|
| mavlink-router | FC UART ↔ UDP 14550, fans out to multiple GCS |
| 802.11s mesh (wlan1) | WPA3/SAE, babeld unicast routing |
| smcroute + br-lan | Multicast routing — drone acts as a full mesh point |
| hostapd (wlan0) | 5.8 GHz AP for local device access |
| eth0 | WAN/LAN, USB ethernet for bench updates |
| Tailscale | Remote admin |

## Install

```bash
./install-packages.sh     # packages + builds mavlink-router from source
# edit /etc/nucleus/mesh.conf for this node
./deploy.sh
sudo /opt/nucleus/bin/config_generation.sh
sudo reboot
```

### UART prerequisite

`/dev/ttyAMA0` is owned by Bluetooth by default. In `/boot/firmware/config.txt`:

```
enable_uart=1
dtoverlay=disable-bt
```

Then `sudo systemctl disable hciuart && sudo reboot`. `deploy.sh` warns if this
is missing.

### Flight controller

The Pi connects to the `TX2`/`RX2` through-holes (USART2), which ArduPilot
exposes as `SERIAL3`. Set on the FC so it matches `MAVLINK_BAUD` in `mesh.conf`:

```
SERIAL3_PROTOCOL = 2      # MAVLink2
SERIAL3_BAUD     = 921    # 921600
```

Wiring: Pi pin 8 (GPIO14 TX) → FC `RX2`, Pi pin 10 (GPIO15 RX) → FC `TX2`,
Pi pin 6 → FC `GND`. See `docs/drone/drone-hardware.md` for the full UART map.

## Configuration

Everything is driven by `/etc/nucleus/mesh.conf`. MAVLink keys:

| Key | Default | Meaning |
|---|---|---|
| `MAVLINK_SERIAL` | `/dev/ttyAMA0` | FC UART device |
| `MAVLINK_BAUD` | `921600` | Must match `SERIAL3_BAUD` |
| `MAVLINK_UDP_PORT` | `14550` | GCS listen port |

`config_generation.sh` writes `/etc/mavlink-router/main.conf` from these.

## Ground station

```bash
mavproxy.py --master=udpout:<DRONE_MESH_IP>:14550 --joystick
```

## Bench testing

`opt/nucleus/drone/` has two loopback tools that need no flight controller:

```bash
python3 /opt/nucleus/drone/drone_sim.py              # fake FC on UDP 14550
python3 /opt/nucleus/drone/zorro_mavlink_sender.py   # joystick → RC override
```

## Docs

- `docs/drone/` — build guide and hardware list
- `docs/babeld/` — routing and smcroute reference
- `docs/congestion_collision_tuning/` — mesh RF tuning
