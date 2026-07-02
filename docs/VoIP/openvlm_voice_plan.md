# OpenVLM Voice — Mesh PTT Voice Transmission

Status: Phase 1/2 first pass built (PTT TX + additive RX mixing, fixed channel w/ runtime switch hook)

## Overview

`openvlm-voice.py` is a daemon that provides push-to-talk voice comms between
Nucleus nodes over the wlan1 802.11s mesh. It uses the OpenVLM USB sound card
(C-Media CM108, 0d8c:0012) for mic/headset audio and its HID GPIO for PTT.

Key properties:

- **Transport:** UDP multicast directly on wlan1. One multicast group per
  voice channel: `239.10.10.<channel>`, UDP port 5555.
- **No smcroute involvement.** The daemon lives on the node and transmits on
  wlan1 itself. 802.11s handles multi-hop multicast natively (mesh_fwding=1,
  RMC dedup), same as ATAK CoT. TTL is set to `MESH_802_TTL` (default 8).
- **Additive audio:** there is no floor control. Every node transmits whenever
  its PTT is held. The receiver keeps a per-source jitter buffer and *mixes*
  all active sources together (sum + clamp), so simultaneous talkers are all
  heard, overlaid.
- **No app-layer crypto.** The 802.11s mesh is SAE-encrypted at L2.

## Packet Format

```
struct, little-endian:
  4s  magic      "NVOX"
  B   version    1
  B   codec      0 = PCM S16_LE 16 kHz mono
  H   node_id    last octet of MESH_IP (unique per node)
  B   channel    voice channel number (1-254)
  B   flags      reserved (0)
  I   seq        per-transmission incrementing frame counter
  --  payload    640 bytes = 320 samples = 20 ms of audio
```

Total: 14-byte header + 640-byte payload = 654 bytes per packet, 50 pkt/s
while transmitting (~262 kbps). Phase 4 (Opus @ ~24 kbps) cuts this ~10x.

## Audio Pipeline

```
TX:  hidraw PTT ──> gate ──> arecord 16k mono S16 raw ──> 20ms frames ──> mcast send
RX:  mcast recv ──> filter (own id, wrong channel) ──> per-source jitter buffers
         ──> additive mixer (sum + clamp) ──> aplay 16k mono S16 raw
```

- `arecord`/`aplay` use `plughw:<card>,0` so ALSA resamples 16 kHz to the
  card's native 48 kHz.
- The mixer loop is **self-clocked by aplay**: it blocking-writes one 20 ms
  frame (mixed audio, or silence when idle) per iteration, so aplay's
  real-time consumption paces the loop. No sleep-drift issues.
- Each source must accumulate `VOICE_JITTER_MS` (default 80 ms = 4 frames)
  before playback starts, absorbing mesh jitter. A source that runs dry
  re-buffers; a source idle >1 s is dropped from the mixer.
- Own packets are excluded twice: `IP_MULTICAST_LOOP` off + node_id filter.

### Latency budget (mouth-to-ear, 1 hop)

| stage | ms |
|---|---|
| ALSA capture | 20–40 |
| frame accumulation | 20 |
| network (802.11s) | 1–5 (+2–5/extra hop) |
| jitter buffer | 80 (VOICE_JITTER_MS) |
| playback buffer | 20–50 |
| **total** | **~150–200** |

Tunable down to ~100 ms via VOICE_JITTER_MS and ALSA buffer params.

## Configuration (`/etc/nucleus/mesh.conf`)

```
VOICE_CHANNEL=1       # startup channel -> group 239.10.10.1
VOICE_JITTER_MS=80    # per-source RX buffer before playback starts
VOICE_TX_GAIN=4       # software mic gain applied before transmit
```

Also read: `MESH_IP` (node_id + multicast egress interface selection),
`MESH_802_TTL` (multicast TTL). Restart the service after changing:
`sudo systemctl restart openvlm-voice` (or `voice restart`).

## User Interface: the `voice` command

Installed to `/usr/local/bin/voice` by deploy.sh. This is the primary way to
interact with the voice system:

```
voice start        # start the voice service
voice stop         # stop the voice service
voice restart      # restart (e.g. after mesh.conf changes)
voice status       # service state + JSON status (channel, PTT, talkers)
voice channel 2    # switch to voice channel 2 (live, no restart)
voice log          # follow the live daemon log (Ctrl-C to exit)
```

Example `voice status` output:

```
service: active
{"ok": true, "node_id": 22, "channel": 1, "group": "239.10.10.1",
 "ptt": false, "sources": [], "card": 1, "hardware": true}
```

Field meanings: `node_id` = last octet of MESH_IP; `ptt` = PTT currently
held on this node; `sources` = node_ids currently being received/mixed;
`card` = ALSA card number of the OpenVLM; `hardware` = OpenVLM detected.

## Control Socket (hooks for web UI / channel switching)

UDP on `127.0.0.1:5556`, plain-text commands, JSON replies. This is the seam
the Flask web UI will use later.

| command | reply |
|---|---|
| `STATUS` | `{"node_id":9,"channel":1,"ptt":false,"sources":[...],"card":1}` |
| `CHANNEL <n>` | switches channel live (leave old group, join new) `{"ok":true,"channel":n}` |

Example: `echo -n "CHANNEL 2" | nc -u -w1 127.0.0.1 5556`

## Hardware resilience

The daemon waits in a retry loop until the OpenVLM card + hidraw node appear,
and returns to that loop if the device disappears (USB unplug). It is safe to
enable the service on nodes without an OpenVLM attached.

## Files

| file | purpose |
|---|---|
| `/opt/nucleus/bin/openvlm-voice.py` | the daemon |
| `/usr/local/bin/voice` | user CLI (start/stop/status/channel/log) |
| `/etc/systemd/system/openvlm-voice.service` | service (After=mesh-start) |
| `/etc/nucleus/mesh.conf` | VOICE_CHANNEL / VOICE_JITTER_MS / VOICE_TX_GAIN |
| `/opt/nucleus/bin/openvlm-monitor.py` | standalone PTT/audio hardware test tool |

## Roadmap

- [x] Phase 1: PTT TX + RX playback over mesh, fixed channel, PCM 16k
- [x] Phase 2: per-source jitter buffers + additive mixing
- [x] Phase 3: mesh.conf config, control socket, systemd service, deploy.sh
- [ ] Phase 4: Opus codec (~24 kbps) behind the codec byte in the header
- [ ] Phase 5: Web UI — channel selector (Flask -> control socket)
- [ ] Phase 6: Phone audio via Flask WebSocket (listen tap, then browser-mic
      PTT inject; talk path needs HTTPS for getUserMedia)

## Test procedure (2 nodes)

1. Deploy on both nodes (`./deploy.sh`), confirm `VOICE_CHANNEL` matches.
2. `voice status` on both — should show `"hardware": true`.
3. Hold PTT on node A, speak; audio plays on node B's headset (and vice versa).
   While A is talking, `voice status` on B shows A's node_id in `sources`.
4. `sudo tcpdump -n -i wlan1 udp port 5555` to watch voice frames on the air.
5. Both hold PTT simultaneously — verify both are heard (additive mixing needs
   a 3rd node to fully verify, since you don't hear yourself).
6. Channel switch test: `voice channel 2` on one node — audio should stop
   until the other node runs `voice channel 2` too.
7. Tuning: too quiet/loud -> adjust `VOICE_TX_GAIN`; choppy -> raise
   `VOICE_JITTER_MS`. Edit mesh.conf then `voice restart`.
