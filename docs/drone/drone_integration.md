
# Indoor Drone Control via 802.11s Mesh — High-Level Design

## Project: NATAK Indoor Drone System

**Date:** 2026-04-28
**Last Updated:** 2026-04-29
**Status:** Design / Planning

---

## 1. Project Overview

### Goals

- Fly a small drone **indoors** (inside buildings, houses, warehouses) safely and reliably
- The pilot **does not need to be highly skilled** — the system should be forgiving and stable
- Control the drone over an **existing 802.11s mesh network** (Pi-based, babel-routed) rather than traditional RC radio links
- Provide **real-time telemetry and situational awareness** via MAVLink, with integration into **ATAK** (Android Team Awareness Kit)
- Use **ArduPilot** as the flight controller firmware for native MAVLink support and mature indoor flight capabilities

### Design Philosophy

- Leverage existing, mature, open-source software wherever possible — minimize custom code
- Use the 802.11s mesh as the sole communications backbone for control, telemetry, and SA
- Prioritize **stability and ease of flight** over agility or performance
- The drone should hold altitude and ideally position with minimal pilot input
- Failsafe behavior must be safe and predictable — if comms are lost, the drone lands

---

## 2. System Architecture

### High-Level Diagram

```
┌─────────────────────┐
│  RadioMaster Zorro   │
│  (EdgeTX, USB HID)   │
└──────────┬──────────┘
           │ USB (HID Joystick)
           ▼
┌─────────────────────┐         ┌─────────────────────┐
│  Ground Station Pi   │◄───────►│    ATAK Device       │
│  (mesh node)         │  mesh   │  (UAS Plugin,        │
│                      │  UDP    │   MAVLink consumer)   │
│  • MAVProxy          │         └─────────────────────┘
│    (joystick input,  │
│     MAVLink GCS)     │
└──────────┬──────────┘
           │ MAVLink over UDP
           │ (802.11s mesh, babel-routed, unicast)
           ▼
┌─────────────────────┐
│  Drone Pi Zero 2 W   │
│  (mesh node)         │
│                      │
│  • mavlink-router    │
│    (serial ↔ UDP)    │
└──────────┬──────────┘
           │ MAVLink serial (UART, 115200–921600 baud)
           ▼
┌─────────────────────┐
│  ArduPilot FC        │
│  (Copter firmware)   │
│                      │
│  • F7/H7 board       │
│  • TF-Luna LiDAR     │
│  • Optional: PMW3901 │
│    optical flow       │
│  • ESCs + Motors      │
└─────────────────────┘
```

### Data Flows

| Flow | Protocol | Transport | Direction |
|------|----------|-----------|-----------|
| Stick/switch input | MAVLink `RC_CHANNELS_OVERRIDE` | UDP over 802.11s mesh | Ground Pi → Drone Pi → FC |
| Telemetry | MAVLink (HEARTBEAT, ATTITUDE, ALTITUDE, SYS_STATUS, etc.) | UDP over 802.11s mesh | FC → Drone Pi → Ground Pi / ATAK |
| GCS commands (arm, mode change, etc.) | MAVLink `COMMAND_LONG` | UDP over 802.11s mesh | Ground Pi or ATAK → Drone Pi → FC |

**Single protocol end-to-end:** Everything is MAVLink. No protocol translation needed anywhere in the chain.

---

## 3. The Indoor Challenge

### Why Indoor Flight Is Hard

Traditional drones rely on **GPS** for position hold, return-to-home, and navigation. GPS does not work indoors. Without GPS:

- The drone has **no absolute position reference** — it will drift laterally
- **Barometric altitude hold is unreliable indoors** — pressure fluctuations from HVAC, doors, prop wash, and room pressurization cause the barometer to report altitude changes of 1–3 meters that aren't real
- Without stabilization aids, the pilot must constantly correct for drift — demanding high skill

### The Solution: Sensor-Assisted Stabilization

To make indoor flight easy for an unskilled pilot, we rely on:

1. **Self-leveling flight mode** (ArduPilot "Stabilize" or "AltHold" mode) — the drone automatically levels itself when the pilot releases the sticks
2. **Rangefinder-based altitude hold** — a downward-facing LiDAR sensor provides accurate, stable altitude measurements at indoor ranges, replacing the unreliable barometer
3. **Optional: Optical flow position hold** — a downward-facing camera/sensor tracks ground texture to hold lateral position without GPS

With these in place, the pilot experience becomes:
- **Release the sticks → the drone holds still in the air** (altitude hold, and position hold if optical flow is present)
- **Push a stick → the drone moves in that direction at a controlled rate**
- **No risk of flipping, no altitude bobbing, no uncontrolled drift**

---

## 4. Altitude Hold: TF-Luna LiDAR Rangefinder

### Why Not the Barometer?

The barometer (BMP280/BMP388/etc.) on the flight controller measures atmospheric pressure and converts it to altitude. Indoors, this is essentially useless:

- **HVAC systems** create pressure differentials between rooms
- **Opening/closing doors** causes sudden pressure changes
- **Prop wash** creates local pressure disturbances around the sensor
- Net result: the drone "thinks" it's climbing or descending when it isn't, leading to erratic altitude behavior

A barometer might show ±2 meters of phantom altitude change in an indoor environment. That's the difference between hovering at waist height and crashing into the ceiling or floor.

### The TF-Luna: Recommended Rangefinder

The **Benewake TF-Luna** is the recommended altitude sensor for this project.

| Specification | Value |
|---|---|
| **Sensor type** | Time-of-Flight LiDAR (905 nm infrared laser) |
| **Range** | 0.2 – 8 meters |
| **Accuracy** | ±2 cm (at 0.2–3 m), ±1% of distance (3–8 m) |
| **Update rate** | 1–250 Hz (configurable, recommend 100 Hz) |
| **Interface** | UART (default) or I2C |
| **Weight** | ~5 grams |
| **Size** | 35 × 21.2 × 13.5 mm |
| **Power** | 5V, ~70 mA |
| **Price** | ~$20–30 USD |
| **ArduPilot driver** | Native — `RNGFND_TYPE = 20` (Benewake TFminiPlus, compatible with TF-Luna in UART mode) |

### Why TF-Luna Over Alternatives

