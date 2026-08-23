# Drone Build Guide

Build log. See [drone-hardware.md](drone-hardware.md) for parts list.

---

## 1. Flash ArduPilot — ✅ 2026-05-16

DFU mode: hold BOOT while plugging USB. Flash `arducopter_with_bl.hex` from [firmware.ardupilot.org/Copter/stable/MatekH743/](https://firmware.ardupilot.org/Copter/stable/MatekH743/) using **STM32CubeProgrammer** (dfu-util fails on H743 dual-bank flash). Full chip erase, then program.

Verify: `ls /dev/ttyACM*` — FC appears as serial device. Heartbeat confirmed: Quadrotor, ArduPilotMega, MAVLink2, SysID=1.

## 2. MAVLink Comms — ✅ 2026-05-16

```bash
python3 -c "
from pymavlink import mavutil
conn = mavutil.mavlink_connection('/dev/ttyACM0', baud=115200)
hb = conn.wait_heartbeat(timeout=10)
print(f'type={hb.type} autopilot={hb.autopilot} sysid={conn.target_system}')
conn.close()
"
```

## 3. Wire MicoAir MTF-01 — TODO

Combined TOF rangefinder (0.02–8m) + PMW3901 optical flow. One sensor, one UART, gives both AltHold and Loiter. Backup: TF-Luna + Matek 3901-L0X on separate UARTs.

### Wiring (FC UART7 — `TX7`/`RX7` through-holes)

MTF-01 TX→`RX7`, RX→`TX7`, GND→GND, 5V→5V. Mount underside, pointing down.

### MTF-01 Mode

Must be set to **MAVLink output mode** (not default binary) at 115200 baud before connecting to FC.

### ArduPilot Params

```
SERIAL1_PROTOCOL = 18       # OpticalFlow MAVLink
SERIAL1_BAUD     = 115      # 115200

FLOW_TYPE        = 5        # MAVLink optical flow
RNGFND1_TYPE     = 10       # MAVLink rangefinder
RNGFND1_MIN_CM   = 2
RNGFND1_MAX_CM   = 800
RNGFND1_GNDCLEAR = 15       # landing gear height cm

EK3_SRC1_POSZ    = 2        # rangefinder for altitude
EK3_SRC1_VELXY   = 5        # optical flow for horizontal velocity
EK3_SRC1_POSXY   = 0        # no absolute position source
```

### Verify

Rangefinder:
```bash
python3 -c "
from pymavlink import mavutil
conn = mavutil.mavlink_connection('/dev/ttyACM0', baud=115200)
conn.wait_heartbeat()
while True:
    msg = conn.recv_match(type='RANGEFINDER', blocking=True, timeout=5)
    if msg: print(f'dist={msg.distance:.2f}m')
    else: break
"
```

Optical flow:
```bash
python3 -c "
from pymavlink import mavutil
conn = mavutil.mavlink_connection('/dev/ttyACM0', baud=115200)
conn.wait_heartbeat()
while True:
    msg = conn.recv_match(type='OPTICAL_FLOW_RAD', blocking=True, timeout=5)
    if msg: print(f'x={msg.integrated_x:.4f} y={msg.integrated_y:.4f} q={msg.quality} d={msg.distance:.2f}m')
    else: break
"
```

### Status
- [ ] MTF-01 set to MAVLink mode
- [ ] Wired to UART7 (`TX7`/`RX7`)
- [ ] Params set
- [ ] Rangefinder verified
- [ ] Optical flow verified

## 4. Wire Pi Zero 2 W — TODO

Pi runs mavlink-router bridging FC serial ↔ mesh UDP.

### Physical

Pi TX (pin 8, GPIO14) → FC `RX2`, Pi RX (pin 10, GPIO15) → FC `TX2`, common GND
(Pi pin 6). Both 3.3V, no level shifter. `TX2`/`RX2` are the USART2
through-holes, which ArduPilot exposes as SERIAL3.

### FC Params

```
SERIAL3_PROTOCOL = 2        # MAVLink2
SERIAL3_BAUD     = 921      # 921600
```

### mavlink-router config

```ini
[General]
TcpServerPort = 0

[UartEndpoint drone_fc]
Device = /dev/ttyAMA0
Baud = 921600

[UdpEndpoint ground]
Mode = Normal
Address = 0.0.0.0
Port = 14550
```

## 5. Flight Mode Config — TODO

| Zorro Switch | Mode | What it does |
|---|---|---|
| Pos 1 | Stabilize | Self-level, manual throttle |
| Pos 2 | AltHold | Self-level + rangefinder alt hold |
| Pos 3 | Loiter | Full 3D position hold (needs optical flow) |
| Pos 4 | Land | Auto descend and disarm |

Arm/disarm: dedicated switch → CH5.

## 6. Failsafe Config — TODO

```
RC_OVERRIDE_TIME = 3.0      # land if no RC input for 3s
FS_THR_ENABLE    = 3        # land on throttle failsafe
FS_GCS_ENABLE    = 1        # land on GCS heartbeat loss
FS_GCS_TIMEOUT   = 5
FENCE_ENABLE     = 1        # altitude fence
FENCE_TYPE       = 1        # alt only (no GPS fence indoors)
FENCE_ALT_MAX    = 5        # ceiling meters
FENCE_ACTION     = 1        # land on breach
```

## 7. Control Chain

```
Zorro (USB HID) → Ground Pi (MAVProxy) → 802.11s mesh UDP → Drone Pi (mavlink-router) → FC UART
```

MAVProxy launch:
```bash
mavproxy.py --master=udpout:DRONE_IP:14550 --joystick
```

Add ATAK forwarding:
```bash
mavproxy.py --master=udpout:DRONE_IP:14550 --out=udp:ATAK_IP:14550 --joystick
```

## 8. Bench Test — TODO

Props off. Verify RC_CHANNELS_OVERRIDE reaches FC through mesh.

## 9. First Hover — TODO

Tethered, AltHold mode. Then Loiter. Then tune PIDs.

---

## Test Log

### Zorro USB HID — ✅ 2026-04-29

Zorro detected as `ID 1209:4f54` → `/dev/input/js0`. 7 axes (4 sticks + 3 switches), 24 buttons. User in `input` group.

### MAVProxy + Joystick — ✅ 2026-04-29

Venv at `/opt/nucleus/drone-venv`. pymavlink 2.4.49, MAVProxy 1.8.74, pygame 2.6.1. Zorro reads correctly.

### Local Loopback — ✅ 2026-04-29

`drone_sim.py` (UDP listener) + `zorro_mavlink_sender.py` (stick→RC_CHANNELS_OVERRIDE at 50Hz). All 4 sticks + 3 switch axes working end-to-end.

### Cross-Mesh — pending

### ATAK Integration — pending
