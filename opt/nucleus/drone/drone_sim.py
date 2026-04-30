#!/usr/bin/env python3
"""
drone_sim.py — Simulated ArduPilot drone for MAVLink comms testing.

Listens on UDP for incoming MAVLink messages (RC_CHANNELS_OVERRIDE, etc.)
and sends back heartbeat + telemetry, simulating what a real ArduPilot FC
would do over mavlink-router.

Usage (run in Terminal 1):
    /opt/nucleus/drone-venv/bin/python3 /opt/nucleus/drone/drone_sim.py

Then run zorro_mavlink_sender.py in Terminal 2 to send stick data here.
Press Ctrl+C to stop.
"""

import time
import sys
import threading
import math

from pymavlink import mavutil


class DroneSim:
    def __init__(self, listen_port=14550, sysid=1):
        self.sysid = sysid
        self.conn = mavutil.mavlink_connection(
            f"udpin:0.0.0.0:{listen_port}",
            source_system=sysid,
            source_component=1
        )
        self.start_time = time.time()
        self.rc_msg_count = 0
        self.heartbeat_count = 0
        self.armed = False
        self.altitude = 0.0
        self.rc_channels = [1500] * 8

    def send_heartbeat(self):
        base_mode = mavutil.mavlink.MAV_MODE_FLAG_CUSTOM_MODE_ENABLED
        if self.armed:
            base_mode |= mavutil.mavlink.MAV_MODE_FLAG_SAFETY_ARMED
        self.conn.mav.heartbeat_send(
            mavutil.mavlink.MAV_TYPE_QUADROTOR,
            mavutil.mavlink.MAV_AUTOPILOT_ARDUPILOTMEGA,
            base_mode, 0,
            mavutil.mavlink.MAV_STATE_STANDBY
        )
        self.heartbeat_count += 1

    def send_attitude(self):
        t = time.time() - self.start_time
        self.conn.mav.attitude_send(
            int(t * 1000),
            0.02 * math.sin(t * 0.5),   # roll
            0.015 * math.cos(t * 0.3),   # pitch
            (t * 0.1) % (2 * math.pi),   # yaw
            0.0, 0.0, 0.0
        )

    def send_sys_status(self):
        elapsed = time.time() - self.start_time
        voltage = 16.8 - (elapsed / 600) * 2.4
        remaining = max(0, int(100 - (elapsed / 600) * 100))
        self.conn.mav.sys_status_send(
            0, 0, 0, 200,
            int(voltage * 1000), 500, remaining,
            0, 0, 0, 0, 0, 0
        )

    def telemetry_loop(self):
        last_hb = 0
        last_att = 0
        last_sys = 0
        while True:
            now = time.time()
            if now - last_hb >= 1.0:
                self.send_heartbeat()
                last_hb = now
            if now - last_att >= 0.1:
                self.send_attitude()
                last_att = now
            if now - last_sys >= 0.5:
                self.send_sys_status()
                last_sys = now
            time.sleep(0.02)

    def receive_loop(self):
        while True:
            try:
                msg = self.conn.recv_match(blocking=True, timeout=0.05)
                if msg is None:
                    continue
                msg_type = msg.get_type()
                if msg_type == "RC_CHANNELS_OVERRIDE":
                    self.rc_msg_count += 1
                    ch = [msg.chan1_raw, msg.chan2_raw, msg.chan3_raw, msg.chan4_raw,
                          msg.chan5_raw, msg.chan6_raw, msg.chan7_raw, msg.chan8_raw]
                    self.rc_channels = ch
                    labels = ["Roll", "Pitch", "Throt", "Yaw", "CH5", "CH6", "CH7", "CH8"]
                    parts = [f"{labels[i]}:{ch[i]:5d}" for i in range(8)]
                    print(f"\r[RC #{self.rc_msg_count:5d}] {' | '.join(parts)}", end="", flush=True)
                elif msg_type in ("HEARTBEAT", "BAD_DATA"):
                    pass
            except Exception as e:
                print(f"\nError: {e}")
                time.sleep(0.1)


def main():
    print("=" * 70)
    print("  DRONE SIMULATOR")
    print("  Listening on UDP port 14550")
    print("  Sending: HEARTBEAT (1Hz), ATTITUDE (10Hz), SYS_STATUS (2Hz)")
    print("  Waiting for RC_CHANNELS_OVERRIDE messages...")
    print("=" * 70)
    print()
    print("  Run zorro_mavlink_sender.py in another terminal to send stick data.")
    print("  Press Ctrl+C to stop.")
    print()

    sim = DroneSim()
    telem = threading.Thread(target=sim.telemetry_loop, daemon=True)
    telem.start()

    try:
        sim.receive_loop()
    except KeyboardInterrupt:
        print(f"\n\nDone. Received {sim.rc_msg_count} RC messages, sent {sim.heartbeat_count} heartbeats.")


if __name__ == "__main__":
    main()
