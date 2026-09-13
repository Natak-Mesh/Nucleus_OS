#!/usr/bin/env python3
"""
gps-monitor.py — GNSS reader that keeps the current fix in tmpfs.

Runs as gps-monitor.service. Reads NMEA from the GNSS serial port and
writes the latest parsed fix to a single state file, overwriting it in
place every update. It never appends and never logs routine output, so
there is no log growth and nothing hits the SD card — the state file
lives on /run (tmpfs, RAM only).

    python3 /opt/nucleus/drone/gps-monitor.py
    python3 /opt/nucleus/drone/gps-monitor.py --port /dev/ttyUSB1 --baud 115200

Config is read from /etc/nucleus/mesh.conf (GPS_SERIAL, GPS_BAUD) and
overridden by CLI flags. Look at the result with gps-status.py.

The SIM7600 GNSS port can drop out when ModemManager touches the modem,
so the serial port is reopened on any error rather than exiting — same
resilience pattern as lidar-bridge.py.
"""

import argparse
import json
import os
import sys
import tempfile
import time

try:
    import serial
except ImportError:
    sys.exit("pyserial missing: sudo apt install python3-serial")

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from gps_nmea import (
    Fix, read_mesh_conf, DEFAULT_PORT, DEFAULT_BAUD, STATE_FILE,
)

WRITE_HZ = 1.0


def write_state(path, fix):
    """Atomically overwrite the state file. Never appends.

    Temp file in the same directory + os.replace() means a reader
    (gps-status.py) never sees a half-written file.
    """
    payload = fix.to_dict()
    payload["updated"] = time.time()
    d = os.path.dirname(path)
    os.makedirs(d, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=d, prefix=".gps.", suffix=".json")
    try:
        with os.fdopen(fd, "w") as fh:
            json.dump(payload, fh)
        os.replace(tmp, path)
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def run(port, baud, state_file):
    fix = Fix()
    last_write = 0.0
    while True:
        try:
            with serial.Serial(port, baud, timeout=1) as ser:
                buf = b""
                while True:
                    chunk = ser.readline()
                    if chunk:
                        try:
                            fix.update(chunk.decode("ascii", "ignore"))
                        except Exception:
                            pass
                    now = time.time()
                    if now - last_write >= 1.0 / WRITE_HZ:
                        write_state(state_file, fix)
                        last_write = now
        except serial.SerialException as exc:
            # Port vanished (modem reset, cable) — mark stale and retry.
            print(f"serial error on {port}: {exc}; retrying", file=sys.stderr)
            time.sleep(2)
        except OSError as exc:
            print(f"os error on {port}: {exc}; retrying", file=sys.stderr)
            time.sleep(2)


def main():
    conf = read_mesh_conf()
    ap = argparse.ArgumentParser(description="GNSS reader -> tmpfs state file")
    ap.add_argument("--port", default=conf.get("GPS_SERIAL", DEFAULT_PORT))
    ap.add_argument("--baud", type=int,
                    default=int(conf.get("GPS_BAUD", DEFAULT_BAUD)))
    ap.add_argument("--state", default=STATE_FILE)
    args = ap.parse_args()
    run(args.port, args.baud, args.state)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        pass
