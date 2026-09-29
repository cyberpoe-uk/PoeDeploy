#!/usr/bin/env bash
case "${1:-}" in
  burp|firefox|terminal|code|wireshark|web-ctf) ;;
  *) exit 2 ;;
esac
mkdir -p "${XDG_CACHE_HOME:-$HOME/.cache}/poedash"
# Return promptly to Eww; the helper waits for slow application startup.
nohup python3 "$(dirname "$(realpath "$0")")/ctf-control.py" launch "$1" >> "${XDG_CACHE_HOME:-$HOME/.cache}/poedash/ctf-launch.log" 2>&1 </dev/null &
