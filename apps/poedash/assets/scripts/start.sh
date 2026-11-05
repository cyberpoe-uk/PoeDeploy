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
backend=${POEDASH_BACKEND:-$(cat "$root/surface-backend" 2>/dev/null || echo gtk)}
case "$backend" in gtk|eww) ;; *) echo 'Select gtk or eww with poedash backend.' >&2; exit 1 ;; esac
sleep 2
if ! python3 "$root/scripts/dashboard_native.py" --check >/dev/null 2>&1; then
    echo 'Both PoeDash backends require python-gobject, python-cairo and gtk-layer-shell. Run poedash doctor.' >&2
    exit 1
fi
python3 "$root/poedash.py" --root "$root" render
if python3 "$root/scripts/dashboard_native.py" --root "$root" --control status >/dev/null 2>&1; then
    if [ "$(cat "$root/state/surface-backend" 2>/dev/null || true)" = "$backend" ]; then
        python3 "$root/scripts/dashboard_native.py" --root "$root" --control reload
        exit 0
    fi
    python3 "$root/scripts/dashboard_native.py" --root "$root" --control quit >/dev/null 2>&1 || true
fi
[ -f "$root/disabled" ] && exit 0
timeout 3 eww --config "$root" kill 9>&- >/dev/null 2>&1 || true
if [ "$backend" = gtk ]; then
    setsid python3 "$root/scripts/dashboard_native.py" --root "$root" 9>&- &
    native_pid=$!
    for ((attempt=0; attempt<50; attempt++)); do
        if python3 "$root/scripts/dashboard_native.py" --root "$root" --control status >/dev/null 2>&1; then exit 0; fi
        kill -0 "$native_pid" 2>/dev/null || { wait "$native_pid"; exit 1; }
        sleep .1
    done
else
    host_module=$(python3 "$root/scripts/eww-host.py")
    [ -f "$root/disabled" ] && exit 0
    previous_modules=${GTK_MODULES-}
    GTK_MODULES="${previous_modules:+$previous_modules:}$host_module" POEDASH_ROOT="$root" POEDASH_PREVIOUS_GTK_MODULES="$previous_modules" \
        eww --config "$root" --force-wayland daemon 9>&-
    eww --config "$root" open dashboard 9>&-
    for ((attempt=0; attempt<50; attempt++)); do
        if python3 "$root/scripts/dashboard_native.py" --root "$root" --control status >/dev/null 2>&1; then exit 0; fi
        sleep .1
    done
fi
echo "PoeDash $backend surface did not become ready. Run poedash doctor." >&2
exit 1
