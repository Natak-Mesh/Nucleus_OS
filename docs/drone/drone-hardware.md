# Drone Hardware

## Parts

| Part | Role | Status |
|------|------|--------|
| Matek H743-SLIM V2 | Flight controller (ArduPilot Copter `MatekH743`) | Have |
| MicoAir MTF-01 | Rangefinder + optical flow (TOF 0.02–8m + PMW3901) | Have |
| Benewake TF-Luna | Standalone rangefinder 0.2–8m (backup) | Have |
| Matek 3901-L0X | Standalone optical flow (backup) | Have |
| LDRobot LD-06 | 360° 2D scanning LiDAR (future obstacle avoidance) | Have |
| Pi Zero 2 W | Companion computer, mesh node, MAVLink bridge | Need |
| 5V BEC | Power Pi from drone battery | Need |
| RadioMaster Zorro | Pilot controller (USB HID joystick via EdgeTX) | Have |
| 4S LiPo / Frame / Motors / ESCs / Props | Existing airframe | Have |

## FC UART Allocation

| UART | Device | Config |
|------|--------|--------|
| 1 | Pi Zero 2 W | `SERIAL1_PROTOCOL=2` (MAVLink2) @ 921600 |
| 2 | MicoAir MTF-01 | `SERIAL2_PROTOCOL=18` (OptFlow MAVLink) @ 115200 |
| 3 | LD-06 (future) | TBD |
| 4 | Free | — |
