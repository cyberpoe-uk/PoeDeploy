#!/usr/bin/env bash
set -Eeuo pipefail

repo=https://github.com/cyberpoe-uk/PoeDeploy.git
temporary=$(mktemp -d -t poedash-update-XXXXXX)
trap 'rm -rf -- "$temporary"' EXIT

command -v git >/dev/null 2>&1 || {
    printf 'PoeDash update requires Git. Install it and try again.\n' >&2
    exit 1
}
printf 'Finding the latest stable PoeDeploy release...\n'
tag=$(git ls-remote --tags --refs "$repo" |
    awk '{sub("refs/tags/", "", $2); print $2}' |
    grep -E '^v?[0-9]+\.[0-9]+\.[0-9]+$' |
    sort -V | tail -n 1)
[[ -n "$tag" ]] || { printf 'No stable PoeDeploy release was found.\n' >&2; exit 1; }
git clone --depth=1 --branch "$tag" -c advice.detachedHead=false "$repo" "$temporary/PoeDeploy"
bash "$temporary/PoeDeploy/poedeploy.sh" --install-dashboard poedash
