# Yggdrasil Overlay Network

## Status: DEFERRED

Installed via `install-packages.sh` but **not enabled or configured**. Tailscale covers current remote access needs.

---

## What It Is

Yggdrasil is a decentralized, end-to-end encrypted IPv6 overlay network. No central server, no accounts, no third-party dependencies. Each node gets a stable `200::/7` address derived from its keypair. Nodes peer over TCP/TLS connections through the internet.

## How It Would Work

A Nucleus node plugged into any internet connection would establish encrypted tunnels back to configured Yggdrasil peers — extending the mesh over the internet. Nodes just need to know at least one peer address (a VPS, a HQ node, etc.) to connect.

## Why Not Now

Tailscale already handles remote access with better NAT traversal and an existing web GUI integration. Yggdrasil becomes relevant when:

- Nodes ship to customers who shouldn't need a Tailscale account
- Operating where Tailscale's servers or WireGuard protocol are blocked
- Zero external service dependency is a product requirement
- Self-hosted anchor peer (simple VPS) is preferred over running Headscale

## Current State

- **Installed:** Yes (apt package)
- **Enabled:** No
- **Configured:** No (default config at `/etc/yggdrasil/yggdrasil.conf`)
- **Web GUI:** None

## When We Revisit

- Decide integration model (separate overlay vs. route injection into babeld)
- Design peer config (anchor peers with known addresses)
- Add config to `mesh.conf` / `config_generation.sh`
- Add web GUI page
- Test alongside Tailscale
