# Nucleus Node — Private Communications Platform

The Nucleus node is a layered, infrastructure-independent communication system. Every layer is encrypted, decentralized, and operates without reliance on commercial services. Multiple independent communication paths mean that if one is compromised or blocked, others continue to function.

No cloud accounts. No call logs. No metadata collection. The operator controls all infrastructure.

---

## Part 1 — Capabilities

### At a Glance

| Layer | Tool | Status | Needs Internet? | Key Feature |
|-------|------|--------|-----------------|-------------|
| Voice & Video | Jami + OpenDHT | ✅ Ready | No | E2E encrypted calls, no servers, no accounts |
| Secure Messaging | Reticulum (Sideband/LXMF) | ✅ Ready | No | Sender-anonymous, forward secrecy |
| Long-Range Text | Meshtastic LoRa | ✅ Ready | No | Miles of range, AES-256, no carrier |
| Remote Link (managed) | Tailscale | ✅ Ready | Yes | WireGuard VPN, easy setup |
| Remote Link (sovereign) | Yggdrasil | ⚙️ Installed | Yes | Zero-dependency, DPI-resistant |
| Anonymous Uplink | Cellular + privacy SIM | ✅ Ready | Yes (creates it) | Prepaid, crypto-purchasable SIMs |
| Local Network | 802.11s Mesh | ✅ Ready | No | Encrypted, self-healing, no AP |

### Voice & Video — Jami + OpenDHT

Encrypted voice and video calls between any devices on the mesh. No phone company, no SIP server, no cloud accounts.

- OpenDHT runs on every node with network isolation — your DHT is invisible to the public internet
- Peer discovery is entirely within your network — no external observer can see who's calling whom
- Works fully offline (verified)
- Supports 1:1 and group encrypted messaging alongside voice/video
- **Works across Tailscale/Yggdrasil tunnels** — remote nodes add each other's tunnel IPs to `OPENDHT_BOOTSTRAP_IPS` and calls route transparently over the encrypted link

### Secure Messaging — Reticulum

The node runs a Reticulum transport instance that bridges encrypted traffic across whatever connectivity is available — the WiFi mesh, ethernet, cellular, or VPN tunnels. Your phone or laptop connects to the node and gains access to the entire Reticulum network through it.

Install a Reticulum app like **Sideband** on your device, point it at the node, and you have end-to-end encrypted messaging with forward secrecy and store-and-forward delivery. The node handles the routing — you don't need to care whether your message travels over the mesh, the internet, or both.

Packets don't reveal source addresses. Destinations are cryptographic hashes, not assigned addresses. Every link uses ephemeral keys. The protocol assumes the network is hostile.

Reticulum can peer with remote nodes over standard TCP connections or over a VPN, though given Reticulum's built-in encryption this is largely redundant — it's already encrypted end-to-end regardless of transport.

### Long-Range Text — Meshtastic LoRa

Encrypted text messaging and GPS over LoRa radio. Multi-mile range through terrain that blocks WiFi. No cell towers, no ISP, no infrastructure.

- AES-256 channel encryption — only nodes with the key can read traffic
- Dual-transport: LoRa for range, WiFi UDP for speed between nearby nodes
- No carrier records, no tower logs, no metadata trail
- Web UI for messaging — no phone app required

**Planned:** Codec2 voice notes (~2.5s encrypted voice clips in a single LoRa packet) and voice-text-voice bridge (speak → STT → LoRa → TTS → audio on the other end).

### Remote Linking — Tailscale vs. Yggdrasil

Both connect geographically separated nodes over the internet. Different tradeoffs.

| | Tailscale | Yggdrasil |
|---|---|---|
| Central dependency | Tailscale coordination server | **None** |
| Account required | Yes (Google/MS/etc) | **No** — local keypair only |
| NAT traversal | Excellent (DERP relays) | Good (TCP/TLS, no relay fallback) |
| Traffic signature | WireGuard — detectable by DPI | **Looks like normal TLS** — hard to block |
| Setup | Login and done | Config file + one public peer |
| Infrastructure | Tailscale's servers (or self-hosted Headscale) | **Your VPS** (existing Linode) |