| Sensor | Range | Weight | Indoor Suitability | Notes |
|---|---|---|---|---|
| **TF-Luna** ✓ | 0.2–8 m | 5 g | **Excellent** | Best all-around for indoor. Fast, accurate, light, cheap, ArduPilot native. |
| TF-Mini Plus | 0.1–12 m | 12 g | Excellent | Slightly heavier, slightly more range. Also a strong choice. |
| VL53L1X (ToF) | 0.04–4 m | <1 g | Good for close range | Very light but limited to 4 m max. Fine for tight spaces, insufficient for warehouses. |
| HC-SR04 (Ultrasonic) | 0.02–4 m | 10 g | Poor | Susceptible to prop noise, slow update rate, unreliable readings from soft/angled surfaces. |
| Garmin LiDAR-Lite v4 | 0.1–10 m | 20 g | Overkill | Expensive (~$60+), heavier, same effective indoor range as TF-Luna. |

### How It Works in ArduPilot

1. The TF-Luna is mounted on the underside of the drone, pointing straight down
2. It connects to a spare UART on the flight controller (TX/RX/GND/5V)
3. ArduPilot reads the distance measurements at 100 Hz
4. **ArduPilot's EKF (Extended Kalman Filter)** fuses the rangefinder data with accelerometer and (optionally) barometer data to produce a smooth, accurate altitude estimate
5. In **AltHold** or **Loiter** flight mode, ArduPilot uses this fused altitude estimate to hold the drone at a constant height above the ground

**The pilot experience:** Push the throttle stick to the middle → the drone climbs to a moderate height and holds there. Nudge the stick up or down → the drone smoothly adjusts altitude. Release the stick → it holds the new altitude. The rangefinder gives centimeter-level accuracy at indoor ranges.

### ArduPilot Rangefinder Configuration (Key Parameters)

| Parameter | Value | Purpose |
|---|---|---|
| `RNGFND1_TYPE` | 20 | Benewake serial driver |
| `RNGFND1_MIN_CM` | 20 | Minimum range: 20 cm |
| `RNGFND1_MAX_CM` | 800 | Maximum range: 800 cm (8 m) |
| `RNGFND1_GNDCLEAR` | 15 | Ground clearance when landed (cm) — set to landing gear height |
| `SERIAL4_PROTOCOL` | 9 | Rangefinder (on whatever serial port you wire the TF-Luna to) |
| `SERIAL4_BAUD` | 115 | 115200 baud |
| `EK3_SRC1_POSZ` | 2 | Use rangefinder as primary altitude source (when in range) |

When the rangefinder is active and in range, ArduPilot will prefer it over the barometer for altitude estimation. When the drone flies above the rangefinder's max range (unlikely indoors), it gracefully falls back to the barometer.

---

## 5. Ease of Use: Flight Modes for Unskilled Pilots

### Recommended Flight Modes

ArduPilot Copter supports many flight modes. For an unskilled indoor pilot, configure the following on the Zorro's mode switch:

| Switch Position | ArduPilot Mode | Behavior | Skill Required |
|---|---|---|---|
| **Position 1** | **Stabilize** | Self-leveling, manual throttle. Drone levels when sticks are released, but pilot controls altitude manually. | Low-Medium |
| **Position 2** | **AltHold** | Self-leveling + rangefinder altitude hold. Drone holds altitude when throttle stick is centered. **This is the primary indoor flight mode.** | **Low** |
| **Position 3** | **Loiter** (if optical flow available) | Self-leveling + altitude hold + position hold. Drone holds its exact position in 3D space when all sticks are released. Requires optical flow sensor. | **Very Low** |
| **Position 4** | **Land** | Automated landing. Drone descends at a controlled rate and disarms on touchdown. Emergency use / end of flight. | **None** |

### AltHold: The Default Indoor Mode

For a pilot with no drone experience, **AltHold mode with the TF-Luna rangefinder** is the sweet spot:

- **Sticks released = drone hovers in place** (altitude-wise; it may drift laterally without optical flow, but slowly)
- **Roll/pitch sticks = gentle, rate-limited translation** — the drone tilts and moves, but self-levels when released
- **Throttle stick centered = maintain altitude.** Push up = climb, push down = descend, release = hold.
- **Yaw stick = rotate in place**

The drone will not flip, will not suddenly climb or descend, and will not accelerate uncontrollably. It behaves like a predictable, gentle hovercraft.

### Loiter: The "Zero Skill" Mode (with Optical Flow)

If an optical flow sensor is added (see Section 12), **Loiter mode** provides full 3D position hold:

- **All sticks released = drone holds its exact position** — no lateral drift, no altitude change
- **Stick input = controlled velocity in that direction**
- This is how commercial drones (DJI, etc.) behave by default — and it's achievable indoors with optical flow + rangefinder on ArduPilot

### Arming Safety

To prevent accidents:
- **Arm/disarm via a dedicated switch** on the Zorro (e.g., SB or SC switch → Channel 5)
- ArduPilot will refuse to arm if pre-arm checks fail (accelerometer not calibrated, rangefinder not detected, etc.)
- Configure `ARMING_CHECK` to enforce sensor health before arming

---

## 6. Control Chain: Zorro → Mesh → ArduPilot

### Step-by-Step Control Flow

#### 6.1 RadioMaster Zorro (Controller)

- The Zorro runs **EdgeTX firmware**
- Connected to the ground station Pi via **USB-C cable**
- EdgeTX is configured for **USB Joystick (HID) mode**: `System → Hardware → USB Mode → Joystick`
- When connected, the Zorro appears to the Pi as a standard Linux gamepad at `/dev/input/js0`
- All configured channels (sticks, switches, pots, sliders — up to 16) are exposed as HID axes/buttons
- Update rate: ~100 Hz over USB HID

**Channel mapping (typical Zorro Mode 2):**

| EdgeTX Channel | HID Axis | Function |
|---|---|---|
| CH1 | Axis 0 | Roll (Aileron) |
| CH2 | Axis 1 | Pitch (Elevator) |
| CH3 | Axis 2 | Throttle |
| CH4 | Axis 3 | Yaw (Rudder) |
| CH5 | Axis 4 / Button | Arm/Disarm switch |
| CH6 | Axis 5 / Button | Flight mode switch |
| CH7+ | Axes/Buttons | Additional functions as needed |

