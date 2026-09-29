#!/usr/bin/env bash
case "${1:-read}" in
  read) exec python3 "$(dirname "$(realpath "$0")")/ctf-control.py" target ;;
  edit)
    mkdir -p "${XDG_CACHE_HOME:-$HOME/.cache}/poedash"
    nohup python3 "$(dirname "$(realpath "$0")")/ctf-control.py" edit-target >> "${XDG_CACHE_HOME:-$HOME/.cache}/poedash/ctf-target.log" 2>&1 </dev/null &
    ;;
  *) exit 2 ;;
esac
