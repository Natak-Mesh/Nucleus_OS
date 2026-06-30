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


def meter_bar(level, width=30):
    """Render a 0.0-1.0 level as a text bar."""
    filled = int(min(1.0, max(0.0, level)) * width)
    return "[" + "#" * filled + "-" * (width - filled) + "]"


def main():
    parser = argparse.ArgumentParser(description="OpenVLM PTT + audio monitor")
    parser.add_argument("--event", help="input event node (default: auto-detect)")
    parser.add_argument("--card", type=int, help="ALSA card number (default: auto-detect)")
    parser.add_argument("--device", help="explicit ALSA device, e.g. plughw:1,0 (overrides --card)")
    args = parser.parse_args()

    event_path = args.event or find_openvlm_event()
    if not event_path:
        sys.exit("ERROR: could not locate OpenVLM input event node; pass --event /dev/input/eventX")

    if args.device:
        alsa_device = args.device
    else:
        card = args.card if args.card is not None else find_openvlm_card()
        if card is None:
            sys.exit("ERROR: could not locate OpenVLM ALSA card; pass --card N or --device plughw:N,0")
        alsa_device = "plughw:{},0".format(card)

    # Open the PTT event device (raw, non-blocking).
    try:
        ev_fd = os.open(event_path, os.O_RDONLY | os.O_NONBLOCK)
    except PermissionError:
        sys.exit("ERROR: permission denied opening {}. Run with sudo or join the 'input' group.".format(event_path))
    except OSError as e:
        sys.exit("ERROR: cannot open {}: {}".format(event_path, e))

    # Launch arecord, streaming raw PCM to stdout.
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
        os.close(ev_fd)
        sys.exit("ERROR: arecord not found (install alsa-utils).")

    audio_fd = arec.stdout.fileno()

    ptt_state = "RELEASED"
    last_keycode = None
    rms = 0.0
    peak = 0.0
    audio_buf = b""

    print("OpenVLM monitor")
    print("  PTT event:  {}".format(event_path))
    print("  ALSA input: {}".format(alsa_device))
    print("  Press the PTT and talk. Ctrl-C to quit.")
    print("")

    try:
        while True:
            rlist, _, _ = select.select([ev_fd, audio_fd], [], [], 0.1)

            if ev_fd in rlist:
                try:
                    data = os.read(ev_fd, EVENT_SIZE * 64)
                except BlockingIOError:
                    data = b""
                for off in range(0, len(data) - EVENT_SIZE + 1, EVENT_SIZE):
                    _, _, etype, ecode, evalue = struct.unpack(
                        EVENT_FORMAT, data[off:off + EVENT_SIZE]
                    )
                    if etype == EV_KEY and evalue in (0, 1):
                        ptt_state = "PRESSED " if evalue == 1 else "RELEASED"
                        last_keycode = ecode
                        sys.stdout.write("\n")
                        sys.stdout.write(
                            "[{}] PTT {} (keycode {})\n".format(
                                time.strftime("%H:%M:%S"), ptt_state.strip(), ecode
                            )
                        )

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

            key_label = "" if last_keycode is None else " key={}".format(last_keycode)
            sys.stdout.write(
                "\rPTT: {:8s}{}  | mic {} rms={:.3f} peak={:.3f}   ".format(
                    ptt_state, key_label, meter_bar(rms), rms, peak
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
        os.close(ev_fd)


if __name__ == "__main__":
    main()
