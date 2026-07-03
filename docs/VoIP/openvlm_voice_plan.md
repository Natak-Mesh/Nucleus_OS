# OpenVLM Voice — Mesh PTT Voice Transmission

Status: Real-time PTT working with two interchangeable front-ends —
(1) tactical headset on the OpenVLM USB card (hardware PTT), and
(2) a phone/browser on the node's Wi-Fi AP using the `/voice` web page
(soft PTT, phone mic + speaker). Both put identical voice frames on the mesh
and interoperate transparently. Named multi-channel support included.

## Overview

`openvlm-voice.py` is a daemon that provides real-time push-to-talk voice
between Nucleus nodes over the wlan1 802.11s mesh. The **mesh transport is
independent of the OpenVLM hardware**: the mesh RX, per-source jitter buffers,
the mixer, the control socket, and the WebSocket server always run. Audio
endpoints are pluggable:

- **Hardware endpoint (OpenVLM):** the CM108 USB sound card (0d8c:0012) for
  mic/headset audio and its HID GPIO for PTT. Attaches/detaches automatically
  with the USB device — a node with no OpenVLM still runs the phone + mesh
  paths.
- **Soft endpoint (phone/browser):** a phone on the node's Wi-Fi AP opens the
  node's `/voice` page. The phone's own mic/speaker are the handset; audio
  streams to/from the daemon over a WebSocket. No OpenVLM needed on that node.

