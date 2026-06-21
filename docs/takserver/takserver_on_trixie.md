# Installing TAKServer on Debian Trixie

> ✅ **Tested and Confirmed** - This installation method has been successfully tested with TAKServer 5.3 and 5.6 on Debian Trixie.

## Problem Statement

TAKServer requires:
- PostgreSQL 15
- OpenJDK 17 (JDK)

Debian Trixie ships with:
- PostgreSQL 18
- No OpenJDK 17 (removed from repositories)

TAKServer's postinstall scripts expect PostgreSQL 15 and OpenJDK 17 specifically, leading to installation failures.

## Solution Overview

Use Debian Bookworm repositories with APT pinning to install the exact versions TAKServer expects, while keeping the rest of the system on Trixie packages.

---

## Step-by-Step Installation

### 1. Remove Incompatible PostgreSQL (if installed)

If PostgreSQL 18 is already installed, remove it:

```bash
sudo systemctl stop postgresql
sudo apt purge postgresql postgresql-18 postgresql-client-18 postgresql-common
sudo rm -rf /var/lib/postgresql/18
```

### 2. Add Bookworm Repository with Pinning

Create APT pin to prioritize Trixie packages by default, only using Bookworm when explicitly needed:

```bash
echo -e "Package: *\nPin: release n=bookworm\nPin-Priority: 100" | sudo tee /etc/apt/preferences.d/bookworm
```

Add Bookworm repository:

```bash
echo "deb http://deb.debian.org/debian bookworm main" | sudo tee /etc/apt/sources.list.d/bookworm.list
```

Update package lists:

```bash
sudo apt update
```

### 3. Install PostgreSQL 15 from Bookworm

```bash
sudo apt install postgresql-15 postgresql-client-15 -y
```

Verify PostgreSQL 15 is running:

```bash
systemctl status postgresql
pg_lsclusters
```

You should see PostgreSQL 15 cluster running.

### 4. Install OpenJDK 17 from Bookworm

```bash
sudo apt install openjdk-17-jdk openjdk-17-jre -y
```

Verify Java 17 installation:

```bash
java -version
```

Should show OpenJDK 17.

### 5. Install TAKServer

Navigate to the directory containing your TAKServer .deb file and install:

```bash
cd /opt/nucleus/takserver  # or wherever your .deb is located
sudo apt install ./takserver_*.deb
```

The installation should now complete successfully without PGDATA errors or dependency issues.

### 6. Verify Installation

Check TAKServer files are in place:

```bash
ls -la /opt/tak/
```

---

## Post-Installation

Follow TAKServer documentation to:
1. Generate certificates (see Appendix B of TAKServer configuration guide)
2. Set up database
3. Create admin user
4. Configure CoreConfig.xml

---

## Notes

- **APT pinning ensures Trixie packages are used by default** - The priority 100 setting means Bookworm packages will only be used when explicitly needed
- Only PostgreSQL 15 and OpenJDK 17 are pulled from Bookworm
- This is the cleanest solution - no dummy packages, no environment variables, no hacks
- System remains primarily on Trixie
- Works with TAKServer 5.3, 5.6, and likely future versions

### TAK Server Boot CPU Impact on Meshtastic Radio

TAK Server's JVM initialization pegs the CPU at 160%+ for 2-4 minutes after boot
(load average > 10 on a Pi). During this window, the Meshtastic `cot-bridge` service
may fail to complete its serial handshake with the RAK4631 radio — the protobuf
exchange times out after ~30 seconds because the CPU is too starved to process it.

Additionally, the USB hub power cycle in `mesh-start.sh` (used to recover the
RAK4631 from firmware lockups) must allow **at least 15 seconds** after powering
on the hub before the unbind/rebind step. The nRF52840 Meshtastic firmware needs
5-10 seconds to fully initialize after power-on. If the USB is yanked during
firmware init, the application layer hangs — USB CDC-ACM still works
(`/dev/ttyACM0` appears) but serial and Bluetooth are unresponsive until a
hardware reset.

**Requirements:**
- `mesh-start.sh`: `sleep 15` after `uhubctl -a on` (not `sleep 3`)
- `cot-bridge.service`: starts after `mesh-start.service` completes, with an
  additional 5-second delay (already handled by the background restart at the
  end of `mesh-start.sh`)
- On a fresh boot, expect cot-bridge to connect successfully only after TAK
  Server's CPU spike subsides (~2-4 minutes post-boot)

---

## Troubleshooting

**If PostgreSQL service fails to start:**
```bash
sudo systemctl restart postgresql
sudo pg_ctlcluster 15 main start
```

**To check which packages came from Bookworm:**
```bash
apt-cache policy postgresql-15
apt-cache policy openjdk-17-jdk
```

**To verify APT pinning is working:**
```bash
cat /etc/apt/preferences.d/bookworm
apt-cache policy
```

**Nucleus-specific UFW rules (IMPORTANT):**

TAKServer's firewall docs enable UFW with `deny incoming` as the default policy. This blocks
critical Nucleus services on the local bridge and mesh interfaces. After enabling UFW, add:

```bash
# Trust local interfaces (AP clients and mesh peers are already authenticated)
sudo ufw allow in on br-lan
sudo ufw allow in on wlan1

# CRITICAL: allow forwarded/routed traffic between trusted interfaces.
# UFW defaults to 'deny (routed)', which silently breaks BOTH:
#   - Internet gateway sharing (EUD on br-lan -> eth0/router)
#   - ATAK multicast forwarding across the mesh (br-lan <-> wlan1)
sudo ufw default allow routed
sudo ufw reload
```

Without these rules, `systemd-networkd`'s DHCP server on br-lan won't respond to AP clients,
and `cot-bridge` won't receive ATAK multicast traffic to forward over LoRa.

> ⚠️ **Watch for this symptom:** If the node itself has internet but a connected wlan0/EUD
> client does **not**, the cause is almost always `deny (routed)`. The node reaching the
> internet is locally-originated traffic (covered by `allow outgoing`), but EUD traffic must
> be *forwarded* br-lan → eth0, which `deny (routed)` blocks. Verify with
> `sudo ufw status verbose` (look at the `Default:` line) and fix with
> `sudo ufw default allow routed && sudo ufw reload`.

These rules are interface-specific (or, for `allow routed`, scoped to forwarding between
trusted interfaces) — they do NOT weaken eth0 (WAN/internet) protection. `deny (incoming)`
stays in place and eth0 remains firewalled with only explicitly allowed ports (SSH,
TAKServer, etc.). See `docs/system_info/UFW_settings.md` for the full firewall reference.


**To remove Bookworm repos later (not recommended while TAKServer is installed):**
```bash
sudo rm /etc/apt/sources.list.d/bookworm.list
sudo rm /etc/apt/preferences.d/bookworm
sudo apt update
```

---

## Why This Works

The APT pinning configuration with priority 100 is lower than the default priority (500), which means:
- Trixie packages are always preferred when available
- Bookworm packages are only selected when no Trixie version exists
- This prevents unwanted downgrades or package conflicts
- The system stays clean and maintainable
