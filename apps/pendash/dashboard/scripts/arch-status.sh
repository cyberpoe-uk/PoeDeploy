#!/usr/bin/env bash
case "${1:-system}" in
    system)
        seconds=$(cut -d. -f1 /proc/uptime)
        days=$((seconds / 86400)); hours=$((seconds / 3600 % 24)); minutes=$((seconds / 60 % 60))
        compact="${hours}h ${minutes}m"
        ((days > 0)) && compact="${days}d $compact"
        jq -cn --arg kernel "$(uname -r)" --arg uptime "$compact" '{kernel:$kernel,uptime:$uptime}' ;;
    packages)
        if packages=$(pacman -Qq 2>/dev/null); then printf '%s\n' "$packages" | awk 'NF {n++} END {print n+0}'; else echo --; fi ;;
    updates)
        # Cached repository metadata only; a live network refresh is explicit.
        output=$(pacman -Qu 2>/dev/null); result=$?
        if ((result == 0)); then printf '%s\n' "$output" | awk 'NF {n++} END {print n+0}'; else echo --; fi ;;
    ram) free | awk '/Mem:/ {if ($2>0) printf "%.0f\n", $3/$2*100; else print 0}' ;;
    *) exit 2 ;;
esac
