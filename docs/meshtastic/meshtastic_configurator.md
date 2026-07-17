# Meshtastic Radio Configurator — Web UI

## Problem This Solves

With the CoT bridge as the default operating mode, `cot-bridge.service` owns
the radio's USB serial port exclusively. Previously, configuring the radio
meant disabling the bridge entirely (which reboots the node) and using the
official Meshtastic phone app over BLE — a slow, phone-dependent workflow.

The Radio Configurator eliminates the phone app for fleet radios entirely:

- **Configure** the radio (names, channel, preset, hop limit, tx power,
  encryption key) straight from the node's web page
- **Share** the config to other nodes and to phone-app users via QR code
  or channel URL — no fleet push, no SSH, no templates

Everything lives on the existing **Meshtastic page** (`/meshtastic`) in two
new panels: **Radio Config** and **Share Config**.

---

## Architecture: The Bridge-Pause Pattern

Every radio operation transparently wraps the meshtastic CLI in a temporary
bridge pause. The node does **not** reboot (unlike the BLE-mode toggle):

```
1. sudo systemctl stop cot-bridge.service     (only if it was running)
2. sleep 2s                                    (SerialInterface port release)
3. python3 -m meshtastic <operation>           (export / --set / --ch-set-url)
4. wait for radio                              (config writes reboot the radio)
5. sudo systemctl start cot-bridge.service    (only if it was running)
```

Implemented as the `_bridge_paused()` context manager in
`opt/nucleus/meshtastic/meshtastic_api.py`. If the bridge wasn't running
(BLE mode), steps 1/2/5 are skipped and the CLI just runs.

Notes:

