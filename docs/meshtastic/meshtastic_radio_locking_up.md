# Meshtastic Radio Lockup on Boot — Node 9

**Date:** 2026-03-29  
**Affected:** Node 9 (0009-nucleus)  
**Not affected:** Node 8 (0008-nucleus), Node 10 (0010-nucleus)  
**Status:** Workaround found, root cause still unknown

---

## Problem

Node 9's Meshtastic radio (RAK4631 / nRF52840) locks up during every boot such that **neither serial nor Bluetooth** can communicate with it. The radio is completely unresponsive until a physical USB unplug/replug or pressing the reset button on the radio.

Nodes 8 and 10 have no such issue with the exact same software and identical radio hardware.

Before Nucleus OS was installed on the Pi, the Meshtastic radio did not lock up. The problem began after Nucleus OS was deployed.

---

## Environment

- All nodes: Raspberry Pi 4, RAK4631 Meshtastic radios (USB CDC-ACM, vendor 239a:8029)
- All nodes: Kernel 6.12.47+rpt-rpi-v8
- Node 8: Debian Bookworm base image
- Nodes 9 and 10: Debian Trixie base image
- Identical config.txt, cmdline.txt, kernel modules, USB topology across all nodes
- Radio enumerates on USB bus 1-1.4 as "WisCore RAK4631 Board" by RAKwireless

---

## Symptoms After Boot (Node 9)

- `/dev/ttyACM0` exists with proper permissions
- USB device properly enumerated (visible in lsusb, sysfs shows manufacturer/product)
- **No process holds the serial port** (fuser shows empty)
- `cat /dev/ttyACM0` times out — radio firmware is frozen
- Bluetooth on the radio is also unresponsive
- Physical USB unplug/replug or reset button on the radio restores normal operation

---

## What Was Investigated

### Nucleus OS Software
- **mesh-start.sh** — Only configures WiFi mesh (wlan1), does not touch serial or Meshtastic
- **mesh-web.service / app.py** — Flask web app imports MeshtasticManager but does NOT auto-connect to serial at boot. Serial connection only happens on explicit API call to `/api/meshtastic/connect`
- **meshtastic_manager.py** — Creates UDP listener on init if enabled, but serial connection is only opened in `connect()` method, never automatically
- **rnsd.service / Reticulum config** — KISSInterface is disabled and pointed at `/dev/rfcomm0` (not ttyACM0). AutoInterface uses wlan1 only
- **No cron jobs, shell profiles, or startup scripts** reference meshtastic or serial ports

### Udev Rules
- `60-meshtastic.rules` is deployed identically on all nodes — sets `ID_MM_DEVICE_IGNORE=1` and `MTP_NO_PROBE=1` for vendor 239a:8029
- Boot logs confirm mtp-probe only checks device 1-1.2 (the WiFi adapter), NOT the Meshtastic radio at 1-1.4
- Rule content verified identical between nodes 9 and 10

### Things Tried That DID NOT Fix the Problem

1. **Disabled ModemManager** — Was enabled/active on node 9 but disabled on node 8. Disabling it on node 9 made no difference. Node 10 runs ModemManager active and works fine.

2. **cloud-init** — Present on node 9, not on node 8. But also present on node 10 which works fine. Not the cause.

3. **Removed meshtastic Python package** — Manually removed meshtastic pip package and CLI tools. No difference. (Package was reinstalled after testing.)

4. **Disabled ALL Nucleus services** — Disabled mesh-web, mesh-start, rnsd, brlan-setup, hostapd, babeld, smcroute, smcroute-helper. Radio STILL locked up on reboot. This proves the problem is not any Nucleus service.

5. **Software USB reset attempts** — Tried `authorized` sysfs toggle, usb driver unbind/rebind, and `usbreset` command. None of these recover the radio — the nRF52840 firmware is hard-crashed and only responds to a real power cycle.

### Comparison: Node 9 vs Node 10 (both Trixie, both work except node 9)

