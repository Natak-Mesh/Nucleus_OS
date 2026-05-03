# Voice-Text-Voice Bridge (STT → LoRa → TTS)

## Architecture

```
┌──────── Sending Node ────────┐       ┌──────── Receiving Node ───────┐
│                               │       │                               │
│  EUD browser → hold-to-talk   │       │  cot_bridge.py RX callback    │
│  ↓ MediaRecorder + WebSocket  │       │  ↓ voice-text portnum         │
│  Vosk STT on Pi (audio→text)  │       │  Piper TTS on Pi (text→audio) │
│  ↓                            │       │  ↓                            │
│  cot_bridge.py TX over LoRa   │       │  WebSocket → browser playback │
└───────────────────────────────┘       └───────────────────────────────┘
```

Every node runs both STT and TTS. Audio I/O is via the EUD browser connected to the node's AP.

---

## Components

- **Vosk** — offline STT. `vosk-model-small-en-us-0.15` (~40 MB). Python API.
- **Piper** — offline neural TTS. Voice models 15–75 MB. CLI or Python.
- **cot_bridge.py** — add voice-text portnum handler alongside existing CoT (portnum 257). Single service, no serial port contention.
- **app.py + voice.html** — flask-socketio WebSocket for audio capture/playback in browser. New `/voice` route.

---

## LoRa Packet Format

```
┌───────┬───────┬──────────────────────┐
│ seq   │ flags │ UTF-8 text payload   │
│ (1B)  │ (1B)  │ (up to ~224 bytes)   │
└───────┴───────┴──────────────────────┘
```

- **seq**: Sequence number for multi-packet utterances
- **flags**: `0x01` = final, `0x02` = continuation
- **text**: UTF-8 speech text

Most sentences fit in one packet (~50–200 bytes). Sender node ID is in the Meshtastic packet header.

---

## Latency Budget

| Stage | Estimate |
|-------|----------|
| Audio capture + WebSocket to Pi | ~100 ms |
| Vosk STT | 500 ms – 2 s |
| LoRa TX (Short/Fast, single packet) | 500 ms – 1.5 s |
| Piper TTS | 500 ms – 1 s |
| WebSocket + playback | ~100 ms |
| **Total** | **~2–5 s** |

---

## Implementation Steps

### Phase 1: Single Node Pipeline
1. Install Vosk + small model, Piper + English voice model
2. Add flask-socketio to app.py
3. Create `voice.html` — hold-to-talk, audio capture/playback via WebSocket
4. Wire: browser audio → Vosk → text → Piper → browser playback

### Phase 2: LoRa Integration
5. Add voice-text portnum to cot_bridge.py (TX: local socket accepts text, sends over LoRa; RX: onReceive handles voice-text portnum, feeds Piper)
6. Test node-to-node

### Phase 3: Integration
7. Add `VOICE_TEXT_ENABLED` to mesh.conf
8. Add `/voice` to web UI nav
9. Multi-packet support (seq/flags)

---

## Dependencies

| Package | Purpose |
|---------|---------|
| `vosk` | STT engine (pip + ~40 MB model) |
| `piper-tts` | TTS engine (binary + ~20–75 MB model) |
| `flask-socketio` | WebSocket for Flask |
| `eventlet` | Async backend for socketio |

---

## Files

| File | Change |
|------|--------|
| `opt/nucleus/meshtastic/cot_bridge.py` | Add voice-text portnum TX/RX |
| `opt/nucleus/web/app.py` | Add socketio, `/voice` route |
| `opt/nucleus/web/templates/voice.html` | Audio capture/playback UI |
| `etc/nucleus/mesh.conf` | `VOICE_TEXT_ENABLED` toggle |
