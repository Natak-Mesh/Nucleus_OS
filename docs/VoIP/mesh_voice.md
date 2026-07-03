# Mesh Voice — PTT Voice over the 802.11s Mesh

Real-time push-to-talk voice between Nucleus nodes, carried as UDP multicast
directly on the wlan1 mesh. One daemon per node (`openvlm-voice.py`, run by
`openvlm-voice.service`) with two interchangeable PTT front-ends that put
identical frames on the air and interoperate transparently:

- **Hardware PTT** — a tactical headset on the OpenVLM USB sound card
  (CM108, 0d8c:0012). Mic/speaker via ALSA, PTT via the HID GPIO. Hot-plugs:
  the daemon attaches/detaches it automatically; everything else keeps running
  on nodes with no OpenVLM.
- **Soft PTT** — a phone/browser on the node's Wi-Fi AP opens the `/voice`
  web page. The phone's own mic/speaker are the handset; audio streams to the
  daemon over a WebSocket. Requires HTTPS (browser mic policy).

## How it works

```
mesh wlan1  <── TX sender ──┬── OpenVLM mic   (while hardware PTT held)
UDP mcast                   └── phone mic     (while soft PTT held, via WS)
239.10.10.n
            ── RX ── per-source jitter buffers ── mixer ──┬── OpenVLM aplay
                                                          └── phone(s) via WS
```

- **Transport:** each voice channel N is multicast group `239.10.10.N` on UDP
  port 5555. 802.11s forwards multicast natively multi-hop (same as ATAK CoT);
  no smcroute involvement. TTL comes from `MESH_802_TTL`.
- **Audio format:** PCM S16_LE, 16 kHz mono, 20 ms frames (640 bytes).
  50 pkt/s while transmitting (~262 kbps). Packet = 14-byte header
  (`"NVOX"`, version, codec, node_id, channel, flags, seq) + one frame.
  `node_id` is the last octet of `MESH_IP`.
- **Receive path:** frames are demuxed per sending node into small jitter
  buffers (`VOICE_JITTER_MS`, default 80 ms). A self-clocked 20 ms mixer sums
  all active talkers (no floor control — simultaneous talkers overlay) and
  fans the mix out to every playback sink: the OpenVLM `aplay` and every
  connected phone. The mixer runs with or without hardware attached.
- **Channel switch** is live: the daemon leaves the old multicast group and
  joins the new one; no restart needed. All nodes must be on the same channel
  to hear each other.
- **Security:** no app-layer crypto — the mesh itself is SAE-encrypted at L2.
- **Latency:** ~150–200 ms mouth-to-ear at 1 hop (mostly the jitter buffer).

## Files

| file | purpose |
|---|---|
| `/opt/nucleus/bin/openvlm-voice.py` | the daemon: mesh TX/RX, jitter buffers, mixer, control socket, WebSocket server, OpenVLM hot-plug supervisor |
| `/etc/systemd/system/openvlm-voice.service` | runs the daemon as root (hidraw access); After=mesh-start; restarted by deploy.sh |
| `/usr/local/bin/voice` | user CLI (thin wrapper: systemctl + control socket) |
| `/opt/nucleus/web/templates/voice.html` | the `/voice` soft-PTT web page (forces itself onto HTTPS) |
| `/etc/nucleus/mesh.conf` | `VOICE_*` configuration (below) |
| `/opt/nucleus/bin/config_generation.sh` | generates the nginx glue: the voice snippet + `.local` vhost + IP-SAN self-signed cert |
| `/etc/nginx/snippets/nucleus-voice.conf` | generated: the `/voice-ws`, `/voice`, `/static` locations — included by the nucleus vhost and injected into the OTS 443 vhost so voice works by IP |
| `opt/nucleus/bin/archive/openvlm-monitor.py` | archived standalone hardware test tool (not in the live path, not deployed) |

## Configuration (`/etc/nucleus/mesh.conf`)

```
VOICE_CHANNEL=1                                  # startup channel -> 239.10.10.1
VOICE_CHANNELS="1:Command,2:Squad,3:Logistics"   # named channel picker list
VOICE_JITTER_MS=80                               # RX buffer; raise if choppy
VOICE_TX_GAIN=4                                  # software mic gain (OpenVLM path)
```

- `VOICE_CHANNELS` is a comma-separated `number:label` list (numbers 1–254).
  It is the **only** place channels are defined — the web page and CLI picker
  both render whatever this says. `VOICE_CHANNEL` picks the startup channel.
- Also read: `MESH_IP` (node_id + multicast egress interface) and
  `MESH_802_TTL` (multicast TTL).
- Apply changes with `voice restart` (or `sudo systemctl restart openvlm-voice`).

## Ports & control interfaces

| port | proto | bind | purpose |
|---|---|---|---|
| 5555 | UDP | wlan1 mcast | voice frames on the mesh |
| 5556 | UDP | 127.0.0.1 | control socket (CLI/scripts) |
| 5557 | TCP | 127.0.0.1 | WebSocket server (nginx proxies `/voice-ws` here) |

**Control socket** — plain-text commands, JSON replies:
`STATUS` (full state), `CHANNELS` (named list), `CHANNEL <n>` (live switch).
Example: `echo -n "CHANNEL 2" | nc -u -w1 127.0.0.1 5556`

**WebSocket** (`wss://<host>/voice-ws`) — text JSON for control
(`{"type":"ptt","down":bool}`, `{"type":"channel","n":N}`, status pushes from
the daemon) and raw binary 640-byte frames for audio in both directions.

**nginx glue:** browsers require HTTPS for mic capture, and phones may reach
the node by `.local` name or by IP. `config_generation.sh` writes one shared
snippet with the voice locations, includes it in both server blocks of the
nucleus `.local` vhost, and injects it into OpenTAKServer's 443 vhost (the
by-IP default on OTS nodes). The self-signed cert carries the node's IPs as
SANs so `wss://<ip>` passes TLS.

## Operations

```
voice start|stop|restart   # control the service
voice status               # channel, PTT state, active talkers, hardware
voice channels             # list configured named channels
voice channel N            # switch voice channel live (1-254)
voice log                  # follow the daemon log
```

Quick test: two nodes on the same channel, hold PTT (headset or web page) on
one and speak — heard on the other. `voice status` on the receiver lists the
talker's node_id in `sources`. Watch frames on the air with
`sudo tcpdump -n -i wlan1 udp port 5555`.

Tuning: too quiet/loud on the headset path → `VOICE_TX_GAIN`; choppy audio →
raise `VOICE_JITTER_MS` (at the cost of delay). Edit mesh.conf, `voice restart`.

## Future work

- Opus codec (~24 kbps, ~10x bandwidth cut) behind the header's codec byte
- Direct messaging to a specific node (header `flags` byte + a reserved
  channel range are set aside for this; RX already filters by node_id)
