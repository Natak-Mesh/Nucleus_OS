#!/bin/bash
# cell-stats.sh — Cellular data usage tracker for wwan0 (SIM7600G-H)
# Uses vnstat to display data usage statistics

IFACE="wwan0"
SCRIPT_NAME="$(basename "$0")"

# Colors
BOLD='\033[1m'
CYAN='\033[0;36m'
GREEN='\033[0;32m'
YELLOW='\033[0;33m'
RED='\033[0;31m'
NC='\033[0m' # No Color

# Check if vnstat is installed
if ! command -v vnstat &>/dev/null; then
    echo -e "${RED}Error: vnstat is not installed.${NC}"
    echo "Install with: sudo apt install -y vnstat"
    exit 1
fi

# Check if wwan0 exists in vnstat database
if ! vnstat --dbiflist 2>/dev/null | grep -q "$IFACE"; then
    echo -e "${RED}Error: Interface '$IFACE' not found in vnstat database.${NC}"
    echo "Add it with: sudo vnstat --add -i $IFACE"
    exit 1
fi

usage() {
    echo -e "${BOLD}Usage:${NC} $SCRIPT_NAME [OPTION]"
    echo ""
    echo "  Cellular data usage statistics for the SIM7600G-H modem (wwan0)"
    echo ""
    echo -e "${BOLD}Options:${NC}"
    echo "  -s, --summary     Show summary (default)"
    echo "  -d, --daily       Show daily breakdown"
    echo "  -m, --monthly     Show monthly breakdown"
    echo "  -h, --hourly      Show hourly graph"
    echo "  -l, --live        Show live real-time traffic monitor"
    echo "  -a, --all         Show summary + daily + monthly"
    echo "  -5, --five        Show top 5 traffic days"
    echo "  --help            Show this help message"
    echo ""
    echo -e "${BOLD}Examples:${NC}"
    echo "  $SCRIPT_NAME              # Show summary"
    echo "  $SCRIPT_NAME -d           # Daily breakdown"
    echo "  $SCRIPT_NAME -a           # Show all stats"
    echo "  $SCRIPT_NAME -l           # Live monitor (Ctrl+C to stop)"
}

header() {
    echo -e "${CYAN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
    echo -e "${BOLD}  📡 Cellular Data Usage — $IFACE (SIM7600G-H / eIOT Club)${NC}"
    echo -e "${CYAN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
}

show_summary() {
    echo ""
    echo -e "${GREEN}── Summary ──${NC}"
    vnstat -i "$IFACE"
    echo ""
}

show_daily() {
    echo ""
    echo -e "${GREEN}── Daily Breakdown ──${NC}"
    vnstat -i "$IFACE" -d
    echo ""
}

show_monthly() {
    echo ""
    echo -e "${GREEN}── Monthly Breakdown ──${NC}"
    vnstat -i "$IFACE" -m
    echo ""
}

show_hourly() {
    echo ""
    echo -e "${GREEN}── Hourly Graph ──${NC}"
    vnstat -i "$IFACE" -hg
    echo ""
}

show_top5() {
    echo ""
    echo -e "${GREEN}── Top 5 Traffic Days ──${NC}"
    vnstat -i "$IFACE" -t 5
    echo ""
}

show_live() {
    echo ""
    echo -e "${YELLOW}── Live Traffic Monitor (Ctrl+C to stop) ──${NC}"
    vnstat -i "$IFACE" -l
}

show_all() {
    show_summary
    show_daily
    show_monthly
    show_top5
}

# Default to summary if no args
if [ $# -eq 0 ]; then
    header
    show_summary
    exit 0
fi

# Parse arguments
case "$1" in
    -s|--summary)
        header
        show_summary
        ;;
    -d|--daily)
        header
        show_daily
        ;;
    -m|--monthly)
        header
        show_monthly
        ;;
    -h|--hourly)
        header
        show_hourly
        ;;
    -l|--live)
        header
        show_live
        ;;
    -a|--all)
        header
        show_all
        ;;
    -5|--five)
        header
        show_top5
        ;;
    --help)
        usage
        ;;
    *)
        echo -e "${RED}Unknown option: $1${NC}"
        echo ""
        usage
        exit 1
        ;;
esac
