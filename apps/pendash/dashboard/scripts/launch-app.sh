#!/usr/bin/env bash
case "${1:-}" in
  burp|firefox|terminal|code|wireshark|web-ctf) ;;
  *) exit 2 ;;
esac
mkdir -p "$HOME/.cache/eww"
# Return promptly to Eww; the helper waits for slow application startup.
nohup python3 "$HOME/.config/eww/scripts/ctf-control.py" launch "$1" >> "$HOME/.cache/eww/ctf-launch.log" 2>&1 </dev/null &
