# LoRa Voice→Text — STT/TTS PTT over Meshtastic (SHORT_FAST)

**Target platform:** Raspberry Pi 4 (2 GB+) + Meshtastic radio (USB serial, `/dev/ttyACM*`)
**Preset:** `SHORT_FAST`
**Status:** implemented — replaces the Codec2 burst transport
**Supersedes:** [lora_voice_burst.md](lora_voice_burst.md) (Codec2 clips, retired)

## TL;DR

The Codec2 burst approach maxed out at **~2.6 s of speech per packet** — not
operationally useful. This transport pivots to **voice→text→voice**: speech is
transcribed on the sending node (Vosk streaming STT), the *text* is sent as a
single Meshtastic packet, and the receiving node speaks it aloud (Piper TTS)
while also displaying the text in the `/voice` page message log.

One ~235-byte packet now carries **~40 words ≈ 15–20 seconds of speech** —
about 8x the capacity of Codec2 700C, at perfect intelligibility, for the same
~200 ms of SHORT_FAST airtime. The text itself is a free byproduct: a readable,
reviewable message history even when audio is off.

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
- **cot-bridge is unchanged functionally** — its voice relay is
  payload-agnostic (it moved Codec2 bytes before; it moves UTF-8 now).
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

### Files changed (vs the Codec2 implementation)

| file | change |
|---|---|
| `opt/nucleus/bin/openvlm-voice.py` | Codec2 removed entirely (codecs table, bit-packing, 8k↔16k resamplers, c2enc/c2dec). Added: STT worker (resident Vosk model + per-clip streaming recognizer), text packetizer, TTS worker (Piper → mixer), message history + WS text events, `TEXTS` control command |
| `opt/nucleus/web/templates/voice.html` | transport button relabeled "LoRa (voice→text)", Messages log panel, SENDING state cleared by tx confirmation |
| `opt/nucleus/bin/voice` | added `voice texts` |
| `etc/nucleus/mesh.conf` | `VOICE_LORA_CODEC` removed; `VOICE_LORA_MAX_SECS` added |
| `install-packages.sh` | `codec2` apt removed; `vosk`/`piper-tts` pip + model downloads added |
| `opt/nucleus/meshtastic/cot_bridge.py` | comment updates only — relay unchanged |

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
