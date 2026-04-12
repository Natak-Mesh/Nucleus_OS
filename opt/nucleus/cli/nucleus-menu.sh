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
#           CLI Terminal Menu               #
#############################################

# Interactive menu for Nucleus node troubleshooting and diagnostics.
# Launch: ssh -t natak@<host> /opt/nucleus/cli/nucleus-menu.sh
# Or just run it from a shell on the Pi.

CLI_DIR="$(dirname "$(readlink -f "$0")")"

source /etc/nucleus/mesh.conf 2>/dev/null

# --- Node-to-Node SSH Credentials ---
# Used by: iperf3 (auto-start remote server), file transfer (scp), mtr
# TODO: Move to /etc/nucleus/mesh.conf when config is finalized
NODE_USER="natak"
NODE_PASS="52235223"

# Ensure natak's pip-installed tools are in PATH (needed when running as root)
export PATH="/home/${NODE_USER}/.local/bin:${PATH}"

# Staging directory for file transfers (laptop ↔ Pi and Pi ↔ Pi)
TRANSFER_DIR="/home/${NODE_USER}/transfer"
mkdir -p "$TRANSFER_DIR" 2>/dev/null

# --- Colors ---
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[0;33m'
CYAN='\033[0;36m'
BOLD='\033[1m'
DIM='\033[2m'
RESET='\033[0m'

# --- Helpers ---

# Prompt for an IP/hostname, with optional default
# NOTE: All display output goes to stderr so this works inside $() capture
prompt_target() {
    local prompt_text=${1:-"Target IP/hostname"}
    local default=${2:-""}
    local target

    if [ -n "$default" ]; then
        printf "  ${prompt_text} [${default}]: " >&2
        read -r target
        target=${target:-$default}
    else
        printf "  ${prompt_text}: " >&2
        read -r target
    fi

    if [ -z "$target" ]; then
        echo "" >&2
        printf "  ${RED}No target specified.${RESET}\n" >&2
        sleep 1
        return 1
    fi
    echo "$target"
}

# Run a command on a remote node via sshpass
# Usage: remote_ssh <host> <command...>
remote_ssh() {
    local host="$1"; shift
    sshpass -p "$NODE_PASS" ssh -o StrictHostKeyChecking=no -o ConnectTimeout=5 \
        "${NODE_USER}@${host}" "$@"
}

# Copy a file to a remote node via sshpass
# Usage: remote_scp <local_file> <host> <remote_path>
remote_scp_to() {
    local file="$1" host="$2" dest="$3"
    sshpass -p "$NODE_PASS" scp -o StrictHostKeyChecking=no -o ConnectTimeout=5 \
        "$file" "${NODE_USER}@${host}:${dest}"
}

# Copy a file from a remote node via sshpass
# Usage: remote_scp_from <host> <remote_file> <local_path>
remote_scp_from() {
    local host="$1" file="$2" dest="$3"
    sshpass -p "$NODE_PASS" scp -o StrictHostKeyChecking=no -o ConnectTimeout=5 \
        "${NODE_USER}@${host}:${file}" "$dest"
}

# Pause after a command finishes
pause_after() {
    echo ""
    printf "${DIM}  Press any key to return to menu...${RESET}"
    read -rsn1
}

# Check if a command exists
has_cmd() {
    command -v "$1" &>/dev/null
}

# Show numbered list of mesh nodes, let user pick or type an IP
# Sets PICKED_NODE to the chosen IP. Returns 1 if cancelled.
pick_node() {
    local label=${1:-"Select node"}

    # Gather mesh node IPs from Babel routing table (extract gateway/next-hop IPs)
    local nodes=()
    while IFS= read -r ip; do
        [ -n "$ip" ] && nodes+=("$ip")
    done < <(ip route show proto babel 2>/dev/null | grep -oP 'via \K[0-9.]+' | sort -u)

    echo ""
    if [ ${#nodes[@]} -gt 0 ]; then
        printf "  ${BOLD}Mesh nodes:${RESET}\n"
        for i in "${!nodes[@]}"; do
            printf "   ${CYAN}%d${RESET}  %s\n" "$((i+1))" "${nodes[$i]}"
        done
        echo ""
        printf "  ${label} [1], enter IP, or ${DIM}q to cancel${RESET}: "
    else
        printf "  ${DIM}No mesh nodes found in Babel routes.${RESET}\n"
        printf "  Enter IP ${DIM}(q to cancel)${RESET}: "
    fi

    read -r node_choice

    # Cancel
    if [ "$node_choice" = "q" ] || [ "$node_choice" = "Q" ]; then
        return 1
    fi

    # Default to first node
    if [ -z "$node_choice" ] && [ ${#nodes[@]} -gt 0 ]; then
        node_choice=1
    fi

    # Check if it's a number (picking from list)
    if [[ "$node_choice" =~ ^[0-9]+$ ]] && [ ${#nodes[@]} -gt 0 ]; then
        local idx=$((node_choice - 1))
        if [ $idx -ge 0 ] && [ $idx -lt ${#nodes[@]} ]; then
            PICKED_NODE="${nodes[$idx]}"
            return 0
        fi
    fi

    # Otherwise treat as raw IP
    if [ -n "$node_choice" ]; then
        PICKED_NODE="$node_choice"
        return 0
    fi

    printf "  ${RED}No node selected.${RESET}\n"
    sleep 1
    return 1
}

# --- Menu Display ---

show_menu() {
    clear
    HOSTNAME=$(hostname)

    printf "${DIM}"
    printf "       ..        .....        ...       \n"
    printf "       ....     ......       ....       \n"
    printf "       .......... ...       .....       \n"
    printf "       ........    ..      ......       \n"
    printf "       ......      ..     .......       \n"
    printf "       .....       ...  .........       \n"
    printf "       ....        .....     ....       \n"
    printf "       ...         ....        ..       \n"
    printf "${RESET}"
    printf "${BOLD}═══════════════════════════════════════════${RESET}\n"
    printf "${BOLD}   Nucleus OS — ${CYAN}${HOSTNAME}${RESET}\n"
    printf "${BOLD}═══════════════════════════════════════════${RESET}\n"
    echo ""
    printf "  ${BOLD}System Monitoring${RESET}\n"
    printf "   ${CYAN}1${RESET}  System Status\n"
    printf "   ${CYAN}2${RESET}  Disk Usage ${DIM}(ncdu)${RESET}\n"
    printf "   ${CYAN}3${RESET}  System Logs ${DIM}(journalctl)${RESET}\n"
    printf "   ${CYAN}4${RESET}  Process Monitor ${DIM}(btop)${RESET}\n"
    echo ""
    printf "  ${BOLD}Network Testing${RESET}\n"
    printf "   ${CYAN}5${RESET}  Ping\n"
    printf "   ${CYAN}6${RESET}  Bandwidth Test ${DIM}(iperf3)${RESET}\n"
    printf "   ${CYAN}7${RESET}  Path Analysis ${DIM}(mtr)${RESET}\n"
    echo ""
    printf "  ${BOLD}File Transfer${RESET}\n"
    printf "   ${CYAN}8${RESET}  Transfer Files ${DIM}(scp)${RESET}\n"
    echo ""
    printf "  ${BOLD}Reticulum${RESET}\n"
    printf "   ${CYAN}10${RESET} Reticulum / NomadNet\n"
    echo ""
    printf "   ${CYAN}9${RESET}  Shell Access ${DIM}(bash)${RESET}\n"
    printf "   ${CYAN}0${RESET}  Exit\n"
    echo ""
    printf "  Select [1]: "
}

# --- Menu Actions ---

do_status() {
    "$CLI_DIR/nucleus-status.sh"
}

do_ncdu() {
    if ! has_cmd ncdu; then
        printf "  ${RED}ncdu not installed.${RESET} Install with: sudo apt install ncdu\n"
        pause_after
        return
    fi
    ncdu /
}

do_journalctl() {
    echo ""
    printf "  ${BOLD}System Logs${RESET}\n"
    echo ""
    printf "  ${CYAN}1${RESET}) Browse recent logs ${DIM}(scrollable, q to quit)${RESET}\n"
    printf "  ${CYAN}2${RESET}) Follow live ${DIM}(Ctrl-C to stop)${RESET}\n"
    echo ""
    printf "  Select [1]: "
    read -r log_mode
    log_mode=${log_mode:-1}

    if [ "$log_mode" = "2" ]; then
        echo ""
        printf "  ${DIM}Following live logs... Ctrl-C to stop${RESET}\n"
        echo ""
        # Trap SIGINT so Ctrl-C stops journalctl but not the menu
        trap '' INT
        journalctl --no-pager -f &
        local jpid=$!
        trap "kill $jpid 2>/dev/null; trap - INT" INT
        wait $jpid 2>/dev/null
        trap - INT
    else
        journalctl -n 500
    fi
}

do_btop() {
    if ! has_cmd btop; then
        printf "  ${RED}btop not installed.${RESET} Install with: sudo apt install btop\n"
        pause_after
        return
    fi
    btop
}

do_ping() {
    pick_node "Ping target" || return
    local target="$PICKED_NODE"
    echo ""
    printf "  ${DIM}Press Ctrl-C to stop${RESET}\n"
    echo ""
    # Trap SIGINT so Ctrl-C stops ping but not the menu
    trap '' INT
    ping "$target" &
    local pid=$!
    trap "kill $pid 2>/dev/null; trap - INT" INT
    wait $pid 2>/dev/null
    trap - INT
    pause_after
}

do_iperf3() {
    if ! has_cmd iperf3; then
        printf "  ${RED}iperf3 not installed.${RESET} Install with: sudo apt install iperf3\n"
        pause_after
        return
    fi
    if ! has_cmd sshpass; then
        printf "  ${RED}sshpass not installed.${RESET} Install with: sudo apt install sshpass\n"
        printf "  ${DIM}(needed to auto-start iperf3 server on remote node)${RESET}\n"
        pause_after
        return
    fi
    echo ""
    printf "  ${BOLD}iperf3 — Bandwidth Test${RESET}\n"
    echo ""
    printf "  Mode:  ${CYAN}1${RESET}) Client (test to remote node)  ${CYAN}2${RESET}) Server (listen for incoming)\n"
    printf "  Select [1]: "
    read -r mode
    mode=${mode:-1}

    if [ "$mode" = "2" ]; then
        echo ""
        printf "  ${DIM}Listening on port 5201... Press Ctrl-C to stop${RESET}\n"
        echo ""
        # Trap SIGINT so Ctrl-C stops iperf3 but not the menu
        trap '' INT
        iperf3 -s &
        local pid=$!
        trap "kill $pid 2>/dev/null; trap - INT" INT
        wait $pid 2>/dev/null
        trap - INT
        pause_after
    else
        pick_node "Target node" || return
        local target="$PICKED_NODE"
        echo ""
        printf "  Starting iperf3 server on ${CYAN}%s${RESET}...\n" "$target"

        # Start iperf3 server on remote node (--one-off exits after first test)
        remote_ssh "$target" "iperf3 -s --one-off" &>/dev/null &
        local server_pid=$!
        sleep 2  # let server start

        # Check if SSH succeeded
        if ! kill -0 $server_pid 2>/dev/null; then
            printf "  ${RED}Failed to start iperf3 server on %s${RESET}\n" "$target"
            printf "  ${DIM}Check SSH connectivity: ssh ${NODE_USER}@%s${RESET}\n" "$target"
            pause_after
            return
        fi

        printf "  Running bandwidth test → ${CYAN}%s${RESET}\n" "$target"
        echo ""
        iperf3 -c "$target"
        local rc=$?
        echo ""

        # Clean up remote server (should auto-exit with --one-off, but be safe)
        wait $server_pid 2>/dev/null

        if [ $rc -eq 0 ]; then
            printf "  ${GREEN}Bandwidth test complete.${RESET}\n"
        else
            printf "  ${RED}iperf3 client failed (exit code %d).${RESET}\n" "$rc"
        fi
        pause_after
    fi
}

do_mtr() {
    if ! has_cmd mtr; then
        printf "  ${RED}mtr not installed.${RESET} Install with: sudo apt install mtr-tiny\n"
        pause_after
        return
    fi
    pick_node "MTR target" || return
    local target="$PICKED_NODE"
    echo ""
    mtr "$target"
}

do_transfer() {
    echo ""
    printf "  ${BOLD}File Transfer${RESET}  ${DIM}(staging: ~/transfer/)${RESET}\n"
    echo ""
    printf "  ${CYAN}1${RESET}) List files in transfer directory\n"
    printf "  ${CYAN}2${RESET}) Send file to another node\n"
    printf "  ${CYAN}3${RESET}) Receive file from another node\n"
    printf "  ${CYAN}4${RESET}) Back to menu\n"
    echo ""
    printf "  Select [1]: "
    read -r xfer_mode
    xfer_mode=${xfer_mode:-1}

    case "$xfer_mode" in
        1)
            echo ""
            printf "  ${BOLD}Files in ${TRANSFER_DIR}:${RESET}\n"
            echo ""
            local file_count
            file_count=$(find "$TRANSFER_DIR" -maxdepth 1 -not -name '.' -not -path "$TRANSFER_DIR" | wc -l)
            if [ "$file_count" -eq 0 ]; then
                printf "  ${DIM}(empty)${RESET}\n"
            else
                ls -lhA "$TRANSFER_DIR" | tail -n +2 | while read -r line; do
                    printf "  %s\n" "$line"
                done
            fi
            pause_after
            ;;
        2)
            echo ""
            printf "  ${BOLD}Send file to another node${RESET}\n"
            echo ""
            # List files for easy reference
            printf "  ${DIM}Files in ~/transfer/:${RESET}\n"
            ls -1A "$TRANSFER_DIR" 2>/dev/null | while read -r f; do
                printf "    %s\n" "$f"
            done
            echo ""
            printf "  File to send ${DIM}(name, full path, or q to cancel)${RESET}: "
            read -r send_file

            # Cancel
            [ "$send_file" = "q" ] || [ "$send_file" = "Q" ] && return

            # If just a filename, assume it's in TRANSFER_DIR
            if [ -n "$send_file" ] && [ ! -f "$send_file" ] && [ -f "$TRANSFER_DIR/$send_file" ]; then
                send_file="$TRANSFER_DIR/$send_file"
            fi

            if [ -z "$send_file" ] || [ ! -f "$send_file" ]; then
                printf "  ${RED}File not found.${RESET}\n"
                pause_after
                return
            fi

            # Pick target node inline
            pick_node "Target node" || return
            local target="$PICKED_NODE"
            echo ""
            printf "  Sending ${CYAN}%s${RESET} → ${CYAN}%s${RESET}:~/transfer/\n" "$(basename "$send_file")" "$target"
            echo ""
            remote_scp_to "$send_file" "$target" "${TRANSFER_DIR}/"
            local rc=$?
            echo ""
            if [ $rc -eq 0 ]; then
                printf "  ${GREEN}Transfer complete.${RESET}\n"
            else
                printf "  ${RED}Transfer failed (exit code %d).${RESET}\n" "$rc"
            fi
            pause_after
            ;;
        3)
            echo ""
            printf "  ${BOLD}Receive file from another node${RESET}\n"

            # Pick source node inline
            pick_node "Source node" || return
            local target="$PICKED_NODE"
            echo ""

            # List remote transfer directory
            printf "  ${DIM}Files on %s:~/transfer/:${RESET}\n" "$target"
            remote_ssh "$target" "ls -1A ${TRANSFER_DIR} 2>/dev/null" 2>/dev/null | while read -r f; do
                printf "    %s\n" "$f"
            done
            echo ""
            printf "  File to receive ${DIM}(q to cancel)${RESET}: "
            read -r recv_file

            # Cancel
            [ "$recv_file" = "q" ] || [ "$recv_file" = "Q" ] && return

            if [ -z "$recv_file" ]; then
                printf "  ${RED}No file specified.${RESET}\n"
                pause_after
                return
            fi

            printf "  Receiving ${CYAN}%s${RESET} ← ${CYAN}%s${RESET}\n" "$recv_file" "$target"
            echo ""
            remote_scp_from "$target" "${TRANSFER_DIR}/${recv_file}" "$TRANSFER_DIR/"
            local rc=$?
            echo ""
            if [ $rc -eq 0 ]; then
                printf "  ${GREEN}Transfer complete.${RESET} Saved to ~/transfer/\n"
            else
                printf "  ${RED}Transfer failed (exit code %d).${RESET}\n" "$rc"
            fi
            pause_after
            ;;
        4|"")
            return
            ;;
    esac
}

do_reticulum() {
    echo ""
    printf "  ${BOLD}Reticulum Network${RESET}\n"
    echo ""

    # rnsd runs as natak — Reticulum commands must run as natak to find
    # the shared instance socket and config at /home/natak/.reticulum/
    local run_as=""
    if [ "$(id -u)" -eq 0 ]; then
        run_as="sudo -u ${NODE_USER}"
    fi

    # Show rnstatus if available
    if has_cmd rnstatus; then
        $run_as rnstatus 2>/dev/null
    else
        printf "  ${RED}rnstatus not found.${RESET} Is RNS installed?\n"
    fi

    echo ""
    # TODO: NomadNet TUI launch from menu not yet working — urwid's event
    # loop conflicts with the menu's terminal state. Works fine standalone:
    #   ssh natak@<host> then run: nomadnet
    printf "  ${DIM}NomadNet installed — run 'nomadnet' from shell (option 9)${RESET}\n"
    pause_after
}

do_shell() {
    echo ""
    printf "  ${DIM}Dropping to bash. Type 'exit' to return to menu.${RESET}\n"
    echo ""
    bash --login
}

# --- Main Loop ---

while true; do
    show_menu
    read -r choice
    choice=${choice:-1}

    case "$choice" in
        1) do_status ;;
        2) do_ncdu ;;
        3) do_journalctl ;;
        4) do_btop ;;
        5) do_ping ;;
        6) do_iperf3 ;;
        7) do_mtr ;;
        8) do_transfer ;;
        10) do_reticulum ;;
        9) do_shell ;;
        0) clear; exit 0 ;;
        *)
            printf "  ${RED}Invalid choice.${RESET}"
            sleep 0.5
            ;;
    esac
done
