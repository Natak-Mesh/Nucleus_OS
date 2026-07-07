# LoRa Voice→Text — STT/TTS PTT over Meshtastic (SHORT_FAST)

**Target platform:** Raspberry Pi 4 (2 GB+) + Meshtastic radio (USB serial, `/dev/ttyACM*`)
**Preset:** `SHORT_FAST`
**Status:** implemented
**History:** replaces the retired Codec2 burst transport — see
[archive/lora_voice_burst.md](archive/lora_voice_burst.md) for that design and
its full airtime math.

## TL;DR

This transport is **voice→text→voice**: speech is transcribed on the sending
node (Vosk streaming STT), the *text* is sent as a single Meshtastic packet,
and the receiving node speaks it aloud (Piper TTS) while also displaying the
text in the `/voice` page message log.

One packet (2-byte header + up to 235 bytes of UTF-8 text) carries **~40
words ≈ 15–20 seconds of speech** at perfect intelligibility, for only
~200 ms of SHORT_FAST airtime. (The retired Codec2 approach fit ~2.6 s of
audio in the same packet — not operationally useful.) The text itself is a
free byproduct: a readable, reviewable message history even when audio is
off.

## Airtime background (SHORT_FAST)

Condensed from the archived burst doc — the physics that drives the
one-packet doctrine:

| Parameter | Value |
|---|---|
| SHORT_FAST raw link speed (SF7 / BW 250 kHz / CR 4/5) | ~10.94 kbps |
| Max-size packet on-air time | **~200 ms** (255 B wire frame) |
| Same packet on LONG_FAST | ~4 s — feature should stay disabled there |
| Usable app payload per packet | ~233–237 B (256 B wire frame − 16 B network header − protobuf `Data` framing) |

Airtime discipline (inherited unchanged):

1. **One utterance = one packet — never fragment.** Overflow is truncated and
   flagged instead.
2. **`want_ack=False`** — ACKs double the RF footprint.
3. **Low hop limit** (`VOICE_LORA_HOP_LIMIT=0`, direct RF neighbors) so voice
   packets aren't rebroadcast by every router in earshot.
4. **Half-duplex:** while the radio transmits it hears nothing; PTT is a
   strict lockout.

## Why Vosk (not whisper.cpp)

| | Vosk small-en-us | whisper.cpp base-q5_0 |
|---|---|---|
| Model size | ~40 MB disk / ~100 MB RAM | ~150 MB RAM |
| Mode | **Streaming** — transcribes *while PTT is held* | Batch — can't start until PTT release |
| Latency at release | ~instant (finalize only) | 3–6x realtime on Pi 4 → 45–90 s for a 15 s clip |
| Accuracy | Good for short tactical phrases; no punctuation | Better, but irrelevant if unusably slow |

Streaming is the killer feature: by the time the user releases PTT the
transcript is already computed. Whisper remains a possible future upgrade for
higher-RAM nodes, but Vosk is the fielded baseline.

**TTS:** Piper `en_US-lessac-low.onnx` (~60 MB). The `-low` voices output
**16 kHz S16 mono — exactly the voice daemon's mixer format**, so synthesized
audio feeds the existing mixer with zero resampling.

## Architecture

```
/voice page or headset PTT               (PTT front-ends unchanged;
        │                                 UDP/IP live-voice path untouched)
        ▼
openvlm-voice.py ── transport=ip ──> UDP mcast 239.10.10.N (unchanged)
        │
        └─ transport=lora:
           20 ms PCM frames stream into Vosk recognizer LIVE while keyed
           → PTT release: FinalResult() → text (near-instant)
           → packet: flags(B) channel(B) + UTF-8 text (≤235 B,
             word-boundary truncation — NEVER fragmented)
           → UDP 127.0.0.1:5558 ──> cot_bridge.py
                                    └─> iface.sendData(portnum 260,
                                        want_ack=False, hop_limit=cfg)

RX: cot_bridge onReceive(portnum 260)
    → UDP 127.0.0.1:5559 (4-byte sender node num + payload)
    → openvlm-voice: text → message history + web UI push
                     text → Piper TTS → 16 kHz PCM → existing mixer
                     (headset + phones hear it)
```

Key properties:

- **The real-time IP voice path is completely untouched.** LoRa mode only
  diverges inside the existing `transport == "lora"` branch of
  `transmit_frame()`.
- **cot-bridge is payload-agnostic** — its voice relay just moves bytes
  between the localhost UDP sockets and portnum 260; it never inspects the
  text.
- **Own messages are text-only.** Your sent transcript appears in the message
  log as confirmation, but your own TTS audio is never played back to you.
  Only packets received over LoRa are synthesized.
- **RX always listens on both paths** regardless of the TX transport toggle.

## On-air packet format (portnum 260)

