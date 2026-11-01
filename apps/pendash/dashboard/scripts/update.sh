#!/usr/bin/env bash
set -Eeuo pipefail

repo=https://github.com/cyberpoe-uk/PoeDeploy.git
temporary=$(mktemp -d -t pendash-update-XXXXXX)
trap 'rm -rf -- "$temporary"' EXIT

command -v git >/dev/null 2>&1 || {
    printf 'PenDash update requires Git. Install it and try again.\n' >&2
    exit 1
}
printf 'Downloading the latest PoeDeploy main branch for pendash...\n'
git clone --depth=1 --single-branch --branch main "$repo" "$temporary/PoeDeploy"
bash "$temporary/PoeDeploy/poedeploy.sh" --install-dashboard pendash
