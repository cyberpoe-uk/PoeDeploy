#!/usr/bin/env bash
set -euo pipefail
case "${1:-}" in
    previous|play-pause|next)
        # Match the card: prefer a playing player over the first paused one.
        selected=
        while IFS= read -r player; do
            [[ -n "$player" ]] || continue
            status=$(playerctl -p "$player" status 2>/dev/null) || continue
            [[ -n "$selected" ]] || selected=$player
            if [[ "$status" == Playing ]]; then selected=$player; break; fi
        done < <(playerctl -l 2>/dev/null)
        [[ -n "$selected" ]] || exit 0
        exec playerctl -p "$selected" "$1"
        ;;
    spotify)
        workspaces=$(hyprctl workspaces -j)
        workspace=2
        while jq -e --argjson id "$workspace" '.[] | select(.id == $id)' <<<"$workspaces" >/dev/null; do
            ((workspace++))
        done
        if command -v spotify-launcher >/dev/null; then
            hyprctl dispatch exec "[workspace $workspace silent] spotify-launcher"
        elif command -v spotify >/dev/null; then
            hyprctl dispatch exec "[workspace $workspace silent] spotify"
        elif command -v flatpak >/dev/null && flatpak info com.spotify.Client >/dev/null 2>&1; then
            hyprctl dispatch exec "[workspace $workspace silent] flatpak run com.spotify.Client"
        else
            notify-send "PenDash" "Spotify is not installed"
            exit 1
        fi
        ;;
    *) exit 2 ;;
esac
