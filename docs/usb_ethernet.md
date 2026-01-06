# Raspberry Pi 4 USB Gadget Mode - USB-C Ethernet

Configure the Pi 4's USB-C port to function as an ethernet interface for direct device connection.

## Prerequisites
- Raspberry Pi 4
- Raspberry Pi OS (kernel modules dwc2 and g_ether are included)

## Configuration

### 1. Enable USB OTG
Edit `/boot/firmware/config.txt` (or `/boot/config.txt` on older systems):

```bash
sudo nano /boot/firmware/config.txt
```

Add to the end:
```
dtoverlay=dwc2
```

### 2. Load kernel modules
Edit `/etc/modules`:

```bash
sudo nano /etc/modules
```

Add:
```
dwc2
g_ether
```

### 3. Configure the USB interface
Create `/etc/systemd/network/usb0.network`:

```bash
sudo nano /etc/systemd/network/usb0.network
```

Add:
```
[Match]
Name=usb0

[Network]
Address=192.168.7.1/24
```

Enable systemd-networkd if not already active:
```bash
sudo systemctl enable systemd-networkd
```

### 4. Reboot
```bash
sudo reboot
```

## Phone Configuration

### Android
1. Connect phone to Pi's USB-C port with USB cable
2. Enable **USB tethering** in phone settings
3. Phone will auto-configure (typically 192.168.7.x)
4. SSH to Pi: `ssh user@192.168.7.1`

### iOS
iOS does not natively support USB ethernet gadgets.

## Verification
After connection:
```bash
ip addr show usb0
```

Should show usb0 interface with 192.168.7.1 address.

## Troubleshooting
- Ensure you're using a **data-capable USB cable** (not charge-only)
- Use the **USB-C port**, not the USB-A ports
- Check `dmesg | grep dwc2` for driver loading
- Check `lsmod | grep g_ether` to verify module loaded
