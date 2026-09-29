#!/usr/bin/env bash
root=$(dirname "$(dirname "$(realpath "$0")")")

visible() {
    monitor=$(jq -c '.monitor' "$root/settings.json")
    monitors=$(timeout 1 hyprctl monitors -j 2>/dev/null)
    state=$(jq -r --argjson monitor "$monitor" '
      (if ($monitor|type) == "number" then .[$monitor] else map(select(.name == $monitor))[0] end)
      | .activeWorkspace.id == 1 and .specialWorkspace.id == 0' <<< "$monitors" 2>/dev/null)
    [[ "$state" == true ]] && echo true || echo false
}

if [[ "${1:-}" != "--listen" ]]; then
    visible
    exit
fi

# Keep the widget tree warm and react to compositor events instead of rebuilding it
# after a polling delay. Reconnect automatically when Hyprland restarts.
while true; do
    visible
    socket="${XDG_RUNTIME_DIR:-/run/user/$(id -u)}/hypr/${HYPRLAND_INSTANCE_SIGNATURE:-}/.socket2.sock"
    if [[ -S "$socket" ]]; then
        socat -U - "UNIX-CONNECT:$socket" 2>/dev/null | while IFS= read -r event; do
            case "$event" in
                workspace\>\>*|workspacev2\>\>*|focusedmon\>\>*|activespecial\>\>*) visible ;;
            esac
        done
    fi
    sleep 1
done
