# CLI Terminal Menu — Planning

Easy access to Nucleus node tools. Plug in via eth0 or WiFi, run `nucleus`, get a menu. No IP addresses, no SSH commands, no passwords.

## Architecture

Two pieces:

**Pi-side (this repo):** `nucleus-menu.sh` presents a numbered menu of curated CLI tools. `nucleus-status.sh` shows a one-page system summary. Both live in `/opt/nucleus/bin/`.

**Laptop-side (separate repo):** `nucleus-tools` — a pip-installable Python package (`pip install nucleus-tools`). User types `nucleus` → tool auto-discovers the node, SSHes in, launches the menu. Handles node discovery via gateway detection and mDNS. Repo: `Natak-Mesh/nucleus-tools`.

No sshd_config changes needed. The client does `ssh -t natak@host /opt/nucleus/bin/nucleus-menu.sh`.

## Build Order

1. Pi-side first — menu + status script, testable via plain SSH
2. Laptop client second — polished wrapper around what already works

## Tools Inventory

### System Monitoring

| Tool | What it does | Installed? | Menu? |
|------|-------------|------------|-------|
| **htop** | CPU, RAM, processes (noisy — shows all 47 tailscale threads) | ✅ Yes | No — replaced by nucleus-status |
| **portrm** | Pretty port listing with PIDs, memory, uptime | ✅ Yes (standalone binary via `pip install portrm`) | Candidate |
| **ncdu** | Interactive disk usage browser — navigate dirs, find what's eating space | ✅ Yes | ✅ Yes |
| **top** | Basic process monitor (uglier htop) | ✅ Yes | No |
| **free -h** | RAM/swap at a glance | ✅ Yes (built-in) | No — covered by nucleus-status |
| **df -h** | Disk space per filesystem | ✅ Yes (built-in) | No — covered by nucleus-status |
| **vmstat** | CPU, memory, IO, swap activity | ✅ Yes | No |
| **lsblk** | Block devices, partitions, mount points | ✅ Yes | No |
| **ss -tlnp** | Listening ports + PIDs | ✅ Yes (built-in) | No — portrm is prettier |
| **journalctl** | System/service logs | ✅ Yes | ✅ Yes |
| **btop** | htop on steroids — CPU, RAM, disk, net in one TUI | ❌ No (`apt install btop`, ~2MB) | Candidate |
| **duf** | Beautiful df replacement — colored disk usage table | ❌ No (`apt install duf`, ~1MB) | Candidate |
| **nethogs** | Live bandwidth per-process | ❌ No (`apt install nethogs`) | Candidate |
| **iftop** | Live bandwidth per-connection | ❌ No (`apt install iftop`) | Candidate |
| **lsof** | List open files/sockets by process | ❌ No (`apt install lsof`) | No |

### Mesh / Radio

| Tool | What it does | Installed? | Menu? |
|------|-------------|------------|-------|
| **meshtastic --info** | Radio info, channel config, connected nodes | ✅ Yes | Candidate |
| **meshtastic --nodes** | List all known Meshtastic nodes | ✅ Yes | Candidate |
| **meshtastic --sendtext** | Send text message over LoRa | ✅ Yes | Candidate |
| **meshtastic --traceroute** | Trace route to a LoRa node | ✅ Yes | Candidate |
| **meshtastic --export-config** | Dump full radio configuration | ✅ Yes | Candidate |
| **mesh-tunnel** | Meshtastic IP tunnel utility | ✅ Yes | No |
| **iw wlan1 station dump** | Mesh WiFi peer details (signal, bitrate) | ✅ Yes | Candidate |
| **iw wlan1 info** | Mesh interface config (channel, meshid) | ✅ Yes | Candidate |
| **ip route show proto babel** | Babel routing table | ✅ Yes | Candidate |

### Reticulum