- config.txt: Identical
- cmdline.txt: Identical (except PARTUUID)
- Kernel version: Identical (6.12.47+rpt-rpi-v8)
- Kernel modules: Identical set loaded
- USB topology: Identical (hub/4p → mt76x0u on port 2, cdc_acm on port 4)
- Installed packages: 673 (node 9) vs 679 (node 10) — node 10 has MORE packages
- udev rules: Same set in /etc/udev/rules.d/ and /usr/lib/udev/rules.d/
- Reticulum config: Identical (KISSInterface disabled)

---

## Working Workaround

A USB hub power cycle using `uhubctl` recovers the radio after boot:

**Required package:**
```
sudo apt install uhubctl
```

**Command to recover the radio:**
```
sudo uhubctl -a off -l 1-1
sleep 3
sudo uhubctl -a on -l 1-1
```

This power-cycles the entire USB hub (hub 1-1), which includes both the Meshtastic radio (port 4) and the WiFi mesh radio mt76x0u (port 2). **Impact on the WiFi mesh radio needs to be tested before this can be used as a boot-time workaround.**

---

## Remaining Questions

1. **Why only node 9?** — All software, configs, kernel, and modules are identical to node 10 which works fine. The problem persists across different Pi hardware and different radios. Something about node 9's SD card image triggers this, but we cannot identify what.

2. **What is actually crashing the radio?** — The nRF52840 TinyUSB firmware crashes during early USB enumeration. No process is holding the port afterward. The crash happens before any userspace service starts (proven by disabling all services). This suggests something at the kernel/udev/firmware level during USB initialization.

3. **Will the uhubctl power cycle disrupt the WiFi mesh radio?** — The mt76x0u WiFi adapter is on the same USB hub. Power-cycling the hub will reset it too. Need to test whether it re-enumerates cleanly and whether the mesh network recovers.

4. **Could this be a Pi firmware/bootloader issue?** — The XHCI USB controller initialization happens in the Pi's bootloader before Linux starts. If this specific Pi's EEPROM firmware behaves slightly differently during USB power-on sequencing, it could crash the RAK4631. However, the user reports trying a different Pi body.

---

## Implemented Fix — Boot-time USB Power Cycle + Side Effects

**Date:** 2026-03-29

The `uhubctl` workaround was integrated into `mesh-start.sh` as a boot-time fix. This resolved the Meshtastic radio lockup but introduced two side effects that required additional fixes.

### Change 1: USB Hub Power Cycle in mesh-start.sh

The power cycle block was added to the top of `mesh-start.sh`, before any WiFi mesh configuration. Since the WiFi adapter (mt76x0u) is on the same USB hub, it gets reset too — but because the mesh hasn't been configured yet, no state is lost. The adapter re-enumerates cleanly and is configured fresh afterward.

**Answer to Question 3:** The WiFi mesh radio re-enumerates cleanly after the hub power cycle. The mesh network configures normally since the power cycle runs before any `iw`/`wpa_supplicant` commands.

### Side Effect 1: wlan1 Not Registered as Multicast VIF

**Problem:** After the USB power cycle, wlan1 comes back in `NO-CARRIER` / `DORMANT` state. The `smcroute.service` starts independently at boot and tries to register wlan1 as a kernel multicast VIF. The kernel rejects it because of the NO-CARRIER state. Result: wlan1 is permanently absent from the multicast routing table (`/proc/net/ip_mr_vif`), and ATAK multicast (239.2.3.1 CoT, 224.10.10.1 discovery) cannot cross between br-lan and wlan1. ATAK devices on this node have zero connectivity to ATAK devices on other mesh nodes.

**Diagnosis:** `cat /proc/sys/net/ipv4/conf/wlan1/mc_forwarding` returned `0` (should be `1`). The kernel MFC cache showed ATAK multicast arriving from the local ATAK device but being forwarded to an empty output interface list.

**Fix:** Added `systemctl restart smcroute` to the end of `mesh-start.sh`, after the mesh is fully established and wlan1 has active peer links. This re-registers wlan1 as a multicast VIF when it's in a working state.

### Side Effect 2: Multicast Echo Storm with 3+ Nodes

