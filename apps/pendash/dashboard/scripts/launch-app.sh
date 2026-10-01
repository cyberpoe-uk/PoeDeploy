#!/usr/bin/env bash
case "${1:-}" in
  tailscale)
    if command -v tailscale >/dev/null; then
      exec kitty --class dashboard-tailscale --hold sh -c 'tailscale status; printf "\nTo log in, run: sudo tailscale up\n"; exec "${SHELL:-/bin/bash}"'
    fi
    notify-send "PenDash" "Tailscale: Not installed. Install it through PoeDeploy."
    exit 1
    ;;
  proton)
    for client in protonvpn-app protonvpn proton-vpn; do
      if command -v "$client" >/dev/null; then exec "$client"; fi
    done
    notify-send "PenDash" "Proton VPN: Not installed. Install it through PoeDeploy."
    exit 1
    ;;
  burp|chromium|terminal|code|wireshark|web-ctf) ;;
  *) exit 2 ;;
esac
mkdir -p "$HOME/.cache/eww"
# Return promptly to Eww; the helper waits for slow application startup.
nohup python3 "$HOME/.config/eww/scripts/ctf-control.py" launch "$1" >> "$HOME/.cache/eww/ctf-launch.log" 2>&1 </dev/null &
