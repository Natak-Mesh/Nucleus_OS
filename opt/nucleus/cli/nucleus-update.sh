#!/bin/bash

#       ..        .....        ...       
#       ....     ......       ....      
#       .......... ...       .....       
#       ........    ..      ......       
#       ......      ..     .......       
#       .....       ...  .........       
#       ....        .....     ....      
#       ...         ....        ..   

#############################################
#        N A T A K   -   Nucleus OS         #
#                                           #
#            In-Place Update Tool           #
#############################################

# Pulls the latest Nucleus OS from GitHub and runs the full deploy sequence
# in place, so a node can be updated over SSH without pushing via Tailscale.
#
# Sequence:
#   1. Pre-flight checks (internet, git repo, clean-ish tree)
#   2. git fetch + show version/commit diff, confirm
#   3. git pull
#   4. self re-exec (so the freshly-pulled logic runs the rest)
#   5. install-packages.sh  -> deploy.sh
#   6. config auto-migrate (append only NEW keys to /etc/nucleus/mesh.conf)
#   7. config_generation.sh -> offer reboot
#
# Launch from the menu, or directly:
#   /opt/nucleus/cli/nucleus-update.sh

set -o pipefail

# --- Repo location ---
# The git checkout lives in the natak user's home. Resolve the real user even
# when this runs under sudo.
REPO_USER="${SUDO_USER:-natak}"
REPO_DIR="/home/${REPO_USER}/Nucleus_OS"
LIVE_CONF="/etc/nucleus/mesh.conf"