You use *either* a headset on the OpenVLM *or* a phone on the web page per
node; both are treated as the same node (they share the node's `node_id`).

Key properties:

- **Transport:** UDP multicast directly on wlan1. One multicast group per
  voice channel: `239.10.10.<channel>`, UDP port 5555.
- **No smcroute involvement.** The daemon transmits on wlan1 itself. 802.11s
  handles multi-hop multicast natively (mesh_fwding=1, RMC dedup), same as
  ATAK CoT. TTL is set to `MESH_802_TTL` (default 8).
- **Real-time streaming** (not record/replay). While PTT is held, 20 ms audio
  frames go straight onto the mesh; the receiver plays them out continuously
  through a small (~80 ms) jitter buffer. (`openvlm-monitor.py` is a separate
  throwaway hardware test tool — it is not part of the live path.)
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
  B   flags      reserved (0)  ← reserved for future direct-messaging
  I   seq        per-transmission incrementing frame counter
  --  payload    640 bytes = 320 samples = 20 ms of audio
```

Total: 14-byte header + 640-byte payload = 654 bytes per packet, 50 pkt/s
while transmitting (~262 kbps). Phase 4 (Opus @ ~24 kbps) cuts this ~10x.

**Direct-messaging (future, reserved now):** the `flags` byte + a reserved
channel range (e.g. 200–254) can carry a "direct" marker + target `node_id`.
RX already filters by `node_id`, so a directed frame would only be un-muted by
the addressed node. Documenting the reservation now means the packet format
does not need to change when DM is added.

## Architecture / Audio Pipeline

```
mesh wlan1  <── TX sender ──┬── OpenVLM mic   (while hardware PTT held)
UDP mcast                   └── phone mic     (while soft PTT held, via WS)
239.10.10.n
            ── RX ── per-source jitter buffers ── mixer ──┬── OpenVLM aplay
                                                          └── phone(s) via WS
```

- The **mixer is self-clocked** by a 20 ms monotonic timer (not by `aplay`), so
  it runs whether or not an OpenVLM is attached. Each 20 ms tick it mixes the
  active sources and fans the result out to every active playback sink: the
  OpenVLM `aplay` process (fed through a bounded queue so the mixer never
  blocks) and every connected phone WebSocket.
- `arecord`/`aplay` use `plughw:<card>,0` so ALSA resamples 16 kHz ↔ the card's
  native 48 kHz. The browser resamples 16 kHz ↔ its AudioContext rate in JS.
- Each source must accumulate `VOICE_JITTER_MS` (default 80 ms = 4 frames)
  before playback starts, absorbing mesh jitter. A source that runs dry
  re-buffers; a source idle >1 s is dropped from the mixer.
- Own packets are excluded twice: `IP_MULTICAST_LOOP` off + node_id filter.

### Latency budget (mouth-to-ear, 1 hop)

| stage | ms |
|---|---|
| capture (ALSA or browser) | 20–40 |
| frame accumulation | 20 |
| network (802.11s) | 1–5 (+2–5/extra hop) |
| jitter buffer | 80 (VOICE_JITTER_MS) |
| playback buffer | 20–50 |
| **total** | **~150–200** |

The phone adds a little extra browser buffering; still well within PTT norms.

## Configuration (`/etc/nucleus/mesh.conf`)

```
VOICE_CHANNEL=1                          # startup channel -> group 239.10.10.1
VOICE_CHANNELS="1:Command,2:Squad,3:Logistics"   # named channel picker list
VOICE_JITTER_MS=80                       # per-source RX buffer before playback
VOICE_TX_GAIN=4                          # software mic gain (OpenVLM path)
```

`VOICE_CHANNELS` is a comma-separated list of `number:label` pairs (numbers
1–254). It populates the channel picker in the web page and the `voice
channels` CLI. `VOICE_CHANNEL` selects which of them is active at startup.

Also read: `MESH_IP` (node_id + multicast egress interface selection),
`MESH_802_TTL` (multicast TTL). Restart after changes:
`sudo systemctl restart openvlm-voice` (or `voice restart`).

## User Interface

### The `voice` CLI

Installed to `/usr/local/bin/voice` by deploy.sh:

```
voice start        # start the voice service
voice stop         # stop the voice service
voice restart      # restart (e.g. after mesh.conf changes)
voice status       # service state + JSON status (channel, PTT, talkers)
voice channels     # list configured named channels
voice channel 2    # switch to voice channel 2 (live, no restart)
voice log          # follow the live daemon log (Ctrl-C to exit)
```

### The `/voice` web page (soft PTT)

Reached from the dashboard's Tools grid ("Voice PTT") or directly at
`https://<serial>-nucleus.local/voice` **or** `https://<node-ip>/voice`.
**Must be HTTPS** — browsers only allow microphone capture (`getUserMedia`) in a
secure context. The page enforces this itself: if it's opened over `http` or on
the Flask port `:5000`, it redirects to `https://<same-host>/voice`. Works by IP
or `.local` (click through the self-signed cert warning, same as the rest of the
UI).

**By-IP support:** nginx routes by hostname, so the `.local` vhost alone would
not serve voice when the phone connects by IP (on an OTS node, by-IP falls
through to OTS). `config_generation.sh` therefore writes
`/etc/nginx/snippets/nucleus-voice.conf` (`/voice-ws`, `/voice`, `/static`) and
includes it in the OTS `ots_https` block, and the self-signed cert includes the
node's IPs as SANs so `wss://<ip>` passes TLS. See
`docs/system_info/web_ui_local_hostname.md` for the full nginx/cert detail.


Features: a large press-and-hold PTT button (touch or Spacebar), a named
channel picker, a live "receiving" talker list, and connection/hardware status.
The browser captures the mic at 16 kHz, frames it into 20 ms chunks, and sends
them over the WebSocket only while PTT is held; incoming mixed mesh audio is
played back through a small Web Audio jitter buffer.

## Control interfaces

### UDP control socket (CLI + scripts)

UDP on `127.0.0.1:5556`, plain-text commands, JSON replies.

| command | reply |
|---|---|
| `STATUS` | `{"node_id":9,"channel":1,"channel_label":"Command","ptt":false,"sources":[...],"card":1,"channels":[...]}` |
| `CHANNELS` | `{"ok":true,"current":1,"channels":[{"n":1,"label":"Command"},...]}` |
| `CHANNEL <n>` | switches channel live `{"ok":true,"channel":n}` |

Example: `echo -n "CHANNEL 2" | nc -u -w1 127.0.0.1 5556`

### WebSocket server (web page)

TCP on `127.0.0.1:5557`, minimal dependency-free RFC6455 server built into the
daemon. nginx proxies `wss://<host>/voice-ws` → `127.0.0.1:5557` (both the 80
and 443 vhost blocks, generated by `config_generation.sh`).

- client → server **text**: `{"type":"ptt","down":bool}`,
  `{"type":"channel","n":N}`, `{"type":"hello"}` / `{"type":"status"}`
- client → server **binary**: raw S16_LE 16 kHz 20 ms frames (640 B) while soft
  PTT is held
- server → client **text**: `{"type":"status",...}` (channels, current channel,
  talkers, hardware present, this node's id)
- server → client **binary**: mixed RX audio frames (640 B), continuous

## Hardware resilience

The OpenVLM front-end is supervised independently: it attaches when the card +
hidraw node appear and cleanly detaches on USB unplug, **without disturbing the
mesh/phone path**. It is safe to enable the service on nodes without an OpenVLM
attached — the phone (WebSocket) and mesh paths run regardless.

## Files

| file | purpose |
|---|---|
| `/opt/nucleus/bin/openvlm-voice.py` | the daemon (mesh + mixer + WS server + OpenVLM front-end) |
| `/usr/local/bin/voice` | user CLI (start/stop/status/channels/channel/log) |
| `/opt/nucleus/web/templates/voice.html` | the `/voice` soft-PTT web page (forces itself onto https/443; back button uses history) |
| `/etc/systemd/system/openvlm-voice.service` | service (After=mesh-start; deploy.sh restarts it on each deploy) |
| `/etc/nucleus/mesh.conf` | VOICE_CHANNEL / VOICE_CHANNELS / VOICE_JITTER_MS / VOICE_TX_GAIN |
| `opt/nucleus/bin/config_generation.sh` | generates the `.local` nginx vhost + IP-SAN cert + `nucleus-voice.conf` (by-IP `/voice-ws`, `/voice`, `/static`) |
| `/etc/nginx/snippets/nucleus-voice.conf` | generated: voice locations included into the OTS 443 vhost for by-IP access |
| `/opt/nucleus/bin/openvlm-monitor.py` | standalone PTT/audio hardware test tool (not in live path) |


## Ports

| port | proto | bind | purpose |
|---|---|---|---|
| 5555 | UDP | wlan1 mcast | voice frames on the mesh |
| 5556 | UDP | 127.0.0.1 | control socket (CLI) |
| 5557 | TCP | 127.0.0.1 | WebSocket server (nginx proxies `/voice-ws` here) |

## Roadmap

- [x] Phase 1: PTT TX + RX playback over mesh, fixed channel, PCM 16k
- [x] Phase 2: per-source jitter buffers + additive mixing
- [x] Phase 3: mesh.conf config, control socket, systemd service, deploy.sh
- [x] Phase 5a: daemon refactor — mesh decoupled from OpenVLM, self-clocked
      mixer with multi-sink fan-out, named multi-channel config
- [x] Phase 5b: WebSocket bridge in daemon + `/voice` web page (soft PTT:
      phone mic → mesh, mesh → phone speaker) + nginx WSS proxy
- [ ] Phase 4: Opus codec (~24 kbps) behind the codec byte in the header
- [ ] Phase 6: direct-messaging to a specific user/IP (reserve flags/channel
      range now; wire up target-node addressing + web talker-tap later)

## Test procedure

### Two nodes, both headsets (regression)

1. Deploy on both (`./deploy.sh`), confirm `VOICE_CHANNEL` matches.
2. `voice status` on both — should show `"hardware": true`.
3. Hold PTT on node A, speak; audio plays on node B's headset (and vice versa).
   While A talks, `voice status` on B lists A's node_id in `sources`.
4. `sudo tcpdump -n -i wlan1 udp port 5555` to watch voice frames on the air.

### Headset ↔ phone (soft PTT)

1. On node A: tactical headset on the OpenVLM. On node B: connect a phone to
   node B's Wi-Fi AP and browse to `https://<B-serial>-nucleus.local/voice`
   (accept the self-signed cert). "Link: connected" should show.
2. Pick the same channel on the phone as node A's `voice status` channel.
3. Hold PTT on A and speak → heard on the phone speaker. Hold the phone's TALK
   button and speak → heard on A's headset. Node B need not have an OpenVLM.
4. On a 3rd node, verify additive mixing (two simultaneous talkers both heard).

### Channel switching

`voice channel 2` on one node (or tap a channel on the phone) — audio stops
until the other endpoint moves to channel 2 as well.

### Tuning

Too quiet/loud on the OpenVLM path → adjust `VOICE_TX_GAIN`; choppy → raise
`VOICE_JITTER_MS`. Edit mesh.conf then `voice restart`.
