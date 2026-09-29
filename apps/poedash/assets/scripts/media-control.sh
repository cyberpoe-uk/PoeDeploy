#!/usr/bin/env bash
set -euo pipefail
case "${1:-}" in
    previous|play-pause|next) playerctl "$1" ;;
    spotify)
        workspaces=$(hyprctl workspaces -j)
        workspace=2
        while jq -e --argjson id "$workspace" '.[] | select(.id == $id)' <<<"$workspaces" >/dev/null; do
            ((workspace++))
        done
        if command -v spotify >/dev/null; then
            hyprctl dispatch exec "[workspace $workspace silent] spotify"
        elif command -v flatpak >/dev/null && flatpak info com.spotify.Client >/dev/null 2>&1; then
            hyprctl dispatch exec "[workspace $workspace silent] flatpak run com.spotify.Client"
        else
            notify-send "PoeDash" "Spotify is not installed"
            exit 1
        fi
        ;;
    *) exit 2 ;;
esac
