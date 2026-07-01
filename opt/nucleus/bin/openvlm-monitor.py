#!/usr/bin/env python3
"""
openvlm-monitor.py - Combined PTT + audio-input monitor for the OpenVLM USB sound card.

Dependency-free (Python 3 stdlib only). Shows, in a single live view:
  * PTT button state  - read raw from /dev/input/eventX (the OpenVLM HID interface)
  * Microphone level  - RMS/peak meter from arecord capturing plughw:<card>,0

The OpenVLM device (C-Media 0d8c:0012) exposes:
  - an ALSA capture device (mono, S16_LE, 48000/44100 Hz)
  - an HID/keyboard input that emits a key event when the PTT is pressed/released

Run with sudo (or as a member of the 'input' group) because /dev/input/eventX
is root:input mode 0660.

Usage:
    sudo ./openvlm-monitor.py
    sudo ./openvlm-monitor.py --event /dev/input/event0 --card 1
"""

import argparse
import glob
import math
import os
import select
import struct
import subprocess
import sys
import time

# struct input_event on 64-bit Linux:
#   struct timeval { long tv_sec; long tv_usec; }  -> 'll'  (16 bytes)
#   __u16 type; __u16 code; __s32 value            -> 'HHi' (8 bytes)
EVENT_FORMAT = "llHHi"
EVENT_SIZE = struct.calcsize(EVENT_FORMAT)

EV_KEY = 0x01
# value: 0 = release, 1 = press, 2 = autorepeat

# PTT is read from the CM108 HID GPIO via /dev/hidraw0.
# Report byte[1]: 0x01 = PRESSED, 0x05 = RELEASED (observed on this OpenVLM).
HIDRAW_PATH = "/dev/hidraw0"
PTT_BYTE_INDEX = 1
PTT_PRESSED_MASK = 0x04  # bit 2: 0 = pressed, 1 = released (0x01 vs 0x05)


# Audio capture params (match the OpenVLM capture endpoint)
RATE = 48000
CHANNELS = 1
SAMPLE_BYTES = 2  # S16_LE
CHUNK_FRAMES = 1024
CHUNK_BYTES = CHUNK_FRAMES * CHANNELS * SAMPLE_BYTES


def find_openvlm_event():
    """Best-effort: locate the OpenVLM input event node by scanning sysfs names."""
    for evdev in sorted(glob.glob("/dev/input/event*")):
        name_path = "/sys/class/input/{}/device/name".format(os.path.basename(evdev))
        try:
            with open(name_path, "r") as f:
                name = f.read().strip()
        except OSError:
            continue
        if "openvlm" in name.lower():
            return evdev
    return None


def find_openvlm_card():
    """Best-effort: locate the OpenVLM ALSA card number from /proc/asound/cards."""
    try:
        with open("/proc/asound/cards", "r") as f:
            text = f.read()
    except OSError:
        return None
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or not stripped[0].isdigit():
            continue
        if "openvlm" in line.lower():
            return int(stripped.split()[0])
    return None


def rms_and_peak(pcm_bytes):
    """Return (rms, peak) as 0.0-1.0 floats from a chunk of S16_LE mono PCM."""
    count = len(pcm_bytes) // 2
    if count == 0:
        return 0.0, 0.0
    samples = struct.unpack("<{}h".format(count), pcm_bytes[: count * 2])
    sumsq = 0
    peak = 0
    for s in samples:
        sumsq += s * s
        a = abs(s)
        if a > peak:
            peak = a
    rms = math.sqrt(sumsq / count) / 32768.0
    return rms, peak / 32768.0


# The ComTac mic is a low-level signal, so displayed levels are small.
# Scale the meter bar for visibility (does NOT change the raw rms/peak numbers).
METER_DISPLAY_GAIN = 15.0


def meter_bar(level, width=30):
    """Render a 0.0-1.0 level as a text bar (with display gain for low-level mics)."""
    filled = int(min(1.0, max(0.0, level * METER_DISPLAY_GAIN)) * width)
    return "[" + "#" * filled + "-" * (width - filled) + "]"


