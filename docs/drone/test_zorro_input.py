#!/usr/bin/env python3
"""
test_zorro_input.py — Interactive Zorro joystick input test.

Run this in a terminal:
    /opt/nucleus/drone-venv/bin/python3 /opt/nucleus/drone/test_zorro_input.py

It will show you live axis values as you move sticks and switches.
Press Ctrl+C to stop.
"""

import pygame
import time
import sys
import os

def main():
    # Suppress pygame welcome message
    os.environ['PYGAME_HIDE_SUPPORT_PROMPT'] = '1'

    pygame.init()
    pygame.joystick.init()

    count = pygame.joystick.get_count()
    if count == 0:
        print("ERROR: No joystick found. Is the Zorro plugged in and powered on?")
        print("Check: lsusb | grep -i radio")
        sys.exit(1)

    js = pygame.joystick.Joystick(0)
    js.init()

    print("=" * 60)
    print(f"  ZORRO JOYSTICK TEST")
    print(f"  Device: {js.get_name()}")
    print(f"  Axes: {js.get_numaxes()}  Buttons: {js.get_numbuttons()}")
    print("=" * 60)
    print()
    print("  Move the sticks and flip switches on the Zorro.")
    print("  You should see the values change in real time below.")
    print("  Press Ctrl+C to stop.")
    print()
    print("-" * 60)

    # Expected mapping for Mode 2 Zorro
    axis_names = {
        0: "Roll (CH1)    ",
        1: "Pitch (CH2)   ",
        2: "Throttle (CH3)",
        3: "Yaw (CH4)     ",
        4: "Switch (CH5)  ",
        5: "Switch (CH6)  ",
        6: "Switch (CH7)  ",
    }

    # Track min/max to show range of movement
    axis_min = {}
    axis_max = {}
    for i in range(js.get_numaxes()):
        axis_min[i] = 999.0
        axis_max[i] = -999.0

    try:
        while True:
            pygame.event.pump()

            # Move cursor up to overwrite previous output
            if js.get_numaxes() > 0:
                sys.stdout.write(f"\033[{js.get_numaxes() + 2}A")

            print(f"  {'Axis':<18} {'Value':>8}  {'Min':>8}  {'Max':>8}  {'Bar'}")
            print(f"  {'----':<18} {'-----':>8}  {'---':>8}  {'---':>8}  {'---'}")

            for i in range(js.get_numaxes()):
                val = js.get_axis(i)
                name = axis_names.get(i, f"Axis {i}          ")

                # Update min/max
                if val < axis_min[i]:
                    axis_min[i] = val
                if val > axis_max[i]:
                    axis_max[i] = val

                # Draw a simple bar
                bar_pos = int((val + 1.0) / 2.0 * 30)  # -1..+1 → 0..30
                bar = "." * 30
                bar = bar[:bar_pos] + "█" + bar[bar_pos+1:]

                print(f"  {name}  {val:+.3f}   {axis_min[i]:+.3f}   {axis_max[i]:+.3f}   [{bar}]")

            # Check buttons
            pressed = []
            for b in range(js.get_numbuttons()):
                if js.get_button(b):
                    pressed.append(str(b))
            btn_str = ", ".join(pressed) if pressed else "none"
            print(f"\n  Buttons pressed: {btn_str:<40}")

            time.sleep(0.05)  # 20 Hz update

    except KeyboardInterrupt:
        print("\n")
        print("=" * 60)
        print("  TEST COMPLETE — Movement summary:")
        print("=" * 60)
        for i in range(js.get_numaxes()):
            name = axis_names.get(i, f"Axis {i}          ")
            rng = axis_max[i] - axis_min[i]
            status = "✅ MOVED" if rng > 0.05 else "❌ NO MOVEMENT"
            print(f"  {name}  range: {rng:.3f}  {status}")
        print()
        pygame.quit()


if __name__ == "__main__":
    main()
