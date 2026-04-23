# Nucleus Node Update Guide

**Purpose:** Update a deployed Nucleus node to the latest software from the Git repository while keeping your existing mesh configuration intact.

This update will also add two new configuration variables that weren't in older versions:
- `USB_HUB_POWER_CYCLE` — fixes Meshtastic radio lockups on boot
- `COT_BRIDGE_ENABLED` — enables ATAK CoT bridging over Meshtastic LoRa

Additionally, we'll disable the `mosquitto` service which has been interfering with OpenTAK Server nodes.

---

## Prerequisites

- A computer on the same network as the node (Wi-Fi AP or Ethernet)
- A terminal application (Terminal on Mac/Linux, PowerShell or PuTTY on Windows)

---

## Step 1 — SSH Into the Node

Open your terminal and connect to the node:

```bash
ssh natak@0021-nucleus.local
```

When prompted for a password, type:

```
52235223
```

> **Note:** You won't see the password as you type — that's normal. Just type it and press Enter.

> **Important:** This is also the `sudo` password. Any time a command in this guide starts with `sudo` and asks for a password, enter `52235223`.

If it asks "Are you sure you want to continue connecting?" type `yes` and press Enter.

You should now see a command prompt like `natak@nucleus:~$`. You're in.

---

## Step 2 — Pull the Latest Code

Navigate to the Nucleus OS directory and download the latest version:

```bash
cd ~/Nucleus_OS
```

```bash
git pull
```

You should see output showing files being updated. If it says "Already up to date" then the node is already on the latest version (but continue anyway to pick up the new config variables).

---

## Step 3 — Back Up Your Mesh Config

Your mesh.conf has all of your node's unique settings (IP addresses, mesh name, passwords, etc). We need to protect it before the deploy overwrites it.

```bash
sudo mv /etc/nucleus/mesh.conf /etc/nucleus/mesh.bak.conf
```

> This renames your config to `mesh.bak.conf` so deploy.sh won't overwrite it.

---

## Step 4 — Install New Packages

Run the package installer to pick up any new dependencies:

```bash
cd ~/Nucleus_OS
```

```bash
sudo ./install-packages.sh
```

This may take a few minutes. Wait for it to finish completely.

---

## Step 5 — Run the Deploy Script

This copies all the updated files (scripts, services, web interface, etc.) to the right system locations:

```bash
sudo ./deploy.sh
```

Wait for it to finish. You'll see "Deployment complete." when it's done.

---

## Step 6 — Restore Your Mesh Config

The deploy script just copied a fresh template mesh.conf (with default values). We need to remove that and put your real config back:

```bash
sudo rm /etc/nucleus/mesh.conf
```

```bash
sudo mv /etc/nucleus/mesh.bak.conf /etc/nucleus/mesh.conf
```

Your original config is now back in place.

---

## Step 7 — Add the New Config Variables

Your restored mesh.conf is from an older version and is missing two new variables. We need to add them to the bottom of the file.

Open the file in nano:

```bash
sudo nano /etc/nucleus/mesh.conf
```

**How to navigate in nano:**
- Use the **arrow keys** to move around
- Scroll all the way to the **bottom** of the file (hold the down arrow, or press `Ctrl+End`)

At the very bottom of the file, **after the last line**, add these two blocks. You can copy-paste them one at a time:

```
# USB Hub Power Cycle — Meshtastic radio lockup workaround
# Power-cycles all USB devices on hub 1-1 at boot to recover a crashed
# RAK4631 Meshtastic radio. Only enable on nodes that experience
# Meshtastic radio lockups on boot.
USB_HUB_POWER_CYCLE=false

# ATAK CoT Bridge Configuration
# Bridges ATAK multicast CoT to/from Meshtastic LoRa
# When true, cot-bridge.service runs and the radio is in bridge mode
# When false (default), the radio is left in BLE mode for phone app
COT_BRIDGE_ENABLED=false
```

