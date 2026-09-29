#!/usr/bin/env bash
root=$(dirname "$(dirname "$(realpath "$0")")")
monitor=$(jq -c '.monitor' "$root/settings.json")
monitors=$(timeout 1 hyprctl monitors -j 2>/dev/null)
visible=$(jq -r --argjson monitor "$monitor" '
  (if ($monitor|type) == "number" then .[$monitor] else map(select(.name == $monitor))[0] end)
  | .activeWorkspace.id == 1 and .specialWorkspace.id == 0' <<< "$monitors" 2>/dev/null)
[[ "$visible" == true ]] && echo true || echo false
