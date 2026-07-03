# OpenDHT Deployment Guide

## Overview
This guide covers the automated deployment of OpenDHT for Jami voice/video support on Nucleus mesh nodes.

## Deployment Workflow

### 1. Initial Setup (While Online)
Run the package installation script to install Docker and pull the OpenDHT image:
```bash
./install-packages.sh
```

This will:
- Install Docker using the official Docker installation script
- Add your user to the docker group (may require logout/login)
- Pull the OpenDHT image: `ghcr.io/savoirfairelinux/opendht/opendht-alpine`

### 2. Configure mesh.conf
Edit `/etc/nucleus/mesh.conf` (or your local copy before deployment) to configure OpenDHT:

```bash
# OpenDHT Configuration (Jami Support)
OPENDHT_ENABLED=true
OPENDHT_NETWORK_ID=12345
# IMPORTANT: Update the IPs below to match YOUR actual mesh node IPs
# Example: If you have nodes at 10.20.1.2 and 10.20.1.3, use: OPENDHT_BOOTSTRAP_IPS="10.20.1.2,10.20.1.3"
OPENDHT_BOOTSTRAP_IPS="10.20.1.11,10.20.1.12,10.20.1.13"
```

**Configuration Fields:**
- `OPENDHT_ENABLED`: Set to `true` to enable OpenDHT, `false` to disable
- `OPENDHT_NETWORK_ID`: Network ID to isolate from public DHT (default: 12345)
- `OPENDHT_BOOTSTRAP_IPS`: Comma-separated list of mesh IPs of other nodes
  - **CRITICAL:** Replace the example IPs with your actual mesh node IPs
  - The script automatically filters out the current node's own IP
  - List at least 2-3 other node IPs for redundancy
  - Example: If your mesh has nodes at 10.20.1.2, 10.20.1.3, 10.20.1.5, list all of them

### 3. Deploy Configuration
Run the deployment script to copy all files to system locations:
```bash
./deploy.sh
```

This will:
- Copy `opendht-start.sh` to `/opt/nucleus/bin/`
- Set executable permissions
- Update `mesh-start.sh` to call OpenDHT on startup

### 4. Start or Reboot
Either reboot the node or manually start the mesh network:
```bash
sudo systemctl restart mesh-start.service
```

OpenDHT will automatically start after the mesh network is configured.

## Verification

### Check Container Status
```bash
docker ps
```

Should show a container named `dhtnode` running.

### Check DHT Connectivity
```bash
curl http://127.0.0.1:8000/
```

Expected output:
```json
{"good":1}
```

The number indicates connected DHT nodes. `"good":1` means at least one peer is connected.

### View Container Logs
```bash
docker logs dhtnode
```

## How It Works

### Bootstrap Strategy
1. Each node reads `OPENDHT_BOOTSTRAP_IPS` from mesh.conf
2. The startup script filters out its own `MESH_IP`
3. Uses the first remaining IP as bootstrap: `-b <IP>:4222`
4. Once connected to one node, the DHT automatically discovers all other nodes

### Docker Command
The actual command executed:
```bash
docker run -d --network host --restart=unless-stopped --name dhtnode \
  ghcr.io/savoirfairelinux/opendht/opendht-alpine \
  dhtnode -p 4222 -D -s --proxyserver 8000 -n 12345 -b <bootstrap_ip>:4222
```

**Flags Explained:**
- `-d`: Run in detached mode
- `--network host`: Required for multicast discovery
- `--restart=unless-stopped`: Auto-start on boot
- `-p 4222`: DHT port
- `-D`: Enable multicast peer discovery
- `-s`: Service mode (daemon)
- `--proxyserver 8000`: HTTP proxy for mobile clients (Jami Android)
- `-n 12345`: Network ID (isolates from public DHT)
- `-b <ip>:4222`: Bootstrap to specific node

## Jami Client Configuration

### On Mobile Devices (Android)
Configure Jami to use the local DHT:

