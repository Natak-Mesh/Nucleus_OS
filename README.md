# Use Cases: 
## ATAK / Takserver
## Data
### Wi-Fi IP Mesh Network
- Reticulum
## Text
### Meshtastic
- Onboard stand along Meshtastic node. Interface via official application over BT
### Reticulum
- Onboard transport instance. Connected/configured Reticulum devices can communicate over the mesh network
### Jami
- Direct and group text
## VOIP
### Jami
- Direct and group calls, PTT or full tim voice functionality
### Reticulum
- Voice messages via Sideband
## VPN
- Onboard Tailscale instance pre-configured to the natakmesh Tailnet but avialable to user to add their own
## Internet Gateway
- Any mesh node can be connected to an Internet source and pass that connection out across the mesh

# Interfaces
## Wi-Fi
### 2.4 GHz 802.11s mesh network on wlan1. 
- WPA3 encryption
- Unicast routing via babeld, multicast routing via smcroute
## LoRa
### Onboard RAK4631 LoRa radio running Meshtastic firmware
- Interface via the Meshtastic official application
- Powered by USB connection to radio SBC
- USB connection provides data path, can be configured to run Rnode firmware or interact with Meshtastic CLI on radio
## Ethernet
### eth0 
- Can either provide internet access to the node to be passed to mesh, or can provide local hard line access for devices to connect to mesh
## Onboard Access Point
### Pi onboard Wi-Fi (wlan0) in AP mode
- 5.8GHz AP to connect external devices to the mesh node
