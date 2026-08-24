#!/usr/bin/env python3
"""
fc-link-check.py — verify the Pi <-> flight controller UART link.

Read-only diagnostic. Changes nothing; safe to run at any time.

    python3 /opt/nucleus/drone/fc-link-check.py
    python3 /opt/nucleus/drone/fc-link-check.py --port /dev/ttyAMA0 --baud 921600

Checks, in order:
  1. enable_uart=1 and dtoverlay=disable-bt in the boot config
  2. No serial console left in cmdline.txt
  3. Serial getty units are not running on the FC port
  4. Bluetooth is not bound to the PL011
  5. The port device exists, and the user can open it
  6. Nothing else already holds the port (mavlink-router in particular)
  7. Raw bytes arrive, and MAVLink2 framing (0xFD start byte) is present
  8. A HEARTBEAT decodes, reporting autopilot type, sysid and firmware version

Wiring assumed (see docs/drone/drone-hardware.md):
    Pi pin 8  GPIO14 TXD -> FC RX2
    Pi pin 10 GPIO15 RXD -> FC TX2
    Pi pin 6  GND        -> FC GND
FC side is USART2 = ArduPilot SERIAL3, SERIAL3_PROTOCOL=2, SERIAL3_BAUD=921.
"""

import argparse
import glob
import os
import subprocess
import sys

DEFAULT_PORT = "/dev/ttyAMA0"
DEFAULT_BAUD = 921600
MESH_CONF = "/etc/nucleus/mesh.conf"

results = []


def record(name, ok, detail=""):
    """Store a check result and print it as it happens."""
    tag = "PASS" if ok else "FAIL"
    results.append((name, ok, detail))
    print(f"  [{tag}] {name}")
    if detail:
        for line in detail.splitlines():
            print(f"         {line}")
    return ok


def note(name, detail=""):
    """Informational line that is not pass/fail."""
    print(f"  [info] {name}")
    if detail:
        for line in detail.splitlines():
            print(f"         {line}")


def read_mesh_conf():
    """Pull MAVLINK_SERIAL / MAVLINK_BAUD out of mesh.conf if present."""
    port, baud = None, None
    try:
        with open(MESH_CONF) as fh:
            for line in fh:
                line = line.strip()
                if line.startswith("MAVLINK_SERIAL="):
                    port = line.split("=", 1)[1].strip().strip('"')
                elif line.startswith("MAVLINK_BAUD="):
                    baud = line.split("=", 1)[1].strip().strip('"')
    except OSError:
        pass
    return port, baud


def boot_file(name):
    for path in (f"/boot/firmware/{name}", f"/boot/{name}"):
        if os.path.isfile(path):
            return path
    return None


def check_boot_config():
    path = boot_file("config.txt")
    if not path:
        record("boot config found", False,
               "neither /boot/firmware/config.txt nor /boot/config.txt exists")
        return
    with open(path) as fh:
        lines = [ln.strip() for ln in fh]
    record("enable_uart=1 in " + path, "enable_uart=1" in lines)
    has_bt = "dtoverlay=disable-bt" in lines
    record(
        "dtoverlay=disable-bt in " + path,
        has_bt,
        "" if has_bt else
        "Without this the Bluetooth controller keeps the PL011 UART and\n"
        "/dev/ttyAMA0 never appears; GPIO14/15 fall back to the mini-UART.",
    )


def check_cmdline():
    path = boot_file("cmdline.txt")
    if not path:
        record("boot cmdline found", False, "cmdline.txt not located")
        return
    with open(path) as fh:
        cmdline = fh.read()
    consoles = [tok for tok in cmdline.split()
                if tok.startswith("console=") and "tty1" not in tok]
    record(
        "no serial console in " + path,
        not consoles,
        "" if not consoles else
        f"found {' '.join(consoles)}\n"
        "The kernel prints boot messages onto GPIO14 into the FC RX pin.",
    )


def check_getty(port):
    """A login prompt on the FC port will hold it open against mavlink-router."""
    dev = os.path.basename(port)
    unit = f"serial-getty@{dev}.service"
    try:
        out = subprocess.run(["systemctl", "is-active", unit],
                             capture_output=True, text=True).stdout.strip()
    except OSError:
        out = "unknown"
    record(f"{unit} not running", out != "active",
           "" if out != "active" else "A login prompt owns the port.")


