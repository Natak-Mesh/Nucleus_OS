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
prompt_target() {
    local prompt_text=${1:-"Target IP/hostname"}
    local default=${2:-""}
    local target

    if [ -n "$default" ]; then
        printf "  ${prompt_text} [${default}]: "
        read -r target
        target=${target:-$default}
    else
        printf "  ${prompt_text}: "
        read -r target
    fi

    if [ -z "$target" ]; then
        echo ""
        printf "  ${RED}No target specified.${RESET}\n"
        sleep 1
        return 1
    fi
    echo "$target"
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

# --- Menu Display ---

show_menu() {
    clear
    HOSTNAME=$(hostname)

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
    printf "   ${CYAN}8${RESET}  Shell Access ${DIM}(bash)${RESET}\n"
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
    printf "  ${BOLD}Logs — last 100 lines, following${RESET}\n"
    printf "  ${DIM}Press Ctrl-C to stop${RESET}\n"
    echo ""
    journalctl --no-pager -n 100 -f
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
    echo ""
    target=$(prompt_target "Ping target") || return
    echo ""
    printf "  ${DIM}Press Ctrl-C to stop${RESET}\n"
    echo ""
    ping "$target"
}

do_iperf3() {
    if ! has_cmd iperf3; then
        printf "  ${RED}iperf3 not installed.${RESET} Install with: sudo apt install iperf3\n"
        pause_after
        return
    fi
    echo ""
    printf "  ${BOLD}iperf3 — Bandwidth Test${RESET}\n"
    echo ""
    printf "  Mode:  ${CYAN}1${RESET}) Client (connect to server)  ${CYAN}2${RESET}) Server (listen)\n"
    printf "  Select [1]: "
    read -r mode
    mode=${mode:-1}

    if [ "$mode" = "2" ]; then
        echo ""
        printf "  ${DIM}Listening on port 5201... Press Ctrl-C to stop${RESET}\n"
        echo ""
        iperf3 -s
    else
        target=$(prompt_target "Server IP") || return
        echo ""
        iperf3 -c "$target"
        pause_after
    fi
}

do_mtr() {
    if ! has_cmd mtr; then
        printf "  ${RED}mtr not installed.${RESET} Install with: sudo apt install mtr-tiny\n"
        pause_after
        return
    fi
    echo ""
    target=$(prompt_target "MTR target") || return
    mtr "$target"
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
        8) do_shell ;;
        0) clear; exit 0 ;;
        *)
            printf "  ${RED}Invalid choice.${RESET}"
            sleep 0.5
            ;;
    esac
done
