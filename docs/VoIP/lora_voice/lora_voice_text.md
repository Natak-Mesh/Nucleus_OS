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

| | Vosk (streaming) | whisper.cpp base-q5_0 |
|---|---|---|
| Mode | **Streaming** — transcribes *while PTT is held* | Batch — can't start until PTT release |
| Latency at release | ~instant (finalize only) | 3–6x realtime on Pi 4 → 45–90 s for a 15 s clip |
| Accuracy | Good–very good depending on model (see below); no punctuation | Better, but irrelevant if unusably slow |

Streaming is the killer feature: by the time the user releases PTT the
transcript is already computed. Whisper remains a possible future upgrade for
higher-RAM nodes, but Vosk is the fielded baseline.

### STT model selection

`install-packages.sh` installs the small model; the daemon loads it by
default. `VOICE_STT_MODEL` in mesh.conf forces a different model (directory
name under `/opt/nucleus/models/vosk/` or absolute path) — for faster
hardware only.

| Model | Disk | RAM (loaded) | Pi 4 verdict |
|---|---|---|---|
| `vosk-model-small-en-us-0.15` (**default**) | ~40 MB | ~100 MB | decodes faster than real-time — transcript truly ready at PTT release |
| `vosk-model-en-us-0.22-lgraph` (tested, **rejected on Pi 4**) | ~128 MB | ~500–700 MB | decodes *slower* than real-time → 10+ s latency after release (field-tested 2026-07-07) |

The lesson: on a Pi 4, model size buys nothing if decode falls behind the
live audio — the "streaming = instant transcript" property only holds when
the recognizer keeps up. The active model is logged at startup and reported
in `voice status` / the WS status (`lora.stt_model`). **For accuracy gains
on Pi 4, use the grammar constraint below instead of a bigger model.**

### Optional: grammar-constrained recognition (opt-in)

For traffic that sticks to a fixed radio vocabulary (callsigns, prowords,
phonetic alphabet, digits), Vosk can be constrained to a phrase list, making
recognition of those phrases dramatically more accurate — even with the
small model. The trade-off: out-of-vocabulary speech maps to `[unk]`
(dropped) instead of being transcribed, so only enable it if traffic really
is disciplined.

- Set `VOICE_STT_GRAMMAR=/opt/nucleus/models/vosk/grammar.txt` in mesh.conf
  (file format: one lowercase word/phrase per line, `#` comments allowed).
- A starter vocabulary ships at
  `/opt/nucleus/models/vosk/grammar.example.txt` — copy it, add your
  callsigns/locations, and point the config at your copy.
- Empty/unset (default) = normal free-form recognition.

### STT audio path note

In LoRa mode the recognizer is fed the **raw mic frames**, *before* the
`VOICE_TX_GAIN` software gain is applied. That gain (4x by default, for the
low-level ComTac mics on the IP voice path) hard-clips loud audio, and
clipped audio wrecks STT accuracy; Vosk doesn't need the level boost.

**TTS:** Piper `en_US-lessac-low.onnx` (~60 MB). The `-low` voices output
**16 kHz S16 mono — exactly the voice daemon's mixer format**, so synthesized
audio feeds the existing mixer with zero resampling.

### TTS: resident Piper + chunked streaming (2026-07-07)

The original implementation spawned a `piper` **subprocess per received
message**, which field-tested at 5–10 s from message arrival to speech. The
fix, measured on a Pi 4 with the same test sentence (~3.8 s of audio):

| TTS path | Time to audio |
|---|---|
| `piper` subprocess per message (**old**) | **~8.8 s** — interpreter + onnxruntime + ONNX model load + espeak init, every message |
| Resident `PiperVoice` (loaded once), whole message | ~2.3 s |
| Resident + chunked streaming (**current**) | **< 1 s to first words** |

Two changes in `tts_worker_thread`:

1. **Resident voice** — `PiperVoice.load()` (piper-tts ≥ 1.4 Python API) runs
   once at thread startup (~5.6 s, in the background like the Vosk model,
   plus a short warm-up synthesis). Every message after that pays only raw
   synthesis time, which is ~1.7x *faster* than real time on a Pi 4.
2. **Chunked streaming** — Vosk emits no punctuation, so Piper treats the
   whole transcript as one long sentence and won't return any audio until
   the entire thing is synthesized. The worker instead splits the text into
   8-word chunks (`TTS_CHUNK_WORDS`), synthesizes chunk by chunk, and pushes
   each chunk's PCM into the mixer `Source` as soon as it's ready. Playback
   starts on the first chunk; because synthesis outruns real time, later
   chunks always land before the buffer runs dry.

