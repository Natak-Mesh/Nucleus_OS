# Nucleus Node Update Guide

**Purpose:** Update a deployed Nucleus node to the latest software from GitHub, in place, over SSH. Your existing mesh configuration is preserved automatically.

The node has a built-in updater that handles the whole process — pulling the latest code, installing any new dependencies, deploying files, migrating your config, and regenerating system configs. You no longer have to run each step by hand.

> **What about my config?** The updater never overwrites your `mesh.conf`. It backs it up first, then only *adds* any brand-new settings that didn't exist in your version (with safe defaults). All of your existing values — IP addresses, mesh name, passwords, tuning — are left exactly as they are.

---

## Prerequisites

- The node must have **internet access** (eth0 plugged into a router, or internet shared over the mesh). The updater pulls from GitHub.
- A computer on the same network as the node (its Wi-Fi AP or Ethernet).
- A terminal application (Terminal on Mac/Linux, PowerShell or PuTTY on Windows).

---

## Step 1 — SSH Into the Node

Open your terminal and connect to the node:

```bash
ssh natak@0021-nucleus.local
```

When prompted for a password, type:

```
52235223
```

> **Note:** You won't see the password as you type — that's normal. Just type it and press Enter.

> **Important:** This is also the `sudo` password.

If it asks "Are you sure you want to continue connecting?" type `yes` and press Enter.

You should now see a prompt like `natak@nucleus:~$`. You're in.

---

## Step 2 — Open the Nucleus Menu

```bash
/opt/nucleus/cli/nucleus-menu.sh
```

The Nucleus OS menu appears. Look under **System & Updates** and choose:

```
11  Update Node
```

Type `11` and press Enter.

---

## Step 3 — Review and Confirm

The updater will:

1. **Check connectivity** — confirms it can reach GitHub.
2. **Show the version change** — e.g. `v2.13.0 → v2.14.0` and a list of what's new.
3. **Ask you to confirm** — type `y` and press Enter to proceed (anything else cancels).

If the node has local changes that would block the update, it will offer to stash them — answer `y` to continue.

---

## Step 4 — Let It Run

Once you confirm, the updater runs the whole sequence on its own:

- Pulls the latest code from GitHub
- Installs any new packages *(this can take a few minutes — let it finish)*
- Deploys updated files to their system locations
- **Migrates your config** — backs up `/etc/nucleus/mesh.conf`, then adds any new settings. It prints a summary of what it added, if anything.
- Regenerates all system configuration files

You'll see progress messages along the way. When it's done it shows **"Update complete."**

---

## Step 5 — Reboot

When prompted **"Reboot now?"**, type `y` and press Enter. The node will reboot to apply all changes.

Your SSH session will disconnect — that's expected. Wait about 60–90 seconds for the node to come back up, then reconnect if you need to verify anything.

---

## What If New Settings Were Added?

If the updater reported that it added new config keys (for example a new feature flag), they're set to safe defaults. To review or change them:

1. SSH back in and open the menu (`/opt/nucleus/cli/nucleus-menu.sh`)
2. Choose **13 Edit Mesh Config**
3. Edit the file, save (`Ctrl+O`, Enter in nano), exit (`Ctrl+X`)
4. When asked, choose `y` to regenerate configs

A timestamped backup of your previous config is always saved at `/etc/nucleus/mesh.conf.bak-<date>` in case you need to roll back.

---

## Troubleshooting

| Problem | Solution |
|---------|----------|
| "Can't reach the update server" | The node needs internet. Plug eth0 into a router with WAN access and try again. |
| Can't SSH to the node | Make sure you're on the node's Wi-Fi AP or connected via Ethernet. Try the IP address directly if `.local` doesn't resolve. |
| "Local changes detected" | Let the updater stash them (`y`), or investigate with `cd ~/Nucleus_OS && git status`. |
| Update stopped partway | Re-run option 11 — the steps are safe to repeat. Your config backup is in `/etc/nucleus/`. |
| Services look wrong after reboot | Open the menu → **12 Service Control** to check/restart individual services, or re-run **11 Update Node**. |

---

## Running the Updater Directly (Advanced)

You can skip the menu and run the updater straight from a shell:

```bash
/opt/nucleus/cli/nucleus-update.sh
```

This is the same tool the menu launches.
