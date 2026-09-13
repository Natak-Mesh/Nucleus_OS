# Drone Hardware

## Parts

### Matek H743-SLIM V2

Connected to the Pi over the PL011 UART on GPIO14/15 — header pins 8 and 10.

| Pi Zero 2 W | H743-SLIM |
|---|---|
| pin 8, GPIO14 (TXD) | `RX2` |
| pin 10, GPIO15 (RXD) | `TX2` |
| pin 6, GND | `GND` |

FC side is the `TX2`/`RX2` through-holes (USART2), which ArduPilot exposes as
`SERIAL3`. On the Pi the port is `/dev/ttyAMA0` at 921600 baud.

Bluetooth must be disabled to get access to these pins. The Bluetooth
controller claims the PL011 UART by default, so `/dev/ttyAMA0` does not exist
until `dtoverlay=disable-bt` is set in `/boot/firmware/config.txt`.

The FC runs 3.3V and GND off the Pi power pins.

### MicoAir MTF-01

![MicoAir MTF-01 wiring](mico-air-MTF-01-wiring.jpg)

Assumes the sensor is on the autopilot's Serial1 port. Any serial port can be
used.

| Parameter | Value | Meaning |
|---|---|---|
| `SERIAL1_BAUD` | `115` | 115200 |
| `SERIAL1_PROTOCOL` | `1` | MAVLink1 |
| `FLOW_TYPE` | `5` | MAVLink |
| `RNGFND1_TYPE` | `10` | MAVLink |

Reboot the autopilot to see the rangefinder parameters, then set:

| Parameter | Value | Meaning |
|---|---|---|
| `RNGFND1_MAX` | `8` | Maximum range 8m |
| `RNGFND1_MIN` | `0.01` | Minimum range |
| `RNGFND1_ORIENT` | `25` | Downward |

Once the sensor is active, the optical flow and range data show up on Mission
Planner's "Status" page — `opt_qua` and `rangefinder1` should have some value.

### LDRobot D500

Connected via USB to the companion computer.

### Arducam IMX708

Connected to a CSI ribbon connector on the carrier board. Not on a UART, so it
does not compete with the FC link or the MTF-01.

| Property | Value |
|---|---|
| Sensor | Sony IMX708, 4608x2592, 10-bit RGGB |
| Detected as | `imx708_wide` |
| Compute module | Raspberry Pi Compute Module 4 (CM4) |
| Carrier | Waveshare CM4-DUAL-ETH-4G/5G-BASE (2x CSI) |
| CSI port used | **CAM0** (the connector nearest the M.2/SIM edge) |
| Bus | CSI-2, i2c-20/21 addr `0x1a` |
| Autofocus | VCM lens driver, addr `0x0c` |

**This is a CM4, not a regular Pi — camera auto-detect does NOT work.** The CM4
has no camera EEPROM, so `camera_auto_detect=1` finds nothing and the sensor
must be declared explicitly in `/boot/firmware/config.txt`. The camera is wired
to the CM4's **CAM0** CSI port, so the overlay must say `cam0` (not `cam1`).

Working config (`/boot/firmware/config.txt`):

```
# CM4 has no camera EEPROM autodetect - sensor declared explicitly.
#camera_auto_detect=1

# --- CM4 CAM0: Arducam IMX708 ---
dtparam=i2c_vc=on
dtparam=cam0_reg=on
dtoverlay=imx708,cam0

# leave the modern graphics stack alone
dtoverlay=vc4-kms-v3d
```

Reboot, then verify:

```bash
rpicam-hello --list-cameras     # expect: imx708_wide [4608x2592 ...] @ .../imx708@1a
dmesg | grep imx708             # expect: "camera module ID 0x0302" (not "error -5")
```

`vcgencmd get_camera` reports `detected=0` even when working — it only knows the
removed legacy MMAL stack; ignore it.

#### Do NOT use the Waveshare dt-blob / fkms path

The Waveshare wiki for this board tells you to install a `/boot/dt-blob.bin` and
switch to `dtoverlay=vc4-fkms-v3d`. That is **Bookworm-and-older guidance and is
wrong on this Trixie (Debian 13) image.** `dt-blob.bin` is legacy firmware pin
routing that the modern `kms` camera path ignores, and `vc4-fkms-v3d` is
deprecated (it binds but fails with "No compatible format found"). If a
`dt-blob.bin` is present, delete it (`sudo rm /boot/firmware/dt-blob.bin
/boot/dt-blob.bin`) and use `vc4-kms-v3d`.

#### Wrong CSI port = "failed to read chip id 708, error -5"

If the overlay names the wrong CSI port, the sensor's EEPROM (`0x51`) still ACKs
on the muxed I2C bus but the imaging chip (`0x1a`) never powers/clocks, so the
driver logs `failed to read chip id 708, with error -5`. This looks identical to
a dead camera or bad ribbon. Before suspecting hardware, try the other port:
swap `cam0` <-> `cam1` in both the `dtoverlay` and `dtparam=camN_reg=on` lines
and reboot. On this carrier the camera is on **CAM0**.

### Video to QGroundControl

