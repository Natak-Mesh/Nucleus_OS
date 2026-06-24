# Web UI `.local` Hostname Access

## Summary

The Nucleus web UI can be reached from a browser at:

```
http://<serial>-nucleus.local
```

e.g. `http://0009-nucleus.local` — **no IP address and no `:5000` port needed.**

This works in addition to the direct `http://<node-ip>:5000` URL, which still
functions as before.

## How it works

Three pieces combine to make this work:

1. **Avahi / mDNS** — `avahi-daemon` is installed and running on every node, and
   the system hostname is `<serial>-nucleus` (e.g. `0009-nucleus`). Avahi
   advertises this hostname over multicast DNS, so any client on the same L2
   segment (the node's Wi-Fi AP, a direct Ethernet cable, or the same LAN) can
   resolve `<serial>-nucleus.local` to the node's IP without any DNS server.

2. **The Flask web UI** — still listens on `0.0.0.0:5000`, run by
   `mesh-web.service`. Nothing about the app itself changed.

3. **nginx reverse proxy on ports 80 and 443** — `nginx` is installed via
   `install-packages.sh`, and `config_generation.sh` generates a vhost at
   `/etc/nginx/sites-available/zzz-nucleus-web` (symlinked into
   `sites-enabled/`). That vhost has two `server` blocks, both matching
   `server_name <serial>-nucleus.local` and proxying `/` to
   `http://127.0.0.1:5000`:
   - **port 80 (HTTP)** — matched by the `Host:` header
   - **port 443 (HTTPS)** — matched by SNI, using our own self-signed cert
     (see below)

So when a browser requests `http://<serial>-nucleus.local`, it connects to
port 80; nginx sees the `Host:` header, matches the Nucleus vhost, and proxies
the request to the Flask UI. The port is "dropped" because nginx is answering
on the default HTTP port 80.

### Why a 443 (HTTPS) block is required

Phones and modern desktop browsers frequently **force HTTPS** — either because
they previously visited the OTS site (which sends an HSTS header), or via the
browser's own automatic `http://` → `https://` upgrade. In that case typing
`<serial>-nucleus.local` actually requests **`https://<serial>-nucleus.local`
(port 443)**, not port 80.

If only a port-80 block existed, those HTTPS requests would fall through to
whatever owns 443 — on an OTS node that's OTS, so the phone would land on the
OTS login screen. The dedicated 443 block fixes this. nginx selects the HTTPS
`server` block by **SNI** (the hostname inside the TLS handshake), so
`https://<serial>-nucleus.local` matches our block while `https://<node-ip>`
and OTS hostnames go to OTS, untouched.

### TLS certificate (our own, self-signed)

`config_generation.sh` generates a self-signed certificate for
`<serial>-nucleus.local` (idempotent — only created if missing), stored at:

```
/etc/nucleus/certs/nucleus-web.crt
/etc/nucleus/certs/nucleus-web.key
```

We use **our own** cert (not OTS's) so the HTTPS path behaves identically on OTS
and non-OTS nodes. Because it's self-signed for a LAN `.local` hostname,
browsers will show a "not secure" / certificate warning that the user clicks
through — this is expected and unavoidable for a local self-signed host (it's
the same click-through OTS already requires).

## Coexistence with OpenTAKServer (OTS)

OTS, when installed, brings its own nginx and **owns port 80** with vhosts named
`ots_http`, `ots_https`, `ots_certificate_enrollment`. We deliberately do **not**
touch those.

nginx routes requests by the `Host:` header (name-based virtual hosting):

| Request                                  | Served by                          |
|------------------------------------------|------------------------------------|
| `http(s)://<serial>-nucleus.local`       | Nucleus web UI (our vhost → :5000) |
| `http(s)://<node-ip>` (by IP)            | OTS (its existing default block)   |
| OTS hostnames / OTS ATAK ports (8443/8080/8089/...) | OTS, unchanged          |

The Nucleus vhost file is intentionally named with a `zzz-` prefix so it sorts
**after** the `ots_*` files in `sites-enabled/`. This keeps the OTS blocks as
the *default* responder for any request that doesn't match our explicit
`.local` server_name / SNI (e.g. access by raw IP), so OTS behavior is preserved
exactly.

**Net effect:** the only thing that changed is what happens when you browse to
the `.local` hostname — it now lands on the Nucleus web UI instead of OTS.

## Install / deploy ordering

- `nginx` is in `install-packages.sh`, which runs **before** `config_generation.sh`.
  So nginx is always present when the vhost is generated — no special-casing.
- `config_generation.sh` writes the vhost, creates the symlink, runs `nginx -t`,
  and reloads nginx. It is idempotent and safe to re-run.

### OpenTAKServer is installed *after* the base setup

OTS is a manual install step that happens *after* `install-packages.sh` /
`deploy.sh` / `config_generation.sh`. Two notes:

- The OTS installer creates its **own** nginx vhost files and does not delete
  our separately-named `zzz-nucleus-web` file, so our config survives the OTS
  install. nginx's main config keeps the standard
  `include /etc/nginx/sites-enabled/*;`, so our vhost continues to load.
- **After installing OTS, re-run `config_generation.sh`** (this is already the
  established pattern — see the note at the bottom of `mesh.conf`). Re-running
  re-asserts the vhost and reloads nginx, and lets you verify coexistence.

## Verification

On a node, after deploy:

```bash
# vhost present and enabled
ls -l /etc/nginx/sites-enabled/zzz-nucleus-web

# nginx config valid
sudo nginx -t

# avahi resolves the hostname (install avahi-utils if avahi-resolve is missing)
avahi-resolve -n "$(hostname).local"
```

From a client on the same network:

- Browse to `http://<serial>-nucleus.local` → **Nucleus web UI**
- On an OTS node, browse to `http://<node-ip>` → **OTS** (unchanged)

## Files involved

| File | Role |
|------|------|
| `install-packages.sh` | Installs `nginx` |
| `opt/nucleus/bin/config_generation.sh` | Generates the `zzz-nucleus-web` nginx vhost from the system hostname |
| `/etc/nginx/sites-available/zzz-nucleus-web` | Generated vhost (symlinked into `sites-enabled/`) |
| `mesh-web.service` | Runs the Flask web UI on `:5000` (unchanged) |

## Notes / troubleshooting

- **UFW:** currently inactive on nodes, so no firewall rule is required. If UFW
  is ever enabled, allow ports 80 and 443 (`sudo ufw allow 80/tcp`,
  `sudo ufw allow 443/tcp`).
- **`.local` doesn't resolve:** the client must be on the same L2 segment and
  support mDNS (macOS/iOS built-in; most Linux via `nss-mdns`; Windows 10+ has
  it, older Windows may need Bonjour). Fall back to `http://<node-ip>:5000`.
