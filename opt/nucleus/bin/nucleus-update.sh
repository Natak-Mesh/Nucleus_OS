#!/bin/bash

# Nucleus OS - Node Update Script (Stage 1: CLI)
#
# Pulls the latest code from the git repository and re-runs the standard
# install/deploy/config flow WITHOUT clobbering the node's live mesh.conf.
# deploy.sh preserves /etc/nucleus/mesh.conf on an existing node (it only
# appends keys that are missing), so this is an update, not a reflash.
#
# Order of operations:
#   1. Pre-flight WAN reachability check (abort if offline)
#   2. Back up /etc/nucleus/mesh.conf (timestamped) + record current git HEAD
#   3. Refuse to continue if the repo working tree is dirty (uncommitted edits)
#   4. git pull
#   5. install-packages.sh
#   6. deploy.sh
#   7. config_generation.sh
#
# This script does NOT reboot. Reboot is a separate, explicit operator action.
#
# Exit codes:
#   0  updated successfully
#   1  already up to date (no changes pulled)
#   2  offline / no WAN reachability
#   3  dirty working tree (uncommitted local changes) - stopped, reported
#   4  git pull failed
#   5  install-packages.sh failed
#   6  deploy.sh failed
#   7  config_generation.sh failed
#   8  environment/setup error (repo missing, not a git repo, etc.)

REPO_DIR="${NUCLEUS_REPO_DIR:-$(eval echo ~"${SUDO_USER:-$USER}")/Nucleus_OS}"
MESH_CONF="/etc/nucleus/mesh.conf"
LOG_FILE="/var/log/nucleus-update.log"

# --- logging -----------------------------------------------------------------
# Fall back to a user-writable log if /var/log is not writable.
if ! touch "$LOG_FILE" 2>/dev/null; then
    LOG_FILE="$HOME/nucleus-update.log"
fi

log() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*" | tee -a "$LOG_FILE"
}

fail() {
    # $1 = exit code, rest = message
    local code="$1"; shift
    log "ERROR: $*"
    log "===== update FAILED (exit $code) ====="
    exit "$code"
}

log "===== nucleus-update started ====="
log "repo: $REPO_DIR"

# --- environment checks ------------------------------------------------------
[ -d "$REPO_DIR" ] || fail 8 "repo directory not found: $REPO_DIR"
cd "$REPO_DIR" || fail 8 "cannot cd into repo: $REPO_DIR"
git rev-parse --is-inside-work-tree >/dev/null 2>&1 || fail 8 "$REPO_DIR is not a git repository"

# --- step 1: pre-flight WAN reachability ------------------------------------
log "checking network reachability to git remote..."
if ! timeout 20 git ls-remote origin >/dev/null 2>&1; then
    log "git remote unreachable"
    log "===== update ABORTED (offline) ====="
    exit 2
fi
log "network OK"

# --- step 2: backups ---------------------------------------------------------
BEFORE_HEAD="$(git rev-parse HEAD 2>/dev/null)"
log "current git HEAD: $BEFORE_HEAD"

if [ -f "$MESH_CONF" ]; then
    BACKUP="${MESH_CONF}.bak.$(date '+%Y%m%d-%H%M%S')"
    if cp "$MESH_CONF" "$BACKUP" 2>/dev/null; then
        log "backed up mesh.conf -> $BACKUP"
    else
        log "note: could not back up mesh.conf (permissions); deploy.sh still preserves it"
    fi
else
    log "note: $MESH_CONF not present (fresh node); deploy.sh will install the template"
fi

# --- step 3: dirty working tree check ---------------------------------------
if [ -n "$(git status --porcelain)" ]; then
    log "working tree has uncommitted changes:"
    git status --short | tee -a "$LOG_FILE"
    fail 3 "repository has local modifications - stopping. Resolve them, then re-run."
fi

# --- step 4: git pull --------------------------------------------------------
log "pulling latest code..."
if ! git pull --ff-only 2>&1 | tee -a "$LOG_FILE"; then
    fail 4 "git pull failed"
fi
AFTER_HEAD="$(git rev-parse HEAD 2>/dev/null)"
log "git HEAD after pull: $AFTER_HEAD"

if [ "$BEFORE_HEAD" = "$AFTER_HEAD" ]; then
    log "already up to date - no new code pulled"
    log "===== update finished (no changes) ====="
    exit 1
fi

# --- step 5: install-packages.sh --------------------------------------------
log "running install-packages.sh..."
if ! sudo ./install-packages.sh 2>&1 | tee -a "$LOG_FILE"; then
    fail 5 "install-packages.sh failed"
fi

# --- step 6: deploy.sh -------------------------------------------------------
log "running deploy.sh..."
if ! sudo ./deploy.sh 2>&1 | tee -a "$LOG_FILE"; then
    fail 6 "deploy.sh failed"
fi

# --- step 7: config_generation.sh -------------------------------------------
log "running config_generation.sh..."
if ! sudo /opt/nucleus/bin/config_generation.sh 2>&1 | tee -a "$LOG_FILE"; then
    fail 7 "config_generation.sh failed"
fi

log "update applied. A reboot is recommended to apply all changes."
log "===== update SUCCEEDED ====="
exit 0
