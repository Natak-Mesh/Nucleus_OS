# Tailscale Web GUI Deployment Guide

## Overview
This guide covers deploying the Tailscale integration to the Nucleus OS web GUI.

## Prerequisites
- Tailscale installed on the system (`sudo apt install tailscale`)
- Internet connection
- Web GUI running (mesh-web.service)

## Initial Tailscale Setup

If this is your first time setting up Tailscale on this Pi, you need to start the daemon and login:

### Start Tailscale Daemon

```bash
# Start the Tailscale daemon
sudo systemctl start tailscaled

# Enable it to start on boot
sudo systemctl enable tailscaled

# Verify it's running
sudo systemctl status tailscaled
```

### Login to Your First Tailscale Account

```bash
# Login to Tailscale (will provide a URL to authenticate)
tailscale login
```

This command will output a URL like:
```
To authenticate, visit: https://login.tailscale.com/a/xxxxx
```

1. Copy the URL and open it in a browser
2. Log in with your Tailscale account
3. Authorize the device

### Bring Up the Connection

After completing authentication in the browser:

```bash
# Connect to your tailnet
tailscale up

# Verify connection status
tailscale status
```

You should now see your device connected. You can view your Tailscale IP:

```bash
tailscale ip -4
```

## Deployment Steps

### 1. Copy Sudoers Configuration

The sudoers file allows the web GUI to run Tailscale commands without requiring a password.

```bash
sudo cp /home/natak/Nucleus_OS/etc/sudoers.d/tailscale-web /etc/sudoers.d/tailscale-web
sudo chmod 0440 /etc/sudoers.d/tailscale-web
sudo chown root:root /etc/sudoers.d/tailscale-web
```

**Verify the sudoers file is valid:**
```bash
sudo visudo -c
```

### 2. Restart Web Service

The code changes are already in place. Restart the web service to load the new endpoints:

```bash
sudo systemctl restart mesh-web.service
```

**Check service status:**
```bash
sudo systemctl status mesh-web.service
```

### 3. Verify Tailscale is Configured

Check that at least one Tailscale profile exists:

```bash
tailscale switch --list
```

If no profiles exist, log in to Tailscale:

```bash
tailscale login
```

## Testing the Implementation

### Test API Endpoints Directly

1. **Test status endpoint:**
```bash
curl http://localhost:5000/api/tailscale/status | jq
```

Expected output:
```json
{
  "connected": true,
  "ip": "100.x.x.x",
  "tailnet": "example.tailnet.ts.net",
  "hostname": "0002-nucleus",
  "status": "Running"
}
```

2. **Test profiles endpoint:**
```bash
curl http://localhost:5000/api/tailscale/profiles | jq
```

Expected output:
```json
{
  "profiles": [
    {
      "id": "123456",
      "account": "user@example.com",
      "current": true
    }
  ]
}
```

3. **Test connection control (requires sudo permissions to be configured):**
```bash
# Turn off
curl -X POST http://localhost:5000/api/tailscale/down | jq

# Wait 2 seconds
sleep 2

# Turn on
curl -X POST http://localhost:5000/api/tailscale/up | jq
```

### Test Web Interface

1. Open browser and navigate to: `http://<nucleus-ip>:5000/remote`

2. Verify the page shows:
   - Status (Connected/Disconnected)
   - Tailscale IP address (if connected)
   - Current tailnet name
   - Turn On/Off buttons
   - Profile dropdown with available accounts

3. Test functionality:
   - Click "Turn Off" → status should change to Disconnected
   - Click "Turn On" → status should change to Connected
   - Select different profile from dropdown → click "Switch" → verify tailnet changes

## Troubleshooting

### Issue: Sudo password prompts appear in logs

**Solution:** Verify sudoers file is installed correctly:
```bash
sudo cat /etc/sudoers.d/tailscale-web
```

### Issue: "No profiles available"

**Cause:** No Tailscale accounts logged in

**Solution:** Log in to at least one Tailscale account:
```bash
tailscale login
```

### Issue: API returns errors

**Check Flask logs:**
```bash
sudo journalctl -u mesh-web.service -f
```

### Issue: Commands timeout

**Cause:** Tailscale daemon not running

**Solution:** Start tailscaled:
```bash
sudo systemctl start tailscaled
sudo systemctl enable tailscaled
```

## Security Notes

1. The sudoers file grants password-less access only to specific Tailscale commands
2. Only the `natak` user can execute these commands
3. Commands are limited to: `tailscale up`, `tailscale down`, and `tailscale switch`
4. The web GUI runs as the `natak` user via the mesh-web.service

## Adding Additional Tailscale Profiles

To add more Tailscale accounts/profiles:

```bash
# Login to additional account
tailscale login

# Verify all profiles
tailscale switch --list
```

Each logged-in account will appear in the web GUI dropdown automatically.

## Rollback Procedure

If you need to revert to the old rpi-connect system:

1. **Restore old remote.html:**
   - Keep a backup of the original file before deployment
   - Copy backup back to `/opt/nucleus/web/templates/remote.html`

2. **Remove Tailscale endpoints from app.py:**
   - Comment out the Tailscale endpoints (lines with `/api/tailscale/*`)
   - Uncomment the rpi-connect endpoints

3. **Remove sudoers file:**
```bash
sudo rm /etc/sudoers.d/tailscale-web
```

4. **Restart web service:**
```bash
sudo systemctl restart mesh-web.service
```

## Maintenance

### Updating Tailscale

When updating Tailscale, the CLI commands should remain compatible. However, verify after updates:

```bash
tailscale version
tailscale --help
```

### Monitoring

Monitor web service logs for any Tailscale-related errors:

```bash
sudo journalctl -u mesh-web.service -f | grep tailscale
```
