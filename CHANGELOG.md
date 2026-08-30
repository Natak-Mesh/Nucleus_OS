# Changelog

## v3.1.0

This release adds an in-browser node update workflow, first-class support for
HAT- and USB-connected Meshtastic radios via `meshtasticd`, and optional
integration with the official TAK Server — plus radio/mesh reliability fixes
and repo cleanup. The 1W LoRa work has been merged back into the main line for
this release.

### New Features

**Node updates from the web UI**
- New `nucleus-update.sh` update flow: pre-flight WAN check, timestamped
  `mesh.conf` backup, refuses to run on a dirty tree, runs
  `git pull → install-packages.sh → deploy.sh → config_generation.sh`, logs to
  `/var/log/nucleus-update.log`, with distinct per-stage exit codes. Never
  auto-reboots.
- New **Update** page in the web UI with a network indicator, live streaming
  log, and a separate explicit **Reboot** action.
- Passwordless (NOPASSWD sudoers) execution for one-click updates on deployed
  nodes.

**Meshtastic `meshtasticd` radio support**
- Support for radios on the **RAK6421 Pi HAT** (SPI/GPIO) via `meshtasticd` in
  Docker, exposing the Meshtastic API on TCP `localhost:4403`.
- **Auto-detection** of USB vs HAT/SPI radios at startup — the rest of the
  system always talks over TCP regardless of physical connection.
- Web UI (QR code, channel URL share/apply, radio config) now works identically
  on TCP/`meshtasticd` nodes, and reports the actual radio transport (HAT vs USB
  serial).

**Optional official TAK Server integration**
- New **TAK Server Certs** page (gated behind `official_takserver=true` in
  `mesh.conf`, default off) for downloading intermediate/webadmin certs and
  reaching the WebAdmin panel.

### Fixes & Improvements
- **TAK Server** stack now ordered after mesh bring-up so its Java/PostgreSQL/
  Docker load no longer starves the Pi's CPU during radio startup (inert on
  nodes without TAK Server).
- **Radio config now persists across reboots** (named Docker volume); region
  auto-set to `US` on first boot, fixing silent "Region unset" TX failures.
- Corrected LoRa radio binding to **Slot 2**, fixing "SX126x init / No sx1262
  radio" errors.
- Filtered phantom/ghost self-nodes from the web UI heard list.
- Pinned `meshtastic-tak@v0.9.1` and the TAKPacket-SDK version for reproducible
  builds.
- Fixed web-triggered updates resolving the repo path via `SUDO_USER`.

### Maintenance
- Removed the outdated Reticulum manual, ignored docs binaries, and resolved
  stray `.gitignore` merge-conflict markers.
