# ATAK Voice & Video Plugin Configuration

## Voice Plugin

**Recommended Setting:** `udp://239.255.255.1:1024`

To change the voice address/port, you must update:
1. `/etc/smcroute.conf` - Add/modify the multicast group and routes
2. UFW firewall rules - Allow the new multicast address and UDP port

## Video Plugin (OpenTAK ICU)

### OpenTAK ICU Plugin Settings
- **RTSP URL:** `rtsp://<MediaMTX-IP>:8554/mystream`
- **Video Codec:** H.264, Baseline profile, yuv420p
- **Audio Codec:** AAC, 44100 Hz, Stereo, 128 kbps
- **Secure:** Off

### TAKServer Feed Settings (Video Tab)
- **Protocol:** RTSP
- **Address:** `<MediaMTX-IP>`
- **Port:** 8554
- **Path:** `mystream` (no leading /)
- **Auth:** Leave blank if no auth required
- **Secure:** Off

### Notes
- Do not prefix path with `/` in TAKServer
- Enable AAC audio in OpenTAK ICU
- Force TCP in MediaMTX to avoid UDP/NAT issues
- Test with: `ffplay rtsp://<MediaMTX-IP>:8554/mystream`
- Workflow: OpenTAK ICU → RTSP → MediaMTX → TAKServer → ATAK Clients
