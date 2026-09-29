#!/usr/bin/env bash
# Check the dashboard's monitor, and hide beneath special workspaces.
monitors=$(timeout 1 hyprctl monitors -j 2>/dev/null)
visible=$(jq -r 'any(.[]; .id == 0 and .activeWorkspace.id == 1 and .specialWorkspace.id == 0)' <<< "$monitors" 2>/dev/null)
[[ "$visible" == true ]] && echo true || echo false
