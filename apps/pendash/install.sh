#!/usr/bin/env bash
# Legacy entry point. Dashboard actions migrate to PoeDash without packages.
set -euo pipefail
exec python3 "$(dirname "$(realpath "$0")")/pendash.py" "$@"
