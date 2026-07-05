#!/usr/bin/env python3
"""
ptt-characterize.py - Characterize an unknown USB PTT device.

Opens BOTH the device's evdev input node and its hidraw node simultaneously
and prints every event with timestamps. Run it, press/release the PTT button
(and any other buttons) a few times, then hit Ctrl+C for a summary.

Usage:
    sudo systemctl stop openvlm-voice   # free up the hidraw node first
    sudo python3 ptt-characterize.py [--vidpid VVVV:PPPP] [--name SUBSTR]

Defaults target the "Generic NBT POC" device (USB 0020:0b21).
Stdlib only - no external dependencies.
"""

import argparse
import glob
import os
import select
import struct
import sys
import time

# ---------------------------------------------------------------------------
# Defaults for the NBT POC device
# ---------------------------------------------------------------------------
DEFAULT_VIDPID = "0020:0B21"
DEFAULT_NAME = "NBT POC"

# struct input_event: time(2x long), type(H), code(H), value(i)
EV_FORMAT = "llHHi"
EV_SIZE = struct.calcsize(EV_FORMAT)

EV_TYPES = {
    0x00: "EV_SYN",
    0x01: "EV_KEY",
    0x02: "EV_REL",
    0x03: "EV_ABS",
    0x04: "EV_MSC",
    0x11: "EV_LED",
}

# Common keycodes we might see from a PTT/headset-style device
KEY_NAMES = {
    28: "KEY_ENTER",
    57: "KEY_SPACE",
    103: "KEY_UP",
    108: "KEY_DOWN",
    113: "KEY_MUTE",
    114: "KEY_VOLUMEDOWN",
    115: "KEY_VOLUMEUP",
    116: "KEY_POWER",
    119: "KEY_PAUSE",
    128: "KEY_STOP",
    139: "KEY_MENU",
    142: "KEY_SLEEP",
    148: "KEY_PROG1",
    149: "KEY_PROG2",
    161: "KEY_EJECTCD",
    163: "KEY_NEXTSONG",
    164: "KEY_PLAYPAUSE",
    165: "KEY_PREVIOUSSONG",
    166: "KEY_STOPCD",
    167: "KEY_RECORD",
    168: "KEY_REWIND",
    169: "KEY_PHONE",
    200: "KEY_PLAYCD",
    201: "KEY_PAUSECD",
    207: "KEY_PLAY",
    208: "KEY_FASTFORWARD",
    240: "KEY_UNKNOWN",
    582: "KEY_VOICECOMMAND",
}

VALUE_NAMES = {0: "RELEASE", 1: "PRESS", 2: "REPEAT"}


def log(tag, msg):
    print("[{:>10.3f}] {:<7} {}".format(time.monotonic() - START, tag, msg))
    sys.stdout.flush()


START = time.monotonic()


# ---------------------------------------------------------------------------
# Device discovery
# ---------------------------------------------------------------------------

def find_event_devices(vidpid, name_substr):
    """Find /dev/input/eventN nodes belonging to the target USB device."""
    found = []
    vid, _, pid = vidpid.upper().partition(":")
    for dev_dir in sorted(glob.glob("/sys/class/input/event*")):
        base = os.path.basename(dev_dir)
        # Read the parent input device name
        name_path = os.path.join(dev_dir, "device", "name")
        name = ""
        try:
            with open(name_path) as f:
                name = f.read().strip()
        except OSError:
            pass
        # Read id vendor/product
        idv = idp = ""
        try:
            with open(os.path.join(dev_dir, "device", "id", "vendor")) as f:
                idv = f.read().strip().upper().zfill(4)
            with open(os.path.join(dev_dir, "device", "id", "product")) as f:
                idp = f.read().strip().upper().zfill(4)
        except OSError:
            pass
        if (idv == vid.zfill(4) and idp == pid.zfill(4)) or \
           (name_substr and name_substr.lower() in name.lower()):
            found.append(("/dev/input/" + base, name))
    return found