def check_bluetooth():
    """hci_uart_bcm bound to a serial device means Bluetooth still holds the PL011."""
    holders = []
    for uevent in glob.glob("/sys/bus/serial/devices/*/uevent"):
        try:
            with open(uevent) as fh:
                if "hci_uart" in fh.read():
                    holders.append(os.path.basename(os.path.dirname(uevent)))
        except OSError:
            continue
    record(
        "Bluetooth not bound to the PL011 UART",
        not holders,
        "" if not holders else
        f"hci_uart driver is bound to: {', '.join(holders)}\n"
        "Apply dtoverlay=disable-bt and reboot.",
    )


def check_device(port):
    if not os.path.exists(port):
        alt = "/dev/ttyS0" if port != "/dev/ttyS0" else "/dev/ttyAMA0"
        extra = f"{alt} does exist - the UARTs are swapped." if os.path.exists(alt) else ""
        record(f"{port} exists", False, extra)
        return False

    target = os.path.realpath(port)
    st = os.stat(port)
    record(f"{port} exists", True,
           f"resolves to {target}, mode {oct(st.st_mode & 0o777)}")

    if target.endswith("ttyS0"):
        note("this is the mini-UART",
             "Its baud rate follows the VPU core clock and is not reliable\n"
             "at 921600. Use the PL011 (/dev/ttyAMA0) via dtoverlay=disable-bt.")

    can_open = os.access(port, os.R_OK | os.W_OK)
    record("current user can open the port", can_open,
           "" if can_open else
           "Add the user to the dialout group: sudo usermod -aG dialout $USER")
    return True


def check_holder(port):
    """fuser tells us whether another process already owns the port."""
    try:
        proc = subprocess.run(["fuser", port], capture_output=True, text=True)
        pids = proc.stdout.split()
    except FileNotFoundError:
        note("fuser not installed, skipping port-holder check")
        return True
    if not pids:
        record(f"nothing else holds {port}", True)
        return True

    detail = []
    for pid in pids:
        try:
            with open(f"/proc/{pid}/comm") as fh:
                detail.append(f"pid {pid} = {fh.read().strip()}")
        except OSError:
            detail.append(f"pid {pid}")
    record(f"nothing else holds {port}", False,
           "\n".join(detail) +
           "\nIf this is mavlink-router it owns the port and nothing else\n"
           "can read it:  sudo systemctl stop mavlink-router")
    return False


def check_raw_bytes(port, baud, seconds):
    """Read raw bytes and look for the MAVLink2 start-of-frame byte 0xFD."""
    try:
        import serial
    except ImportError:
        note("pyserial not installed, skipping raw byte check",
             "sudo pip3 install --break-system-packages pyserial")
        return None

    import time
    try:
        with serial.Serial(port, baud, timeout=0.2) as ser:
            ser.reset_input_buffer()
            data = bytearray()
            deadline = time.time() + seconds
            while time.time() < deadline:
                chunk = ser.read(4096)
                if chunk:
                    data.extend(chunk)
    except serial.SerialException as exc:
        record(f"opened {port} at {baud}", False, str(exc))
        return None

    if not data:
        record(f"bytes received on {port} at {baud}", False,
               "Nothing arrived at all. See the causes listed below.")
        return data

    v2 = data.count(0xFD)
    v1 = data.count(0xFE)
    record(f"bytes received on {port} at {baud}", True,
           f"{len(data)} bytes in {seconds}s")
    record("MAVLink2 framing (0xFD) present", v2 > 0,
           f"0xFD count {v2}, 0xFE (MAVLink1) count {v1}\n"
           f"first bytes: {data[:16].hex(' ')}" +
           ("" if v2 else
            "\nBytes are arriving but no MAVLink2 frames. Either the baud rate\n"
            "is wrong (garbage bytes), or SERIAL3_PROTOCOL is not 2 on the FC."))
    return data


