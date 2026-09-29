#!/usr/bin/env bash
# An administratively UP tunnel with an IPv4 address is a local VPN indicator,
# not a claim of remote reachability. Tailscale's backend state is preferred.
links=$(ip -j -4 addr show 2>/dev/null)
names=()
if jq -e 'any(.[]; .ifname == "tailscale0" and (.flags | index("UP")) != null and (.addr_info | length) > 0)' <<< "$links" >/dev/null 2>&1; then
    ts=true
    if command -v tailscale >/dev/null; then
        status=$(timeout 2 tailscale status --json 2>/dev/null)
        [[ -z "$status" ]] || ts=$(jq -r '.BackendState == "Running"' <<< "$status" 2>/dev/null)
    fi
    [[ "$ts" == true ]] && names+=("Tailscale")
fi
while IFS= read -r interface; do
    [[ -z "$interface" || "$interface" == tailscale0 ]] || names+=("$interface")
done < <(jq -r '.[] | select((.ifname | test("^(tun|tap|wg|proton|mullvad)[0-9A-Za-z_-]*$")) and (.flags | index("UP")) != null and (.addr_info | length) > 0) | .ifname' <<< "$links" 2>/dev/null)
if ((${#names[@]})); then
    summary=$(IFS=', '; printf '%s' "${names[*]}")
    jq -cn --arg summary "$summary" --arg count "${#names[@]}" '{summary:$summary,count:$count}'
else
    printf '{"summary":"No active VPN","count":"0"}\n'
fi