def maximize_mic_gain(card):
    """Set the OpenVLM 'Mic' capture control to max and enable AGC, best-effort."""
    for args in (["sset", "Mic", "100%", "cap"],
                 ["sset", "Auto Gain Control", "on"]):
        try:
            subprocess.run(["amixer", "-c", str(card)] + args,
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except FileNotFoundError:
            return



def diagnose():
    """Watch ALL /dev/input/event* and poll /dev/hidraw* simultaneously,
    printing anything that changes. Use this to find which source your real
    PTT actually drives. Press your PTT a few times, then Ctrl-C."""
    sources = {}  # fd -> (label, kind)

    # Open every input event node.
    for evdev in sorted(glob.glob("/dev/input/event*")):
        name = "?"
        try:
            with open("/sys/class/input/{}/device/name".format(os.path.basename(evdev))) as f:
                name = f.read().strip()
        except OSError:
            pass
        try:
            fd = os.open(evdev, os.O_RDONLY | os.O_NONBLOCK)
            sources[fd] = ("{} ({})".format(evdev, name), "event")
        except OSError as e:
            print("skip {}: {}".format(evdev, e))

    # Open every hidraw node.
    hidraw_last = {}
    for hidraw in sorted(glob.glob("/dev/hidraw*")):
        try:
            fd = os.open(hidraw, os.O_RDONLY | os.O_NONBLOCK)
            sources[fd] = (hidraw, "hidraw")
            hidraw_last[fd] = None
        except OSError as e:
            print("skip {}: {} (try sudo)".format(hidraw, e))

    if not sources:
        sys.exit("ERROR: could not open any input/hidraw devices. Run with sudo.")

    print("DIAGNOSE MODE - watching:")
    for fd, (label, kind) in sources.items():
        print("  [{}] {}".format(kind, label))
    print("\nNow press/hold your REAL PTT a few times. Ctrl-C to quit.\n")

    poll_fds = list(sources.keys())
    try:
        while True:
            rlist, _, _ = select.select(poll_fds, [], [], 0.05)

            # Also actively poll hidraw nodes (some report only on change).
            for fd, (label, kind) in sources.items():
                if kind != "hidraw":
                    continue
                try:
                    data = os.read(fd, 64)
                except (BlockingIOError, OSError):
                    data = b""
                if data:
                    hexb = " ".join("{:02x}".format(b) for b in data)
                    prev = hidraw_last.get(fd)
                    changed = ""
                    if prev is not None and len(prev) == len(data):
                        diffs = [i for i in range(len(data)) if data[i] != prev[i]]
                        if diffs:
                            changed = "  changed bytes: {}".format(diffs)
                    hidraw_last[fd] = data
                    print("[{}] HIDRAW {}: {}{}".format(
                        time.strftime("%H:%M:%S"), label, hexb, changed))

            for fd in rlist:
                label, kind = sources[fd]
                if kind != "event":
                    continue
                try:
                    data = os.read(fd, EVENT_SIZE * 64)
                except (BlockingIOError, OSError):
                    continue
                for off in range(0, len(data) - EVENT_SIZE + 1, EVENT_SIZE):
                    _, _, etype, ecode, evalue = struct.unpack(
                        EVENT_FORMAT, data[off:off + EVENT_SIZE])
                    if etype == 0:  # EV_SYN, skip noise
                        continue
                    print("[{}] EVENT {}: type={} code={} value={}".format(
                        time.strftime("%H:%M:%S"), label, etype, ecode, evalue))
    except KeyboardInterrupt:
        print("\nDiagnose stopped.")
    finally:
        for fd in sources:
            try:
                os.close(fd)
            except OSError:
                pass


def main():
    parser = argparse.ArgumentParser(description="OpenVLM PTT + audio monitor")
    parser.add_argument("--event", help="input event node (default: auto-detect)")
    parser.add_argument("--card", type=int, help="ALSA card number (default: auto-detect)")
    parser.add_argument("--device", help="explicit ALSA device, e.g. plughw:1,0 (overrides --card)")
    parser.add_argument("--diagnose", action="store_true",
                        help="watch ALL input event* and hidraw* nodes to find the real PTT source")
    args = parser.parse_args()

    if args.diagnose:
        diagnose()
        return

    if args.device:
        alsa_device = args.device
    else:
        card = args.card if args.card is not None else find_openvlm_card()
        if card is None:
            sys.exit("ERROR: could not locate OpenVLM ALSA card; pass --card N or --device plughw:N,0")
        alsa_device = "plughw:{},0".format(card)
        maximize_mic_gain(card)


    # Open the PTT source: CM108 HID GPIO via /dev/hidraw0 (non-blocking).
    try:
        ptt_fd = os.open(HIDRAW_PATH, os.O_RDONLY | os.O_NONBLOCK)
    except PermissionError:
        sys.exit("ERROR: permission denied opening {}. Run with sudo.".format(HIDRAW_PATH))
    except OSError as e:
        sys.exit("ERROR: cannot open {}: {}".format(HIDRAW_PATH, e))

    # Launch arecord, streaming raw PCM to stdout continuously.
    arecord_cmd = [
        "arecord",
        "-D", alsa_device,
        "-f", "S16_LE",
        "-c", str(CHANNELS),
        "-r", str(RATE),
        "-t", "raw",
        "-q",
    ]
    try:
        arec = subprocess.Popen(arecord_cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    except FileNotFoundError:
        os.close(ptt_fd)
        sys.exit("ERROR: arecord not found (install alsa-utils).")

    audio_fd = arec.stdout.fileno()

    ptt_state = "RELEASED"
    rms = 0.0
    peak = 0.0
    audio_buf = b""

    print("OpenVLM monitor")
    print("  PTT source: {} (byte[{}], pressed when bit {:#x} clear)".format(
        HIDRAW_PATH, PTT_BYTE_INDEX, PTT_PRESSED_MASK))
    print("  ALSA input: {}".format(alsa_device))
    print("  Hold the PTT and talk - the mic meter should move. Ctrl-C to quit.")
    print("")

    try:
        while True:
            rlist, _, _ = select.select([ptt_fd, audio_fd], [], [], 0.05)

            # PTT: read HID report, decode byte[PTT_BYTE_INDEX].
            if ptt_fd in rlist:
                try:
                    report = os.read(ptt_fd, 64)
                except (BlockingIOError, OSError):
                    report = b""
                if len(report) > PTT_BYTE_INDEX:
                    pressed = (report[PTT_BYTE_INDEX] & PTT_PRESSED_MASK) != 0

                    new_state = "PRESSED " if pressed else "RELEASED"
                    if new_state != ptt_state:
                        ptt_state = new_state
                        sys.stdout.write("\n[{}] PTT {}\n".format(
                            time.strftime("%H:%M:%S"), ptt_state.strip()))

            # Audio: always running, so meter moves whenever there's signal.
            if audio_fd in rlist:
                try:
                    chunk = os.read(audio_fd, CHUNK_BYTES)
                except BlockingIOError:
                    chunk = b""
                if chunk == b"" and arec.poll() is not None:
                    err = arec.stderr.read().decode(errors="replace").strip()
                    sys.stdout.write("\narecord exited: {}\n".format(err or "(no error output)"))
                    break
                audio_buf += chunk
                while len(audio_buf) >= CHUNK_BYTES:
                    rms, peak = rms_and_peak(audio_buf[:CHUNK_BYTES])
                    audio_buf = audio_buf[CHUNK_BYTES:]

            sys.stdout.write(
                "\rPTT: {:8s} | mic {} rms={:.3f} peak={:.3f}   ".format(
                    ptt_state, meter_bar(rms), rms, peak
                )
            )
            sys.stdout.flush()

    except KeyboardInterrupt:
        sys.stdout.write("\nStopping...\n")
    finally:
        try:
            arec.terminate()
        except Exception:
            pass
        os.close(ptt_fd)



if __name__ == "__main__":
    main()
