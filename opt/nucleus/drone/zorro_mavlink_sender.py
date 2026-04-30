#!/usr/bin/env python3
"""
zorro_mavlink_sender.py — Reads Zorro joystick and sends MAVLink RC_CHANNELS_OVERRIDE.

Reads stick/switch positions from the RadioMaster Zorro via pygame,
converts them to RC channel values (1000-2000 µs), and sends them
as MAVLink RC_CHANNELS_OVERRIDE messages over UDP.

Usage (run in Terminal 2, after drone_sim.py is running in Terminal 1):
    /opt/nucleus/drone-venv/bin/python3 /opt/nucleus/drone/zorro_mavlink_sender.py

By default sends to 127.0.0.1:14550 (localhost — where drone_sim.py listens).
To send to a remote mesh Pi instead:
    /opt/nucleus/drone-venv/bin/python3 /opt/nucleus/drone/zorro_mavlink_sender.py --target DRONE_IP:14550

Press Ctrl+C to stop.
"""

import argparse
import time
import sys
import os

os.environ['PYGAME_HIDE_SUPPORT_PROMPT'] = '1'

import pygame
from pymavlink import mavutil


def axis_to_rc(value, center=1500, half_range=500):
    """Convert pygame axis value (-1.0 to +1.0) to RC µs value (1000-2000)."""
    return int(center + value * half_range)


def main():
    parser = argparse.ArgumentParser(description="Zorro → MAVLink RC_CHANNELS_OVERRIDE sender")
    parser.add_argument("--target", default="127.0.0.1:14550",
                        help="Target IP:port to send MAVLink to (default: 127.0.0.1:14550)")
    parser.add_argument("--rate", type=int, default=50,
                        help="Send rate in Hz (default: 50)")
    args = parser.parse_args()

    # Init joystick
    pygame.init()
    pygame.joystick.init()

    if pygame.joystick.get_count() == 0:
        print("ERROR: No joystick found. Is the Zorro plugged in?")
        sys.exit(1)

    js = pygame.joystick.Joystick(0)
    js.init()

    print("=" * 70)
    print("  ZORRO MAVLink SENDER")
    print(f"  Joystick: {js.get_name()}")
    print(f"  Axes: {js.get_numaxes()}  Buttons: {js.get_numbuttons()}")
    print(f"  Target: udpout:{args.target}")
    print(f"  Send rate: {args.rate} Hz")
    print("=" * 70)
    print()

    # Create MAVLink connection (UDP output to drone_sim or real drone)
    conn = mavutil.mavlink_connection(
        f"udpout:{args.target}",
        source_system=255,      # GCS system ID
        source_component=190    # GCS component
    )

    print("  Sending RC_CHANNELS_OVERRIDE... move sticks to see values change.")
    print("  Press Ctrl+C to stop.")
    print()

    # Axis mapping: Zorro Mode 2
    # Axis 0 = Roll (CH1),  Axis 1 = Pitch (CH2)
    # Axis 2 = Throttle (CH3),  Axis 3 = Yaw (CH4)
    # Axis 4-6 = Switches (CH5-CH7)

    interval = 1.0 / args.rate
    msg_count = 0

    try:
        while True:
            pygame.event.pump()

            # Read all axes
            roll     = axis_to_rc(js.get_axis(0))   # CH1: 1000-2000
            pitch    = axis_to_rc(js.get_axis(1))   # CH2: 1000-2000
            throttle = axis_to_rc(js.get_axis(2))   # CH3: 1000-2000
            yaw      = axis_to_rc(js.get_axis(3))   # CH4: 1000-2000

            # Switches (axes 4-6 if they exist)
            ch5 = axis_to_rc(js.get_axis(4)) if js.get_numaxes() > 4 else 1500
            ch6 = axis_to_rc(js.get_axis(5)) if js.get_numaxes() > 5 else 1500
            ch7 = axis_to_rc(js.get_axis(6)) if js.get_numaxes() > 6 else 1500
            ch8 = 1500  # unused

            # Send RC_CHANNELS_OVERRIDE
            conn.mav.rc_channels_override_send(
                conn.target_system if conn.target_system else 1,  # target system
                conn.target_component if conn.target_component else 1,  # target component
                roll, pitch, throttle, yaw,
                ch5, ch6, ch7, ch8
            )

            msg_count += 1

            # Display what we're sending
            print(f"\r[TX #{msg_count:5d}] "
                  f"Roll:{roll:5d} | Pitch:{pitch:5d} | Throt:{throttle:5d} | Yaw:{yaw:5d} | "
                  f"CH5:{ch5:5d} | CH6:{ch6:5d} | CH7:{ch7:5d}",
                  end="", flush=True)

            time.sleep(interval)

    except KeyboardInterrupt:
        print(f"\n\nDone. Sent {msg_count} RC_CHANNELS_OVERRIDE messages.")
        pygame.quit()


if __name__ == "__main__":
    main()