def find_hidraw_devices(vidpid, name_substr):
    """Find /dev/hidrawN nodes belonging to the target USB device."""
    found = []
    target = vidpid.upper()
    for node in sorted(glob.glob("/sys/class/hidraw/hidraw*")):
        uevent = os.path.join(node, "device", "uevent")
        try:
            with open(uevent) as f:
                text = f.read()
        except OSError:
            continue
        up = text.upper()
        # HID_ID format: 0003:00000020:00000B21
        vid, _, pid = target.partition(":")
        hid_match = "{}:{}".format(vid.zfill(8), pid.zfill(8)) in up.replace(
            "HID_ID=0003:", "").replace("HID_ID=0005:", "")
        name_match = name_substr and name_substr.upper() in up
        if hid_match or name_match or target in up:
            found.append(("/dev/" + os.path.basename(node), text.strip()))
    return found


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    ap = argparse.ArgumentParser(description="Characterize a USB PTT device")
    ap.add_argument("--vidpid", default=DEFAULT_VIDPID,
                    help="USB VID:PID to match (default {})".format(DEFAULT_VIDPID))
    ap.add_argument("--name", default=DEFAULT_NAME,
                    help="Device name substring to match (default '{}')".format(DEFAULT_NAME))
    args = ap.parse_args()

    if os.geteuid() != 0:
        print("ERROR: run as root (sudo) for /dev/input and /dev/hidraw access.")
        sys.exit(1)

    events = find_event_devices(args.vidpid, args.name)
    hidraws = find_hidraw_devices(args.vidpid, args.name)

    print("=" * 70)
    print("PTT device characterization  (target: {} / '{}')".format(args.vidpid, args.name))
    print("=" * 70)
    if not events and not hidraws:
        print("No matching evdev or hidraw devices found. Is it plugged in?")
        sys.exit(1)

    fds = {}          # fd -> (kind, path, buffer)
    summary = {"keys": {}, "reports": {}}

    for path, name in events:
        try:
            fd = os.open(path, os.O_RDONLY | os.O_NONBLOCK)
            fds[fd] = ("EVDEV", path, b"")
            print("Opened {} ({})".format(path, name))
        except OSError as e:
            print("WARN: cannot open {}: {}".format(path, e))

    for path, info in hidraws:
        try:
            fd = os.open(path, os.O_RDONLY | os.O_NONBLOCK)
            fds[fd] = ("HIDRAW", path, b"")
            print("Opened {}".format(path))
        except OSError as e:
            print("WARN: cannot open {}: {} (is openvlm-voice still running?)".format(path, e))

    if not fds:
        print("ERROR: could not open any device nodes.")
        sys.exit(1)

    print("-" * 70)
    print("Press and release the PTT button a few times (short and long holds).")
    print("Try any other buttons too. Press Ctrl+C when done.")
    print("-" * 70)

    poller = select.poll()
    for fd in fds:
        poller.register(fd, select.POLLIN)

    try:
        while True:
            for fd, _flags in poller.poll(500):
                kind, path, _ = fds[fd]
                try:
                    data = os.read(fd, 4096)
                except OSError:
                    continue
                if not data:
                    continue
                if kind == "EVDEV":
                    handle_evdev(path, data, summary)
                else:
                    handle_hidraw(path, data, summary)
    except KeyboardInterrupt:
        pass
    finally:
        for fd in fds:
            os.close(fd)

    print()
    print("=" * 70)
    print("SUMMARY")
    print("=" * 70)
    if summary["keys"]:
        print("Key events seen (code -> counts):")
        for code, counts in sorted(summary["keys"].items()):
            name = KEY_NAMES.get(code, "code {}".format(code))
            print("  {:<20} press={} release={} repeat={}".format(
                name, counts.get(1, 0), counts.get(0, 0), counts.get(2, 0)))
    else:
        print("No evdev key events captured.")
    if summary["reports"]:
        print("Distinct hidraw reports seen (hex -> count):")
        for report, count in sorted(summary["reports"].items()):
            print("  {}  x{}".format(report, count))
    else:
        print("No hidraw reports captured.")
    print("=" * 70)


def handle_evdev(path, data, summary):
    n = len(data) // EV_SIZE
    for i in range(n):
        _sec, _usec, etype, code, value = struct.unpack_from(EV_FORMAT, data, i * EV_SIZE)
        tname = EV_TYPES.get(etype, "type 0x{:02x}".format(etype))
        if etype == 0x00:  # EV_SYN - noise, skip printing
            continue
        if etype == 0x01:  # EV_KEY
            kname = KEY_NAMES.get(code, "code {}".format(code))
            vname = VALUE_NAMES.get(value, str(value))
            log("EVDEV", "{} KEY {} ({}) -> {}".format(path, code, kname, vname))
            summary["keys"].setdefault(code, {})
            summary["keys"][code][value] = summary["keys"][code].get(value, 0) + 1
        else:
            log("EVDEV", "{} {} code={} value={}".format(path, tname, code, value))


def handle_hidraw(path, data, summary):
    hexstr = " ".join("{:02x}".format(b) for b in data)
    log("HIDRAW", "{} report ({} B): {}".format(path, len(data), hexstr))
    summary["reports"][hexstr] = summary["reports"].get(hexstr, 0) + 1


if __name__ == "__main__":
    main()
