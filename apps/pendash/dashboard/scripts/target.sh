#!/usr/bin/env bash
case "${1:-read}" in
  read) exec python3 "$HOME/.config/eww/scripts/ctf-control.py" target ;;
  edit)
    mkdir -p "$HOME/.cache/eww"
    nohup python3 "$HOME/.config/eww/scripts/ctf-control.py" edit-target >> "$HOME/.cache/eww/ctf-target.log" 2>&1 </dev/null &
    ;;
  *) exit 2 ;;
esac
