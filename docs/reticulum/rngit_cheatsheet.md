# rngit Cheat Sheet — Git over Reticulum

A quick, beginner-friendly reference for hosting and using a git repository
over the **Reticulum** mesh network — no internet, GitHub, or central server
required. The repo travels peer-to-peer over whatever Reticulum interfaces you
have (LoRa, packet radio, TCP, I2P, etc.).

---

## The big picture

There are **two sides** to rngit, handled by two different programs:

| Side | Program | What it does |
|------|---------|--------------|
| **Server / host** | `rngit` | Serves a repo to the mesh. Has its own Reticulum identity (a destination hash). This is what others connect *to*. |
| **Client** | `git-remote-rns` | A git "remote helper" that teaches plain `git` how to talk to `rns://` URLs. You never call it directly — `git push`/`git pull` use it automatically. |

Supporting Reticulum tools you'll also see:
- `rnsd`     — the Reticulum daemon (must be running for any of this to work)
- `rnstatus` — show interface/link status
- `rnpath`   — show/lookup the path to a destination hash

A repo's address looks like:
```
rns://<destination-hash>/public/<RepoName>.git
```

---

## This repo (Nucleus_OS) quick reference

```bash
# The rngit remote is already configured as "rngit":
rns://92b31186445606000c24ab99ce6b7d0e/public/Nucleus_OS.git

# Push the current branch
git push rngit V2-OS-Babeld

# Push all tags (release markers)
git push rngit --tags

# Pull updates from the mesh
git pull rngit V2-OS-Babeld

# See what the mesh copy currently has
git ls-remote rngit
```

---

## Client side — everyday commands

These are just normal git commands; the `rns://` URL makes them go over the mesh.

```bash
# Clone a repo from the mesh
git clone rns://<hash>/public/RepoName.git

# Add a mesh remote to an existing repo (named "rngit" here by convention)
git remote add rngit rns://<hash>/public/RepoName.git

# Push a branch
git push rngit <branch>

# Push tags too (so version markers are mirrored)
git push rngit --tags

# Fetch / pull
git fetch rngit
git pull rngit <branch>

# List the remote's branches & tags without downloading
git ls-remote rngit
```

> Tip: pushing is a normal git fast-forward. If git refuses a push, the mesh
> copy has commits you don't have locally — `git fetch rngit` first, then
> reconcile, just like with GitHub.

---

## Tags vs. "releases"

- A **git tag** (e.g. `v2.13.1`) is a permanent bookmark pointing at one commit,
  used to mark a release. Tags live inside git and are mirrored to rngit.
- GitHub "Releases" (web pages with notes + downloadable files) are a
  GitHub-only feature built *on top of* a tag. rngit is plain git, so it mirrors
  the **tags** but not GitHub's release pages.

```bash
# Create a tag for the current commit
git tag v2.14.0

# Push one specific tag
git push rngit v2.14.0

# Push every tag
git push rngit --tags

# List local tags (newest first)
git tag --sort=-creatordate
```

---

## Server side — hosting a repo with rngit

```bash
# Show this node's identity & destination hash (the address others connect to)
rngit -p

# Run rngit interactively (drops into a shell after init)
rngit -i

# Run as a background service (logs to file)
rngit -s

# Use an alternate config directory
rngit --config /path/to/config

# Help / version
rngit --help
rngit --version
```

The destination hash printed by `rngit -p` is what goes into the `rns://<hash>/...`
URL that clients use to reach your repo.

---

## Reticulum stack — keeping the mesh up

`rngit` needs Reticulum running underneath it.

```bash
# Start the Reticulum daemon (must be running)
rnsd

# Check interface and link status
rnstatus

# Look up / display the path to a destination hash
rnpath <destination-hash>
```

If a `git push rngit ...` hangs on "Requesting path...", the destination isn't
reachable yet — check `rnstatus` and `rnpath`, and make sure `rnsd` is running
on both ends.

---

## Common troubleshooting

| Symptom | Likely cause / fix |
|---------|--------------------|
| `Requesting path...` never resolves | Destination unreachable. Check `rnsd` is running; `rnstatus`; `rnpath <hash>`. |
| Push rejected (non-fast-forward) | Mesh copy is ahead. `git fetch rngit`, reconcile, push again. |
| `git-remote-rns` not found | The helper isn't on PATH. Ensure `~/.local/bin` is in `$PATH`. |
| Slow transfers | Normal over low-bandwidth links (LoRa). Be patient; pushes are incremental. |

---

*Reticulum keeps your git history syncing across the mesh even when the internet
is down — useful for field/disconnected operations.*
