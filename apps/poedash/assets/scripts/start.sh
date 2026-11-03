#!/usr/bin/env bash
set -euo pipefail
root=$(dirname "$(dirname "$(realpath "$0")")")
cd "$root"
cache="${XDG_CACHE_HOME:-$HOME/.cache}/poedash"
mkdir -p "$cache"
exec >>"$cache/startup.log" 2>&1
exec 9>"$cache/start.lock"
flock -n 9 || exit 0
# Give the compositor and wallpaper autostart a short head start.
sleep 2
python3 "$root/poedash.py" --root "$root" render
# The native surface provides free placement and resizing. Eww remains a fallback.
if python3 "$root/scripts/dashboard_native.py" --check >/dev/null 2>&1; then
    [ -f "$root/disabled" ] && exit 0
    if python3 "$root/scripts/dashboard_native.py" --root "$root" --control status >/dev/null 2>&1; then
        python3 "$root/scripts/dashboard_native.py" --root "$root" --control reload
        exit 0
    fi
    timeout 3 eww --config "$root" kill >/dev/null 2>&1 || true
    python3 "$root/scripts/dashboard_native.py" --root "$root" 9>&- &
    native_pid=$!
    for ((native_attempt=0; native_attempt<30; native_attempt++)); do
        if python3 "$root/scripts/dashboard_native.py" --root "$root" --control status >/dev/null 2>&1; then exit 0; fi
        kill -0 "$native_pid" 2>/dev/null || { wait "$native_pid"; exit 1; }
        sleep .1
    done
    echo 'PoeDash native surface did not become ready.' >&2
    exit 1
fi
printf 'GTK desktop support is unavailable; starting the Eww fallback.\n'
if ! timeout 3 eww --config "$root" ping >/dev/null 2>&1; then
    eww --config "$root" --force-wayland daemon 9>&-
else
    eww --config "$root" reload
    # Recreate this surface so updated layer and monitor settings take effect.
    eww --config "$root" close dashboard >/dev/null 2>&1 || true
fi
for ((attempt=0; attempt<10; attempt++)); do
    if timeout 3 eww --config "$root" active-windows | grep -q '^dashboard: dashboard$'; then exit 0; fi
    if timeout 3 eww --config "$root" open dashboard; then exit 0; fi
    sleep 1
done
echo 'PoeDash startup failed.' >&2
exit 1
