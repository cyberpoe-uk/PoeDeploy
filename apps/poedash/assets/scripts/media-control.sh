#!/usr/bin/env bash
set -euo pipefail
case "${1:-}" in
    previous|play-pause|next)
        # Match the card: prefer a playing player over the first paused one.
        selected=
        selected_status=
        while IFS= read -r player; do
            [[ -n "$player" ]] || continue
            status=$(playerctl -p "$player" status 2>/dev/null) || continue
            if [[ -z "$selected" ]]; then selected=$player; selected_status=$status; fi
            if [[ "$status" == Playing ]]; then selected=$player; selected_status=$status; break; fi
        done < <(playerctl -l 2>/dev/null)
        if [[ -z "$selected" || ( "$1" == play-pause && "$selected_status" == Stopped ) ]]; then
            if [[ "$1" == play-pause ]]; then
                nohup python3 "$(dirname "$(realpath "$0")")/media-actions.py" resume >/dev/null 2>&1 &
            fi
            exit 0
        fi
        exec playerctl -p "$selected" "$1"
        ;;
    spotify|open)
        exec python3 "$(dirname "$(realpath "$0")")/desktop.py" media
        ;;
    *) exit 2 ;;
esac
