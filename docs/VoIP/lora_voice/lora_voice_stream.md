# LoRa Voice Streaming — live Codec2 PTT over Meshtastic (SHORT_FAST)

**Target platform:** Raspberry Pi 4 (2 GB+) + Meshtastic radio (USB serial, `/dev/ttyACM*`)
**Preset:** `SHORT_FAST` (REQUIRED — see airtime section)
**Status:** implemented
**Origin:** adapted from the community [VoiceOverLoRa (VLoRa)](https://github.com/SomeGuy-dev/VoiceOverLoRa)
project, which proved bidirectional real-time-capable Codec2 voice between two
Nucleus nodes at SF7 using a fork of our `cot_bridge.py`. This integration
merges that transport natively into the Nucleus PTT voice system (headset +
`/voice` page) while keeping the on-air format wire-compatible with VLoRa's
ATAK Vx bridges for a future Vx integration.

## TL;DR

A third voice transport on the `/voice` PTT page: **live Codec2 3200 bps
audio streamed over the LoRa radio while PTT is held**. The remote node
starts hearing you ~0.5–1 s after you start talking — like a real PTT
radio — instead of waiting for you to unkey.

The three transports now:

| Transport | Path | Behavior |
|---|---|---|
| **IP Mesh** | wlan1 802.11s multicast | real-time, full quality (unchanged) |
| **LoRa voice→text** | Meshtastic portnum 260 | burst at release: STT → 1 text packet → TTS ([doc](lora_voice_text.md)) |
| **LoRa streaming** (this doc) | Meshtastic portnum 256 | live Codec2 voice while keyed |

All three share the same PTT front-ends (OpenVLM headset hardware PTT and
the `/voice` web page soft PTT) and the same RX mixer (headset + phones hear
whatever arrives on any transport, always).

## When to use which LoRa transport

| | voice→text (burst) | streaming (this) |
|---|---|---|
| Airtime for 15 s of speech | ~200 ms (1 packet) | ~5 s (~58 packets, ~35% duty while keyed) |
| Remote hears | synthesized TTS voice, after release | *your actual voice*, while you talk |
| Names/callsigns/accents/non-English | STT recognition errors possible | carried verbatim |
| Byproduct | reviewable text log | none |
| Radio preset tolerance | works even on slower presets | **SHORT_FAST-class only** |
| Half-duplex impact on CoT/SA | negligible | radio deaf to CoT ~1/3 of talk time |

Rule of thumb: streaming for short tactical exchanges when the channel is
quiet and you need real voice; voice→text when airtime matters, you want a
log, or the link is marginal.

## Airtime math (why SHORT_FAST is mandatory)

Codec2 3200 bps produces 8 bytes per 20 ms frame. The bridge packs 9 frames
(72 B = 180 ms of audio) per LoRa packet:

| Parameter | Value |
|---|---|
| Payload per packet | 72 B audio + 3 B header + ~21 B Meshtastic framing |
| SHORT_FAST airtime per packet (SF7/BW250/CR4:5) | ~60 ms |
| Audio carried per packet | 180 ms |
| **Airtime duty while keyed** | **~33%** — radio keeps up with margin |
| Same packet on LONG_FAST (SF11) | ~1+ s airtime per 180 ms audio — **falls behind ~6x, unusable** |

VLoRa field-tested this exact framing bidirectionally at SF7 with
"real-time-capable voice quality." At higher SF the TX queue grows faster
than the radio can drain it; there is no software fix for that — it is the
LoRa PHY throughput ceiling.

Airtime discipline (inherited from the voice-text doctrine):
`want_ack=False`, `hopLimit` = `VOICE_LORA_HOP_LIMIT` (default 0 = direct RF
neighbors only), and PTT is a strict half-duplex lockout.

## Architecture

```
/voice page or headset PTT                (PTT front-ends unchanged; IP and
        │                                  voice-text paths untouched)
        ▼
openvlm-voice.py ── transport=stream:
   each 20 ms mic frame (16 kHz S16) LIVE while keyed
   → downsample 16k → 8k (pair-average decimation)
   → pycodec2 3200 encode (8 B / frame)
   → UDP 127.0.0.1:4245 ──> cot_bridge.py  _stream_raw_loop
                            └─ packetize: INIT (key-down)
                               + 72 B data packets (seq 1..65534)
                               + TERM (0.5 s input silence = key-up)
                            └─ iface.sendData(portnum 256,
                               want_ack=False, hop_limit=cfg)

RX: cot_bridge onReceive(portnum 256)
    → strip 3 B header, drop INIT/TERM markers
    → UDP 127.0.0.1:4244 (raw Codec2 bytes, streaming)
    → openvlm-voice stream_rx_thread:
        decode each 8 B frame as it arrives (partial bytes carry over)
        → upsample 8k → 16k (linear interp)
        → jitter-buffered mixer Source ("lora", 300 ms buffer)
        → existing mixer → headset + phones hear it live
```

Key properties:

- **The IP voice path and the voice-text path are completely untouched.**
  The stream transport only adds a new branch in `transmit_frame()` and two
  new daemon threads.
- **True streaming on both ends.** TX encodes and ships frames as you speak
  (unlike VLoRa's Vx TX bridge, which buffered the whole clip and burst at
  release); RX decodes and plays each LoRa packet as it lands. End-to-end
  voice delay ≈ 180 ms packetization + ~60 ms airtime + 300 ms RX jitter
  buffer ≈ **0.5–1 s behind the talker**.
- **cot-bridge stays payload-agnostic** about the audio itself — it only
  frames/deframes; all codec work lives in the voice daemon.
- **RX always listens** on the stream port regardless of the TX transport
  toggle, same as the other transports.

## On-air packet format (portnum 256, VLoRa-compatible)

```
header (3 B, big-endian): payload_size(B)  seq(H)
  seq 0      = stream INIT   (payload: 2 B reserved + codec id, 2=Codec2)
  seq 65535  = stream TERM   (no payload)
  seq 1..65534 = data        (payload: 1-72 B of raw Codec2 3200 frames)
```

This is byte-identical to the VLoRa project's framing, so its
`vlora_tx_bridge.py` / `vlora_rx_bridge.py` (ATAK Vx plugin ↔ LoRa) can be
dropped onto a node later and interoperate over the same relay sockets
(4245 in / 4244 out) with zero bridge changes — that is the planned Vx
integration hook.

## Nucleus integration

Config (`/etc/nucleus/mesh.conf`):

```
VOICE_LORA_STREAM_ENABLED=true   # feature gate (daemon + bridge both read it)
VOICE_LORA_STREAM_PORTNUM=256    # PRIVATE_APP range; same on all nodes;
                                 # must differ from 257 (CoT) and 260 (text)
VOICE_LORA_HOP_LIMIT=0           # shared with voice-text; 0 = direct RF only
```

Dependencies (handled by `install-packages.sh`, needs internet at install):

| What | Why |
|---|---|
| `libcodec2-dev` (apt) | C library + headers pycodec2 builds against |
| `pycodec2` (pip, system-wide) | Codec2 3200 encode/decode in the daemon |
| `numpy` (pip, system-wide) | sample-rate conversion (16k↔8k) |

No models, no downloads — total footprint is a few MB, and the transport is
usable seconds after daemon start (no model-loading wait like the STT path).

### Implementation files

| file | role |
|---|---|
| `opt/nucleus/bin/openvlm-voice.py` | `stream_worker_thread` (live mic → Codec2 → UDP 4245), `stream_rx_thread` (UDP 4244 → streaming decode → mixer Source), `"stream"` transport mode, status `stream.enabled/ready` |
| `opt/nucleus/meshtastic/cot_bridge.py` | `_stream_raw_loop` (UDP 4245 → INIT/data/TERM packetizer → portnum 256), `_handle_stream_rx` (portnum 256 → strip header → UDP 4244), `stream_*` stats |
| `opt/nucleus/web/templates/voice.html` | "LoRa (streaming)" transport button, "LoRa voice" talker tag |
| `opt/nucleus/bin/voice` | `voice transport stream` |
| `etc/nucleus/mesh.conf` | `VOICE_LORA_STREAM_ENABLED / _PORTNUM` keys |
| `install-packages.sh` | `libcodec2-dev` + `pycodec2` + `numpy` installs |

### Enabling on a node

1. Run `install-packages.sh` (or manually: `sudo apt install libcodec2-dev &&
   sudo pip3 install --break-system-packages pycodec2 numpy`)
2. In `/etc/nucleus/mesh.conf`: `COT_BRIDGE_ENABLED=true`,
   `VOICE_LORA_STREAM_ENABLED=true` (same `VOICE_LORA_STREAM_PORTNUM` on all
   nodes)
3. Confirm the Meshtastic radios are on **SHORT_FAST** on every node
4. `sudo systemctl restart cot-bridge openvlm-voice`
5. On `/voice` pick **LoRa (streaming)**, or `voice transport stream`

### Testing

- Single node: `voice transport stream`, key up, speak. `voice log` shows
  `STREAM:` lines and the cot-bridge log shows
  `STREAM TX | key-down` / seq'd sends / `key-up | packets=N`.
- Two nodes: same stream portnum + SHORT_FAST on both. Key up on node A and
  keep talking — node B's headset/phone starts playing ~0.5–1 s in, while
  A is still keyed. The `/voice` page on B shows a **LoRa voice** talker tag.
- `voice status` → `"stream": {"enabled": true, "ready": true}`.

### Known limitations / future work

- **SHORT_FAST-class presets only** — physics, not software (see airtime
  math). No auto-detection of the radio preset; misconfiguration shows up
  as badly lagging, gappy audio.
- **One talker at a time per LoRa channel.** All received stream audio mixes
  into a single "lora" Source; overlapping talkers would interleave. LoRa
  half-duplex makes simultaneous talkers destructive anyway — PTT
  discipline applies, as on any simplex radio net.
- **No per-channel filtering** on the stream (the VLoRa wire header has no
  channel byte, kept for Vx compatibility). All nodes on the portnum hear
  all stream traffic regardless of the `/voice` channel picker.
- **Codec2 3200 quality** is intelligible-radio, not natural: robotic
  timbre, mono, 8 kHz band. That is the price of fitting live voice in LoRa.
- **ATAK Vx integration** (phones' native Vx PTT riding this same link) is
  the designed next step: deploy VLoRa's per-node Vx bridges pointing at the
  same 4245/4244 sockets. Requires `opuslib` + `soxr` and per-node IP
  constants — see the VLoRa repo.
- 16k↔8k conversion uses cheap pair-averaging / linear interpolation rather
  than a proper polyphase resampler (`soxr`); at Codec2 3200's quality floor
  the difference is inaudible, and it avoids another dependency. Swap in
  `soxr` if the Vx bridges (which already need it) get deployed.
