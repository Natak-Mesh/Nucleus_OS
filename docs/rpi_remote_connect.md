# Enabling Raspberry Pi Connect on an Existing Headless Raspberry Pi (Bookworm)

## Preconditions
- Internet access
- A normal (non-root) user account (e.g. `natak`)
- Writable home directory for that user

## 1. Install Raspberry Pi Connect

Raspberry Pi Connect is not installed by default on minimal/headless images.

```bash
sudo apt update
sudo apt install rpi-connect
```

This installs:
- rpi-connect CLI
- rpi-connectd (user-session daemon)

## 2. Enable user lingering (critical on headless systems)

On headless/minimal systems, systemd user services do not start unless the user is logged in.
Raspberry Pi Connect runs as a systemd --user service, so lingering must be enabled.

```bash
loginctl enable-linger natak
```

This allows the user’s systemd services to start at boot without a GUI or active login session.

## 3. Ensure a working user systemd + DBus session

Verify that the user systemd instance is running:

```bash
systemctl --user status
```

If this fails with a DBus error, install the required package:

```bash
sudo apt install dbus-user-session
```

Then log out and back in, or reboot.

## 4. Start Raspberry Pi Connect

Start the Raspberry Pi Connect user service:

```bash
rpi-connect on
```

Internally, this starts:
- rpi-connect.service (systemd --user)
- rpi-connectd
- Runtime sockets under:
  /run/user/UID/

Confirm it is running:

```bash
systemctl --user status rpi-connect.service
```

## 5. Sign in to Raspberry Pi Connect


```bash
rpi-connect signin
```

This will:
- Open a browser, or
- Provide a URL and one-time code for account authentication

The device is now associated with your Raspberry Pi account.

## 6. Verify status

```bash
rpi-connect status
```

You should see:
- Service running
- Signed in with your account
- Device visible at https://connect.raspberrypi.com

## 7. Remote Development with VS Code

Once connected via RPI Connect's remote shell, you can set up VS Code remote development using the **VS Code CLI** (package: `code-cli` or downloadable from Microsoft). The CLI tool creates a secure tunnel that allows VS Code on any device to connect to your Pi without requiring direct SSH access or port forwarding. This works seamlessly through the RPI Connect shell interface, giving you full IDE functionality remotely.
