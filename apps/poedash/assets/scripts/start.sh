#!/usr/bin/env bash
set -euo pipefail
root=$(dirname "$(dirname "$(realpath "$0")")")
[ -f "$root/disabled" ] && exit 0
cd "$root"
cache="${XDG_CACHE_HOME:-$HOME/.cache}/poedash"
mkdir -p "$cache"
exec >>"$cache/startup.log" 2>&1
exec 9>"$cache/start.lock"
flock -n 9 || exit 0
sleep 2
if ! python3 "$root/scripts/dashboard_native.py" --check >/dev/null 2>&1; then
    echo 'PoeDash requires python-gobject, python-cairo and gtk-layer-shell. Run poedash doctor.' >&2
    exit 1
fi
python3 "$root/poedash.py" --root "$root" render
if python3 "$root/scripts/dashboard_native.py" --root "$root" --control status >/dev/null 2>&1; then
    python3 "$root/scripts/dashboard_native.py" --root "$root" --control reload
    exit 0
fi
[ -f "$root/disabled" ] && exit 0
setsid python3 "$root/scripts/dashboard_native.py" --root "$root" 9>&- &
native_pid=$!
for ((attempt=0; attempt<50; attempt++)); do
    [ -f "$root/disabled" ] && exit 0
    if python3 "$root/scripts/dashboard_native.py" --root "$root" --control status >/dev/null 2>&1; then exit 0; fi
    kill -0 "$native_pid" 2>/dev/null || { wait "$native_pid"; exit 1; }
    sleep .1
done
echo 'PoeDash GTK surface did not become ready. Run poedash doctor.' >&2
exit 1
