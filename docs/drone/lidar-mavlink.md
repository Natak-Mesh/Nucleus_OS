# LiDAR to MAVLink

How LD06/LD19 LiDAR readings reach a ground station over the mesh.

## Problem

The LD06 sits on a CP2102 USB-UART bridge and enumerates as
`/dev/ttyUSB0`. It is wired to the **Pi**, not to a flight controller UART,
so the autopilot never sees it and it cannot appear in the MAVLink stream on
its own. Nothing was forwarding it.

Separately, the `mavlink-router` UDP endpoint was Server-only. That waits for
the ground station to transmit first, so nothing crossed `wlan1` until the GCS
sent a packet — telemetry looked dead from the ground even though the FC link
was healthy.

## Data path

```
LD06 LiDAR
  -> CP2102 USB bridge, /dev/ttyUSB0 @ 230400
  -> lidar-bridge.py          decode 47-byte frames, emit DISTANCE_SENSOR
  -> udpout 127.0.0.1:14550
  -> mavlink-router           merges with FC telemetry from /dev/ttyAMA0
  -> udp 10.20.1.42:14550     over the 802.11s mesh on wlan1
  -> ground station
```

## Files

| Path | Purpose |
|---|---|
| `opt/nucleus/drone/lidar-bridge.py` | Reads the LiDAR, decodes its native frames, injects `DISTANCE_SENSOR` (msgid 132) into `mavlink-router` at 10 Hz. |
| `etc/systemd/system/lidar-bridge.service` | Runs the bridge. `Restart=always`, gated on `/etc/nucleus/lidar-bridge.enabled`. |
| `opt/nucleus/bin/config_generation.sh` | Generates `/etc/mavlink-router/main.conf` and the bridge's enable flag from `mesh.conf`. |
| `/etc/nucleus/mesh.conf` | Node config. `LIDAR_*` and `GCS_IP` keys. Not in git — per-node. |
| `/etc/mavlink-router/main.conf` | Generated. Do not edit; changes are overwritten. |

### `lidar-bridge.py`

Decodes the LD06 wire format: 47-byte frames, header `0x54 0x2C`, 12 points
each of `uint16` distance in mm plus `uint8` intensity, CRC8 (poly `0x4D`)
from the datasheet. Resyncs on the header, so a dropped byte costs one frame.

Each frame's closest valid reading is sent as `DISTANCE_SENSOR` in
centimetres, range clamped to the sensor's rated 0.02–12 m. Readings with
zero distance or zero intensity are discarded as no-return.

Two details that are easy to get wrong:

- `MAVLINK20=1` is set **before** `pymavlink` is imported. Without it
  pymavlink emits MAVLink1 frames (`0xFE`) while the FC and router speak
  MAVLink2 (`0xFD`).
- The serial port is reopened on any error rather than exiting. The CP2102
  drops out intermittently, so the bridge must survive the sensor coming and
  going.

Sends as `source_system=1` (matching the FC) and `source_component=194`, so
the GCS files the reading under the same vehicle.

Config comes from `mesh.conf`, overridable per-run:

```
python3 /opt/nucleus/drone/lidar-bridge.py --verbose
python3 /opt/nucleus/drone/lidar-bridge.py --port /dev/ttyUSB0 --baud 230400
```

### `lidar-bridge.service`

Runs as `natak`, group `dialout` — `pymavlink` is installed under
`~natak/.local`, not system-wide, and `dialout` is what grants access to
`/dev/ttyUSB0`.

`ConditionPathExists=/etc/nucleus/lidar-bridge.enabled` keeps the unit inert
on nodes with no LiDAR fitted, mirroring how `mavlink-router.service` is gated
on its generated config.

## Configuration

In `/etc/nucleus/mesh.conf`:

```sh
LIDAR_ENABLED=true
LIDAR_SERIAL=/dev/ttyUSB0
LIDAR_BAUD=230400          # LD06 is fixed at this rate
LIDAR_ORIENTATION=25       # MAV_SENSOR_ROTATION_PITCH_270, straight down
                           # use 0 for forward-facing

GCS_IP=10.20.1.42          # push telemetry here unprompted
                           # empty = inbound GCS connections only
```

Apply with:

```sh
sudo /opt/nucleus/bin/config_generation.sh
sudo systemctl restart mavlink-router lidar-bridge
```

`LIDAR_ENABLED` requires `DRONE_ENABLED=true`; without `mavlink-router` there
is nothing to inject into. Setting either to `false` removes the flag file and
disables the unit.

### `GCS_IP`

Adds a second `UdpEndpoint` in `Mode = Normal` alongside the existing server,
pushing to that address without waiting to be contacted. The server endpoint
stays, so a GCS can still connect inbound and several can attach at once.

This build of mavlink-router spells the push mode **`Normal`**. `Client` is
rejected at parse time and the daemon exits with
`Unknown 'mode' key: Client`.

## Verifying

Bridge is running and reading the sensor:

```sh
systemctl status lidar-bridge
journalctl -u lidar-bridge -f
```

`DISTANCE_SENSOR` is actually on the mesh — msgid 132, MAVLink2 framing:

```sh
sudo tcpdump -i wlan1 -n udp port 14550 -c 20
```

On the ground node, decode the stream. Note `udpin`, not `udpout`; `udpout`
only listens and will appear to hang:

```sh
python3 -c "
from pymavlink import mavutil
m = mavutil.mavlink_connection('udpin:0.0.0.0:14550')
while True:
    msg = m.recv_match(type='DISTANCE_SENSOR', blocking=True)
    print(msg.current_distance, 'cm')
"
```

Verified on node 0022: 2101 MAVLink frames in 10 s to `10.20.1.42`, 67 of
them `DISTANCE_SENSOR`, distances tracking the sensor.

## Known issues

**The CP2102 drops out.** It enumerates, runs from a fraction of a second to a
few seconds, disconnects, and re-enumerates with a climbing USB device number:

```
cp210x 1-1.4:1.0: cp210x converter detected
usb 1-1.4: cp210x converter now attached to ttyUSB0
usb 1-1.4: USB disconnect, device number 5
```

Descriptor reads are clean each time and `vcgencmd get_throttled` reports
`0x0`, so the chip is fine and this is not undervoltage — it points at the
cable or the connector. The bridge reconnects automatically, but readings stop
during each gap. Worth reseating or replacing the cable.

## Using the LiDAR for flight control

The above only relays readings to the GCS. For ArduPilot to *use* the sensor
for altitude hold or obstacle avoidance, it has to receive them itself — set
on the flight controller:

```
RNGFND1_TYPE   = 10    # MAVLink rangefinder
RNGFND1_ORIENT = 25    # match LIDAR_ORIENTATION
```

`RNGFND1_TYPE` only takes effect after an FC reboot. This also requires
`mavlink-router` to forward the injected messages back down the UART to the
FC, which the current config does.

Not needed if the ground station only has to display the data.
