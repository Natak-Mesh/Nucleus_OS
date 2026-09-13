# GPS / GNSS status monitor

A lightweight, always-on readout of the GNSS receiver. It does **not** touch
the LTE connection, issue AT commands, or push anything into MAVLink (that is
a later step). It just parses NMEA and keeps the current fix somewhere you can
look at it.

## Where the GPS is

On this build the GNSS receiver is the one built into the **SIM7600G-H LTE
modem**. ModemManager exposes the modem's ports like this:

```
$ mmcli -m 0
... ports: cdc-wdm0 (qmi), ttyUSB0 (ignored), ttyUSB1 (gps),
           ttyUSB2 (at), ttyUSB3 (at), ttyUSB4 (audio), wwan0 (net)
```

The GNSS NMEA stream is on **`/dev/ttyUSB1`**. ModemManager does *not* hold
that port open (`fuser /dev/ttyUSB1` is empty), so the monitor reads it
directly without disturbing the cellular link.

Note this is a *different* connector from the LTE MAIN/AUX antennas — the
SIM7600G-H has a separate GNSS u.FL pad. If you see satellites in view but
never get a fix, suspect the GNSS antenna/connector first.

## How it works

- `gps-monitor.py` runs as `gps-monitor.service`. It reads NMEA and writes the
  current fix to **`/run/nucleus/gps.json`**, overwriting it in place ~1 Hz.
  `/run` is tmpfs (RAM) — it never appends, never logs routine output, and
  never touches the SD card. There is no log to grow.
- `gps-status.py` reads that file and prints a status block. It never opens the
  serial port, so it never fights the monitor.
- `gps_nmea.py` is the shared parser both use. Its `Fix` fields are named to
  line up with MAVLink `GPS_INPUT` (msgid 232) so the future sender is a thin
  consumer of the same module.

## Turning it on

In `/etc/nucleus/mesh.conf`:

```
GPS_ENABLED=true
GPS_SERIAL=/dev/ttyUSB1
GPS_BAUD=115200
```

then apply:

```
sudo /opt/nucleus/bin/config_generation.sh
```

`config_generation.sh` creates `/etc/nucleus/gps-monitor.enabled` and enables
the service when `GPS_ENABLED=true`, and removes/disables it when false.

## Looking at it

```
python3 /opt/nucleus/drone/gps-status.py            # one snapshot
python3 /opt/nucleus/drone/gps-status.py --watch    # live, redraw in place
python3 /opt/nucleus/drone/gps-status.py --json      # raw state
```

## Reading the output

- **NO FIX (searching)** — receiver is alive, no position yet. The satellite
  list with SNR bars is shown; use it to aim the antenna. Cold start outdoors
  is typically 1–5 minutes.
- **2D FIX** — position but no reliable altitude (needs 4+ sats).
- **3D FIX** — full position + altitude.
- **STALE DATA** — the state file has not updated in >5 s; the monitor is
  probably down or the port dropped. Check `systemctl status gps-monitor`.

## Next step (not yet implemented)

Emitting `GPS_INPUT` to `127.0.0.1:MAVLINK_UDP_PORT` so the fix appears in the
GCS, exactly as `lidar-bridge.py` emits `DISTANCE_SENSOR`. The parser split
above means that is an addition to this daemon, not a rewrite.
