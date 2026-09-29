#!/usr/bin/env bash
# Query the preferred IPv4 route; never return the entire route as an interface.
route=$(ip -j -4 route get 1.1.1.1 2>/dev/null)
dev=$(jq -r '.[0].dev // empty' <<< "$route" 2>/dev/null)
addr=$(jq -r '.[0].prefsrc // .[0].src // empty' <<< "$route" 2>/dev/null)
if [[ -n "$dev" && -z "$addr" ]]; then
    addr=$(ip -j -4 addr show dev "$dev" 2>/dev/null | jq -r '[.[].addr_info[]? | select(.scope == "global") | .local][0] // empty')
fi
[[ -n "$dev" && -n "$addr" ]] && state=Connected || state=Offline
tailscale_ip=$(timeout 2 tailscale ip -4 2>/dev/null | head -n 1)
if [[ -z "$tailscale_ip" ]]; then
    tailscale_ip=$(ip -j -4 addr show dev tailscale0 2>/dev/null | jq -r '[.[].addr_info[]? | select(.scope == "global") | .local][0] // empty')
fi
case "${1:-json}" in
    interface) printf '%s\n' "${dev:---}" ;;
    ip) printf '%s\n' "${addr:---}" ;;
    tailscale) printf '%s\n' "${tailscale_ip:---}" ;;
    json) jq -cn --arg interface "${dev:---}" --arg ip "${addr:---}" --arg tailscale "${tailscale_ip:---}" --arg state "$state" '{interface:$interface,ip:$ip,tailscale:$tailscale,state:$state}' ;;
    *) exit 2 ;;
esac