| Tool | What it does | Installed? | Menu? |
|------|-------------|------------|-------|
| **rnstatus** | Interfaces, transport status, traffic stats | ✅ Yes | Candidate |
| **rnpath** | Known destinations / routing table | ✅ Yes | Candidate |
| **rnprobe** | Ping a Reticulum destination | ✅ Yes | Candidate |
| **rnx** | Remote execute a command on another Reticulum node | ✅ Yes | Candidate |
| **rncp** | Copy a file to a remote Reticulum node | ✅ Yes | Candidate |
| **rnid** | Manage Reticulum identities | ✅ Yes | No |
| **rnodeconf** | Configure RNode hardware | ✅ Yes | No |
| **NomadNet** | TUI mesh messenger/browser over Reticulum | ❌ No (`pip install nomadnet`) | Candidate |

### Network Testing

| Tool | What it does | Installed? | Menu? |
|------|-------------|------------|-------|
| **iperf3** | Bandwidth test between nodes | ✅ Yes | Candidate |
| **ping** | Basic connectivity test | ✅ Yes | Candidate |
| **tcpdump** | Packet capture on any interface | ✅ Yes | Candidate |
| **mtr** | Combined ping + traceroute TUI | ❌ No (`apt install mtr-tiny`) | Candidate |
| **traceroute** | Trace route to destination | ❌ No (`apt install traceroute`) | Candidate |

### Other

| Tool | What it does | Installed? | Menu? |
|------|-------------|------------|-------|
| **tailscale status** | Tailscale VPN status and peer list | ✅ Yes | Candidate |
| **docker ps** | Running containers (OpenDHT etc.) | ✅ Yes | No |

## Menu Categories (Finalized)

### 1. System Monitoring

| Tool | Purpose | Install |
|------|---------|---------|
| **nucleus-status** (custom) | One-page summary: RAM, disk, services, top memory grouped by service | Write it |
| **ncdu** | Interactive disk usage browser | Already installed |
| **journalctl** | System/service logs | Already installed |

### 2. Mesh / Radio — TBD

### 3. Reticulum — TBD

### 4. Network Testing — TBD

### 5. Shell Access

Drop to bash as natak user.

## Evaluated and Dropped

### netwatch (https://github.com/matthart1983/netwatch)

Rust-based TUI network monitor with nice tx/rx rate graphs, connection tracking, and a flight recorder feature. **Dropped** because it reads kernel `operstate` to determine interface status and misreports both:

- **wlan1 (802.11s mesh):** Kernel reports `state DORMANT` / `NO-CARRIER` even with active mesh peers — this is a Linux kernel quirk where carrier detection doesn't apply to mesh mode interfaces. netwatch shows it as "down."
- **tailscale0 (TUN/TAP):** Kernel reports `state UNKNOWN` which is normal for tunnel devices. netwatch shows it as "down."

Since these are the two most critical interfaces on a Nucleus node, the misleading status makes the tool more confusing than helpful. Fixing it would require forking the Rust source — out of scope.

### Redundancy notes

- **htop** replaced by **nucleus-status** for system overview (htop shows too much noise — all tailscale threads etc.)
- **ss** replaced by **portrm** (same data, prettier output)
- **free/df** covered by **nucleus-status** one-page summary
- **top** superseded by htop/btop

## nucleus-tools Client Package

Repo: `Natak-Mesh/nucleus-tools`

User experience:
1. `pip install nucleus-tools`
2. Plug Nucleus into laptop (eth0) or connect to AP WiFi
3. Type `nucleus`
4. Auto-discovers node, connects, menu appears

Features:
- Auto-detect gateway IP (10.10.x.1) for eth0 direct cable
- mDNS discovery (00XX-nucleus-ap.local) for WiFi
- Multi-node discovery — pick from list if multiple found
- Remember last connection
- Cross-platform (macOS, Linux, Windows)

## Install Requirements (Pi-side)

- **nucleus-status.sh** and **nucleus-menu.sh** → `/opt/nucleus/bin/`
- Potential apt packages depending on menu finalization: `btop`, `duf`, `mtr-tiny`, `nethogs`, `iftop`, `traceroute`
- Potential pip packages: `nomadnet`

## Decisions Still Needed

- [ ] Finalize Mesh/Radio menu items
- [ ] Finalize Reticulum menu items
- [ ] Finalize Network Testing menu items
- [ ] Whether to install NomadNet
- [ ] Which optional apt packages to add (btop, duf, mtr, nethogs, iftop)