**Problem:** With wlan1 now properly registered as a multicast VIF on all 3 nodes, the smcroute echo routing (`mroute from wlan1 group 239.2.3.1 to wlan1 br-lan` — note `wlan1` in the output) created a sustained multicast echo storm. Each node echoes received multicast back to the mesh for multi-hop propagation, but with 3 nodes the echo bounces between the two non-originating nodes until TTL expires. With the default TTL of 64, this meant ~32 round trips per packet.

This was not a problem before because node 9's wlan1 was silently excluded from multicast routing (VIF not registered). With only 2 nodes in the echo loop, the originator's RPF (Reverse Path Forwarding) check killed echoed packets on arrival. With 3 nodes, the intermediary has matching RPF and keeps forwarding.

**Symptoms:** 709K+ dropped multicast packets on wlan1 TX queue, 2000+ packets queued, severe messaging lag in ATAK.

**Fix:** Added configurable `MESH_MCAST_TTL` to `mesh.conf` (default: 8, giving 4-hop reach). An iptables mangle rule in `mesh-start.sh` caps the TTL on ATAK multicast entering the mesh from br-lan:

```bash
iptables -t mangle -A PREROUTING -i br-lan -d 239.2.3.1/32 -j TTL --ttl-set $MESH_MCAST_TTL
iptables -t mangle -A PREROUTING -i br-lan -d 224.10.10.1/32 -j TTL --ttl-set $MESH_MCAST_TTL
```

Each mesh hop costs 2 TTL (one for forward, one for echo), so `TTL ÷ 2 = max hops`. TTL=8 supports 4-hop networks. This rule must be deployed on ALL mesh nodes.

### Side Effect 3: Wrong phy for RTS/CTS

**Problem:** The RTS/CTS threshold command was hardcoded as `iw phy phy1 set rts ...`. After the USB power cycle, the WiFi adapter re-enumerates on `phy2` instead of `phy1`, causing the command to fail with "No such file or directory."

**Fix:** Dynamic phy detection:
```bash
MESH_PHY=$(iw dev wlan1 info | grep wiphy | awk '{print "phy"$2}')
iw phy $MESH_PHY set rts $MESH_RTS_THRESHOLD
```

### Summary of All Changes

| File | Change | Purpose |
|------|--------|---------|
| `mesh-start.sh` | USB hub power cycle block | Recover locked Meshtastic radio |
| `mesh-start.sh` | `systemctl restart smcroute` | Register wlan1 as multicast VIF |
| `mesh-start.sh` | TTL mangle rules using `$MESH_MCAST_TTL` | Prevent echo storms with 3+ nodes |
| `mesh-start.sh` | Dynamic phy detection for RTS/CTS | Handle phy number change after USB reset |
| `mesh.conf` | `MESH_MCAST_TTL=8` | Configurable multicast hop limit (4 hops) |
| `install-packages.sh` | Added `uhubctl` | Ensure USB power cycle tool is available |

---

## 2026-06-17 — Fleet-wide Serial Timeout, Recovered by Clean USB Power Cycle

**Affected:** Nodes 35, 36, 37 (3 of 4)
**Not affected:** Node 34
**Status:** Root cause confirmed (radio firmware boot lockup); boot-time recovery
reworked because the previous implementation made it worse.

### Symptom

On 3 of 4 identically-configured nodes the ATAK CoT bridge would not start.
`cot-bridge.service` crash-looped with:

```
Opening SerialInterface(devPath=None)...
Radio connection lost!
Failed to open serial interface: Timed out waiting for connection completion
cot-bridge.service: Failed with result 'exit-code'.
```

The web API reported `service_active: true`, `radio_detected: true` on all three
— i.e. `/dev/ttyACM0` existed — but the bridge could never complete the serial
handshake. Node 34 came up clean and bridged normally.

### What did NOT fix it

All of these were tried multiple times and **failed**:

- Full node reboots (including via power disconnection of the Pi)
- Physically unplugging and replugging the **radio** USB
- Pressing the **reset** button on the RAK4631
- Setting `USB_HUB_POWER_CYCLE` `false` → `true` and rebooting

### What DID fix it

A single clean USB **hub** power cycle, run manually on a settled system:

```
sudo uhubctl -a cycle -l 1-1
```

