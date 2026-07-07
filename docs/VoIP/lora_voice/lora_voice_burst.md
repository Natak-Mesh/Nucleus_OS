# LoRa Voice Burst — Codec2 PTT over Meshtastic (SHORT_FAST)

> **⚠ SUPERSEDED (2026-07):** the Codec2 burst transport was retired — ~2.6 s
> of speech per packet was not operationally useful. It has been replaced by
> the **voice→text→voice** transport (Vosk STT → text packet → Piper TTS),
> which fits ~15–20 s of speech in the same single packet.
> See [lora_voice_text.md](lora_voice_text.md). This doc is kept for the
> airtime math and design rationale, which still apply.

**Target platform:** Raspberry Pi 4 (1 GB) + Meshtastic radio (USB serial, `/dev/ttyACM*`)
**Preset:** `SHORT_FAST`
**Status:** ~~implemented (branch `lora_voice`)~~ **retired — superseded by lora_voice_text.md**

## TL;DR

Short push-to-talk voice clips CAN be sent over standard sub-GHz Meshtastic
without voice-to-text. Codec2 compresses speech to 700 or 450 bps, which fits
**~2.6 s (700C) or ~4.1 s (450) of speech in a single unfragmented Meshtastic
packet** sent on a custom PortNum. On SHORT_FAST that packet costs **~200 ms
of airtime** — cheap enough to coexist with normal mesh traffic (positions,
telemetry, CoT bridge) as long as clips are hard-clipped at the single-packet
limit and **never fragmented**. In Nucleus this becomes a second transport
behind the existing voice daemon: the `/voice` page offers **"IP Mesh
(real-time)"** or **"LoRa (burst)"**, and both feed the same PTT front-ends,
mixer, and playback sinks.

