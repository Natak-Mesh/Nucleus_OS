# OpenTAK ICU + MediaMTX Video Streaming

MediaMTX authenticates all connections through OpenTakServer. Both the streaming EUD and viewing EUD must provide their OTS user credentials.

---

## OpenTAK ICU Plugin Settings (Streaming EUD)

**Stream Settings:**
- **Stream Protocol:** RTSP
- **Stream Address:** 10.20.xx.1 (br-lan IP of node running MediaMTX)
- **Stream Port:** 8554
- **Stream Path:** mystream (configurable, docs assume this path)
- **TCP:** ON
- **Username:** This EUD's OTS username (e.g., `eud1`)
- **Password:** This EUD's OTS password

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

---

## ATAK Video Stream Settings (Viewing EUD)

- **Protocol:** RTSP
- **Address:** `<MediaMTX-IP>` (br-lan IP of node running MediaMTX)
- **Port:** 8554
- **Path:** `mystream` (no leading /)
- **Username:** This viewing EUD's OTS username (e.g., `eud2`)
- **Password:** This viewing EUD's OTS password
- **Secure:** Off

---

## Notes

- Each EUD authenticates with **its own** OTS account — the streaming EUD uses its credentials to publish, the viewing EUD uses its credentials to read
- Do not prefix path with `/` in ATAK
- Enable AAC audio in OpenTAK ICU
- Force TCP in MediaMTX to avoid UDP/NAT issues
- Test with: `ffplay rtsp://<username>:<password>@<MediaMTX-IP>:8554/mystream`
- Workflow: OpenTAK ICU → RTSP → MediaMTX → OTS auth → ATAK Clients
