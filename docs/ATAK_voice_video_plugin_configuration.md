# ATAK Voice & Video Plugin Configuration

## Voice Plugin

**Recommended Setting:** `udp://239.255.255.12:1024` (channel 1)

### Multicast Groups Used
The ATAK voice plugin uses multiple multicast groups:
- **239.255.255.1** - General voice traffic
- **239.255.255.2** - Contact discovery/presence announcements
- **239.255.255.12** - Voice channel 1 (239.255.255.11, .12, .13, etc. for multiple channels)
- **UDP Port:** 1024

### Required Configuration for Mesh Routing

#### 1. smcroute Configuration (`/etc/smcroute.conf`)

**CRITICAL:** Voice routes must NOT echo back to the input interface to prevent audio loops.

```bash
# ATAK Voice
mgroup from wlan1 group 239.255.255.1
mgroup from br-lan group 239.255.255.1
mroute from wlan1 group 239.255.255.1 to br-lan
mroute from br-lan group 239.255.255.1 to wlan1

# ATAK Voice - contact discovery
mgroup from wlan1 group 239.255.255.2
mgroup from br-lan group 239.255.255.2
mroute from wlan1 group 239.255.255.2 to br-lan
mroute from br-lan group 239.255.255.2 to wlan1

# ATAK Voice - channel_1
mgroup from wlan1 group 239.255.255.12
mgroup from br-lan group 239.255.255.12
mroute from wlan1 group 239.255.255.12 to br-lan
mroute from br-lan group 239.255.255.12 to wlan1
```

**Important:** Notice that `from wlan1` routes only output to `br-lan`, NOT `wlan1 br-lan`. Including wlan1 in the output creates an echo loop causing garbled, continuous audio.

#### 2. TTL Fix (iptables mangle rule)

**Problem:** ATAK sends voice multicast traffic with TTL=1, which gets dropped when forwarded through mesh routing (TTL decrements to 0).

**Solution:** Set TTL to allow multi-hop propagation for locally-originated voice traffic before routing.

**CRITICAL - DO NOT USE TTL=64:**
```bash
# WRONG - DO NOT USE - Causes multicast storms on 2+ node mesh
sudo iptables -t mangle -A PREROUTING -i br-lan -d 239.255.255.0/24 -j TTL --ttl-set 64
```

**CORRECT - Use TTL=4 to TTL=8:**
```bash
# CORRECT - Limits propagation to prevent storms
sudo iptables -t mangle -A PREROUTING -i br-lan -d 239.255.255.0/24 -j TTL --ttl-set 4
```

**Why TTL Matters:**
- TTL=64 allows packets to loop 32+ times between nodes before dying
- Combined with smcroute echo routing (`to wlan1 br-lan`), this creates catastrophic channel saturation
- TTL=4 allows 2-3 mesh hops while limiting echo loops to 2 round trips
- TTL=8 can support larger meshes (4-5 hops) with slightly higher loop risk

**Important:** The `-i br-lan` ensures this only applies to locally-originated traffic, not traffic already from the mesh (wlan1), preventing immediate routing loops.

To make this permanent, add to a startup script or save iptables rules.

**Testing Recommendations:**
- Start with TTL=4 for 2-3 node meshes
- Increase to TTL=6-8 only if voice doesn't reach distant nodes
- Monitor with `ip -s link show wlan1` for TX dropped packets
- If drops exceed 1K/minute, reduce TTL

#### 3. UFW Firewall Rules

Add rules for all voice multicast groups:

```bash
sudo ufw allow in on wlan1 to 239.255.255.1
sudo ufw allow in on br-lan to 239.255.255.1
sudo ufw allow in on wlan1 to 239.255.255.2
sudo ufw allow in on br-lan to 239.255.255.2
sudo ufw allow in on wlan1 to 239.255.255.12
sudo ufw allow in on br-lan to 239.255.255.12
sudo ufw allow 1024/udp
sudo ufw reload
```

### Troubleshooting

**Contacts don't appear in voice plugin:**
- Verify discovery traffic (239.255.255.2) is being routed
- Check UFW allows 239.255.255.2
- Verify iptables TTL rule exists: `sudo iptables -t mangle -L PREROUTING -n`
- Verify smcroute routes exist: `sudo smcroutectl show | grep 239.255.255`

**Garbled/continuous audio after pressing PTT:**
- Check smcroute config - routes from wlan1 should only output to br-lan, not back to wlan1
- Verify with: `cat /etc/smcroute.conf`

**Voice traffic not crossing mesh:**
- Check TTL of outgoing packets: `sudo tcpdump -i wlan1 -n -v 'net 239.255.255.0/24' -c 1`
- TTL should be 63 (64 minus 1 hop) after iptables mangle
- If TTL=1, the iptables rule isn't working

**Verify voice traffic flow:**
```bash
# Check local device sends voice traffic
sudo tcpdump -i br-lan -n 'net 239.255.255.0/24' -c 5

# Check traffic appears on mesh
sudo tcpdump -i wlan1 -n 'net 239.255.255.0/24' -c 5
```

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