> This doc corrects several numbers from the original AI-generated spec —
> see [Corrections](#corrections-from-the-original-spec) at the bottom.

---

## 1. Physical layer math (`SHORT_FAST`)

| Parameter | Value |
|---|---|
| Spreading Factor | 7 |
| Bandwidth | 250 kHz |
| Coding Rate | 4/5 |
| Raw link speed | **~10.94 kbps** |
| Max-size packet on-air time | **~200 ms** (255 B wire frame, 16-symbol preamble) |

Notes:

- 21.88 kbps is **SHORT_TURBO** (SF7, BW 500 kHz), not SHORT_FAST. If ~100 ms
  bursts are wanted, SHORT_TURBO is the knob — at the cost of ~3 dB link
  budget (less range/penetration) and it's not legal in all regions.
- ~200 ms per max packet is still ~20x cheaper than the same packet on
  LONG_FAST (~4 s). The core conclusion survives the correction: single-packet
  voice bursts are survivable on an active mesh.

## 2. Payload budget

Meshtastic wire frame maxes at 256 bytes:

| Layer | Bytes |
|---|---|
| Wire frame max | 256 |
| Network header (to/from, id, flags, chan hash, relay) | −16 |
| `Data` protobuf framing on a custom PortNum (portnum tag + payload length framing) | −~4 to 7 |
| **Usable raw payload** | **~233** |

- Sending via a **custom PortNum** (`PRIVATE_APP`, 256+) carries raw binary in
  the `Data.payload` field — no text/Base64 encoding overhead — but the
  protobuf wrapper itself still eats a few bytes. **Design to ~230, not 237.**
- Staying inside one packet means the firmware's fragmentation logic is never
  triggered and the burst looks like any other single packet to the mesh.

## 3. Codec2 capacity

| Mode | Bitrate | Bytes/sec | Speech per ~230 B packet | Quality |
|---|---|---|---|---|
| **700C** (recommended baseline) | 700 bps | 87.5 | **~2.6 s** | Intelligible, robotic but usable |
| **450** (stretch mode) | 450 bps | 56.25 | **~4.1 s** | Borderline; sensitive to mic quality & background noise |

- 450 mode: 40 ms frames × 18 bits (6 pitch, 3 energy, 9 spectral VQ).
  The codec2 library pads each frame to 3 bytes; **manual bit-packing**
  (4 frames × 18 bits = 72 bits = exactly 9 bytes) recovers ~25%. The 4.1 s
  figure assumes packed frames.
- 700C: 40 ms frames × 28 bits; library gives 4 bytes/frame (28 bits padded
  to 32) — packing recovers ~12%. Packed: ~2.6 s; unpadded library output:
  ~2.3 s.
- **Start with 700C.** On a Pi 4 both encode in real time at <2% of one core;
  A/B testing live is cheap. Make the mode a config option.
- Neural vocoders (~300 bps) are feasible on the Pi 4 but are a later
  experiment, not the baseline.

## 4. Airtime discipline (the real rules)

1. **One clip = one packet. Never fragment.** Hard-clip recording at the
   per-packet limit (~2.6 s / ~4.1 s). Multi-packet "streaming" over an
   active mesh multiplies airtime by hop count and collides with background
   traffic — treat it as off the table.
2. **`want_ack=False`.** ACKs double the RF footprint and retransmitted voice
   is useless anyway.
3. **Low hop limit.** Send voice with `hop_limit=0` (direct RF neighbors
   only) or `1`. Default hop limit means every voice burst gets rebroadcast
   by every router in earshot.
4. **VAD before encode.** Run WebRTC VAD or Silero on the Pi; never encode or
   transmit dead air / hot-mic noise.
5. **Pacing multi-clip sends** — there is **no host-visible CSMA/CAD state**.
   The firmware does its own listen-before-talk and TX queueing internally;
   the host just hands it packets. What the host CAN do:
   - watch `airUtilTx` / `channelUtilization` from device telemetry and
     refuse/queue PTT when utilization is high,
   - enforce a fixed inter-clip gap (e.g. ≥1–2 s) in the daemon,
   - rely on the firmware's own queue for back-to-back packets.
6. **Half-duplex.** While the radio is transmitting it hears nothing. PTT is
   a strict lockout: TX state mutes RX handling for the burst duration.

## 5. Pipeline (Pi 4 stack)

```
[ PTT front-end: OpenVLM headset  or  phone via /voice WS ]
            │  (identical to existing IP-mesh path)
            ▼
[ Record buffer, hard-clipped at packet limit ]
            │
            ▼
[ VAD trim (drop leading/trailing silence) ]
            │
            ▼
[ Codec2 encode (700C default, 450 optional) ]
            │
            ▼
[ Bit-packer (strip per-frame byte padding) ]
            │
            ▼
[ + 2-3 byte app header: codec id, channel, seq ]
            │
            ▼
[ meshtastic-python sendData(portNum=PRIVATE_APP,
      want_ack=False, hop_limit=0..1) → /dev/ttyACM* ]
            │
            ▼
[ single ~200 ms LoRa burst on SHORT_FAST ]

RX (reverse): onReceive(portnum) → unpack → Codec2 decode →
inject PCM into the existing mixer → OpenVLM aplay + phone WS sinks
```

## 6. Nucleus integration

Goal: the `/voice` page offers two transports behind the **same PTT UX**:

| Mode | Transport | Character |
|---|---|---|
| **IP Mesh** (existing) | UDP mcast 239.10.10.N over wlan1 802.11s | Real-time, full quality PCM (Opus planned), ~150–200 ms latency |
| **LoRa burst** (new) | Meshtastic custom PortNum via USB serial | Store-and-forward clips ≤2.6/4.1 s, low quality, works beyond WiFi mesh range |

Design decisions:

- **Second transport inside `openvlm-voice.py`, not a separate daemon.** The
  PTT front-ends (CM108 HID GPIO, phone WebSocket), mixer, jitter/playback
  sinks, control socket, and status plumbing all already exist. LoRa mode
  changes only what happens between "PTT down" and "audio out":
  - IP mode: stream 20 ms PCM frames live (current behavior).
  - LoRa mode: buffer while PTT held (auto-release at clip limit), encode on
    PTT-up, send one packet. RX packets decode straight into the mixer.
- **Codec byte:** the NVOX header already reserves `codec` (0 = PCM16).
  Assign e.g. 2 = Codec2-700C, 3 = Codec2-450 for internal bookkeeping;
  on-air LoRa packets carry their own minimal app header (they don't use the
  NVOX/UDP framing).
- **Web UI (`voice.html`):** transport toggle next to the channel picker.
  In LoRa mode show a recording countdown (remaining seconds of the clip
  budget) and a "sending…" state; PTT behavior otherwise identical.
- **Config (`/etc/nucleus/mesh.conf`):**

  ```
  VOICE_LORA_ENABLED=false        # feature gate
  VOICE_LORA_CODEC=700C           # 700C | 450
  VOICE_LORA_PORTNUM=260          # PRIVATE_APP range (256-511)
  VOICE_LORA_HOP_LIMIT=0
  VOICE_LORA_MAX_UTIL=25          # refuse PTT above this channel util %
  ```

- **Dependencies:** `meshtastic` python lib (already vendored at
  `external/meshtastic-python`), `pycodec2` (or the `codec2` CLI /
  libcodec2 via ctypes), `webrtcvad`.

### Open items

1. ~~Radio sharing with the CoT bridge~~ — **resolved:** the cot-bridge is
   the radio broker. It relays voice packets over localhost UDP (see below).
   Consequence: LoRa voice requires `COT_BRIDGE_ENABLED=true`.
2. **Preset verification.** Confirm the fielded radios actually run
   SHORT_FAST; on LONG_FAST the same packet costs ~4 s airtime and this
   feature should stay disabled.
3. **Duty cycle:** at 200 ms/clip this is a non-issue in the US (no duty
   cycle at 915 MHz); EU 868 (1% duty cycle) allows ~18 clips/hour per node.
4. ~~Multi-clip UX~~ — **resolved:** on hitting the clip limit the daemon
   auto-sends and then discards further audio until PTT is released (no
   fragmentation, no accidental second packet).

---

## Implementation

Shipped on branch `lora_voice`. LoRa is a second TX transport inside the
existing voice daemon; RX always listens on both paths.

### Architecture as built

```
/voice page or headset PTT
        │ (identical PTT front-ends)
        ▼
openvlm-voice.py ── transport=ip ──> UDP mcast 239.10.10.N (unchanged)
        │
        └─ transport=lora:
           buffer PCM while keyed (hard-clip at limit)
           → trim silence → 16k→8k → c2enc → bit-pack
           → 3-byte header (codec_id, channel, n_frames)
           → UDP 127.0.0.1:5558 ──> cot_bridge.py
                                    └─> iface.sendData(portnum 260,
                                        want_ack=False, hop_limit=cfg)
RX: cot_bridge onReceive(portnum 260)
    → UDP 127.0.0.1:5559 (4-byte sender node num + payload)
    → openvlm-voice: unpack → c2dec → 8k→16k
    → injected into the existing mixer (headset + phones hear it)
```

### Files changed

| file | change |
|---|---|
| `opt/nucleus/meshtastic/cot_bridge.py` | voice relay: UDP 5558 → LoRa TX; portnum-260 RX → UDP 5559 |
| `opt/nucleus/bin/openvlm-voice.py` | `transport` mode, clip buffer, Codec2 encode/decode via `c2enc`/`c2dec`, bit-packing, LoRa RX thread |
| `opt/nucleus/web/templates/voice.html` | transport toggle, clip countdown on the PTT button, SENDING flash |
| `opt/nucleus/bin/voice` | `voice transport ip\|lora` CLI command |
| `etc/nucleus/mesh.conf` | `VOICE_LORA_ENABLED/CODEC/PORTNUM/HOP_LIMIT` keys |
| `install-packages.sh` | `codec2` apt package (c2enc/c2dec) |
| `deploy.sh` | restarts cot-bridge on deploy (if active) |

### On-air packet format (portnum 260)

```
codec_id(B)  channel(B)  n_frames(B)  packed_codec2_bits...
codec_id: 2 = Codec2 700C (~2.6 s/clip), 1 = Codec2 1200 (~1.5 s/clip)
```

> **Implementation note:** Debian's codec2 CLI (`c2enc`/`c2dec` 1.2.0) does
> **not** ship the experimental 450/700B modes — its lowest rate is 700C.
> So the shipped modes are 700C (default) and 1200 (better quality, shorter
> clip). Reaching 450 would require building codec2 from source with
> `-DUNITTEST=ON` extras; deferred.

Bit-packing strips codec2's per-frame byte padding (700C: 28 bits packed
instead of 32, ~12% recovered; 1200: 48 bits — already byte-aligned).

