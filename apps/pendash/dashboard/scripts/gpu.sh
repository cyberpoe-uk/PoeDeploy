#!/usr/bin/env bash
# Reading runtime_status does not wake the GPU. Periodic nvidia-smi queries do,
# even when used only for temperature, and can prevent idle RTD3 suspend.
gpu=
for device in /sys/bus/pci/devices/*; do
    [ "$(cat "$device/vendor" 2>/dev/null)" = 0x10de ] || continue
    case "$(cat "$device/class" 2>/dev/null)" in
        0x030000|0x030200) gpu=$device; break ;;
    esac
done
state=$(cat "$gpu/power/runtime_status" 2>/dev/null)
label=--
case "$state" in
    suspended) label=Asleep ;;
    active) label=Active ;;
    suspending|resuming) label=Transition ;;
esac
# Utilization/temperature remain unavailable without an explicit GPU query.
jq -cn --arg label "$label" '{usage:0,label:$label,temperature:"--"}'
