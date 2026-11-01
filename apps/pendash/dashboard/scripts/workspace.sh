#!/usr/bin/env bash
# Compatibility entry point for the shared workspace observer.
root=$(dirname "$(dirname "$(realpath "$0")")")
exec python3 "$root/scripts/workspace.py" "$@"