# --- Colors ---
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[0;33m'
CYAN='\033[0;36m'
BOLD='\033[1m'
DIM='\033[2m'
RESET='\033[0m'

# --- Helpers ---

err()  { printf "  ${RED}%s${RESET}\n" "$1" >&2; }
ok()   { printf "  ${GREEN}%s${RESET}\n" "$1"; }
warn() { printf "  ${YELLOW}%s${RESET}\n" "$1"; }
info() { printf "  ${DIM}%s${RESET}\n" "$1"; }

pause_after() {
    echo ""
    printf "${DIM}  Press any key to continue...${RESET}"
    read -rsn1
    echo ""
}

# Run a git command as the repo owner (avoids "dubious ownership" under sudo)
git_repo() {
    sudo -u "$REPO_USER" git -C "$REPO_DIR" "$@"
}

# --- Banner ---

banner() {
    clear
    printf "${BOLD}═══════════════════════════════════════════${RESET}\n"
    printf "${BOLD}   Nucleus OS — Update${RESET}\n"
    printf "${BOLD}═══════════════════════════════════════════${RESET}\n"
    echo ""
}

# --- Pre-flight checks ---

preflight() {
    # Repo present?
    if [ ! -d "${REPO_DIR}/.git" ]; then
        err "No git repo found at ${REPO_DIR}"
        info "Expected the Nucleus_OS checkout in the natak home directory."
        return 1
    fi

    # Internet / GitHub reachable?
    printf "  Checking connectivity... "
    if ! git_repo ls-remote --exit-code origin HEAD &>/dev/null; then
        printf "${RED}offline${RESET}\n"
        err "Can't reach the update server (GitHub)."
        info "This node needs WAN access (eth0 to a router, or internet"
        info "shared over the mesh) to download updates. Check the"
        info "connection and try again."
        return 1
    fi
    printf "${GREEN}ok${RESET}\n"

    # Dirty working tree?
    if [ -n "$(git_repo status --porcelain 2>/dev/null)" ]; then
        echo ""
        warn "Local changes detected in ${REPO_DIR}:"
        git_repo status --short 2>/dev/null | sed 's/^/    /'
        echo ""
        printf "  These would block the update. Stash them? ${DIM}[y/N]${RESET}: "
        read -r ans
        if [ "$ans" = "y" ] || [ "$ans" = "Y" ]; then
            if git_repo stash push -u -m "nucleus-update auto-stash $(date +%Y%m%d-%H%M%S)" &>/dev/null; then
                ok "Local changes stashed (restore later with 'git stash pop')."
            else
                err "Failed to stash changes. Aborting."
                return 1
            fi
        else
            err "Aborting — resolve local changes first."
            return 1
        fi
    fi

    return 0
}

# --- Version / commit diff ---

show_diff() {
    git_repo fetch origin &>/dev/null

    local branch local_ver remote_ver
    branch=$(git_repo rev-parse --abbrev-ref HEAD 2>/dev/null)
    branch=${branch:-main}

    local_ver=$(cat "${REPO_DIR}/VERSION" 2>/dev/null || echo "unknown")
    remote_ver=$(git_repo show "origin/${branch}:VERSION" 2>/dev/null || echo "unknown")

    echo ""
    printf "  ${BOLD}Version${RESET}   %s ${DIM}→${RESET} ${CYAN}%s${RESET}\n" "$local_ver" "$remote_ver"
    echo ""

    # Already up to date?
    if [ "$(git_repo rev-parse HEAD 2>/dev/null)" = "$(git_repo rev-parse "origin/${branch}" 2>/dev/null)" ]; then
        ok "Already up to date — nothing to pull."
        echo ""
        printf "  Re-run the deploy steps anyway? ${DIM}[y/N]${RESET}: "
        read -r ans
        [ "$ans" = "y" ] || [ "$ans" = "Y" ]
        return $?
    fi

    printf "  ${BOLD}Incoming changes${RESET}\n"
    git_repo log --oneline --no-decorate "HEAD..origin/${branch}" 2>/dev/null | head -20 | sed 's/^/    /'
    echo ""
    printf "  Proceed with update? ${DIM}[y/N]${RESET}: "
    read -r ans
    [ "$ans" = "y" ] || [ "$ans" = "Y" ]
}

# --- Config auto-migration ---
# Append keys present in the repo template but missing from the live mesh.conf.
# Existing keys and their values are NEVER touched.
migrate_config() {
    local template="${REPO_DIR}/etc/nucleus/mesh.conf"

    echo ""
    printf "  ${BOLD}Config migration${RESET}\n"

    if [ ! -f "$template" ]; then
        warn "Template ${template} not found — skipping config migration."
        return 0
    fi
    if [ ! -f "$LIVE_CONF" ]; then
        warn "Live ${LIVE_CONF} not found — skipping (config_generation will handle a fresh copy)."
        return 0
    fi

    # Collect keys already present in the live file
    local live_keys
    live_keys=$(grep -oP '^\s*\K[A-Za-z_][A-Za-z0-9_]*(?==)' "$LIVE_CONF" 2>/dev/null | sort -u)

    # Find template keys missing from live
    local missing=()
    local key
    while IFS= read -r key; do
        [ -z "$key" ] && continue
        if ! grep -qx "$key" <<< "$live_keys"; then
            missing+=("$key")
        fi
    done < <(grep -oP '^\s*\K[A-Za-z_][A-Za-z0-9_]*(?==)' "$template" 2>/dev/null | awk '!seen[$0]++')

    if [ ${#missing[@]} -eq 0 ]; then
        ok "No new config keys — mesh.conf is current."
        return 0
    fi

    # Backup before touching anything
    local backup="${LIVE_CONF}.bak-$(date +%Y%m%d-%H%M%S)"
    cp "$LIVE_CONF" "$backup"
    info "Backed up current config to ${backup}"

    # For each missing key, append its comment block + line from the template.
    # awk walks the template, buffering comment/blank lines, and when it hits a
    # target KEY= line it emits the buffered block + that line.
    {
        echo ""
        echo "# ============================================================"
        echo "# Added by nucleus-update on $(date +%Y-%m-%d)"
        echo "# ============================================================"
        for key in "${missing[@]}"; do
            awk -v target="$key" '
                /^[[:space:]]*#/ || /^[[:space:]]*$/ { buf = buf $0 "\n"; next }
                {
                    split($0, a, "=")
                    k = a[1]
                    gsub(/^[[:space:]]+/, "", k)
                    if (k == target) { printf "%s%s\n", buf, $0 }
                    buf = ""
                }
            ' "$template"
        done
    } >> "$LIVE_CONF"

    ok "Added ${#missing[@]} new config key(s): ${missing[*]}"
    info "Review/adjust them via the menu's 'Edit config' option if needed."
    return 0
}

# --- Deploy sequence ---

run_deploy() {
    echo ""
    printf "  ${BOLD}Installing packages${RESET} ${DIM}(this can take a few minutes)${RESET}\n"
    echo ""
    if ! ( cd "$REPO_DIR" && sudo ./install-packages.sh ); then
        err "install-packages.sh failed. Aborting before deploy."
        return 1
    fi

    echo ""
    printf "  ${BOLD}Deploying files${RESET}\n"
    echo ""
    if ! ( cd "$REPO_DIR" && sudo ./deploy.sh ); then
        err "deploy.sh failed."
        return 1
    fi

    # Append any new config keys before regenerating
    migrate_config

    echo ""
    printf "  ${BOLD}Regenerating system configs${RESET}\n"
    echo ""
    if ! sudo /opt/nucleus/bin/config_generation.sh; then
        err "config_generation.sh failed."
        return 1
    fi

    return 0
}

# --- Main ---

# Re-exec guard: after git pull we relaunch the freshly-pulled copy of this
# script exactly once so any changes to nucleus-update.sh itself take effect.
main() {
    banner

    if [ "$NUCLEUS_UPDATE_REEXEC" = "1" ]; then
        # We are the re-exec'd (post-pull) run. Skip straight to deploy.
        info "Running updated deploy sequence..."
        if run_deploy; then
            finish
        else
            err "Update did not complete cleanly. See messages above."
            pause_after
        fi
        return
    fi

    preflight || { pause_after; return; }
    show_diff || { echo ""; info "Update cancelled."; pause_after; return; }

    echo ""
    printf "  ${BOLD}Pulling latest code${RESET}\n"
    if ! git_repo pull --ff-only origin "$(git_repo rev-parse --abbrev-ref HEAD)"; then
        err "git pull failed."
        pause_after
        return
    fi
    ok "Code updated."

    # Re-exec the freshly pulled version of ourselves
    export NUCLEUS_UPDATE_REEXEC=1
    exec bash "${REPO_DIR}/opt/nucleus/cli/nucleus-update.sh"
}

finish() {
    echo ""
    printf "${BOLD}═══════════════════════════════════════════${RESET}\n"
    ok "Update complete."
    printf "${BOLD}═══════════════════════════════════════════${RESET}\n"
    echo ""
    printf "  A reboot is recommended to apply all changes.\n"
    printf "  Reboot now? ${DIM}[y/N]${RESET}: "
    read -r ans
    if [ "$ans" = "y" ] || [ "$ans" = "Y" ]; then
        info "Rebooting..."
        sleep 1
        sudo reboot
    else
        info "Skipped reboot. Reboot manually later with: sudo reboot"
        pause_after
    fi
}

main "$@"