**Tailscale** is the practical choice when ease of setup matters and you trust the coordination layer.

**Yggdrasil** is the privacy choice: no accounts, no identity linkage, traffic blends with normal HTTPS, and the only infrastructure is a VPS you already control. For operating in regions where VPN protocols are blocked or where zero external dependency is required, Yggdrasil is the answer.

Both carry Jami, Reticulum, and all other services transparently — they're just encrypted pipes.

### Anonymous Cellular Uplink

The SIM7600G-H 4G HAT provides WAN backhaul. Paired with a privacy-focused SIM, it creates an internet uplink with minimal identity linkage.

**Anonymous SIM providers:**

| Provider | Payment | KYC Required | Coverage | Notes |
|---|---|---|---|---|
| **Silent Link** (silent.link) | Bitcoin, Lightning, Monero | **None** — no name, no email | Global eSIM + physical SIM | Purpose-built for privacy |
| **Mint Mobile** (US retail) | Cash at Walmart/Target | Minimal | T-Mobile US | Activate with burner email |
| **TOTTL** (tottl.co) | Bitcoin, Monero | Minimal | EU focused | Privacy MVNO |

Silent Link is the standout — buy a SIM with Monero, no identity required, ships physical SIMs that work with the SIM7600G-H.

Combined with Yggdrasil (which looks like normal TLS to an ISP/carrier), the full path is: **anonymous SIM → encrypted Yggdrasil tunnel → private communication** — with no identity linkage at any point in the chain.

---

## Part 2 — Technical Reference

### Architecture: Local Mesh

```
┌─────────────────────────────────────────────────────────┐
│                    Nucleus Node                          │
│                                                          │
│  ┌──────────┐  ┌──────────┐  ┌────────┐  ┌───────────┐ │
│  │ Jami/DHT │  │Reticulum │  │LoRa/   │  │ Tailscale │ │
│  │ Voice/   │  │ LXMF/    │  │Mesh-   │  │ or        │ │
│  │ Video    │  │ Sideband │  │tastic  │  │ Yggdrasil │ │
│  └────┬─────┘  └────┬─────┘  └───┬────┘  └─────┬─────┘ │
│       │              │            │              │        │
│  ┌────┴──────────────┴────────────┴──────────────┴────┐  │
│  │              802.11s Encrypted Mesh (wlan1)         │  │
│  │              + br-lan (EUD access via wlan0/eth0)   │  │
│  └────────────────────────────────────────────────────┘  │
│       │                                      │           │
│  ┌────┴─────┐                          ┌─────┴────────┐  │
│  │ RAK4631  │                          │ SIM7600G-H   │  │
│  │ LoRa     │                          │ 4G Cellular  │  │
│  └──────────┘                          └──────────────┘  │
└─────────────────────────────────────────────────────────┘
```

EUDs (phones/laptops) connect to a node's AP or ethernet port. All services are reachable on the node's `br-lan` IP.

### Architecture: Distributed (Over Internet)

```
┌──────────┐     Yggdrasil/Tailscale      ┌──────────┐
│ Node A   │◄────── encrypted tunnel ─────►│ Node B   │
│ (City 1) │                               │ (City 2) │
└────┬─────┘                               └────┬─────┘
     │                                          │
     ▼                                          ▼
┌──────────┐          ┌──────────┐         ┌──────────┐
│ Local    │          │ Linode   │         │ Local    │
│ Mesh     │          │ Anchor   │         │ Mesh     │
│ Nodes    │          │ Peer     │         │ Nodes    │
└──────────┘          └──────────┘         └──────────┘
```

The Linode VPS serves as:
- **Reticulum transport node** (already running) — TCP peer for all field nodes
- **Yggdrasil anchor peer** (when implemented) — public TLS endpoint for node peering

### Jami Over Tunnels

No special configuration beyond adding remote IPs to the bootstrap list:

```bash
# In /etc/nucleus/mesh.conf on each node:
# Include both local mesh IPs AND remote tunnel IPs
OPENDHT_BOOTSTRAP_IPS="10.20.1.8,10.20.1.10,100.64.0.5,100.64.0.12"
#                       ^^^local mesh^^^       ^^^tailscale IPs^^^
```