#### 6.2 Ground Station Pi (Mesh Ingress)

The ground station Pi is a node on the 802.11s mesh network. It runs **MAVProxy**, an existing, mature, open-source MAVLink ground station and router.

**MAVProxy:**
- Reads the Zorro's joystick input via its built-in `--joystick` module
- Maps joystick axes to RC channel values (1000–2000 µs range)
- Constructs **MAVLink `RC_CHANNELS_OVERRIDE` messages** containing the 16 channel values
- Sends these messages as **UDP packets** to the drone Pi's mesh IP address
- Simultaneously receives and displays telemetry from the drone
- Can forward MAVLink telemetry to additional consumers (ATAK, QGroundControl, etc.)

**Launch example:**
```
mavproxy.py --master=udpout:DRONE_MESH_IP:14550 --out=udp:ATAK_DEVICE_IP:14550 --joystick
```

This single command:
- Connects to the drone over UDP (via the mesh)
- Enables joystick input from the Zorro
- Forwards telemetry to the ATAK device

**Update rate:** MAVProxy sends RC_CHANNELS_OVERRIDE at the joystick polling rate, typically 50–100 Hz. Each message is ~50 bytes — negligible mesh bandwidth.

#### 6.3 802.11s Mesh Network (Transport)

The existing Pi-based 802.11s mesh with **babel routing** carries all traffic:

- **Control packets** (ground → drone): MAVLink RC_CHANNELS_OVERRIDE, ~50–100 packets/sec, ~50 bytes each
- **Telemetry packets** (drone → ground/ATAK): MAVLink telemetry messages, ~10–50 packets/sec, varying size
- **Total bandwidth:** < 100 Kbps — trivial for 802.11s
- **Unicast addressing:** each drone has a mesh IP, routed by babel. No broadcast/multicast needed.
- **Latency per hop:** ~3–5 ms. Indoor deployments typically 1–2 hops. Total mesh latency: ~5–10 ms.

#### 6.4 Drone Pi Zero 2 W (Mesh Node + Serial Bridge)

The Raspberry Pi Zero 2 W rides on the drone and serves as the bridge between the mesh network and the flight controller. It runs **`mavlink-router`**, an existing, lightweight MAVLink routing daemon.

**mavlink-router:**
- **Serial endpoint:** Connected to the flight controller's UART (TX, RX, GND). Sends/receives MAVLink frames over serial.
- **UDP endpoint:** Listens on the mesh interface for incoming MAVLink packets (control commands) and sends outgoing MAVLink packets (telemetry).
- Routes MAVLink messages bidirectionally between serial and UDP.
- No custom code required — configuration file only.

**mavlink-router config example:**
```
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

**Physical connection to FC:**
- Pi Zero 2 W UART TX → FC UART RX (designated MAVLink serial port)
- Pi Zero 2 W UART RX → FC UART TX
- Common GND
- Logic levels: both 3.3V (Pi and most modern FCs) — no level shifter needed

#### 6.5 ArduPilot Flight Controller

The flight controller runs **ArduPilot Copter** with the receiver type set to **MAVLink RC override:**

- RC input comes from `RC_CHANNELS_OVERRIDE` MAVLink messages arriving on the designated serial port
- ArduPilot processes the channel values identically to physical RC receiver input
- PID loops run at 2–8 kHz (gyro rate), motor outputs update accordingly
- Rangefinder provides altitude data for AltHold mode
- Failsafe triggers if RC_CHANNELS_OVERRIDE messages stop arriving (configurable timeout)

**Key ArduPilot Parameters for MAVLink RC Input:**

| Parameter | Value | Purpose |
|---|---|---|
| `SERIAL1_PROTOCOL` | 2 | MAVLink2 on the UART connected to the drone Pi |
| `SERIAL1_BAUD` | 921 | 921600 baud (fast, low latency) |
| `RC_OVERRIDE_TIME` | 3.0 | Timeout (seconds) — how long RC override values persist without new messages before reverting to failsafe |

---

## 7. Telemetry Chain: ArduPilot → Mesh → Ground Station / ATAK

Telemetry flows in the reverse direction through the same infrastructure:

1. **ArduPilot** automatically emits MAVLink telemetry messages on its serial port at configurable rates:
   - `HEARTBEAT` (1 Hz) — alive status, vehicle type, flight mode, arm state
   - `ATTITUDE` (10–50 Hz) — roll, pitch, yaw angles
   - `GLOBAL_POSITION_INT` (10 Hz) — latitude, longitude, altitude, heading
   - `SYS_STATUS` (2 Hz) — battery voltage, current, remaining capacity, sensor health
   - `VFR_HUD` (10 Hz) — airspeed, groundspeed, altitude, climb rate, throttle
   - `ALTITUDE` (10 Hz) — various altitude estimates (rangefinder, baro, terrain)
   - `RANGEFINDER` (10 Hz) — raw rangefinder distance and voltage
   - `GPS_RAW_INT` (2 Hz) — GPS status (will show no-fix indoors, that's fine)
   - `BATTERY_STATUS` (2 Hz) — detailed battery cell info

2. **mavlink-router** on the drone Pi reads these from the serial port and forwards them as UDP packets onto the mesh

3. **MAVProxy** on the ground Pi receives them, displays a console HUD, and optionally forwards to additional endpoints

4. **ATAK** receives the MAVLink stream and renders the drone on the map (see Section 8)

### Telemetry Rates (ArduPilot `SRn_*` Parameters)

These control how often ArduPilot sends each message group on the MAVLink serial port:

| Parameter | Value (Hz) | Messages |
|---|---|---|
| `SR1_POSITION` | 10 | GLOBAL_POSITION_INT, LOCAL_POSITION_NED |
| `SR1_EXTRA1` | 10 | ATTITUDE, SIMSTATE |
| `SR1_EXTRA2` | 10 | VFR_HUD |
| `SR1_EXTRA3` | 2 | BATTERY_STATUS, RANGEFINDER, etc. |
| `SR1_RAW_SENS` | 2 | RAW_IMU, SCALED_PRESSURE |
| `SR1_RC_CHAN` | 2 | RC_CHANNELS, SERVO_OUTPUT_RAW |
| `SR1_EXT_STAT` | 2 | SYS_STATUS, GPS_RAW_INT, MISSION_CURRENT |

Total telemetry bandwidth: roughly 10–30 Kbps. Well within mesh capacity.

---

## 8. ATAK Integration

### Overview

ATAK (Android Team Awareness Kit) is a situational awareness application used by military and first responders. The **ATAK UAS Plugin** (also known as the UAS Tool) adds drone monitoring and control capabilities to ATAK via MAVLink.

### Connection Architecture

```
ArduPilot FC
    ↓ MAVLink serial