Trade-off: the resident voice holds the ONNX model + onnxruntime in RAM
permanently (~100 MB) instead of transiently per message. Only applies when
`VOICE_LORA_ENABLED=true` (which already keeps Vosk resident). Rollback is
confined to `tts_worker_thread` in `openvlm-voice.py` if RAM becomes a
problem.

If the piper Python package or the voice model is missing, received texts
still display in the message log — they just aren't spoken (same fallback as
before).

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

## Latency budget (PTT release → remote playback starts)

| Stage | Estimate |
|---|---|
| Vosk finalize (streaming already done) | ~0.1–0.5 s |
| LoRa TX queue + airtime (SHORT_FAST) | ~0.3–1 s |
| Piper TTS first chunk (resident model, chunked) | ~0.3–1 s |
| **Total** | **~1–2.5 s** |

(Before the resident/chunked TTS rework the Piper stage alone was 5–10 s —
see the TTS section above.)

## Nucleus integration

Config (`/etc/nucleus/mesh.conf`):

```
VOICE_LORA_ENABLED=true       # feature gate
VOICE_LORA_MAX_SECS=30        # max speech per PTT press (auto-finalize after)
VOICE_LORA_PORTNUM=260        # PRIVATE_APP range; same on all nodes
VOICE_LORA_HOP_LIMIT=0        # direct RF neighbors only
VOICE_STT_MODEL=              # empty = small model (default; Pi 4 real-time)
VOICE_STT_GRAMMAR=            # empty = free-form; path = phrase-list file
```

Dependencies (handled by `install-packages.sh`, needs internet at install):

| What | Where |
|---|---|
| `vosk` + `piper-tts>=1.4` (pip, system-wide; ≥1.4 for the resident `PiperVoice` Python API) | daemon runs as root |
| Vosk model `vosk-model-small-en-us-0.15` (~40 MB) | `/opt/nucleus/models/vosk/` |
| Piper voice `en_US-lessac-low.onnx` (~60 MB) | `/opt/nucleus/models/piper/` |
| Grammar example `grammar.example.txt` (deploy.sh) | `/opt/nucleus/models/vosk/` |

Startup behavior: the Vosk model loads in a background thread (~5–15 s on a
Pi 4). Until it's ready the LoRa transport button shows "loading speech
model…" and cannot be selected. The Piper voice also loads once in the
background (~5–6 s) in the TTS worker thread; messages received before it
finishes are simply queued. If the piper package or its voice is missing,
received texts still display in the log — they just aren't spoken.

### Implementation files

| file | role |
|---|---|
| `opt/nucleus/bin/openvlm-voice.py` | STT worker (resident Vosk model + per-clip streaming recognizer), text packetizer, TTS worker (resident PiperVoice, chunked streaming → mixer), message history + WS text events, `TEXTS` control command |
| `opt/nucleus/meshtastic/cot_bridge.py` | payload-agnostic voice relay: UDP 5558 → LoRa TX (portnum 260); portnum-260 RX → UDP 5559 |
| `opt/nucleus/web/templates/voice.html` | "LoRa (voice→text)" transport button, Messages log panel, SENDING state cleared by tx confirmation |
| `opt/nucleus/bin/voice` | `voice transport ip\|lora`, `voice texts` CLI commands |
| `etc/nucleus/mesh.conf` | `VOICE_LORA_ENABLED / MAX_SECS / PORTNUM / HOP_LIMIT / VOICE_STT_MODEL / VOICE_STT_GRAMMAR` keys |
| `install-packages.sh` | `vosk` + `piper-tts` pip installs and model downloads to `/opt/nucleus/models/` |
| `opt/nucleus/models/vosk/grammar.example.txt` | starter phrase list for opt-in grammar-constrained STT |

### Enabling on a node

1. Run `install-packages.sh` (or manually: `sudo pip3 install --break-system-packages vosk "piper-tts>=1.4"` + download the two models to `/opt/nucleus/models/`)
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
  displays the text and starts speaking it ~1–2.5 s after release.
- `voice texts` dumps the message history from the CLI.

### Known limitations / future work

- **English only** (both models). Other Vosk/Piper models drop in via
  `VOICE_STT_MODEL` / the model paths if needed.
- **No punctuation** from Vosk small — fine for radio-style traffic.
- **Bigger Vosk models don't work on Pi 4** (see STT model selection above);
  revisit only on faster hardware.
- Multi-packet utterances (seq/continuation flags) deferred; single-packet
  truncation keeps the airtime doctrine simple.
- ~~Per-message Piper subprocess costs ~1–2 s of model load~~ — resolved
  2026-07-07: switched to the resident `PiperVoice` Python API + chunked
  streaming synthesis (see the TTS section above). Measured cost of the
  subprocess was actually ~8.8 s per message on a Pi 4.