This recovered every affected node on the first try. After it, re-run
`sudo /opt/nucleus/bin/mesh-start.sh` to bring wlan1 back into mesh mode (the
hub also carries the wifi adapter — see below).

### The decisive evidence (captured live, in the failed state)

Earlier investigations kept destroying the evidence by rebooting (journaling is
**volatile by design** to minimize SD-card wear — see
`docs/system_info/minimize_sd_wear.md` — so failed-boot logs are lost on reboot).
This time the failed state was captured before recovery. On the failed cold boot
the kernel log showed the radio enumerating **perfectly**:

```
usb 1-1.4: New USB device found, idVendor=239a, idProduct=8029
usb 1-1.4: Product: WisCore RAK4631 Board
cdc_acm 1-1.4:1.0: ttyACM0: USB ACM device
```

**Zero USB/xHCI errors** — no `-71`, no `-110`, no descriptor read failures, no
reset storms. The USB bus, hub, cable, and power are healthy. `lsusb -t` showed
the device present and bound to `cdc_acm`. The device node existed and was
readable; it simply never answered the Meshtastic protocol handshake.

### Root cause

The **nRF52840 firmware boots into a hung state**: it completes USB enumeration
(so `/dev/ttyACM0` appears and `radio_detected=true`) but never services the
serial protocol. Because the hang is in the radio's own firmware:

- A **warm reboot does not clear it** — a reboot never drops USB VBUS, so the
  nRF52840 is never actually reset.
- A **radio-only replug/reset did not reliably clear it** either in this
  incident (the chip re-entered the hung state on the subsequent boot).
- A **hub VBUS power cycle (`uhubctl`) clears it** — dropping and restoring
  power hard-resets the chip so the firmware boots cleanly.

This is the same class of failure as the original Node 9 lockup above; here it
was reproducible on a cold boot across three nodes.

### Why the existing boot-time workaround was making it worse

The original `USB_HUB_POWER_CYCLE` block in `mesh-start.sh` did:

```
uhubctl -a off → on → sleep 3 → echo 1-1 > unbind → sleep 1 → echo 1-1 > bind
```

The boot log proved the `unbind`/`bind` "force re-enumeration" step fired only
~4 seconds after power-on — i.e. **while the nRF52840 firmware was still
booting** — yanking it off the bus and re-hanging it. So the workaround intended
to recover the radio was itself leaving it hung. A *single clean* cycle on a
settled system (the manual recovery) worked precisely because it had no
unbind/bind and gave the firmware time to come up.

### Fix implemented

Reworked the `USB_HUB_POWER_CYCLE` block in `mesh-start.sh`:

1. **Removed the `unbind`/`bind` force-re-enumeration step** (the thing that
   re-hung the radio).
2. **Clean `uhubctl -a off/on` only**, followed by a settle delay
   (`USB_CYCLE_SETTLE`, default 10s) so the firmware finishes booting before
   anything probes it.
3. **Verify-and-retry:** after the settle, actually probe the radio with
   `meshtastic --port /dev/ttyACM0 --info`. Device-node existence is NOT trusted
   (a hung radio still creates the node). If it doesn't answer, cycle again up to
   `USB_CYCLE_MAX_ATTEMPTS` (default 3).
4. **Ordering preserved:** the block runs BEFORE wlan1 configuration. Hub 1-1
   carries both the radio (1-1.4) and the wifi mesh adapter (wlan1 / 1-1.2), so
   the cycle resets wlan1 too — running it first means wlan1 is built fresh
   afterward instead of being torn down after the mesh is up. (This is why the
   *manual* late cycle during troubleshooting knocked the mesh offline.)

### Operational notes

- **Recovery command (manual, last resort):** `sudo uhubctl -a cycle -l 1-1`,
  then `sudo /opt/nucleus/bin/mesh-start.sh` to restore wlan1.
- **The cycle always resets wlan1** because the radio and wifi share hub 1-1.
  Expect a brief mesh blip whenever the power cycle runs.
- **Root cause of the *initial* hang is the nRF52840 firmware**, not Nucleus
  software or USB hardware. A firmware update on the RAK4631 may be the real
  long-term fix; the power-cycle-on-boot is a reliable workaround.

---

