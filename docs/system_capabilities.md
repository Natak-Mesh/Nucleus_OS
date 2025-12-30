# Natak Nucleus Node - System Capabilities

## Core Systems (Active by Default)

### 1. WiFi Mesh Network
*The backbone that connects everything*

> Multiple Nucleus nodes automatically discover each other and create a secure, encrypted wireless network. Data hops from node to node until it reaches its destination. If one path gets blocked, traffic automatically finds another route—the network heals itself. This is the highway that most of the other services travel on.

---

### 2. Meshtastic / LoRa Radio
*Long-range communication when nothing else works*

> Built-in LoRa radio that can reach **miles** even through buildings, trees, and terrain that would block regular WiFi. Lower bandwidth (best for text and GPS), but works when you need extreme range or when the WiFi mesh can't reach. Managed through the official Meshtastic app on your phone.

---

### 3. Jami (Voice & Video)
*Secure calls without a phone company*

> Make encrypted voice and video calls directly between devices—no cell towers, no phone company, no central server. Works entirely over the mesh network. Uses OpenDHT to find other users without needing a directory server.

---

### 4. Reticulum Network Stack
*A flexible communications layer that runs over almost anything*

> Reticulum is a versatile overlay network that can carry encrypted communications over WiFi, LoRa, packet radio, serial connections, or even the internet. Currently configured as a passthrough—devices using Reticulum apps can talk to each other across the WiFi mesh.
> 
> *(Future: Can also bridge to Reticulum nodes over the internet via ethernet connection)*

---

### 5. Tailscale VPN
*Connect mesh networks across the globe*

> When a node has internet access, Tailscale lets you securely connect it to other nodes, servers, or infrastructure anywhere in the world. Primary use: linking remote mesh networks together or connecting nodes to central systems over the internet.

---

### 6. Ethernet / Internet Gateway
*Share one internet connection with everyone*

> Plug an ethernet cable into any node that has internet access, and that connection gets shared across the entire mesh. Everyone connected to any node can access the internet through that single uplink.

---

### 7. Web Dashboard
*Monitor and manage from any browser*

> Access a simple web interface to see real-time network status: which nodes are connected, signal strength, link quality. Change configuration settings without touching command lines. Includes **WiFi channel analysis**—scans nearby networks and shows which channels are congested so you can pick the clearest one.

---

## Optional Systems (Installed, Configured on Request)

### 8. TAKserver + MediaMTX
*Tactical mapping and live video*

> Situational awareness tools. Share GPS positions, draw on maps, and stream live video between team members. Used by emergency responders, search & rescue, and field teams who need to see where everyone is and share what they're seeing in real-time.

---

### 9. Mumble Server
*Push-to-talk voice channels*

> Low-latency voice server for team communication. Create channels, use push-to-talk, works like a radio net but over the mesh network. Good for coordinating groups who need quick voice comms.
>
> *Note: Mumble and Jami provide similar voice functionality. Jami is used by default because it's fully decentralized. Mumble is included and can be configured if a centralized voice server is preferred.*

---

## Summary View

| System | What It Does | Status |
|--------|--------------|--------|
| **WiFi Mesh** | Encrypted self-healing network backbone | ✅ Active |
| **Meshtastic/LoRa** | Miles-long range text & GPS | ✅ Active |
| **Jami** | Secure voice/video calls | ✅ Active |
| **Reticulum** | Flexible multi-transport comms | ✅ Active |
| **Tailscale** | VPN to remote infrastructure | ✅ Active |
| **Internet Gateway** | Share internet across mesh | ✅ Active |
| **Web Dashboard** | Monitoring, config, WiFi analysis | ✅ Active |
| **TAKserver + MediaMTX** | Tactical mapping & video | ⚙️ On Request |
| **Mumble** | Push-to-talk voice channels | ⚙️ On Request |