### Enabling on a node

1. `sudo apt install codec2` (in install-packages.sh for fresh nodes)
2. In `/etc/nucleus/mesh.conf`: `COT_BRIDGE_ENABLED=true` and
   `VOICE_LORA_ENABLED=true` (same `VOICE_LORA_PORTNUM` and
   `VOICE_LORA_CODEC` on all nodes)
3. Restart: `sudo systemctl restart cot-bridge openvlm-voice`
4. On the `/voice` page pick **LoRa (burst)**, or `voice transport lora`

### Testing

- Single node loopback: `voice transport lora`, key up, speak, release —
  daemon log shows `LORA TX: ...` and cot-bridge log shows `VOICE TX → LoRa`.
- Two nodes: same voice channel + same LoRa channel/preset; clip plays on the
  remote node's headset/phone ~1 s after release (encode + airtime + decode).
- Watch: `voice log` and `sudo journalctl -u cot-bridge -f`.

---

## Corrections from the original spec

The original AI-generated document contained errors, preserved here so nobody
re-imports them:

| Original claim | Corrected |
|---|---|
| SHORT_FAST link speed ~21.88 kbps | **~10.94 kbps** (21.88 is SHORT_TURBO, BW500) |
| Max packet ~100–120 ms on air | **~200 ms** at SF7/BW250 with Meshtastic preamble |
| Clean 237 B payload for raw data | **~233 B** — custom PortNum still pays `Data` protobuf framing |
| 4.21 s per packet at 450 bps | **~4.1 s** (and ~2.6 s at the recommended 700C) |
| "Poll RSSI/CAD flags to gate transmission" | **Not exposed by the host API.** Firmware handles CSMA internally; host paces via `airUtilTx` telemetry + fixed gaps |
| 450 bps as the working baseline | 450 is a stretch mode; **700C is the practical baseline** for intelligibility |
