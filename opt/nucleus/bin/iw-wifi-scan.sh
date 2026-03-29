#!/bin/bash
# iw-wifi-scan.sh - Channel scanner using iw survey data
# Detects ALL RF interference (WiFi + non-WiFi) on each channel

set -e

# Default settings
SCAN_DURATION=10  # seconds per channel
CHANNELS="1 2 3 4 5 6 7 8 9 10 11"  # 2.4GHz channels
JSON_OUTPUT=false
NO_CONFIRM=false

# Parse command line arguments
while [[ $# -gt 0 ]]; do
    case $1 in
        -d|--duration)
            SCAN_DURATION="$2"
            shift 2
            ;;
        --json)
            JSON_OUTPUT=true
            shift
            ;;
        --no-confirm)
            NO_CONFIRM=true
            shift
            ;;
        -h|--help)
            echo "Usage: $0 [OPTIONS]"
            echo ""
            echo "Options:"
            echo "  -d, --duration SECONDS    Duration per channel (default: 10)"
            echo "  --json                    Output results in JSON format"
            echo "  --no-confirm              Skip confirmation prompt"
            echo "  -h, --help                Show this help message"
            echo ""
            echo "Example: $0 --duration 5 --json --no-confirm"
            exit 0
            ;;
        *)
            echo "Unknown option: $1"
            echo "Use -h or --help for usage information"
            exit 1
            ;;
    esac
done

# Check if running as root
if [ "$EUID" -ne 0 ]; then
    echo "Error: This script must be run as root"
    exit 1
fi

# Show banner unless in JSON mode
if [ "$JSON_OUTPUT" = false ]; then
    echo "=== iw WiFi Channel Scanner ==="
    echo "Scanning channels: $CHANNELS"
    echo "Duration per channel: ${SCAN_DURATION}s"
    echo ""
fi

# Skip confirmation if --no-confirm or --json flag is set
if [ "$NO_CONFIRM" = false ] && [ "$JSON_OUTPUT" = false ]; then
    echo "WARNING: This will temporarily disconnect the mesh network!"
    read -p "Continue? (y/n) " -n 1 -r
    echo
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        echo "Scan cancelled."
        exit 0
    fi
fi

# Stop mesh services
if [ "$JSON_OUTPUT" = false ]; then
    echo "Stopping mesh services..."
fi
systemctl stop mesh-start.service 2>/dev/null
pkill wpa_supplicant 2>/dev/null || true
sleep 2

# Enable monitor mode using iw
if [ "$JSON_OUTPUT" = false ]; then
    echo "Enabling monitor mode..."
fi
ip link set wlan1 down 2>/dev/null
iw dev wlan1 set type monitor 2>/dev/null
if [ $? -ne 0 ]; then
    echo "Error: Failed to set wlan1 to monitor mode"
    systemctl start mesh-start.service
    exit 1
fi
ip link set wlan1 up
sleep 1

# Array to store results
declare -A channel_busy
declare -A channel_active

if [ "$JSON_OUTPUT" = false ]; then
    echo ""
    echo "Scanning channels..."
fi

