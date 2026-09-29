#!/usr/bin/env bash
# An administratively UP tunnel with an IPv4 address is a local VPN indicator,
# not a claim of remote reachability. Tailscale's backend state is preferred.
links=$(ip -j -4 addr show 2>/dev/null)
ts=false
lab=false
if jq -e 'any(.[]; .ifname == "tailscale0" and (.flags | index("UP")) != null and (.addr_info | length) > 0)' <<< "$links" >/dev/null 2>&1; then
    ts=true
    if command -v tailscale >/dev/null; then
        status=$(timeout 2 tailscale status --json 2>/dev/null)
        [[ -z "$status" ]] || ts=$(jq -r '.BackendState == "Running"' <<< "$status" 2>/dev/null)
    fi
fi
if jq -e 'any(.[]; (.ifname | test("^tun[0-9]+$")) and (.flags | index("UP")) != null and (.addr_info | length) > 0)' <<< "$links" >/dev/null 2>&1; then lab=true; fi
[[ "$ts" == true ]] || ts=false
printf '{"tailscale":%s,"lab":%s}\n' "$ts" "$lab"