- **Concurrency lock:** a module-level `threading.Lock` allows only one radio
  operation at a time. A second request gets HTTP `409` ("Another radio
  operation is in progress").
- **CLI invocation:** the CLI is run as `python3 -m meshtastic` (not the
  `meshtastic` entry point) because `mesh-web.service`'s PATH does not
  include `~/.local/bin`.
- **Sudoers:** `etc/sudoers.d/nucleus-config` already grants the `natak`
  user passwordless `systemctl start/stop cot-bridge.service`. No changes
  were needed.
- **During the pause** (~15–60s) CoT bridging and LoRa voice are offline.
  ATAK multicast on WiFi is unaffected. The bridge reconnects to the radio
  automatically on restart.

### Config caching

A successful read writes the parsed config to `/tmp/meshtastic_config.json`
(atomic tmp+rename). Page loads show the cached values instantly via
`GET /api/meshtastic/config` without touching the radio; the "Last read from
radio: Xs ago" line tells you how fresh it is. The cache is in tmpfs, so it
clears on node reboot — press **Read Config** to repopulate.

---

## Radio Config Panel

| Field | Editable | CLI mapping |
|---|---|---|
| Long Name | yes (1–39 chars) | `--set-owner` |
| Short Name | yes (1–4 chars) | `--set-owner-short` |
| Modem Preset | yes (dropdown) | `--set lora.modem_preset` |
| Hop Limit | yes (1–7) | `--set lora.hop_limit` |
| TX Power | yes (0–30 dBm) | `--set lora.tx_power` |
| Channel Name | yes (1–11 chars) | `--ch-set name --ch-index 0` |
| Encryption Key | "generate new random key" checkbox | `--ch-set psk random --ch-index 0` |
| Region | read-only (display) | set during initial provisioning |
| Role | read-only (display) | set during initial provisioning |

**Read Config** pauses the bridge, runs `--export-config`, parses the YAML,
updates the cache, and populates the form (~15s).

**Apply Changes** diffs the form against the last-read config and sends only
the changed fields. The backend groups them into at most two CLI
invocations — owner/lora settings in one, channel settings in another
(mixing `--set` and `--ch-set` in a single command is unreliable per
meshtastic docs). Each config commit reboots the radio; the backend waits
for the serial port + a firmware settle delay between groups, then re-reads
the config so the UI shows what the radio actually accepted. Budget
~30–60s.

Generating a new random PSK requires a confirmation click — other radios
lose comms until they receive the new channel URL.

### Adding a new editable field later

Four small touch points (all noted in code comments):

1. `_validate_changes()` in `meshtastic_api.py` — add the field name to
   `allowed` + its validation rule
2. `_build_command_groups()` — add its CLI args
3. `_parse_export()` — pull it out of the export YAML so reads show it
4. `meshtastic.html` — add the input to the Radio Config panel, wire it in
   `populateConfig()` and `collectChanges()`

---

## Share Config Panel

The **channel URL** (`https://meshtastic.org/e/#<base64 protobuf>`) encodes
the complete `ChannelSet`: channel name(s), PSK encryption key, and LoRa
modem config (preset, region, hop limit). It is byte-identical to what the
official phone app's QR code encodes. All radios that must communicate need
the same channel URL; node names, roles, power settings can differ.

The panel shows:

- The channel URL as a **QR code** (rendered server-side with the `qrcode`
  Python package as SVG — fully offline, no internet or CDN)
- The URL as **copyable text** with a Copy button (with a non-HTTPS
  clipboard fallback)
- An **Apply Channel URL** box that accepts a pasted URL and applies it with
  `--ch-set-url` (validated by protobuf-decoding it *before* touching the
  radio)

### Sharing workflows

**Node → Node, no phone (copy/paste):**

1. On node A's `/meshtastic` page: Share Config → **Copy URL**
2. On node B's `/meshtastic` page: paste into **Apply Channel URL** → Apply
3. Node B pauses its bridge, applies the URL, radio reboots, bridge restarts

**Node → Node, phone as courier (QR):**

1. Scan the QR on node A's web page with any camera app → it decodes to the
   URL text → copy it
2. Join node B's WiFi, open node B's web page
3. Paste into **Apply Channel URL** → Apply

**Node → handheld radio / phone-app user (QR):**

1. User opens the official Meshtastic app (BLE-paired to their own radio)
2. Channels → scan QR → point at the node's web page QR
3. Their radio joins the fleet channel instantly — same as scanning another
   phone's share QR

### What the channel URL does NOT carry

Node names, device role, position/power/bluetooth settings, module config,
and security keys are **not** in the URL. Only channels + LoRa config. This
is exactly why URL sharing is safe for fleet use — per-node identity is
preserved.

---

## API Reference

All endpoints in `opt/nucleus/meshtastic/meshtastic_api.py`
(blueprint registered by `opt/nucleus/web/app.py`).

### `GET /api/meshtastic/config`

Cached config — instant, no radio access.

```json
{
  "config": {
    "owner": "0022-nucleus", "owner_short": "0022",
    "region": "US", "modem_preset": "SHORT_FAST",
    "hop_limit": 3, "tx_power": 30, "role": "TAK",
    "channel_url": "https://meshtastic.org/e/#...",
    "channels": [{"index": 0, "name": "natak", "has_psk": true}],
    "channel_name": "natak", "read_at": 1760000000
  },
  "busy": false
}
```

`config` is `null` if never read. `busy` is true while another operation
holds the lock.

### `POST /api/meshtastic/config/read`

Fresh read from the radio (bridge pause, ~15s). Returns
`{"success": true, "config": {...}}` or `{"success": false, "error": "..."}`.

### `POST /api/meshtastic/config/apply`

Body: `{"changes": {<field>: <value>, ...}}` where fields are any of
`owner`, `owner_short`, `modem_preset`, `hop_limit`, `tx_power`,
`channel_name`, `psk_random` (bool). Server-side validated. Radio reboots;
response includes the re-read config. ~30–60s.

### `POST /api/meshtastic/config/channel-url`

Body: `{"url": "https://meshtastic.org/e/#..."}`. Decode-validated before
applying via `--ch-set-url`. Radio reboots; response includes the re-read
config. ~30–60s.

### `GET /api/meshtastic/config/qr`

The cached channel URL rendered as an SVG QR code (`image/svg+xml`).
`404` if no config has been read yet.

### Error codes

| Code | Meaning |
|---|---|
| 400 | No radio detected / validation failed / bad URL |
| 409 | Another radio operation is in progress |
| 500 | CLI failure (last 300 chars of output in `error`) |

---

## Timing Reference

| Operation | Duration | Radio reboots? | Bridge downtime |
|---|---|---|---|
| Read Config | ~10–15s | no | ~10–15s |
| Apply (owner/lora only) | ~30–45s | yes | same |
| Apply (incl. channel fields) | ~60–90s (two CLI groups) | yes, twice | same |
| Apply Channel URL | ~30–45s | yes | same |
| QR / cached config / copy URL | instant | no | none |

---

## Troubleshooting

**"Another radio operation is in progress" (409)** — someone else (or
another browser tab) is mid-operation. Wait for it to finish; operations are
bounded by CLI timeouts (120s per invocation).

**"No radio detected"** — no `/dev/ttyACM*` device. Check USB cable /
radio power. The udev rule `60-meshtastic.rules` must be installed
(prevents mtp-probe crashing RAK4631 firmware).

**Config export fails / times out** — most often the serial port wasn't
released in time or the radio is mid-boot. Retry. If it persists, check
`journalctl -u cot-bridge` for a crash-looping bridge holding the port.

**Bridge doesn't restart after an operation** — the restart is in a
`finally` block, so it fires even on CLI failure. Check
`systemctl status cot-bridge` and the Bridge Log panel. Note the bridge
only restarts if it was running before the operation started.

**Stale values in the form** — the form shows cached data (see "Last read
from radio" age). Press **Read Config** for ground truth. Cache lives in
`/tmp` and clears on node reboot.

**Nodes stopped hearing each other after a channel change** — expected:
channel name/PSK/preset changes must be propagated. Share the new channel
URL to every radio in the fleet (paste on nodes, QR for phone-app users).

## Files

```
opt/nucleus/meshtastic/meshtastic_api.py     # backend: endpoints + bridge-pause
opt/nucleus/web/templates/meshtastic.html    # Radio Config + Share Config panels
etc/sudoers.d/nucleus-config                 # (pre-existing, no changes needed)
docs/meshtastic/meshtastic_configurator.md   # this document
```

## Related Docs

- `docs/cli_tools/meshtastic_radio_config_planning.md` — earlier CLI-based
  planning (field reference tables, Natak standard config values)
- `docs/cli_tools/meshtastic_config_sharing.md` — meshtastic CLI
  export/configure/ch-set-url mechanics
- `docs/meshtastic/cot_bridge_integration.md` — the bridge this pauses