OpenDHT connects across both local and tunnel interfaces. Jami calls route over whichever path is available.

### Reticulum Over Tunnels

Add a TCP client interface pointing at the remote node or Linode:

```ini
# In ~/.reticulum/config — add alongside existing interfaces

[[Remote Peer via Tailscale]]
type = TCPClientInterface
enabled = yes
target_host = 100.64.0.5       # Tailscale IP of remote node or Linode
target_port = 4242

# Or via Yggdrasil (when implemented):
# [[Remote Peer via Yggdrasil]]
# type = TCPClientInterface
# enabled = yes
# target_host = 200:xxxx::1    # Yggdrasil IPv6 of remote node
# target_port = 4242
```

Reticulum automatically discovers destinations across all connected interfaces. Sideband messages, LXMF delivery, and all Reticulum apps work transparently.

### Yggdrasil Implementation Path

Currently installed but not configured. Implementation requires:

1. **On Linode (anchor peer):**
   ```bash
   apt install yggdrasil
   # Edit /etc/yggdrasil/yggdrasil.conf:
   #   Listen: ["tls://0.0.0.0:443"]    # Looks like HTTPS traffic
   systemctl enable --now yggdrasil
   # Note the Linode's Yggdrasil IPv6 address:
   yggdrasilctl getself
   ```

2. **On each Nucleus node:**
   ```bash
   # Edit /etc/yggdrasil/yggdrasil.conf:
   #   Peers: ["tls://<linode-ip>:443"]
   systemctl enable --now yggdrasil
   ```

3. **Verify:** Nodes get `200::/7` addresses. Ping between them over Yggdrasil IPv6.

4. **Integration:** Add Yggdrasil config to `mesh.conf`, start script, and web UI page (same pattern as Tailscale).

That's it. Once peered, every node can reach every other node via stable Yggdrasil IPv6 — no accounts, no coordination server, traffic indistinguishable from TLS.

### Anonymous Uplink Chain

The full privacy chain when combining all layers:

```
Phone/Laptop
    │
    ▼ (connects to node AP — local WiFi, no ISP involvement)
Nucleus Node
    │
    ├─► Jami call ──► OpenDHT ──► direct to other node (mesh or tunnel)
    ├─► Sideband msg ──► Reticulum ──► LXMF delivery (mesh or tunnel)
    ├─► LoRa text ──► Meshtastic ──► RF to remote node (no internet)
    │
    ▼ (for internet-connected operation)
SIM7600G-H Cellular (anonymous SIM — Silent Link via Monero)
    │
    ▼ (carrier sees TLS traffic to a VPS — nothing else)
Yggdrasil tunnel to Linode anchor
    │
    ▼ (encrypted overlay — Linode peers nodes together)
Remote Nucleus Node(s)
```

At no point does an external observer see:
- Who is communicating with whom
- What is being communicated
- The identity of the operator

The carrier sees TLS connections to a VPS. The VPS sees Yggdrasil peer traffic. Neither can read content or determine endpoints.

### What's Ready vs. What Needs Work

| Component | Status | Work Remaining |
|---|---|---|
| Jami + OpenDHT (local mesh) | ✅ Production | None |
| Jami over Tailscale tunnel | ✅ Works now | Add tunnel IPs to bootstrap config |
| Reticulum transport (local) | ✅ Production | None |
| Reticulum over Tailscale | ✅ Works now | Add TCPClientInterface to config |
| Meshtastic LoRa messaging | ✅ Production | None |
| Tailscale VPN | ✅ Production | None |
| Yggdrasil overlay | ⚙️ Installed | Config, systemd service, web UI page |
| Yggdrasil on Linode | ⚙️ Not started | Install + listen config |
| Jami/Reticulum over Yggdrasil | ⚙️ Not tested | Same as Tailscale — just use Ygg IPs |
| Anonymous SIM procurement | 📋 Research | Purchase + test Silent Link SIM |
| Codec2 LoRa voice notes | 📋 Planned | Full implementation needed |
