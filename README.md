# Use Cases: 
## General IP Mesh Network
- Nucleus nodes automatically form an 802.11s mesh network with other nodes configured to be on the same mesh
- Each node expands the mesh network, messages/data automatically path via whatever combination of nodes can "see" each other. Potentially giving much better coverage than a smaller number of highpower units. The solution to range/coverage with mesh networks is density. The more nodes that are added the better the coverage.
## ATAK/Tak Server
- Connected ATAK EUD's will automatically take advantage of the Nucleus IP Mesh network to connect to other ATAK devices on the mesh. Wi-Fi can give enough bandwidth for pictures / video streaming in addition to effectively instant position/text updates
- Takserver can be run on the Nucleus to provide a portable server that stays with the user
- ATAK can take advantage of the onboard Meshtastic radio with the official Meshtastic ATAK plugin giving a long range/low throughput data connection in addition to the IP mesh
## Meshtastic
- Onboard RAK4631 Meshtastic radio, acts just like a stand alone unit. Powered by the Nucleus, interface via the official Meshtastic app.
## Reticulum
- Onboard Reticulum instance. Configured as a transport instance for devices connected via wlan0 or eth0. Will work across mesh network or itnernet if connected
- Interface for Btech UV-Pro can be activated
## "Off Grid" text/VoIP
- Jami can take advantage of onboard OpenDHT server for text and voice over the IP mesh network
## Internet Gateway
- If set in WAN mode, ethernet connection can pass internet back to mesh network
## Wi-Fi Scanning
- Airmon package allows scanning of the local 2.4 GHz environment to allow selection of the least congested band for mesh connections.
- Part of the Aircrack-NG tool suite that can be configured to users desire
## Tailscale
- Tailscale instance for user configured VPN.
- Will come preconfigured with the natak tailnet to allow remote updates and troubleshooting if desired. User activated and can be switched as desired via web UI
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
