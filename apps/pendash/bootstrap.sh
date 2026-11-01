#!/usr/bin/env bash
# Also published at https://cyberpoe.uk/pendash-latest.
# Installs the maintained dashboard from PoeDeploy main; no Git checkout required.
set -Eeuo pipefail

pendash_bootstrap() (
    # Run in a subshell so cleanup and shell options do not leak into callers.
    set -Eeuo pipefail
    local pendash_tmp=''
    cleanup() {
        if [[ -n "$pendash_tmp" && -d "$pendash_tmp" ]]; then
            rm -rf -- "$pendash_tmp"
        fi
    }
    trap cleanup EXIT
    trap 'exit 130' INT
    trap 'exit 143' TERM

    if [[ $EUID -eq 0 ]]; then
        echo 'PenDash: run as your desktop user, without sudo.' >&2
        exit 1
    fi
    for prerequisite in curl tar mktemp python3; do
        if ! command -v "$prerequisite" >/dev/null 2>&1; then
            echo "PenDash: install $prerequisite before running this launcher." >&2
            exit 1
        fi
    done
    command -v pacman >/dev/null 2>&1 || {
        echo 'PenDash: automatic installation requires an Arch-based system.' >&2
        exit 1
    }

    pendash_tmp=$(mktemp -d -t pendash-installer-XXXXXXXX)
    echo 'PenDash: downloading the maintained dashboard from PoeDeploy main...'
    if ! curl --fail --show-error --silent --location \
        --proto '=https' --proto-redir '=https' \
        --connect-timeout 15 --max-time 180 --retry 2 \
        https://codeload.github.com/cyberpoe-uk/PoeDeploy/tar.gz/refs/heads/main \
        --output "$pendash_tmp/pendash.tar.gz"; then
        echo 'PenDash: download failed.' >&2
        exit 1
    fi
    mkdir "$pendash_tmp/source"
    tar --extract --gzip --file "$pendash_tmp/pendash.tar.gz" \
        --directory "$pendash_tmp/source" --strip-components=1 --no-same-owner
    for required in apps/pendash/install.sh apps/pendash/pendash.py apps/pendash/dashboard/eww.yuck apps/pendash/assets/custom.lua; do
        [[ -f "$pendash_tmp/source/$required" ]] || {
            echo "PenDash: downloaded archive is missing $required." >&2
            exit 1
        }
    done

    echo 'PenDash: starting the installer; package installation may request sudo.'
    # curl | bash consumes stdin. Restore the terminal for pacman/AUR prompts.
    if [[ ! -t 0 ]] && { true </dev/tty; } 2>/dev/null; then
        bash "$pendash_tmp/source/apps/pendash/install.sh" "$@" </dev/tty
    else
        bash "$pendash_tmp/source/apps/pendash/install.sh" "$@"
    fi
)

# Keep this call last: a truncated download must not start installation.
pendash_bootstrap "$@"