```
flags(B)   bit0 = transcript truncated to fit one packet; rest reserved
channel(B) voice channel filter (same semantics as the IP path)
text...    UTF-8, ≤235 bytes (truncated at a word boundary, never mid-
           UTF-8-sequence)
```

One utterance = one packet, always. If the transcript overflows, it is
truncated and flagged — never fragmented. Airtime discipline is inherited from
the burst design: `want_ack=False`, low `hop_limit`, single ~200 ms burst.

## Message history

- The daemon keeps the last 50 sent + received texts (direction, sender node,
  channel, timestamp, truncated flag).
- Web UI: `/voice` page shows a scrollable **Messages** log; new WS clients
  get the full history on connect (`{"type":"texts"}`), and live messages
  arrive as `{"type":"text"}` events.
- CLI: `voice texts` dumps the history via the control socket (`TEXTS`).

## Latency budget (PTT release → remote playback)

| Stage | Estimate |
|---|---|
| Vosk finalize (streaming already done) | ~0.1–0.5 s |
| LoRa TX queue + airtime (SHORT_FAST) | ~0.3–1 s |
| Piper TTS synthesis (Pi 4, -low voice) | ~1–3 s |
| **Total** | **~2–4 s** |

## Nucleus integration

Config (`/etc/nucleus/mesh.conf`):

```
VOICE_LORA_ENABLED=true       # feature gate
VOICE_LORA_MAX_SECS=30        # max speech per PTT press (auto-finalize after)
VOICE_LORA_PORTNUM=260        # PRIVATE_APP range; same on all nodes
VOICE_LORA_HOP_LIMIT=0        # direct RF neighbors only
```

Dependencies (handled by `install-packages.sh`, needs internet at install):

| What | Where |
|---|---|
| `vosk` + `piper-tts` (pip, system-wide) | daemon runs as root |
| Vosk model `vosk-model-small-en-us-0.15` (~40 MB) | `/opt/nucleus/models/vosk/` |
| Piper voice `en_US-lessac-low.onnx` (~60 MB) | `/opt/nucleus/models/piper/` |

Startup behavior: the Vosk model loads in a background thread (~5–15 s on a
Pi 4). Until it's ready the LoRa transport button shows "loading speech
model…" and cannot be selected. If piper or its voice is missing, received
texts still display in the log — they just aren't spoken.

### Implementation files

| file | role |
|---|---|
| `opt/nucleus/bin/openvlm-voice.py` | STT worker (resident Vosk model + per-clip streaming recognizer), text packetizer, TTS worker (Piper → mixer), message history + WS text events, `TEXTS` control command |
| `opt/nucleus/meshtastic/cot_bridge.py` | payload-agnostic voice relay: UDP 5558 → LoRa TX (portnum 260); portnum-260 RX → UDP 5559 |
| `opt/nucleus/web/templates/voice.html` | "LoRa (voice→text)" transport button, Messages log panel, SENDING state cleared by tx confirmation |
| `opt/nucleus/bin/voice` | `voice transport ip\|lora`, `voice texts` CLI commands |
| `etc/nucleus/mesh.conf` | `VOICE_LORA_ENABLED / MAX_SECS / PORTNUM / HOP_LIMIT` keys |
| `install-packages.sh` | `vosk` + `piper-tts` pip installs and model downloads to `/opt/nucleus/models/` |

### Enabling on a node

1. Run `install-packages.sh` (or manually: `sudo pip3 install --break-system-packages vosk piper-tts` + download the two models to `/opt/nucleus/models/`)
2. In `/etc/nucleus/mesh.conf`: `COT_BRIDGE_ENABLED=true`, `VOICE_LORA_ENABLED=true`
   (same `VOICE_LORA_PORTNUM` on all nodes)
3. `sudo systemctl restart cot-bridge openvlm-voice`
4. On `/voice` pick **LoRa (voice→text)**, or `voice transport lora`

### Testing

- Single node: `voice transport lora`, key up, speak a sentence, release.
  `voice log` shows `LORA TX: ...B text packet: "..."` and the cot-bridge log
  shows `VOICE TX → LoRa`. Your transcript appears in the `/voice` Messages
  log.
- Two nodes: same voice channel + same LoRa channel/preset. The remote node
  displays the text and speaks it ~2–4 s after release.
- `voice texts` dumps the message history from the CLI.

### Known limitations / future work

- **English only** (both models). Other Vosk/Piper models drop in via the
  model paths if needed.
- **No punctuation** from Vosk small — fine for radio-style traffic.
- Multi-packet utterances (seq/continuation flags) deferred; single-packet
  truncation keeps the airtime doctrine simple.
- Per-message Piper subprocess costs ~1–2 s of model load; if that proves
  annoying, switch to the resident `piper` Python API.