The camera is independent of the flight controller — video and MAVLink are two
separate streams that the GCS composites at display time.

Run by `nucleus-video.service`, gated on `VIDEO_ENABLED` (plus `DRONE_ENABLED`
and `CAMERA_ENABLED`) in `mesh.conf` and enabled by `config_generation.sh`,
following the `mavlink-router.service` pattern. The pipeline it runs
(`/opt/nucleus/drone/video-stream.sh`):

```bash
rpicam-vid -t 0 -n \
  --width $VIDEO_WIDTH --height $VIDEO_HEIGHT --framerate $VIDEO_FPS \
  --codec h264 --inline --intra $VIDEO_FPS --profile baseline \
  --bitrate $VIDEO_BITRATE -o - \
| gst-launch-1.0 -q fdsrc ! h264parse config-interval=1 \
  ! rtph264pay pt=96 config-interval=1 mtu=1400 \
  ! udpsink host=$GCS_IP port=$VIDEO_UDP_PORT sync=false
```

QGC: Application Settings → Video → source `UDP h.264`, port `5600`.

**gstreamer is in the path on purpose.** QGC's `UDP h.264` source is an RTP
receiver, not a raw-stream reader, so `rpicam-vid -o udp://...` (raw Annex-B)
will not render. `rpicam-vid` still does capture and hardware encode;
`gst-launch` only wraps the H.264 in RTP (`rtph264pay`) and sends it. This also
avoids needing `gstreamer1.0-libcamera` for capture.

UDP not TCP — no ACKs or retransmits to consume airtime on the half-duplex
mesh. `--inline` + `config-interval=1` repeat SPS/PPS so a client can join
mid-stream, `--intra $VIDEO_FPS` gives 1s keyframes for fast recovery,
`--profile baseline` avoids B-frame reordering delay, `mtu=1400` keeps RTP
under the mesh MTU so the 802.11s path does not IP-fragment, and `sync=false`
drops rather than buffers when the link congests.

The stream is a **blind push** to `GCS_IP` — unlike MAVLink's server endpoint,
it does not learn the peer from an inbound packet, so `GCS_IP` must be set in
`mesh.conf`. Defaults are 640x480@30 at 750 kbps, conservative for a loaded or
multi-hop mesh; a single-hop bench link can go to 1280x720 via the `VIDEO_*`
keys.

Only one process can hold the camera at a time. `video-stream.sh` runs
`pkill -f rpicam-vid` before starting for this reason: a second `rpicam-vid`
takes the port but fails to get the sensor (`Device or resource busy`,
`Failed to queue buffer`), accepting connections while sending no frames.

#### Verified manual command

Confirmed working from `lte-nucleus`, IMX708 on `cam0`, streaming to
QGroundControl. Substitute `<gcs-ip>` for the GCS address:

```bash
rpicam-vid -t 0 -n --width 640 --height 480 --framerate 30 \
  --codec h264 --inline --intra 30 --profile baseline --bitrate 750000 -o - \
| gst-launch-1.0 -q fdsrc ! h264parse config-interval=1 \
  ! rtph264pay pt=96 config-interval=1 mtu=1400 \
  ! udpsink host=<gcs-ip> port=5600 sync=false
```

QGC: Application Settings → Video → Source `UDP h.264`, UDP URL
`0.0.0.0:5600`. `0.0.0.0` means QGC listens on every interface; leave it as
is — the drone pushes at the GCS, not the other way around.

Tested over **Tailscale**, drone `100.91.66.103` → GCS `100.97.123.74`
(`natak-pc-1`). The mesh path (`GCS_IP` = a `10.20.x.x` address) is the field
path and is not yet verified.

#### Known issue: stream stalls

Seen once: video ran for a few seconds, then froze. Both `rpicam-vid` and
`gst-launch` were still alive but in state `S (sleeping)` — a blocked pipeline,
not a crash — and no packets were leaving the Pi. It did not recur on the next
run with the same command; cause unknown.

Confirm a stall (Pi stopped sending) versus a GCS-side drop:

```bash
timeout 5 tcpdump -ni any udp port 5600 | wc -l   # 0 = Pi is not sending
```

If it stalls, capture where each process is blocked **while it is still
stalled** (the PIDs are gone once you kill it):

```bash
RP=$(pgrep -f 'rpicam-vid -t 0'); GS=$(pgrep -f 'gst-launch-1.0 -q fdsrc')
cat /proc/$RP/wchan; echo; cat /proc/$GS/wchan; echo
sudo cat /proc/$RP/stack; sudo cat /proc/$GS/stack
ss -uanp | grep 5600
```

## FC UART Allocation

Through-holes on the H743-SLIM are silkscreened with the STM32 UART number,
which is **not** the ArduPilot `SERIALn` number. Mapping below.

| Through-holes | STM32 UART | ArduPilot |
|------|------|------|
| `TX2` / `RX2` | USART2 | SERIAL3 |
| `TX7` / `RX7` | UART7 | SERIAL1 |
| `TX3` / `RX3` | USART3 | SERIAL4 |
| `TX4` / `RX4` | UART4 | SERIAL6 |

UART7 is the only port with `CTS7`/`RTS7` broken out.
