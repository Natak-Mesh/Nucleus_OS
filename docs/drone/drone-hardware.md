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

Through-holes on the H743-SLIM are silkscreened with the STM32 UART number,
which is **not** the ArduPilot `SERIALn` number. Mapping below.

| Through-holes | STM32 UART | ArduPilot | Device | Config |
|------|------|------|--------|--------|
| `TX2` / `RX2` | USART2 | SERIAL3 | Pi Zero 2 W | `SERIAL3_PROTOCOL=2` (MAVLink2) @ 921600 |
| `TX7` / `RX7` | UART7 | SERIAL1 | MicoAir MTF-01 | `SERIAL1_PROTOCOL=18` (OptFlow MAVLink) @ 115200 |
| `TX3` / `RX3` | USART3 | SERIAL4 | LD-06 (future) | TBD |
| `TX4` / `RX4` | UART4 | SERIAL6 | Free | — |

UART7 is the only port with `CTS7`/`RTS7` broken out. The Pi link on USART2 has
no hardware flow control.

### Pi Zero 2 W ↔ FC wiring

| Pi Zero 2 W | H743-SLIM |
|---|---|
| pin 8, GPIO14 (TXD) | `RX2` |
| pin 10, GPIO15 (RXD) | `TX2` |
| pin 6, GND | `GND` |

Both sides are 3.3V TTL, no level shifter. Power the Pi from the 5V BEC, not
from the FC, but tie grounds.
