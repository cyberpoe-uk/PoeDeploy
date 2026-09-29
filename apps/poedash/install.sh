#!/usr/bin/env bash
set -euo pipefail
cd -- "$(dirname -- "$(realpath -- "$0")")"
if ! command -v python3 >/dev/null; then
    if [[ " $* " == *" --dry-run "* || " $* " == *" --skip-deps "* ]]; then
        echo 'Python 3 is required. Install it with: sudo pacman -S --needed python' >&2
        exit 1
    fi
    command -v pacman >/dev/null || { echo 'Automatic installation requires Arch Linux.' >&2; exit 1; }
    sudo pacman -S --needed python
fi
exec python3 ./poedash.py install "$@"
