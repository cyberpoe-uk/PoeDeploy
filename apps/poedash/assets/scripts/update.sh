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
# Older main snapshots must not replace this updater with the silent, Eww-only
# control again. Retire this compatibility bridge once main has progress support.
root=${1:-$(dirname "$(dirname "$(realpath "$0")")")}
bundled="$temporary/PoeDeploy/apps/poedash/assets/scripts"
if [[ -f "$root/scripts/dashboard-control.py" && -f "$bundled/dashboard-control.py" ]] &&
   ! grep -q '^def update_status(' "$bundled/dashboard-control.py"; then
    for script in dashboard-control.py DashboardModule.qml start.sh update.sh dashboard_native.py dashboard_collect.py service_health.py; do
        cp -- "$root/scripts/$script" "$bundled/$script"
    done
    cp -- "$root/poedash.py" "$temporary/PoeDeploy/apps/poedash/poedash.py"
fi
printf 'POEDASH_UPDATE_STAGE=install\n'
bash "$temporary/PoeDeploy/poedeploy.sh" --install-dashboard poedash
