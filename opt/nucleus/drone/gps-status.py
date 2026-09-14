#!/usr/bin/env python3
"""
gps-status.py — human-readable GNSS status readout.

Read-only. Reads the state file that gps-monitor.service keeps in tmpfs
(/run/nucleus/gps.json) and prints a status block. It never opens the
serial port itself, so it never contends with the monitor.

    python3 /opt/nucleus/drone/gps-status.py            # snapshot, exits
    python3 /opt/nucleus/drone/gps-status.py --watch    # redraw in place
    python3 /opt/nucleus/drone/gps-status.py --json      # raw state, exits

When there is no fix (the common startup / indoor case) it shows the
satellites in view with their signal strength, so it doubles as an
antenna-aiming tool: get bars to climb, and the fix follows.
"""

import argparse
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from gps_nmea import STATE_FILE

FIX_NAMES = {0: "NO FIX", 1: "NO FIX", 2: "2D FIX", 3: "3D FIX"}


def load_state(path):
    try:
        with open(path) as fh:
            return json.load(fh)
    except FileNotFoundError:
        return None
    except (OSError, ValueError):
        return None


def fmt(v, spec, dash="---"):
    return format(v, spec) if v is not None else dash


def snr_bar(snr):
    if snr is None:
        return "    ·"
    filled = min(5, max(0, snr // 10))
    return "▁▂▃▄▅"[:filled].ljust(5, " ") + f" {snr:2d}"


def render(state):
    lines = []
    lines.append("=" * 44)
    lines.append("  GNSS STATUS")
    lines.append("=" * 44)
    if state is None:
        lines.append("  state file not found — is gps-monitor.service up?")
        lines.append(f"  ({STATE_FILE})")
        lines.append("=" * 44)
        return "\n".join(lines)

    age = time.time() - state.get("updated", 0)
    stale = age > 5
    # sentence_age is the true liveness signal: the monitor rewrites the state
    # file on a 1 Hz timer whether or not new NMEA arrived, so `updated` can
    # look fresh while the port has gone silent. None means no valid sentence
    # has ever been seen.
    sentence_age = state.get("sentence_age")
    ft = state.get("fix_type", 0)
    status = FIX_NAMES.get(ft, "NO FIX")
    if not state.get("has_fix"):
        status += " (searching)"
    if stale:
        status += "  [STALE DATA]"
    if sentence_age is None:
        status += "  [NO DATA EVER]"
    elif sentence_age > 5:
        status += "  [STREAM STALLED]"
    lines.append(f"  Fix        : {status}")
    lines.append(f"  Satellites : {state.get('satellites_used', 0)} used / "
                 f"{state.get('satellites_visible', 0)} in view")

    if state.get("has_fix"):
        lines.append(f"  Latitude   : {fmt(state.get('lat'), '.6f')}")
        lines.append(f"  Longitude  : {fmt(state.get('lon'), '.6f')}")
        lines.append(f"  Altitude   : {fmt(state.get('alt'), '.1f')} m MSL")
        spd = state.get("speed")
        lines.append(f"  Speed      : {fmt(spd, '.1f')} m/s")
        lines.append(f"  Course     : {fmt(state.get('course'), '.0f')} deg true")
    else:
        lines.append("  Latitude   : ---   (no fix yet)")
        lines.append("  Longitude  : ---")

    lines.append(f"  HDOP/VDOP  : {fmt(state.get('hdop'), '.1f')} / "
                 f"{fmt(state.get('vdop'), '.1f')}")
    ut = state.get("utc_time")
    ud = state.get("utc_date")
    if ut:
        t = ut.split(".")[0]
        tstr = f"{t[0:2]}:{t[2:4]}:{t[4:6]}" if len(t) >= 6 else ut
        dstr = f" {ud[0:2]}/{ud[2:4]}/{ud[4:6]}" if ud and len(ud) >= 6 else ""
        lines.append(f"  UTC        : {tstr}{dstr}")
    lines.append(f"  Data age   : {age:.1f} s")
    if sentence_age is None:
        lines.append("  Stream     : no NMEA received yet")
    else:
        lines.append(f"  Stream     : last sentence {sentence_age:.1f} s ago")

    sats = state.get("sats") or {}
    if sats:
        lines.append("-" * 44)
        lines.append("  Signal (SNR dB-Hz):")
        talk = {"GP": "GPS", "GL": "GLO", "GA": "GAL", "GB": "BDS",
                "GN": "GNSS", "GQ": "QZSS"}
        for con, prns in sorted(sats.items()):
            for prn, snr in sorted(prns.items(),
                                   key=lambda kv: (kv[1] is None, -(kv[1] or 0))):
                name = talk.get(con, con)
                lines.append(f"    {name:4s} {prn:>3s}  {snr_bar(snr)}")
    lines.append("=" * 44)
    return "\n".join(lines)


def main():
    ap = argparse.ArgumentParser(description="Show GNSS status from tmpfs state")
    ap.add_argument("--watch", action="store_true",
                    help="redraw in place until Ctrl-C")
    ap.add_argument("--json", action="store_true",
                    help="dump the raw state JSON and exit")
    ap.add_argument("--state", default=STATE_FILE)
    args = ap.parse_args()

    if args.json:
        state = load_state(args.state)
        print(json.dumps(state, indent=2))
        return

    if not args.watch:
        print(render(load_state(args.state)))
        return

    try:
        while True:
            out = render(load_state(args.state))
            sys.stdout.write("\033[2J\033[H" + out + "\n")
            sys.stdout.flush()
            time.sleep(1)
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