Drone Pi (mavlink-router)
    ↓ MAVLink UDP (mesh)
Ground Pi (MAVProxy)
    ↓ MAVLink UDP forwarded to ATAK device IP
ATAK Android Device (on mesh or routed to mesh)
    └→ UAS Plugin receives MAVLink stream
```

MAVProxy's `--out=udp:ATAK_IP:14550` flag forwards all MAVLink traffic to the ATAK device. The ATAK device must be reachable from the mesh — either as a direct mesh participant (Wi-Fi) or via routing (e.g., the ATAK device is on a separate network segment that babel can reach).

### What ATAK Displays

With the UAS Plugin receiving MAVLink from the drone, ATAK will show:

- **Drone icon on the map** with real-time position (lat/lon from `GLOBAL_POSITION_INT`)
- **Heading/orientation** arrow
- **Altitude** readout (from rangefinder-fused estimate)
- **Battery status** (voltage, current, remaining %)
- **Flight mode** (AltHold, Loiter, Land, etc.)
- **Arm state** (armed/disarmed)
- **Link quality** indicators
- **Attitude** (roll/pitch/yaw) on a HUD display

### Indoor Positioning Consideration

**The challenge:** Without GPS, `GLOBAL_POSITION_INT` will contain zeros or the last known GPS position. ATAK needs lat/lon to place the drone on the map.

**Practical approaches:**

1. **Set a home position manually.** Before flying indoors, set ArduPilot's home position to the building's known GPS coordinates (via MAVLink `SET_HOME_POSITION` command or by briefly acquiring GPS fix before going indoors). The drone will appear on the ATAK map at or near the building. It won't track room-to-room movement, but it establishes SA — "there's a drone operating in this building."

2. **Use EKF origin.** ArduPilot can set an EKF origin (`EK3_SRC_OPTIONS`) at a known lat/lon without GPS. The drone's `LOCAL_POSITION_NED` offsets are then converted to global coordinates. With optical flow, these offsets are meaningful (meters from origin), and the drone's ATAK icon will move relative to the building. Accuracy depends on optical flow quality and drift over time.

3. **External positioning system.** For high-fidelity indoor tracking (beyond scope of initial design), systems like UWB beacons (Pozyx, Decawave) or motion capture (OptiTrack) can feed position to ArduPilot via MAVLink `VISION_POSITION_ESTIMATE`. This gives real indoor position on the ATAK map.

**Recommended initial approach:** Option 1 (manual home position). It's simple, requires no additional hardware, and gives ATAK enough info to show the drone on the map. Upgrade to Option 2 if optical flow is added.

### ATAK Commands to Drone (Bidirectional)

The UAS Plugin can also send commands back to the drone:

- **Arm / Disarm**
- **Change flight mode** (e.g., switch to Land)
- **Takeoff to altitude**
- **RTH (Return to Home)** — limited use indoors without GPS
- **Guided mode waypoints** — fly to a lat/lon (requires position estimate)

These commands flow back through the same MAVLink path in reverse: ATAK → UDP → mesh → drone Pi → serial → ArduPilot.

---

## 9. Software Stack Summary

### Drone Pi Zero 2 W

| Software | Purpose | Custom Code? |
|---|---|---|
| **Raspberry Pi OS Lite** | Base OS | No |
| **802.11s mesh + babel** | Mesh networking | Existing config |
| **mavlink-router** | Serial ↔ UDP MAVLink bridge | **No — config file only** |

**Total custom code on drone Pi: Zero.** Everything is existing, packaged software.

### Ground Station Pi

| Software | Purpose | Custom Code? |
|---|---|---|
| **Raspberry Pi OS** | Base OS | No |
| **802.11s mesh + babel** | Mesh networking | Existing config |
| **MAVProxy** | GCS, joystick input, MAVLink routing | **No — CLI flags only** |

**Total custom code on ground Pi: Near zero.** MAVProxy handles joystick→MAVLink and telemetry forwarding out of the box. At most, a small joystick mapping configuration file.

### ATAK Device

| Software | Purpose | Custom Code? |
|---|---|---|
| **ATAK** | Situational awareness | No |
| **ATAK UAS Plugin** | Drone integration via MAVLink | **No — plugin configuration only** |

### Optional: Custom Joystick Mapping Script

If MAVProxy's built-in joystick module doesn't map the Zorro's axes/buttons exactly as needed, a small Python script (~100–200 lines) using `pygame` or `python-evdev` + `pymavlink` can:
- Read the Zorro HID input
- Apply custom axis mapping, scaling, dead zones, expo curves
- Send `RC_CHANNELS_OVERRIDE` via pymavlink
- Run alongside or instead of MAVProxy

This is the only potentially custom software in the entire system, and it may not be needed at all.

---

## 10. Failsafe and Safety

### Loss of Control Link

If the drone stops receiving `RC_CHANNELS_OVERRIDE` messages (mesh failure, ground station crash, Pi reboot, etc.):

| Parameter | Value | Behavior |
|---|---|---|
| `RC_OVERRIDE_TIME` | 3.0 | After 3 seconds with no override messages, ArduPilot reverts to failsafe |
| `FS_THR_ENABLE` | 3 | Failsafe action: **Land** — the drone descends at a controlled rate and disarms on ground contact |
| `FS_THR_VALUE` | 975 | Throttle failsafe threshold (µs) |

**Why "Land" and not "RTH":** RTH requires GPS to navigate home. Indoors without GPS, RTH would be undefined/dangerous. Landing in place is the safest failsafe for indoor operations.

### Battery Failsafe

| Parameter | Value | Behavior |
|---|---|---|
| `BATT_LOW_VOLT` | 3.5 (per cell) | Low battery warning — GCS/ATAK alert |
| `BATT_CRT_VOLT` | 3.3 (per cell) | Critical battery — automatic Land |
| `BATT_FS_LOW_ACT` | 2 | Low battery action: Land |
| `BATT_FS_CRT_ACT` | 2 | Critical battery action: Land |

### GCS Failsafe (MAVLink Heartbeat)

ArduPilot can also monitor for loss of the GCS MAVLink heartbeat:

| Parameter | Value | Behavior |
|---|---|---|
| `FS_GCS_ENABLE` | 1 | Enabled — if GCS heartbeat lost, trigger failsafe |
| `FS_GCS_TIMEOUT` | 5 | Timeout in seconds |

This is a second layer of protection beyond RC override timeout.

### Indoor Fence (Virtual Boundary)

ArduPilot supports a **cylindrical altitude fence** — useful indoors to prevent the drone from climbing too high:

| Parameter | Value | Behavior |
|---|---|---|
| `FENCE_ENABLE` | 1 | Enable fence |
| `FENCE_TYPE` | 1 | Altitude fence only (no GPS-based radius fence indoors) |
| `FENCE_ALT_MAX` | 5 | Maximum altitude: 5 meters (adjust for ceiling height) |
| `FENCE_ACTION` | 1 | Action on breach: Land |

### Pre-Arm Checks

ArduPilot's pre-arm checks prevent arming if something is wrong:

- Accelerometer not calibrated → won't arm
- Rangefinder not detected → won't arm (if required)
- Battery voltage too low → won't arm
- IMU inconsistency → won't arm

This prevents an unskilled pilot from flying an unhealthy drone.

---

## 11. Latency Budget

| Segment | Estimated Latency |
|---|---|
| Zorro USB HID polling | 1–4 ms |
| Ground Pi: joystick read + MAVLink construction | 1–2 ms |
| 802.11s mesh (1 hop) | 3–5 ms |
| 802.11s mesh (2 hops) | 6–10 ms |
| Drone Pi: UDP receive + serial write | 1–2 ms |
| Serial UART transfer | 0.5–1 ms |
| ArduPilot: MAVLink parse + RC input processing | 0.5–1 ms |
| **Total (1 hop)** | **~7–15 ms** |
| **Total (2 hops)** | **~10–20 ms** |

**For comparison:**
- ELRS 500 Hz: ~2–5 ms
- ELRS 150 Hz: ~7–15 ms
- Standard RC (FrSky, Spektrum): ~15–25 ms
- Wi-Fi-based commercial drones (Tello, etc.): ~50–100 ms

Our mesh-based control latency is **comparable to standard RC systems** and well within the acceptable range for stabilized indoor flight. An unskilled pilot in AltHold mode will not perceive any lag.

---

## 12. Optical Flow for Position Hold — Matek 3901-L0X

**Status:** Recommended sensor selected. Provides full indoor 3D position hold (Loiter mode) when combined with TF-Luna rangefinder.

### What It Adds

An **optical flow sensor** is a small, downward-facing camera that tracks ground texture movement. Combined with the TF-Luna rangefinder, it gives ArduPilot an estimate of lateral velocity and position — enabling **Loiter mode (full 3D position hold) indoors without GPS.**

This is the difference between:
- **AltHold only:** Drone holds altitude but drifts laterally — pilot must correct
- **Loiter (with optical flow):** Drone holds exact position — pilot releases sticks, drone stays put

### Selected Hardware: Matek 3901-L0X

The **Matek 3901-L0X** is the easiest optical flow sensor to integrate with ArduPilot. It connects via **UART (serial)** and outputs standard MAVLink `OPTICAL_FLOW_RAD` messages natively — no SPI, no I2C, no custom drivers.

| Specification | Value |
|---|---|
| **Flow sensor** | PMW3901 (Pixart optical flow) |
| **Onboard rangefinder** | VL53L0X ToF (we ignore this — TF-Luna is our primary rangefinder) |
| **Interface** | **UART (serial)** — outputs MAVLink OPTICAL_FLOW_RAD messages natively |
| **Working altitude** | 0.3–3 m (best performance range with good lighting and textured ground) |
| **Weight** | ~3–4 g |
| **Size** | Small — fits under almost any frame |
| **Mounting** | Underside of drone, pointing straight down |
| **ArduPilot support** | Native — `FLOW_TYPE = 5` (MAVLink optical flow) |
| **Search term** | `Matek 3901-L0X optical flow sensor` |

### Why Matek 3901-L0X Is the Easiest Choice

1. **UART connection** — same type of wiring as the TF-Luna (TX/RX/GND/5V to a spare UART). No SPI bus configuration, no I2C address conflicts.
2. **Speaks MAVLink natively** — the onboard MCU converts raw PMW3901 data into standard MAVLink `OPTICAL_FLOW_RAD` messages over serial. ArduPilot reads these directly with zero additional configuration.
3. **Minimal ArduPilot config** — three parameters and it's working.
4. **Well documented** — widely used in the ArduPilot community with extensive setup guides.

### UART Allocation (3 required on FC)

| UART | Peripheral | Protocol |
|---|---|---|
| UART 1 | Pi Zero 2 W | MAVLink2 (control + telemetry) |
| UART 2 | TF-Luna | Rangefinder serial (Benewake) |
| UART 3 | Matek 3901-L0X | MAVLink optical flow |

**This is why an H743 flight controller is important** — H743 boards typically have 7–8 UARTs, so 3 is no problem. An F4 board with only 4–5 total UARTs would be tight.

### Limitations

- Requires some ground texture — doesn't work over perfectly featureless surfaces (plain white floor, still water)
- Performance degrades in very low light
- Drift accumulates over time (no absolute position reference) — but for short indoor flights this is manageable
- Works best below ~3 m altitude

### ArduPilot Configuration for Optical Flow

| Parameter | Value | Purpose |
|---|---|---|
| `FLOW_TYPE` | 5 | MAVLink optical flow (Matek 3901-L0X outputs this natively) |
| `SERIALn_PROTOCOL` | 18 | Optical flow on the UART wired to the 3901-L0X |
| `SERIALn_BAUD` | 115 | 115200 baud |
| `EK3_SRC1_VELXY` | 5 | Use optical flow for horizontal velocity estimation |
| `EK3_SRC1_POSXY` | 0 | No absolute horizontal position source (flow provides velocity only, EKF integrates to position) |

With optical flow active, **Loiter mode** becomes available and the drone will hold position indoors.

---

## 13. Hardware Bill of Materials

### Procurement Status

| Component | Part | Purpose | Status |
|---|---|---|---|
| **Flight Controller** | H743-based, 30.5×30.5mm, ArduPilot-compatible (see note below) | ArduPilot Copter, sensor interfaces | ⏳ Selecting — need 3+ free UARTs, standalone FC (not AIO) |
| **TF-Luna LiDAR** | Benewake TF-Luna | Altitude hold (rangefinder) | ✅ **Ordered** |
| **Optical Flow** | Matek 3901-L0X | Position hold (Loiter mode) | ⏳ Recommended — search: `Matek 3901-L0X optical flow sensor` |
| Frame | 3–5" quad frame (existing) | Airframe | ✅ Existing |
| Motors (×4) | (existing) | Propulsion | ✅ Existing |
| ESCs / PDB | (existing, separate from FC in stack) | Motor control / power distribution | ✅ Existing |
| Props | (existing) | Propulsion | ✅ Existing |
| Battery | 4S LiPo (existing) | Power | ✅ Existing |
| Pi Zero 2 W | Raspberry Pi Zero 2 W | Drone mesh node + MAVLink bridge | ⏳ Need to source |
| Pi power supply | 5V BEC (from drone battery) | Power the Pi on the drone | ⏳ Need to source |
| **RadioMaster Zorro** | (already owned) | Pilot controller (USB HID joystick) | ✅ Existing |
| **Ground Station Pi** | (already in mesh) | Mesh node + MAVProxy | ✅ Existing |
| **802.11s Mesh** | (existing Pi-based mesh with babel) | Communications backbone | ✅ Existing |

### Flight Controller Selection Note

The existing DAKEFPV F405 is **not ArduPilot-compatible**. A replacement H743 board is needed. Requirements:
- **MCU:** STM32H743 (preferred for EKF3, optical flow, sufficient flash/RAM)
- **Form factor:** 30.5×30.5mm mounting holes (matches existing frame/stack)
- **Type:** Standalone FC (not AIO) — existing ESC/PDB board stays in the stack
- **UARTs:** Minimum 3 free (Pi MAVLink, TF-Luna rangefinder, Matek 3901-L0X optical flow)
- **ArduPilot firmware target must exist** — verified list of compatible H743 boards:

```
Matek H743 SLIM V3 flight controller
DAKEFPV H743 flight controller
DAKEFPV H743 Pro flight controller
JHEMCU H743HD flight controller
Mamba H743 V4 flight controller
Flywoo H743 Pro flight controller
Foxeer H743 V1 flight controller
GEPRC Taker H743 flight controller
Blitz H743 Pro flight controller
BrotherHobby H743 flight controller
Spedix H743 flight controller
T-Motor H743 flight controller
SkySakura H743 flight controller
Aocoda-RC H743 Dual flight controller
```

**Pricing note (April 2026):** H743 flight controllers are currently running **~$100–$120** on AliExpress. Prices have roughly doubled from 2023–2024 levels due to supply chain issues.

---

## 14. Video Over Mesh — ATAK Integration

### Concept

Analog FPV cameras (standard CMOS, thermal/FLIR, night vision) output composite video. To get that onto the mesh and into ATAK, the video is **digitized on the drone Pi and streamed as IP video** over the mesh.

### Video Chain

```
Analog FPV Camera (any type — CMOS, thermal, night vision)
    ↓ Composite video (NTSC/PAL)
