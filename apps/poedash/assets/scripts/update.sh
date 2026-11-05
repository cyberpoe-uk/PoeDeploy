#!/usr/bin/env bash
set -Eeuo pipefail

repo=https://github.com/cyberpoe-uk/PoeDeploy.git
temporary=$(mktemp -d -t poedash-update-XXXXXX)
trap 'rm -rf -- "$temporary"' EXIT

command -v git >/dev/null 2>&1 || {
    printf 'PoeDash update requires Git. Install it and try again.\n' >&2
    exit 1
}
printf 'Downloading the latest PoeDeploy main branch for poedash...\n'
printf 'POEDASH_UPDATE_STAGE=download\n'
git clone --depth=1 --single-branch --branch main "$repo" "$temporary/PoeDeploy"
printf 'POEDASH_UPDATE_STAGE=install\n'
bash "$temporary/PoeDeploy/poedeploy.sh" --install-dashboard poedash
