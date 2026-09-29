#!/usr/bin/env bash
[ -f "$(dirname "$(dirname "$(realpath "$0")")")/disabled" ] && exit 0
# Called by Hyprland after login; keep startup logs and prevent duplicate starts.
mkdir -p "$HOME/.cache/eww"
exec >> "$HOME/.cache/eww/dashboard-startup.log" 2>&1
exec 9>"${XDG_RUNTIME_DIR:-/tmp}/eww-dashboard-start-$UID.lock"
flock -n 9 || exit 0

# Wait for the compositor and wallpaper surface so the dashboard is layered above it.
for ((attempt=0; attempt<30; attempt++)); do
    if timeout 2 hyprctl layers -j 2>/dev/null | jq -e 'any(.[] .levels["0"][]?; .namespace == "awww-daemon")' >/dev/null 2>&1; then
        break
    fi
    sleep 1
done
[ -f "$(dirname "$(dirname "$(realpath "$0")")")/disabled" ] && exit 0
if ! timeout 3 eww ping >/dev/null 2>&1; then
    eww --force-wayland daemon 9>&-
else
    eww reload
fi
for ((attempt=0; attempt<10; attempt++)); do
    [ -f "$(dirname "$(dirname "$(realpath "$0")")")/disabled" ] && exit 0
    if timeout 3 eww active-windows 2>/dev/null | grep -q '^dashboard: dashboard$'; then exit 0; fi
    [ -f "$(dirname "$(dirname "$(realpath "$0")")")/disabled" ] && exit 0
    if timeout 3 eww open dashboard; then exit 0; fi
    sleep 1
done
printf '%s: dashboard startup failed\n' "$(date -Is)"
exit 1


# Dashboard toggle checkpoints
