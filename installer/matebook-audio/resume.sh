#!/usr/bin/env bash
# system-sleep hooks run as root with user sessions frozen; no user D-Bus needed.
# Signal only the existing active listener. Never start a disabled service.
if [[ "${1:-}" == post ]]; then
    /usr/bin/systemctl kill --kill-whom=main --signal=SIGUSR1 poedeploy-matebook-audio.service 2>/dev/null || :
fi
