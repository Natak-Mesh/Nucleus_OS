# Patch: Web Config Page Not Writing to hostapd.conf

**Date:** 2026-03-17  
**Severity:** High — All config changes from the web UI silently fail (AP password, mesh settings, etc.)  
**Affected nodes:** Any node deployed before this patch

## Root Cause

The web interface (`mesh-web.service`) runs as `User=natak`. When a user applies config changes, `app.py` calls `config_generation.sh` to regenerate system config files (`/etc/hostapd/hostapd.conf`, `/etc/wpa_supplicant/`, `/etc/systemd/network/`, etc.). However, `config_generation.sh` was called **without `sudo`**, so it silently failed to write to root-owned files. The script also lacked `set -e`, so it exited with code 0 despite all the write failures — making the web UI report success when nothing actually changed.

The value in `/etc/nucleus/mesh.conf` updates correctly (natak owns that file), but the generated configs that services actually read (like `hostapd.conf`) never get updated.

## Patch Steps (Remote Node)

SSH into the affected node and run these commands:

### Step 1: Create sudoers entry

```bash
echo 'natak ALL=(ALL) NOPASSWD: /opt/nucleus/bin/config_generation.sh' | sudo tee /etc/sudoers.d/nucleus-config
sudo chmod 0440 /etc/sudoers.d/nucleus-config
sudo chown root:root /etc/sudoers.d/nucleus-config
```

### Step 2: Patch app.py — add `sudo` to config_generation.sh call

```bash
sudo sed -i "s|subprocess.run(\['/opt/nucleus/bin/config_generation.sh'\]|subprocess.run(\['sudo', '/opt/nucleus/bin/config_generation.sh'\]|" /opt/nucleus/web/app.py
```

### Step 3: Patch config_generation.sh — add `set -e` for error handling

```bash
sudo sed -i '1a set -e' /opt/nucleus/bin/config_generation.sh
```

### Step 4: Restart the web service

```bash
sudo systemctl restart mesh-web.service
```

## Verification

After patching, verify the fix works:

```bash
# 1. Confirm sudoers file exists and is valid
sudo visudo -c -f /etc/sudoers.d/nucleus-config

# 2. Confirm app.py has the sudo call
grep "config_generation" /opt/nucleus/web/app.py

# Expected output should show: ['sudo', '/opt/nucleus/bin/config_generation.sh']

# 3. Confirm config_generation.sh has set -e
head -3 /opt/nucleus/bin/config_generation.sh

# Expected: line 2 should be "set -e"

# 4. Test config generation manually as natak user
sudo -u natak sudo /opt/nucleus/bin/config_generation.sh
echo $?

# Expected: exit code 0, and /etc/hostapd/hostapd.conf should match mesh.conf values

# 5. Verify hostapd.conf matches mesh.conf
grep wpa_passphrase /etc/hostapd/hostapd.conf
grep AP_PASSWORD /etc/nucleus/mesh.conf

# Both should show the same password value
```

## Full Command Block (Copy-Paste)

For quick deployment, copy and paste this entire block:

```bash
# Patch web config generation bug
echo 'natak ALL=(ALL) NOPASSWD: /opt/nucleus/bin/config_generation.sh' | sudo tee /etc/sudoers.d/nucleus-config
sudo chmod 0440 /etc/sudoers.d/nucleus-config
sudo chown root:root /etc/sudoers.d/nucleus-config
sudo sed -i "s|subprocess.run(\['/opt/nucleus/bin/config_generation.sh'\]|subprocess.run(\['sudo', '/opt/nucleus/bin/config_generation.sh'\]|" /opt/nucleus/web/app.py
sudo sed -i '1a set -e' /opt/nucleus/bin/config_generation.sh
sudo systemctl restart mesh-web.service
echo "Patch applied. Verify with: grep config_generation /opt/nucleus/web/app.py"
```

## Files Changed

| File | Change |
|------|--------|
| `/etc/sudoers.d/nucleus-config` | **New** — allows natak to run config_generation.sh as root |
| `/opt/nucleus/web/app.py` | Added `sudo` to `config_generation.sh` subprocess call |
| `/opt/nucleus/bin/config_generation.sh` | Added `set -e` for proper error propagation |

## Notes

- This patch does **not** require a reboot — just a service restart.
- Future deploys via `deploy.sh` include this fix automatically.
- If the node had config changes attempted before the patch, `mesh.conf` may contain the user's intended values while the actual service configs (hostapd, wpa_supplicant, etc.) still have old values. Run `sudo /opt/nucleus/bin/config_generation.sh` after patching to sync them, then `sudo systemctl restart hostapd` to apply.
