# Pi UART Setup for the Flight Controller Link

How to get `/dev/ttyAMA0` working on GPIO14/15 so mavlink-router can reach the
flight controller. This is required on every fresh image — a stock Raspberry Pi
OS install will **not** work out of the box.

```bash
sudo /opt/nucleus/bin/drone-uart-setup.sh
sudo reboot
python3 /opt/nucleus/drone/fc-link-check.py
```

## Why it does not work by default

The Pi has two UARTs that can be routed to GPIO14/15 (header pins 8 and 10):

| UART | Clock source | Device | Usable at 921600 |
|---|---|---|---|
| PL011 ("full" UART) | own fixed clock | `/dev/ttyAMA0` | yes |
| mini-UART | derived from the VPU core clock | `/dev/ttyS0` | no |

On a stock image the PL011 is claimed by the on-board Bluetooth controller. The
`hci_uart_bcm` driver binds it as `serial0-0`, so `/dev/ttyAMA0` is never
created and GPIO14/15 get the mini-UART instead.

Confirm which UART owns the pins:

```bash
ls -l /dev/serial0                  # -> ttyS0 means Bluetooth still has the PL011
cat /sys/bus/serial/devices/*/uevent | grep hci_uart
```

Three separate problems result:

1. **`/dev/ttyAMA0` does not exist.** `MAVLINK_SERIAL` points at it, so
   mavlink-router cannot open the port at all.
2. **The mini-UART is not stable at 921600.** Its baud rate tracks the VPU core
   clock, which moves under CPU load. Framing breaks.
3. **A serial console and login prompt run on the same pins at 115200.** The
   kernel transmits boot messages straight into the FC's `RX2` pin, and
   `serial-getty` holds the port open against mavlink-router.

## The fixes

`drone-uart-setup.sh` applies all of these. They are listed here so the manual
equivalent is on record.

### 1. Release the PL011 from Bluetooth

In `/boot/firmware/config.txt`:

```
enable_uart=1
dtoverlay=disable-bt
```

`disable-bt` unbinds the Bluetooth controller and routes the PL011 to
GPIO14/15, where it appears as `/dev/ttyAMA0`. Bluetooth is not used on the
drone build, so nothing is lost.

Note: `hciuart.service` only exists on older Raspberry Pi OS images. Current
images bind Bluetooth through the kernel serdev mechanism instead, so
`systemctl disable hciuart` fails with "unit could not be found" — this is
expected and not an error. Disable `bluetooth.service` instead.

### 2. Remove the serial console

In `/boot/firmware/cmdline.txt`, delete the `console=serial0,115200` token
(it may also read `console=ttyS0,115200` or `console=ttyAMA0,115200`). Keep
`console=tty1`. The file must remain a **single line**.

### 3. Disable the serial login prompt

```bash
sudo systemctl disable --now serial-getty@ttyS0.service
sudo systemctl mask serial-getty@ttyS0.service
```

The unit is created automatically by a systemd generator from the `console=`
setting in cmdline.txt, so it can be running without being "enabled". Masking
it prevents it from coming back.

### 4. Port permissions

The operating user must be in the `dialout` group to open the port without
sudo:

```bash
sudo usermod -aG dialout natak
```

## Verifying

After reboot:

```bash
ls -l /dev/ttyAMA0            # must exist, crw-rw---- root dialout
ls -l /dev/serial0            # must now point at ttyAMA0
sudo fuser -v /dev/ttyAMA0    # must report no holder
python3 /opt/nucleus/drone/fc-link-check.py
```

`fc-link-check.py` is read-only and checks everything above, then listens on
the port for MAVLink2 framing and decodes a HEARTBEAT. It reports the autopilot
type, system ID and firmware version when the link is up.

Note that mavlink-router holds the port exclusively when it is running. Stop it
before running the check by hand:

```bash
sudo systemctl stop mavlink-router
```

## Flight controller side

The Pi connects to the `TX2`/`RX2` through-holes on the H743-SLIM (USART2),
which ArduPilot exposes as `SERIAL3`:

```
SERIAL3_PROTOCOL = 2      # MAVLink2
SERIAL3_BAUD     = 921    # 921600
```

Wiring, per `drone-hardware.md`:

| Pi | H743-SLIM |
|---|---|
| pin 8, GPIO14 (TXD) | `RX2` |
| pin 10, GPIO15 (RXD) | `TX2` |
| pin 6, GND | `GND` |

The FC must be powered — over USB or from the battery — or nothing will be
transmitted regardless of how the Pi is configured.

## If no data arrives

Work through these in order. `fc-link-check.py` prints the same list.

| Cause | Symptom | Check |
|---|---|---|
| UART still owned by Bluetooth | `/dev/ttyAMA0` missing | `cat /sys/bus/serial/devices/*/uevent \| grep hci_uart` |
| Port held by another process | port opens but no data | `sudo fuser -v /dev/ttyAMA0` |
| TX/RX swapped | no bytes at any baud rate | Pi pin 8 → FC `RX2`, Pi pin 10 → FC `TX2` |
| Wrong baud rate | bytes arrive, but garbage, no `0xFD` | `fc-link-check.py --baud 115200` |
| `SERIAL3_PROTOCOL` not 2 | no bytes, or never valid frames | check params in the ground station |

MAVLink2 frames start with `0xFD`. MAVLink1 frames start with `0xFE` — if you
see those, the FC is set to MAVLink1 and `SERIAL3_PROTOCOL` needs to be 2.