def check_heartbeat(port, baud, seconds):
    """Decode a HEARTBEAT and report autopilot type, sysid and firmware version."""
    try:
        from pymavlink import mavutil
    except ImportError:
        note("pymavlink not installed, skipping HEARTBEAT decode",
             "sudo pip3 install --break-system-packages pymavlink")
        return

    try:
        conn = mavutil.mavlink_connection(port, baud=baud)
    except Exception as exc:                   # noqa: BLE001 - report any open failure
        record("HEARTBEAT decoded", False, f"could not open {port}: {exc}")
        return

    hb = conn.wait_heartbeat(timeout=seconds)
    if hb is None:
        record("HEARTBEAT decoded", False, f"no HEARTBEAT within {seconds}s")
        conn.close()
        return

    ap = mavutil.mavlink.enums["MAV_AUTOPILOT"].get(hb.autopilot)
    ty = mavutil.mavlink.enums["MAV_TYPE"].get(hb.type)
    detail = [
        f"sysid {conn.target_system}, compid {conn.target_component}",
        f"autopilot {hb.autopilot} ({ap.name if ap else 'unknown'})",
        f"vehicle type {hb.type} ({ty.name if ty else 'unknown'})",
        f"mavlink version {hb.mavlink_version}",
    ]

    # AUTOPILOT_VERSION carries the firmware revision; ask for it explicitly.
    conn.mav.command_long_send(
        conn.target_system, conn.target_component,
        mavutil.mavlink.MAV_CMD_REQUEST_MESSAGE, 0,
        mavutil.mavlink.MAVLINK_MSG_ID_AUTOPILOT_VERSION, 0, 0, 0, 0, 0, 0)
    ver = conn.recv_match(type="AUTOPILOT_VERSION", blocking=True, timeout=3)
    if ver is not None:
        raw = ver.flight_sw_version
        detail.append(
            f"firmware {(raw >> 24) & 0xFF}.{(raw >> 16) & 0xFF}.{(raw >> 8) & 0xFF}")
    else:
        detail.append("firmware version not reported (AUTOPILOT_VERSION timeout)")

    record("HEARTBEAT decoded", True, "\n".join(detail))
    conn.close()


def print_causes():
    """Printed only when no data arrived, to narrow down the cause."""
    print("""
No data arrived from the flight controller. Likely causes, in the order
they are worth checking:

  1. UART still owned by Bluetooth
     /dev/ttyAMA0 missing, or hci_uart bound to the PL011.
     Fix: dtoverlay=disable-bt in config.txt, then reboot.

  2. Port held by another process
     mavlink-router or a serial login prompt already has it open.
     Fix: sudo systemctl stop mavlink-router
          sudo systemctl disable --now serial-getty@ttyAMA0

  3. TX/RX swapped
     Pi pin 8 (GPIO14 TXD) must go to FC RX2, and
     Pi pin 10 (GPIO15 RXD) must go to FC TX2. Grounds must be tied.
     Symptom: absolutely no bytes, ever, at any baud rate.

  4. Wrong baud rate
     Symptom: bytes arrive but are garbage with no 0xFD frames.
     Re-run with --baud 115200 and --baud 57600 to test.

  5. SERIAL3 not set to MAVLink2 on the FC
     Check SERIAL3_PROTOCOL=2 and SERIAL3_BAUD=921 in the ground station.
     Symptom: no bytes, or bytes that never form MAVLink frames.
     Note the FC must be powered, over USB or from the battery.
""")


def main():
    parser = argparse.ArgumentParser(
        description="Verify the Pi <-> flight controller UART link (read-only).")
    parser.add_argument("--port",
                        help=f"serial device (default from mesh.conf, else {DEFAULT_PORT})")
    parser.add_argument("--baud", type=int,
                        help=f"baud rate (default from mesh.conf, else {DEFAULT_BAUD})")
    parser.add_argument("--seconds", type=float, default=5.0,
                        help="listen window in seconds (default 5)")
    args = parser.parse_args()

    conf_port, conf_baud = read_mesh_conf()
    port = args.port or conf_port or DEFAULT_PORT
    baud = args.baud or (int(conf_baud) if conf_baud and conf_baud.isdigit()
                         else DEFAULT_BAUD)

    print("=" * 58)
    print("  Nucleus drone - FC UART link check")
    print("=" * 58)
    print(f"  port {port}   baud {baud}   window {args.seconds}s")
    if not conf_port:
        print(f"  (MAVLINK_SERIAL not set in {MESH_CONF}, using default)")
    print("")

    print("Boot configuration")
    check_boot_config()
    check_cmdline()
    print("")

    print("Port ownership")
    check_bluetooth()
    check_getty(port)
    print("")

    print("Device")
    exists = check_device(port)

    data = None
    if exists and check_holder(port):
        print("")
        print("Link traffic")
        data = check_raw_bytes(port, baud, args.seconds)
        check_heartbeat(port, baud, args.seconds)

    print("")
    print("=" * 58)
    failed = [n for n, ok, _ in results if not ok]
    if failed:
        print(f"  {len(failed)} check(s) FAILED - link is DOWN")
        print("=" * 58)
        for name in failed:
            print(f"    - {name}")
        if not data:
            print_causes()
        sys.exit(1)

    print("  All checks passed - link is UP")
    print("=" * 58)
    sys.exit(0)


if __name__ == "__main__":
    main()

