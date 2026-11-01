#!/usr/bin/env bash
[ -f "$(dirname "$(dirname "$(realpath "$0")")")/disabled" ] && exit 0
root=$(dirname "$(dirname "$(realpath "$0")")")
cd "$root"
# Called by Hyprland after login; keep startup logs and prevent duplicate starts.
mkdir -p "$HOME/.cache/eww"
exec >> "$HOME/.cache/eww/dashboard-startup.log" 2>&1
exec 9>"${XDG_RUNTIME_DIR:-/tmp}/eww-dashboard-start-$UID.lock"
flock -n 9 || exit 0

# The bottom layer stays above wallpapers regardless of daemon startup order.
[ -f "$(dirname "$(dirname "$(realpath "$0")")")/disabled" ] && exit 0
if ! timeout 3 eww --config "$root" ping >/dev/null 2>&1; then
    eww --config "$root" --force-wayland daemon 9>&-
else
    eww --config "$root" reload
    # Recreate this surface so updated layer and monitor settings take effect.
    eww --config "$root" close dashboard >/dev/null 2>&1 || true
fi
for ((attempt=0; attempt<10; attempt++)); do
    [ -f "$(dirname "$(dirname "$(realpath "$0")")")/disabled" ] && exit 0
    if timeout 3 eww --config "$root" active-windows 2>/dev/null | grep -q '^dashboard: dashboard$'; then exit 0; fi
    [ -f "$(dirname "$(dirname "$(realpath "$0")")")/disabled" ] && exit 0
    if timeout 3 eww --config "$root" open dashboard; then exit 0; fi
    sleep 1
done
printf '%s: dashboard startup failed\n' "$(date -Is)"
exit 1


# Dashboard toggle checkpoints
