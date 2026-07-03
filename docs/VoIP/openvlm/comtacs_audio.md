# Peltor ComTac Audio via Bifrost Gear USB-C PTT

Bi-directional audio between the Pi and Peltor ComTac headset using a Bifrost Gear USB-C PTT (Zello option).

## Hardware

- **Headset:** Peltor ComTacs → connected to Bifrost Gear PTT
- **PTT:** Bifrost Gear USB-C PTT (Zello option) — has built-in USB audio card
- **Adapter:** USB-C to USB-A adapter → Pi USB port

The PTT enumerates as **"NBT POC Audio"** (`0020:0b21`) with capture, playback, and HID (PTT button) interfaces. Native format: S16_LE, 48kHz, stereo.

## Required Kernel Fix

The Pi's VIA VL805 xHCI controller has a USB 2.0 hub with a single Transaction Translator. The kernel's TT bandwidth scheduler rejects the playback endpoint even though bandwidth is available. Fix by adding to `/boot/firmware/cmdline.txt`:

```
xhci_hcd.quirks=64
```

Append to the end of the existing line. Reboot required.

**Verify after reboot:**
```bash
cat /sys/module/xhci_hcd/parameters/quirks  # should show 64
dmesg | grep -i bandwidth                    # should be clean
```

## Capture Note

Mic signal from ComTacs through this PTT is very low level (~0.01 max amplitude). A **32dB software gain boost** is required when processing captured audio.

## Commands

```bash
# Record (key PTT and talk):
arecord -D plughw:0,0 -f S16_LE -r 48000 -c 1 -d 10 /tmp/recording.wav

# Boost + convert stereo for playback:
sox /tmp/recording.wav /tmp/playback.wav gain 32 channels 2

# Play back to headset:
aplay -D hw:0,0 /tmp/playback.wav
```

> **Note:** Card number may vary. Check with `arecord -l`. Replace `0,0` with the correct card/device.

## What Didn't Work

- **Generic USB-to-3.5mm adapters** into the PTT's 3.5mm jack — the 3.5mm jack doesn't carry the headset mic signal (only PTT switch transients)
- **KTMicro USB audio cable** — playback only, no capture capability
