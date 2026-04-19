# Use Cases: Capabilities provided by the current Nucleus units.
## ATAK / Takserver
### ATAK EUD
- Connected ATAK EUD's will automatically discover other EUD's connected to the IP mesh network
- ATAK CoT bridge transparently forwards SA and chat between the local multicast LAN and remote nodes over Meshtastic LoRa -- no ATAK plugin required on the EUD
- Enough throughput for instant position and text updates along with pictures,video, routes, etc
### TAKserver
- OpenTAKserver can be installed to run locally on the Nucleus
- Included Mediamtx install allows video to be streamed to OpenTAKserver and distributed out to other devices on the IP mesh network.
## Data
### Wi-Fi IP Mesh Network
- Any program using an IP network connection
- Reticulum
## Text
### Meshtastic
- Onboard Meshtastic node operating in bridge mode (default) or BLE mode
- Bridge mode: Nucleus owns the radio over serial, bidirectionally bridges ATAK CoT (SA + chat) between the IP mesh multicast LAN and LoRa
- BLE mode: radio released to Bluetooth for the official Meshtastic phone app
- Mode toggled via Nucleus web UI or REST API
### Reticulum
- Onboard transport instance. Connected/configured Reticulum devices can communicate over the mesh network
### Jami
- Direct and group text
## VOIP
### Jami
- Direct and group calls, PTT or full time voice functionality
### Reticulum
- Voice messages via Sideband
## VPN
- Onboard Tailscale instance pre-configured to the natakmesh Tailnet but available to user to add their own
## Internet Gateway
- Any mesh node can be connected to an Internet source and pass that connection out across the mesh

# Interfaces
## Wi-Fi
### 2.4 GHz 802.11s mesh network on wlan1. 
- WPA3 encryption
- Unicast routing via babeld, multicast routing via smcroute
## LoRa
### Onboard RAK4631 LoRa radio running Meshtastic firmware
- Powered via USB from the Pi SBC
- Bridge mode (default): serial connection used by cot_bridge daemon to forward ATAK CoT over LoRa (portnum 257, ATAK Forwarder protocol)
- BLE mode: serial released, radio available to the official Meshtastic phone app over Bluetooth
## Ethernet
### eth0 
- Can either provide internet access to the node to be passed to mesh, or can provide local hard line access for devices to connect to mesh
## Onboard Access Point
### Pi onboard Wi-Fi (wlan0) in AP mode
- 5.8GHz AP to connect external devices to the mesh node
