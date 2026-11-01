#!/usr/bin/env bash
# Also published at https://cyberpoe.uk/poedash-latest.
# Installs the maintained dashboard from PoeDeploy main; no Git checkout required.
set -Eeuo pipefail

poedash_bootstrap() (
    # Run in a subshell so cleanup and shell options do not leak into callers.
    set -Eeuo pipefail
    local poedash_tmp=''
    cleanup() {
        if [[ -n "$poedash_tmp" && -d "$poedash_tmp" ]]; then
            rm -rf -- "$poedash_tmp"
        fi
    }
    trap cleanup EXIT
    trap 'exit 130' INT
    trap 'exit 143' TERM

    if [[ $EUID -eq 0 ]]; then
        echo 'PoeDash: run as your desktop user, without sudo.' >&2
        exit 1
    fi
    for prerequisite in curl tar mktemp; do
        if ! command -v "$prerequisite" >/dev/null 2>&1; then
            echo "PoeDash: install $prerequisite before running this launcher." >&2
            exit 1
        fi
    done
    command -v pacman >/dev/null 2>&1 || {
        echo 'PoeDash: automatic installation requires an Arch-based system.' >&2
        exit 1
    }

    poedash_tmp=$(mktemp -d -t poedash-installer-XXXXXXXX)
    echo 'PoeDash: downloading the maintained dashboard from PoeDeploy main...'
    curl --fail --show-error --silent --location \
        --proto '=https' --proto-redir '=https' \
        --connect-timeout 15 --max-time 180 --retry 2 \
        https://codeload.github.com/cyberpoe-uk/PoeDeploy/tar.gz/refs/heads/main \
        --output "$poedash_tmp/poedash.tar.gz"
    mkdir "$poedash_tmp/source"
    tar --extract --gzip --file "$poedash_tmp/poedash.tar.gz" \
        --directory "$poedash_tmp/source" --strip-components=1 --no-same-owner
    for required in apps/poedash/install.sh apps/poedash/poedash.py apps/poedash/assets/settings.example.json; do
        [[ -f "$poedash_tmp/source/$required" ]] || {
            echo "PoeDash: downloaded archive is missing $required." >&2
            exit 1
        }
    done

    # Keep the public dashboard-refresh flag compatible with the bundled installer.
    local arguments=()
    local dashboard_refresh=false
    for argument in "$@"; do
        if [[ "$argument" == --update-dashboard ]]; then
            dashboard_refresh=true
            arguments+=(--skip-deps --non-interactive)
        else
            arguments+=("$argument")
        fi
    done
    set -- "${arguments[@]}"

    if [[ "$dashboard_refresh" == true ]]; then
        echo 'PoeDash: refreshing dashboard files without changing packages or repositories.'
    else
        echo 'PoeDash: starting the installer; package installation may request sudo.'
    fi
    # curl | bash consumes stdin. Restore the terminal for pacman/AUR prompts.
    if [[ ! -t 0 ]] && { true </dev/tty; } 2>/dev/null; then
        bash "$poedash_tmp/source/apps/poedash/install.sh" "$@" </dev/tty
    else
        bash "$poedash_tmp/source/apps/poedash/install.sh" "$@"
    fi
)

# Keep this call last: a truncated download must not start installation.
poedash_bootstrap "$@"
