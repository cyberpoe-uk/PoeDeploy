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
    spotify|open)
        exec python3 "$(dirname "$(realpath "$0")")/desktop.py" media
        ;;
    *) exit 2 ;;
esac
