#!/usr/bin/env bash
set -euo pipefail
root=$(dirname "$(dirname "$(realpath "$0")")")
cache="${XDG_CACHE_HOME:-$HOME/.cache}/poedash"
mkdir -p "$cache"
exec >>"$cache/startup.log" 2>&1
exec 9>"$cache/start.lock"
flock -n 9 || exit 0
# Give the compositor and wallpaper autostart a short head start.
sleep 2
python3 "$root/poedash.py" --root "$root" render
if ! timeout 3 eww --config "$root" ping >/dev/null 2>&1; then
    eww --config "$root" --force-wayland daemon 9>&-
else
    eww --config "$root" reload
fi
for ((attempt=0; attempt<10; attempt++)); do
    if timeout 3 eww --config "$root" active-windows | grep -q '^dashboard: dashboard$'; then exit 0; fi
    if timeout 3 eww --config "$root" open dashboard; then exit 0; fi
    sleep 1
done
echo 'PoeDash startup failed.' >&2
exit 1