for ch in $CHANNELS; do
    # Calculate frequency from channel
    if [ $ch -eq 14 ]; then
        freq=2484
    else
        freq=$((2407 + $ch * 5))
    fi
    
    if [ "$JSON_OUTPUT" = false ]; then
        echo -n "Channel $ch (${freq} MHz)... "
    fi
    
    # Set channel
    iw dev wlan1 set channel $ch 2>/dev/null || {
        if [ "$JSON_OUTPUT" = false ]; then
            echo "FAILED"
        fi
        continue
    }
    
    # Reset survey stats
    iw dev wlan1 survey dump >/dev/null 2>&1
    
    # Wait for data to accumulate
    sleep $SCAN_DURATION
    
    # Get survey data
    survey_output=$(iw dev wlan1 survey dump 2>/dev/null)
    
    # Extract busy and active time for this frequency
    busy_time=$(echo "$survey_output" | awk -v freq="$freq" '
        /frequency:/ { current_freq=$2 }
        /channel busy time:/ && current_freq == freq { print $4; exit }
    ')
    
    active_time=$(echo "$survey_output" | awk -v freq="$freq" '
        /frequency:/ { current_freq=$2 }
        /channel active time:/ && current_freq == freq { print $4; exit }
    ')
    
    if [ -z "$busy_time" ] || [ -z "$active_time" ]; then
        if [ "$JSON_OUTPUT" = false ]; then
            echo "NO DATA"
        fi
        channel_busy[$ch]=0
        channel_active[$ch]=0
    else
        channel_busy[$ch]=$busy_time
        channel_active[$ch]=$active_time
        
        # Calculate percentage
        if [ "$active_time" -gt 0 ]; then
            busy_pct=$((busy_time * 100 / active_time))
            if [ "$JSON_OUTPUT" = false ]; then
                echo "${busy_pct}% busy"
            fi
        else
            if [ "$JSON_OUTPUT" = false ]; then
                echo "0% busy"
            fi
        fi
    fi
done

# Stop monitor mode
if [ "$JSON_OUTPUT" = false ]; then
    echo ""
    echo "Stopping monitor mode..."
fi
ip link set wlan1 down 2>/dev/null
iw dev wlan1 set type mesh 2>/dev/null
ip link set wlan1 up 2>/dev/null

# Restart mesh services
if [ "$JSON_OUTPUT" = false ]; then
    echo "Restarting mesh services..."
fi
systemctl start mesh-start.service 2>/dev/null

# Wait for mesh to stabilize
if [ "$JSON_OUTPUT" = false ]; then
    echo "Waiting for mesh to stabilize..."
fi
sleep 10

# Calculate busy percentages
declare -A channel_pct
for ch in $CHANNELS; do
    busy=${channel_busy[$ch]}
    active=${channel_active[$ch]}
    
    if [ "$active" -gt 0 ]; then
        pct=$((busy * 100 / active))
    else
        pct=0
    fi
    
    channel_pct[$ch]=$pct
done

# Output results
if [ "$JSON_OUTPUT" = true ]; then
    # JSON output
    echo "{"
    echo '  "channels": ['
    
    first=true
    for ch in $CHANNELS; do
        pct=${channel_pct[$ch]}
        
        if [ $ch -eq 14 ]; then
            freq=2484
        else
            freq=$((2407 + $ch * 5))
        fi
        
        # Determine status
        if [ $pct -eq 0 ]; then
            status="EMPTY"
        elif [ $pct -lt 20 ]; then
            status="EXCELLENT"
        elif [ $pct -lt 40 ]; then
            status="GOOD"
        elif [ $pct -lt 60 ]; then
            status="MODERATE"
        else
            status="CONGESTED"
        fi
        
        # Mark non-overlapping channels
        is_recommended=false
        if [ $ch -eq 1 ] || [ $ch -eq 6 ] || [ $ch -eq 11 ]; then
            is_recommended=true
        fi
        
        if [ "$first" = false ]; then
            echo ","
        fi
        first=false
        
        echo -n "    {\"channel\": $ch, \"frequency\": $freq, \"busy_percent\": $pct, \"status\": \"$status\", \"recommended\": $is_recommended}"
    done
    
    echo ""
    echo "  ]"
    echo "}"
else
    # Human-readable output
    echo ""
    echo "=== SCAN RESULTS ==="
    echo ""
    printf "%-10s %-12s %-12s %-10s %-15s\n" "Channel" "Frequency" "Busy %" "Status" "Recommendation"
    echo "-------------------------------------------------------------------------"
    
    # Sort channels by busy percentage
    sorted_channels=$(for ch in $CHANNELS; do
        echo "${channel_pct[$ch]} $ch"
    done | sort -n | awk '{print $2}')
    
    # Print sorted results
    for ch in $sorted_channels; do
        pct=${channel_pct[$ch]}
        
        if [ $ch -eq 14 ]; then
            freq=2484
        else
            freq=$((2407 + $ch * 5))
        fi
        
        # Determine status
        if [ $pct -eq 0 ]; then
            status="EMPTY"
        elif [ $pct -lt 20 ]; then
            status="EXCELLENT"
        elif [ $pct -lt 40 ]; then
            status="GOOD"
        elif [ $pct -lt 60 ]; then
            status="MODERATE"
        else
            status="CONGESTED"
        fi
        
        # Mark non-overlapping channels
        recommendation=""
        if [ $ch -eq 1 ] || [ $ch -eq 6 ] || [ $ch -eq 11 ]; then
            recommendation="⭐ Non-overlap"
        fi
        
        printf "%-10s %-12s %-12s %-10s %-15s\n" \
            "$ch" "${freq} MHz" "${pct}%" "$status" "$recommendation"
    done
    
    echo ""
    echo "=== RECOMMENDATIONS ==="
    echo ""
    echo "Best non-overlapping channels (1, 6, 11):"
    for ch in 1 6 11; do
        pct=${channel_pct[$ch]}
        echo "  Channel $ch: ${pct}% busy"
    done
    
    echo ""
    echo "Scan complete!"
fi