USB Video Capture Dongle (on drone Pi)
    ↓ Digitized video (USB UVC device)
Drone Pi Zero 2 W
    ↓ H.264 encode → RTSP stream
802.11s Mesh (babel-routed)
    ↓
ATAK / Ground Station / Any viewer on the mesh
```

### Key Points

- **Camera-agnostic:** Any analog FPV camera works — swap between a standard camera, thermal imager, or night vision without changing the software pipeline. They all output composite video.
- **USB capture dongle:** Cheap (~$10–15), tiny, lightweight USB stick that takes composite video in and presents a standard USB video device to the Pi. No special drivers.
- **RTSP stream:** The drone Pi runs a lightweight RTSP server. Any device on the mesh can connect to the stream URL to view video — ATAK, VLC, QGroundControl, etc.
- **ATAK integration:** The ATAK UAS Plugin supports video streams natively. ArduPilot advertises the video stream URL via MAVLink, and ATAK displays it as a picture-in-picture window on the map alongside drone telemetry. Alternatively, ATAK's standalone Video Plugin can be pointed at the RTSP URL manually.
- **No custom code:** The encode and RTSP server are existing packages running on the drone Pi.
- **Latency:** ~100–200 ms glass-to-glass (analog capture + encode + mesh + decode). Suitable for recon and situational awareness. Not suitable for aggressive FPV flying — but that's not the use case.
- **Bandwidth:** ~1–4 Mbps depending on resolution and bitrate. Fits comfortably alongside control/telemetry (<50 Kbps) on the 802.11s mesh.

### Hardware Addition

| Component | Purpose | Weight | Est. Cost |
|---|---|---|---|
| Analog FPV camera | Video source (existing or any standard FPV cam) | varies | varies |
| USB composite video capture dongle | Digitize analog video for the Pi | ~5 g | ~$10–15 |

### Future: Digital Camera Options

If higher quality or direct USB cameras are desired later (e.g., USB thermal modules like FLIR Lepton, Seek Thermal), they can connect directly to the Pi via USB without the capture dongle — the RTSP streaming pipeline remains the same.

---

## 15. Open Questions and Future Work

### Open Questions

- [ ] **Flight controller selection:** Which specific FC board? Must have ArduPilot Copter support, F7/H7 preferred, sufficient UARTs (at least 2 free: one for Pi MAVLink, one for TF-Luna). Need to verify specific board.
- [ ] **Drone Pi power:** USB from FC? Separate BEC from battery? Pi Zero 2 W draws ~350 mA at 5V — need a clean, reliable 5V source on the drone.
- [ ] **ATAK device connectivity:** Is the ATAK Android device directly on the 802.11s mesh, or on a separate network segment reachable via routing? This affects MAVLink endpoint configuration.
- [ ] **Video:** Is FPV video desired? If so, over the mesh (latency concerns) or via a separate analog/digital VTx? Not addressed in this initial design.
- [ ] **Multi-drone:** If multiple drones are planned, each needs a unique MAVLink system ID (`SYSID_THISMAV`). MAVProxy and ATAK both support multi-vehicle MAVLink.
- [ ] **Indoor testing plan:** Controlled test progression — bench test → tethered hover → free hover in large open room → confined space.

### Future Enhancements

- **Video over mesh:** Stream FPV video from a drone-mounted camera through the mesh to the ground station or ATAK. Latency-sensitive — may need dedicated bandwidth allocation or QoS.
- **Autonomous missions:** Upload waypoint missions via MAVLink from ATAK or QGroundControl. Requires reliable indoor position estimation (optical flow + rangefinder, or UWB beacons).
- **Multi-drone swarm:** Multiple drones on the mesh, each with unique IPs and MAVLink system IDs, all visible in ATAK simultaneously.
- **UWB indoor positioning:** Ultra-wideband beacons (Decawave/Qorvo DW1000) for centimeter-accurate indoor positioning, fed to ArduPilot via `VISION_POSITION_ESTIMATE`. Enables precise GPS-like behavior indoors.
- **Collision avoidance:** Forward-facing ToF or LiDAR sensors for obstacle detection. ArduPilot supports `OBSTACLE_DISTANCE` MAVLink messages for proximity-based avoidance.

---

## 16. Staged Build Plan

This section documents the phased approach to building and validating the system, starting with what can be tested now (mesh comms + controller) and progressing as hardware arrives.

### Phase 1 — Ground Station: Zorro USB HID Verification ✅

**Goal:** Confirm the RadioMaster Zorro is recognized as a USB HID joystick on the ground station Pi and all stick/switch channels are readable.

**Prerequisites:** Zorro with EdgeTX configured for USB Joystick mode, any mesh Pi.

**Steps:**

1. Plug Zorro into ground station Pi via USB-C
2. Verify USB device detection:
   ```bash
   lsusb | grep -i radio
   # Expected: ID 1209:4f54 Generic Radiomaster Zorro Joystick
   ```
3. Verify joystick device node exists:
   ```bash
   ls -la /dev/input/js0
   cat /proc/bus/input/devices | grep -A 5 "Zorro"
   # Expected: "OpenTX Radiomaster Zorro Joystick" with handlers event4 js0
   ```
4. Verify user is in `input` group (required to read the device without root):
   ```bash
   groups | grep input
   # If not present: sudo usermod -aG input $USER && reboot
   ```
5. Read initial axis/button state to confirm all channels come through

**Results (2026-04-29):**

| Item | Result |
|---|---|
| USB detection | ✅ `ID 1209:4f54 Generic Radiomaster Zorro Joystick` |
| Device node | ✅ `/dev/input/js0` → `event4` |
| Device name | ✅ `OpenTX Radiomaster Zorro Joystick` |
| User permissions | ✅ `natak` is in `input` group |
| Axes detected | 7 (4 sticks + 3 switches) |
| Buttons detected | 24 |

**Axis mapping (Mode 2 layout, sticks centered):**

| HID Axis | EdgeTX Channel | Function | Initial Value (centered) |
|---|---|---|---|
| Axis 0 | CH1 | Roll (Aileron) | 0 |
| Axis 1 | CH2 | Pitch (Elevator) | 0 |
| Axis 2 | CH3 | Throttle | 17300 (non-centering stick, resting position) |
| Axis 3 | CH4 | Yaw (Rudder) | 0 |
| Axis 4 | CH5 | Switch (likely SA or arm switch) | 32767 (max position) |
| Axis 5 | CH6 | Switch (likely flight mode) | 32767 (max position) |
| Axis 6 | CH7 | Switch | -32767 (min position) |

### Phase 2 — Ground Station: MAVProxy + Joystick Input

**Status:** ✅ Complete

**Goal:** Install MAVProxy with joystick support, verify it reads the Zorro and generates MAVLink `RC_CHANNELS_OVERRIDE` messages.

**Prerequisites:** Phase 1 complete, Python 3, pip.

**Steps:**

1. Install system dependencies (SDL2 libraries for pygame joystick support):
   ```bash
   sudo apt-get install -y libsdl2-dev libsdl2-image-dev libsdl2-mixer-dev libsdl2-ttf-dev python3-dev python3-full
   ```

2. Create a Python virtual environment (required on Debian Trixie / PEP 668):
   ```bash
   python3 -m venv /opt/nucleus/drone-venv
   /opt/nucleus/drone-venv/bin/pip install --upgrade pip
   ```

3. Install Python packages in the venv:
   ```bash
   /opt/nucleus/drone-venv/bin/pip install --no-cache-dir pymavlink MAVProxy pygame
   ```

4. Verify pygame sees the Zorro joystick:
   ```bash
   /opt/nucleus/drone-venv/bin/python3 -c "import pygame; pygame.init(); pygame.joystick.init(); js=pygame.joystick.Joystick(0); js.init(); print(js.get_name(), js.get_numaxes(), 'axes', js.get_numbuttons(), 'buttons')"
   ```

**Results (2026-04-29):**

| Item | Result |
|---|---|
| SDL2 libraries | ✅ Installed |
| Python venv | ✅ `/opt/nucleus/drone-venv` (Python 3.13.5) |
| pymavlink | ✅ 2.4.49 |
| MAVProxy | ✅ 1.8.74 |
| pygame | ✅ 2.6.1 (SDL 2.28.4) |
| pygame sees Zorro | ✅ "OpenTX Radiomaster Zorro Joystick" — 7 axes, 24 buttons |

**Note:** Debian Trixie enforces PEP 668 (externally-managed-environment), so all drone Python packages must be installed in the venv at `/opt/nucleus/drone-venv`, not system-wide. All scripts use `/opt/nucleus/drone-venv/bin/python3` to run.

**Note:** The 6.7G SD card was at 100% capacity during install. Ran `sudo apt-get clean` and `pip cache purge` to free ~500MB before packages would install. Keep an eye on disk space.

### Phase 3 — Local Loopback: End-to-End MAVLink Validation ✅

**Status:** ✅ Complete

**Goal:** Prove the full MAVLink pipeline on a single machine — Zorro stick input is read, converted to `RC_CHANNELS_OVERRIDE`, sent over UDP, and received by a simulated drone.

**Prerequisites:** Phase 2 complete.

**Scripts created:**

- `/opt/nucleus/drone/drone_sim.py` — Simulated ArduPilot drone. Listens on UDP 14550, prints received RC channel values, sends back HEARTBEAT (1Hz), ATTITUDE (10Hz), SYS_STATUS (2Hz).
- `/opt/nucleus/drone/zorro_mavlink_sender.py` — Reads Zorro sticks via pygame, converts to RC µs values (1000–2000), sends `RC_CHANNELS_OVERRIDE` at 50 Hz over UDP.
- `docs/drone/test_zorro_input.py` — Interactive joystick test (live axis display with visual bars).

**Steps:**

1. Terminal 1 — start the simulated drone:
   ```bash
   /opt/nucleus/drone-venv/bin/python3 /opt/nucleus/drone/drone_sim.py
   ```

2. Terminal 2 — start the Zorro sender:
   ```bash
   /opt/nucleus/drone-venv/bin/python3 /opt/nucleus/drone/zorro_mavlink_sender.py
   ```

3. Move sticks on the Zorro. Verify:
   - Terminal 2 (sender) shows TX with changing Roll/Pitch/Throttle/Yaw values
   - Terminal 1 (drone_sim) shows matching RC channel values received
   - Ctrl+C to stop each

4. For cross-mesh testing, the sender accepts a `--target` flag:
   ```bash
   /opt/nucleus/drone-venv/bin/python3 /opt/nucleus/drone/zorro_mavlink_sender.py --target DRONE_IP:14550
   ```

**Results (2026-04-29):**

| Item | Result |
|---|---|
| drone_sim.py starts and sends heartbeats | ✅ |
| zorro_mavlink_sender.py reads Zorro sticks | ✅ |
| RC_CHANNELS_OVERRIDE sent over UDP | ✅ |
| drone_sim.py receives and displays RC channels | ✅ |
| All 4 main sticks (Roll/Pitch/Throttle/Yaw) | ✅ Captured and changing |
| Switches (CH5-CH7 as axes) | ✅ Captured |
| Some switches not captured | ⚠️ Some Zorro switches are mapped as HID buttons (not axes) — not yet sent as RC channels. Can be added later in EdgeTX config or sender script if needed. |

### Phase 4 — Cross-Mesh: Zorro → Mesh → Simulated Drone

**Status:** ⏳ Pending (waiting for drone Pi IP assignment)

**Goal:** Run the simulated drone on a second mesh Pi, proving MAVLink control and telemetry traverse the 802.11s mesh network.

**Prerequisites:** Phase 3 complete, second mesh Pi with Python available.

**Steps:**

1. Deploy `drone_sim.py` to the second mesh Pi
2. Run it listening on `0.0.0.0:14550`
3. On the ground station Pi, run MAVProxy pointed at the drone Pi's mesh IP:
   ```bash
   mavproxy.py --master=udpout:DRONE_MESH_IP:14550 --joystick
   ```
4. Verify:
   - RC override messages arrive on the drone Pi across the mesh
   - Telemetry heartbeats return to the ground station
   - Measure round-trip latency (target: <20 ms for 1–2 hops)

**Results:** *(pending)*

### Phase 5 — ATAK Integration Test

**Status:** ⏳ Pending

**Goal:** Forward MAVLink telemetry from MAVProxy to an ATAK device and verify the drone appears on the ATAK map.

**Steps:**

1. Add ATAK forwarding to MAVProxy:
   ```bash
   mavproxy.py --master=udpout:DRONE_MESH_IP:14550 --out=udp:ATAK_IP:14550 --joystick
   ```
2. Configure ATAK UAS Plugin to listen on UDP port 14550
3. Set manual home position via MAVProxy (`wp sethome ...`) so ATAK has coordinates
4. Verify drone icon appears on ATAK map with telemetry overlay

**Results:** *(pending)*

### Phase 6 — Hardware Integration (when drone parts arrive)

**Status:** ⏳ Waiting for hardware

**Goal:** Replace the simulated drone with real hardware.

**Steps:**

1. Flash ArduPilot Copter on the H743 flight controller
2. Set up Pi Zero 2 W with mesh + mavlink-router
3. Wire Pi UART to FC UART, verify serial MAVLink
4. Connect TF-Luna rangefinder, verify altitude readings
5. Bench test: MAVProxy → mesh → Pi Zero → FC (props off, verify RC channels arrive)
6. First tethered hover in AltHold mode
7. Tune PIDs, validate failsafes
8. Free hover in large open room

### Phase 7 — Optional Enhancements

- **Optical flow (Matek 3901-L0X):** Add position hold (Loiter mode)
- **Video over mesh:** Analog camera → USB capture → RTSP stream
- **Multi-drone support:** Unique MAVLink system IDs, multi-vehicle ATAK

---

## 17. Summary

This system replaces the traditional RC radio link (ELRS/FrSky/etc.) with the existing 802.11s mesh network, enabling:

1. **Mesh-based drone control** using a familiar RC controller (Zorro) via USB joystick
2. **Stable indoor flight** for unskilled pilots via rangefinder altitude hold (TF-Luna) and self-leveling modes
3. **Native MAVLink end-to-end** — no protocol translation, using ArduPilot + existing tools (MAVProxy, mavlink-router)
4. **ATAK integration** for real-time situational awareness of the drone on a shared map
5. **Minimal custom software** — nearly the entire stack is existing, open-source, and maintained
6. **Mesh-inherent benefits** — range extension via relay nodes, resilient routing via babel, shared infrastructure with other mesh services

The key insight is that ArduPilot's native MAVLink support, combined with existing tools like MAVProxy and mavlink-router, allows us to build this entire system with **virtually no custom code** — just configuration.
