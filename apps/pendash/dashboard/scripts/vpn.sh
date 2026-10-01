#!/usr/bin/env bash
# Installed client state is separate from tunnel connectivity.
links=$(ip -j -4 addr show 2>/dev/null)
[[ -n "$links" ]] || links='[]'
ts=false
lab=false
proton=false
tailscale_state="Not installed"
proton_state="Not installed"
if command -v tailscale >/dev/null; then
    tailscale_state="Disconnected"
    status=$(timeout 2 tailscale status --json 2>/dev/null)
    backend=$(jq -r '.BackendState // empty' <<< "$status" 2>/dev/null)
    case "$backend" in
        Running) ts=true; tailscale_state="Connected" ;;
        NeedsLogin) tailscale_state="Login required" ;;
        NeedsMachineAuth) tailscale_state="Approval required" ;;
    esac
fi
if command -v protonvpn-app >/dev/null || command -v protonvpn >/dev/null ||
   command -v proton-vpn >/dev/null ||
   pacman -Q proton-vpn-gtk-app >/dev/null 2>&1 ||
   pacman -Q proton-vpn-cli >/dev/null 2>&1; then
    proton_state="Disconnected"
    if jq -e 'any(.[]; (.ifname | test("^proton")) and (.flags | index("UP")) != null and (.addr_info | length) > 0)' <<< "$links" >/dev/null 2>&1; then
        proton=true
        proton_state="Connected"
    fi
fi
if jq -e 'any(.[]; (.ifname | test("^tun[0-9]+$")) and (.flags | index("UP")) != null and (.addr_info | length) > 0)' <<< "$links" >/dev/null 2>&1; then lab=true; fi
names=()
[[ "$ts" == true ]] && names+=("Tailscale")
while IFS= read -r interface; do
    [[ -z "$interface" ]] || names+=("$interface")
done < <(jq -r '.[] | select((.ifname | test("^(tun|tap|wg|proton|mullvad)[0-9A-Za-z_-]*$")) and (.flags | index("UP")) != null and (.addr_info | length) > 0) | .ifname' <<< "$links" 2>/dev/null)
summary="No active VPN"
if (("${#names[@]}")); then summary=$(IFS=', '; printf '%s' "${names[*]}"); fi
jq -cn --arg summary "$summary" --arg count "${#names[@]}" \
    --arg tailscale_state "$tailscale_state" --arg proton_state "$proton_state" \
    --argjson tailscale "$ts" --argjson proton "$proton" --argjson lab "$lab" \
    '{summary:$summary,count:$count,tailscale:$tailscale,proton:$proton,lab:$lab,tailscale_state:$tailscale_state,proton_state:$proton_state}'
