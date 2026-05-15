# Nucleus Node — Private Communications Platform

The Nucleus node is a layered, infrastructure-independent communication system. Every layer is encrypted, decentralized, and operates without reliance on commercial services. Multiple independent communication paths mean that if one is compromised or blocked, others continue to function.

No cloud accounts. No call logs. No metadata collection. The operator controls all infrastructure.

---

## Part 1 — Capabilities

### At a Glance

| Layer | Tool | Status | Needs Internet? | Key Feature |
|-------|------|--------|-----------------|-------------|
| Voice & Video | Jami + OpenDHT | Ready | No | E2E encrypted calls, no servers, no accounts |
| Secure Messaging | Reticulum (Sideband/LXMF) | Ready | No | Sender-anonymous, forward secrecy |
| Long-Range Text | Meshtastic LoRa | Ready | No | Miles of range, AES-256, no carrier |
| Remote Link (managed) | Tailscale | Ready | Yes | WireGuard VPN, easy setup |
| Remote Link (sovereign) | Yggdrasil | Installed | Yes | Zero-dependency, DPI-resistant |
| Anonymous Uplink | Cellular + privacy SIM | Ready | Yes (creates it) | Prepaid, crypto-purchasable SIMs |
| Local Network | 802.11s Mesh | Ready | No | Encrypted, self-healing, no AP |

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
| Traffic signature | WireGuard — easily identified by DPI | **Harder to identify** — but not invisible to targeted DPI (see [Traffic Obfuscation](#traffic-obfuscation--dpi-resistance)) |
| Setup | Login and done | Config file + one public peer |
| Infrastructure | Tailscale's servers (or self-hosted Headscale) | **Your VPS** (existing Linode) |

**Tailscale** is the practical choice when ease of setup matters and you trust the coordination layer.

**Yggdrasil** is the privacy choice: no accounts, no identity linkage, and the only infrastructure is a VPS you already control. For operating in regions where VPN protocols are blocked or where zero external dependency is required, Yggdrasil is the answer.

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
```

#### Reticulum Over Yggdrasil (Encapsulated)

When Yggdrasil is running, Reticulum can peer using Yggdrasil IPv6 addresses instead of (or in addition to) Tailscale IPs. This wraps Reticulum traffic inside the Yggdrasil tunnel — the physical network only sees the Yggdrasil connection on port 443, never the Reticulum traffic on port 4242.

**On the VPS** — configure a TCPServerInterface bound to its Yggdrasil address:

```ini
# In ~/.reticulum/config on the VPS

[[Yggdrasil Transport]]
type = TCPServerInterface
enabled = yes
listen_host = 200:xxxx::1       # VPS Yggdrasil IPv6 (from yggdrasilctl getSelf)
listen_port = 4242
```

**On each local node** — configure a TCPClientInterface targeting the VPS through the tunnel:

```ini
# In ~/.reticulum/config on each node

[[Remote Peer via Yggdrasil]]
type = TCPClientInterface
enabled = yes
target_host = 200:xxxx::1       # Same VPS Yggdrasil IPv6
target_port = 4242
```

This gives you a fallback path: if the standard Reticulum TCP interface can't get through (port 4242 blocked, restrictive NAT), the Yggdrasil tunnel on port 443 carries it instead. Reticulum automatically discovers destinations across all connected interfaces — Sideband messages, LXMF delivery, and all Reticulum apps work transparently regardless of which transport is active.

### Yggdrasil Implementation Path

Currently installed but not configured. Implementation requires:

1. **On Linode (anchor peer):**
   ```bash
   apt install yggdrasil
   # Edit /etc/yggdrasil/yggdrasil.conf:
   #   Listen: ["tls://0.0.0.0:443"]
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

That's it. Once peered, every node can reach every other node via stable Yggdrasil IPv6 — no accounts, no coordination server.

#### Why Port 443

The VPS should listen on TCP port 443 for Yggdrasil peering. This is a deliberate choice, not arbitrary:

**Egress filtering** — Most firewalls (corporate, hotel, public Wi-Fi) block outgoing traffic on non-standard ports. Port 51820 (WireGuard/Tailscale default) and random high ports are commonly blocked. Port 443 is the standard HTTPS port — blocking it would break the internet for all users, so it is nearly always allowed. This means your nodes can dial out to the VPS from almost any network.

**Listening vs. connecting** — Only the VPS needs port 443 free. The local nodes *connect to* the VPS on 443 — they don't listen on it. Outbound connections use an ephemeral port (random high number) on the local side. So the local node can still browse the web, run a local web server, or do anything else on 443 without conflict.

**Port conflicts on the VPS** — Only one process can bind to a given port. Since the VPS is a dedicated mesh gateway (not hosting a website), port 443 is sitting empty and Yggdrasil can take it. If you later add a web server, you have three options:
- Move Yggdrasil to a different port (e.g., 8443)
- Use a secondary IP address (bind web server to IP_A:443, Yggdrasil to IP_B:443)
- Use a port multiplexer like `sslh` to inspect incoming packets and route HTTPS to the web server and Yggdrasil traffic to the Yggdrasil process

#### TCP vs. TLS Peering

Yggdrasil supports two TCP-based peering schemes:

- `tcp://` — Standard TCP. Works through most firewalls but the packet structure doesn't look like real HTTPS. A firewall doing DPI could identify it.
- `tls://` — Wraps the connection in a TLS tunnel. Significantly better at passing through firewalls that inspect traffic on port 443 to verify it's actually HTTPS.

For maximum compatibility, the VPS can listen on both:

```json
Listen: [
  "tcp://0.0.0.0:443",
  "tls://0.0.0.0:8443"
]
```

Local nodes peer with whichever works:

```json
Peers: [
  "tcp://your.vps.ip:443",
  // OR for better stealth:
  "tls://your.vps.ip:8443"
]
```

**Note:** Binding to ports below 1024 requires the Yggdrasil process to run as root or have `CAP_NET_BIND_SERVICE`.

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

---

## Part 3 — Network Traversal & Connectivity Reference

Remote access issues generally fall into three categories: **traversal failures** (can't connect), **performance bottlenecks** (connected but degraded), and **security friction** (blocked by policy).

### NAT Types & Traversal

Network Address Translation (NAT) maps one public IP to many private ones. Problems arise when NAT behaves restrictively.

**Symmetric NAT** — The hardest case. Unlike standard NAT, symmetric NAT assigns a different external port for every destination you talk to. This breaks UDP hole punching.
- *Tailscale:* Fails to connect directly and drops to a DERP relay. Adds latency (often +50–200ms) and caps speed.
- *Yggdrasil:* If both you and your peer are behind symmetric NAT, you can't peer directly. The VPS anchor solves this — both nodes dial out to the VPS, which acts as the meeting point.

**Carrier-Grade NAT (CGNAT)** — Common on 5G, mobile, and Starlink. You don't have a public IP; your ISP shares one across hundreds or thousands of customers. Forces Tailscale to use DERP relays and makes direct Yggdrasil peering impossible without a public-facing peer (the VPS).

**Double NAT** — Your router is plugged into another router (e.g., your own router behind an ISP gateway). Adds an extra layer of translation that confuses STUN/ICE protocols used for discovering your public address. Often causes direct connections to fail silently.

### Firewalls & Protocol Blocking

**Deep Packet Inspection (DPI)** — Advanced firewalls (Fortinet, Palo Alto, or state-level systems) can recognize WireGuard or Yggdrasil packets by their headers and drop them, even if the port is open. See [Traffic Obfuscation](#traffic-obfuscation--dpi-resistance) for details.

**UDP throttling/blocking** — Some public Wi-Fi (hotels, airports, planes) blocks all UDP traffic except DNS.
- *Tailscale:* Falls back to DERP relays, which use HTTPS/TCP over port 443 to bypass this.
- *Yggdrasil:* Can be configured to use TCP or TLS peering instead of UDP to get through these restrictions.

**Local firewalls (UFW, Windows Firewall)** — On Linux, if you don't explicitly allow the `tailscale0` or `tun0` (Yggdrasil) interfaces in UFW, services (SSH, web) will silently ignore incoming tunnel traffic. On Windows, virtual adapters are often marked as "Public" networks, which triggers the most restrictive firewall profile by default.

**Inbound vs. outbound rules** — Dialing *out* to a public node bypasses inbound firewall rules (rules that block connections *to* you). It does not bypass outbound rules (rules that block connections *from* you). If a corporate or hotel firewall blocks all outbound traffic except web ports (80/443), your Yggdrasil node won't be able to dial out unless it's configured to use a permitted port — which is why the VPS listens on 443.

### MTU (Maximum Transmission Unit)

MTU is the size of the largest packet a network link can carry. VPN encapsulation adds headers that make packets bigger.

**Fragmentation** — If the encapsulated packet exceeds the physical wire's MTU (usually 1500 bytes), it must be fragmented. This kills performance and can cause connections to "hang" — the classic symptom is SSH connects fine but freezes when you run `ls -l` or transfer files.

- *Tailscale:* Uses a default MTU of 1280. If your underlying connection (PPPoE, satellite) needs something lower, large data transfers may fail or stall.
- *Yggdrasil:* Uses a large internal MTU (65535) and handles fragmentation into TCP streams internally. Generally avoids standard MTU headaches.

**Diagnosis:** `ping -s 1400 <IP>` — if you see packet loss at 1400 bytes but not at 1200, you have an MTU issue.

### IP Conflicts & Routing

**Subnet overlap** — If your home network uses `192.168.1.x` and the remote network also uses `192.168.1.x`, your computer won't know which one you're talking to.

This is mostly a non-issue for Tailscale and Yggdrasil:
- *Tailscale:* Assigns every node an IP in the `100.64.0.0/10` range, which rarely conflicts with home or office networks.
- *Yggdrasil:* Uses a unique IPv6 prefix (`200::/7`) that doesn't exist on the public internet or local LANs. Conflicts are virtually impossible.

The caveat: subnet overlap becomes an issue if you use **subnet routing** (e.g., using Tailscale to expose an entire physical `192.168.1.0/24` network behind a node to the tailnet).

**IPv6 readiness** — Yggdrasil is natively IPv6. If your OS has IPv6 disabled at the kernel level (`net.ipv6.conf.all.disable_ipv6 = 1` in sysctl), Yggdrasil will fail to create its virtual interface.

### Troubleshooting Quick Reference

| Issue | Symptom | How to Check |
|---|---|---|
| DERP relay usage | High latency, slow speed | `tailscale status` — look for "relay" |
| Blocked UDP | No connection at all | `tailscale netcheck` — check UDP status |
| MTU problems | SSH works, but file transfers or htop freeze | `ping -s 1400 <IP>` — check for packet loss |
| Symmetric NAT | Direct connection impossible | `tailscale netcheck` — look for `MappingVariesByDestIP: true` |
| Yggdrasil IPv6 failure | Interface won't come up | Check `sysctl net.ipv6.conf.all.disable_ipv6` is 0 |
| Local firewall blocking tunnel | Services unreachable over VPN | `sudo ufw status` — check tunnel interface is allowed |

---

## Part 4 — Traffic Obfuscation & DPI Resistance

### What Yggdrasil Actually Hides (And What It Doesn't)

Yggdrasil traffic is harder to identify than WireGuard because it doesn't have the same "loud" handshake pattern. But it is **not invisible**. An ISP or firewall using Deep Packet Inspection can identify Yggdrasil by its packet headers and port behavior if they are specifically looking for it. It is "obscure" compared to mainstream VPNs, but not cryptographically steganographic.

For most use cases — dialing out from a home network, a coffee shop, or a mobile hotspot — Yggdrasil on port 443 with TLS peering is more than sufficient. The traffic looks like a long-lived TLS connection to a VPS, which is unremarkable.

The problems start with state-level or enterprise-grade DPI that actively profiles traffic.

### Passive DPI Techniques

These are methods a firewall uses to identify VPN/proxy traffic without actively probing your server:

**Protocol fingerprinting** — DPI identifies the specific handshake signature of a protocol as packets pass through. If the protocol is recognized, the connection is dropped before it ever completes.

**TLS fingerprinting (JA3/JA4)** — Firewalls analyze the Client Hello packet of a TLS handshake. If the cipher suites and extensions don't match a legitimate web browser (Chrome, Firefox), the connection is flagged as a proxy or bot.

**Entropy analysis** — Encrypted VPN traffic appears as high-entropy "random" data. Standard HTTPS traffic has a predictable structure (headers, content types). DPI identifies these statistical differences to flag unidentified encrypted streams.

**Traffic pattern analysis** — Web browsing is "bursty" (request, then multiple small downloads). VPN or mesh traffic is often a continuous, long-lived stream. This behavioral mismatch allows firewalls to identify proxies even if the protocol itself is perfectly obfuscated.

**SNI filtering** — In a standard TLS handshake, the destination domain is sent in plaintext (Server Name Indication). If the domain doesn't match a whitelist or is associated with a known VPS provider, the connection is terminated.

### Advanced Bypass Methods (Reference Only)

These are tools designed to defeat state-level DPI. They are documented here for awareness — none are currently implemented in the Nucleus stack.

**Trojan / Trojan-Go** — Wraps traffic in standard TLS. Designed to be indistinguishable from HTTPS. If the firewall probes the IP, it sees a functional web server instead of a proxy.

**Xray/V2Ray with REALITY** — "Borrows" the TLS certificate and handshake of a popular, unblocked website (e.g., microsoft.com). The firewall cannot block the connection without blocking the legitimate site it's mimicking.

**Shadowsocks (AEAD)** — Encrypts packets to look like random noise. Effective against basic filters but increasingly susceptible to behavioral analysis. Often paired with a plugin (v2ray-plugin) for additional masking.

**CDN tunneling** — Routes traffic through a Content Delivery Network (like Cloudflare). The firewall sees a connection to a reputable CDN IP rather than a private VPS.

**Active probing defense** — Configure the VPS to serve a real, benign website on the same port. When a firewall probes the port to see what's running, it gets a normal web page, hiding the proxy service behind it. Note: this only defeats active probing — it does not bypass passive DPI or behavioral analysis.

### Practical Implications for Nucleus

| Environment | Risk Level | Sufficient Approach |
|---|---|---|
| Home network, mobile hotspot | Low | Standard Yggdrasil peering on any port |
| Public Wi-Fi (hotel, airport) | Medium | Yggdrasil TLS peering on port 443 |
| Corporate network with DPI | Medium-High | Yggdrasil TLS on 443; may need Tailscale DERP fallback |
| State-level censorship (e.g., GFW) | High | Requires steganographic protocols (Trojan, REALITY) — beyond current scope |

For the target use case — field-deployed nodes connecting back to a VPS anchor — TLS peering on port 443 handles the vast majority of restrictive networks. Full anti-censorship tooling is a separate project.

---

## Status Summary

| Component | Status | Work Remaining |
|---|---|---|
| Jami + OpenDHT (local mesh) | Production | None |
| Jami over Tailscale tunnel | Working | Add tunnel IPs to bootstrap config |
| Reticulum transport (local) | Production | None |
| Reticulum over Tailscale | Working | Add TCPClientInterface to config |
| Reticulum over Yggdrasil | Not tested | TCPServer on VPS, TCPClient on nodes using Ygg IPv6 |
| Meshtastic LoRa messaging | Production | None |
| Tailscale VPN | Production | None |
| Yggdrasil overlay | Installed | Config, systemd service, web UI page |
| Yggdrasil on Linode | Not started | Install + listen config (port 443) |
| Jami over Yggdrasil | Not tested | Same as Tailscale — just use Ygg IPs |
| Anonymous SIM procurement | Research | Purchase + test Silent Link SIM |
| Codec2 LoRa voice notes | Planned | Full implementation needed |
