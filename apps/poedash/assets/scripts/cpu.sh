#!/usr/bin/env bash

read -r cpu user nice system idle iowait irq softirq steal guest guest_nice < /proc/stat
idle1=$((idle + iowait))
total1=$((user + nice + system + idle + iowait + irq + softirq + steal))

sleep 0.2

read -r cpu user nice system idle iowait irq softirq steal guest guest_nice < /proc/stat
idle2=$((idle + iowait))
total2=$((user + nice + system + idle + iowait + irq + softirq + steal))

total_diff=$((total2 - total1))
idle_diff=$((idle2 - idle1))

awk -v total="$total_diff" -v idle="$idle_diff" \
    'BEGIN {
        if (total > 0)
            printf "%.0f\n", 100 * (total - idle) / total
        else
            print 0
    }'