**How to save and exit nano:**
1. Press `Ctrl+O` (that's the letter O, not zero) to save — it will ask for a filename, just press **Enter** to confirm
2. Press `Ctrl+X` to exit

---

## Step 8 — Disable Mosquitto

Mosquitto has been interfering with OpenTAK Server nodes. Disable and stop it:

```bash
sudo systemctl disable --now mosquitto
```

> If you get a message like "Unit mosquitto.service not found" — that's fine, it just means it wasn't installed on this node. Move on.

---

## Step 9 — Regenerate System Configs

This reads your mesh.conf and generates all the system configuration files (network, hostapd, babeld, etc.):

```bash
sudo /opt/nucleus/bin/config_generation.sh
```

You should see "Configuration files generated successfully." when it's done.

---

## Step 10 — Reboot

```bash
sudo reboot
```

Your SSH session will disconnect — that's expected. Wait about 60–90 seconds for the node to come back up.

---

## Step 11 — Reconnect and Verify the CoT Bridge

SSH back into the node:

```bash
ssh natak@0021-nucleus.local
```

Password: `52235223`

### Watch the CoT Bridge log live:

Run this command to stream the CoT bridge log output in real time:

```bash
sudo journalctl -u cot-bridge -f
```

This will show a live, scrolling log. **Leave this running** and do the following:

1. **Connect an ATAK device** (phone/tablet) to the node's Wi-Fi access point
2. **Open ATAK** on the device
3. **Watch the terminal** — you should start seeing CoT packets arriving in the log output (position reports, etc.)

If you see packets flowing, **the CoT bridge is working correctly**. Press `Ctrl+C` to stop watching the log.

### If the CoT bridge is NOT running or no packets appear:

The Meshtastic radio may have locked up during boot. Enable the USB hub power cycle to fix this.

Open the mesh config:

```bash
sudo nano /etc/nucleus/mesh.conf
```

Use the arrow keys to find this line:

```
USB_HUB_POWER_CYCLE=false
```

Change it to:

```
USB_HUB_POWER_CYCLE=true
```

Save and exit: `Ctrl+O`, press **Enter**, then `Ctrl+X`.

Then regenerate configs and reboot:

```bash
sudo /opt/nucleus/bin/config_generation.sh
```

```bash
sudo reboot
```

Wait 60–90 seconds, SSH back in, and run the live log again:

```bash
ssh natak@0021-nucleus.local
```

Password: `52235223`

```bash
sudo journalctl -u cot-bridge -f
```

Connect your ATAK device again and confirm packets are now flowing.

### Confirm mosquitto is disabled:

After you're done verifying the CoT bridge (press `Ctrl+C` to stop the log), run:

```bash
sudo systemctl status mosquitto --no-pager
```

It should show **inactive (dead)** or **not found**. Either is fine.

---

## Quick Reference — All Commands in Order

```bash
# Step 1: SSH in
ssh natak@0021-nucleus.local
# password: 52235223

# Step 2: Pull latest
cd ~/Nucleus_OS
git pull

# Step 3: Back up config
sudo mv /etc/nucleus/mesh.conf /etc/nucleus/mesh.bak.conf

# Step 4: Install packages
cd ~/Nucleus_OS
sudo ./install-packages.sh

# Step 5: Deploy
sudo ./deploy.sh

# Step 6: Restore config
sudo rm /etc/nucleus/mesh.conf
sudo mv /etc/nucleus/mesh.bak.conf /etc/nucleus/mesh.conf

# Step 7: Add new variables (open in nano, add to bottom, Ctrl+O to save, Ctrl+X to exit)
sudo nano /etc/nucleus/mesh.conf

# Step 8: Disable mosquitto
sudo systemctl disable --now mosquitto

# Step 9: Regenerate configs
sudo /opt/nucleus/bin/config_generation.sh

# Step 10: Reboot
sudo reboot

# Step 11: Reconnect and verify CoT bridge
ssh natak@0021-nucleus.local
# password: 52235223 (also the sudo password)
sudo journalctl -u cot-bridge -f
# Connect ATAK device to node AP, open ATAK, watch for packets in the log
# Ctrl+C to stop watching
sudo systemctl status mosquitto --no-pager
```

---

## Troubleshooting

| Problem | Solution |
|---------|----------|
| Can't SSH to the node | Make sure you're on the node's Wi-Fi AP or connected via Ethernet. Try the IP address directly if `.local` doesn't resolve. |
| `git pull` fails | Check internet connection on the node. The node needs WAN access (Ethernet to router) to reach GitHub. |
| CoT bridge won't start | Check if Meshtastic radio is detected: `ls /dev/ttyACM*`. If no device found, enable `USB_HUB_POWER_CYCLE=true` and reboot. |
| Services look wrong after reboot | Re-run `sudo /opt/nucleus/bin/config_generation.sh` and reboot again. |