1. Open Jami Settings → Account Settings → Advanced
2. Set these values:
   - **Bootstrap:** `10.20.XX.1:4222` (your node's br-lan gateway IP)
   - **Use DHT proxy:** Enabled ✓
   - **DHT Proxy Address:** `10.20.XX.1:8000` (NO http:// prefix)
   - **Enable local peer discovery:** Enabled ✓
   - **Use DHT proxy list:** Disabled ✗
   - **UPnP:** Disabled ✗
   - **TURN server:** Clear/Empty
   - **Name server:** Clear/Empty

Where `XX` is your node number (e.g., 10.20.12.1 for node 12).

## Troubleshooting

### Jami Shows "No Distributor" Error

This is the most common issue - Jami cannot connect to the DHT network.

**Step 1: Verify DHT is working between nodes**
```bash
# On the node where Jami is having issues:
curl http://127.0.0.1:8000/
```

Look for `"good":` value in the response:
- `"good":0` = **Problem!** No DHT peers connected
- `"good":1` or higher = DHT is working between nodes

**Step 2: If "good":0, check bootstrap configuration**
```bash
# View which IP the container is trying to bootstrap to:
sudo docker logs dhtnode 2>&1 | head -10

# Check if that IP is actually in your mesh:
ping -c 3 <bootstrap_ip>

# Check if the other node has DHT running:
curl http://<bootstrap_ip>:8000/
```

**Common cause:** Bootstrap IPs in `/etc/nucleus/mesh.conf` are incorrect or from an old mesh configuration.

**Solution:**
1. Update `OPENDHT_BOOTSTRAP_IPS` in `/etc/nucleus/mesh.conf` with your actual mesh node IPs
2. Restart OpenDHT: `sudo /opt/nucleus/bin/opendht-start.sh`
3. Verify: `curl http://127.0.0.1:8000/` should show `"good":1` or higher

**Step 3: If DHT is working but Jami still says "No Distributor"**

The issue is likely Jami configuration. Verify from your phone's browser:
```
http://10.20.XX.1:8000/
```
(Replace XX with your node number)

If this loads in the browser but Jami doesn't work, check Jami settings:
- **DHT Proxy Address** must be `10.20.XX.1:8000` (br-lan gateway IP, NOT mesh IP)
- **NO** `http://` prefix in the DHT Proxy Address field
- **Use DHT proxy:** Must be Enabled ✓
- **Use DHT proxy list:** Must be Disabled ✗

### Container Not Starting
Check Docker service status:
```bash
sudo systemctl status docker
```

### No DHT Peers Connecting
- Verify bootstrap IPs are correct and reachable
- Check that mesh network is up: `ip addr show wlan1`
- Verify firewall allows ports 4222 and 8000
- Ensure at least 2 nodes have OpenDHT running

### Restart OpenDHT
```bash
sudo /opt/nucleus/bin/opendht-start.sh
```

This script automatically stops and removes the old container before starting a new one.

## Disabling OpenDHT

To disable OpenDHT without removing files:
1. Edit `/etc/nucleus/mesh.conf`
2. Set `OPENDHT_ENABLED=false`
3. Restart mesh-start service or reboot

The startup script will skip OpenDHT initialization when disabled.

## Maintenance

### Updating Bootstrap List
When adding new permanent nodes:
1. Edit `/etc/nucleus/mesh.conf` on all nodes
2. Add new node IPs to `OPENDHT_BOOTSTRAP_IPS`
3. Restart OpenDHT: `/opt/nucleus/bin/opendht-start.sh`

### Checking DHT Health
Monitor connected peers:
```bash
watch -n 5 'curl -s http://127.0.0.1:8000/ | grep good'
```

## References
- **OpenDHT Documentation:** https://github.com/savoirfairelinux/opendht/wiki
- **Jami Documentation:** https://jami.net/
- **Full Implementation Plan:** `docs/VoIP/jami/jami_opendht_manet_plan.md`
