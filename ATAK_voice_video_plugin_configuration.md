# ATAK Voice & Video Plugin Configuration

## Voice Plugin

**Recommended Setting:** `udp://239.255.255.1:1024`

To change the voice address/port, you must update:
1. `/etc/smcroute.conf` - Add/modify the multicast group and routes
2. UFW firewall rules - Allow the new multicast address and UDP port

## Video Plugin (OpenTAK ICU)

### OpenTAK ICU Plugin Settings

**Stream Settings:**
- **Stream Protocol:** RTSP
- **Stream Address:** 10.20.xx.1 (br-lan IP of node running MediaMTX)
- **Stream Port:** 8554
- **Stream Path:** mystream (configurable, docs assume this path)
- **TCP:** ON

**Video Preferences:**
- **Video Source:** This device's camera
- **Resolution:** 800x600 (configurable)
- **Bitrate:** 1000
- **Adaptive Bitrate:** ON
- **FPS:** 24 (configurable)
- **Codec:** H264

**Audio Settings:**
- **Enable Audio:** ON
- **Bitrate:** 128
- **Sample Rate:** 44100
- **Codec:** AAC
- **Stereo, Echo Canceller, Noise Suppressor:** ON

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
