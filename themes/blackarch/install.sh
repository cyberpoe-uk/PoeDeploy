#!/usr/bin/env bash
# Install or switch to a packaged static or animated BlackArch Plymouth theme.
set -euo pipefail

PACKAGE_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
THEMES=(
    green-static green-animated
    orange-static orange-animated
    purple-static purple-animated
    red-static red-animated
    blue-animated white-animated
)

usage() {
    cat <<'EOF'
Usage: ./install.sh [COLOUR]-[static|animated]
       ./install.sh --list

Installs the selected BlackArch Plymouth theme, makes it the default, and
rebuilds the initramfs. With no theme argument, an interactive menu is shown.
Run as your normal user; sudo is requested only for the system changes.
EOF
}

is_theme() {
    local candidate="$1" theme
    for theme in "${THEMES[@]}"; do
        [[ "$candidate" == "$theme" ]] && return 0
    done
    return 1
}

choose_theme() {
    local index
    printf 'BlackArch Plymouth themes:\n\n'
    for index in "${!THEMES[@]}"; do
        printf '  [%d] %s\n' "$((index + 1))" "${THEMES[$index]}"
    done
    printf '\n'
    while true; do
        read -rp "Choose a theme [1-${#THEMES[@]}]: " index
        if [[ "$index" =~ ^[0-9]+$ ]] &&
           ((index >= 1 && index <= ${#THEMES[@]})); then
            SELECTED_THEME="${THEMES[$((index - 1))]}"
            return
        fi
        printf 'Please enter a number from 1 to %d.\n' "${#THEMES[@]}" >&2
    done
}

case "${1:-}" in
    -h|--help)
        usage
        exit 0
        ;;
    --list)
        printf '%s\n' "${THEMES[@]}"
        exit 0
        ;;
    '')
        choose_theme
        ;;
    *)
        SELECTED_THEME="${1,,}"
        if ! is_theme "$SELECTED_THEME"; then
            printf 'Unknown theme: %s\n\n' "$1" >&2
            usage >&2
            exit 2
        fi
        ;;
esac

for command_name in unzip plymouth-set-default-theme mkinitcpio; do
    command -v "$command_name" >/dev/null 2>&1 || {
        printf 'Required command not found: %s\n' "$command_name" >&2
        exit 1
    }
done

THEME_NAME="blackarch-${SELECTED_THEME}"
ARCHIVE="${PACKAGE_DIR}/../${THEME_NAME}/plymouth/${THEME_NAME}.zip"
[[ -f "$ARCHIVE" ]] || {
    printf 'Theme archive not found: %s\n' "$ARCHIVE" >&2
    exit 1
}

if ((EUID == 0)); then
    PRIVILEGE=()
else
    command -v sudo >/dev/null 2>&1 || {
        printf 'sudo is required when the installer is not run as root.\n' >&2
        exit 1
    }
    PRIVILEGE=(sudo)
fi

WORK_DIR=$(mktemp -d -t blackarch-plymouth-install-XXXXXX)
trap 'rm -rf -- "$WORK_DIR"' EXIT
unzip -q "$ARCHIVE" -d "$WORK_DIR"
SOURCE_DIR="${WORK_DIR}/${THEME_NAME}"
DEFINITION="${SOURCE_DIR}/${THEME_NAME}.plymouth"
[[ -f "$DEFINITION" ]] || {
    printf 'The %s archive is missing its Plymouth definition.\n' "$THEME_NAME" >&2
    exit 1
}
if [[ "$SELECTED_THEME" == *-animated && \
      ! -f "${SOURCE_DIR}/${THEME_NAME}.script" ]]; then
    printf 'The %s archive is missing its Plymouth script.\n' "$THEME_NAME" >&2
    exit 1
fi

DESTINATION="/usr/share/plymouth/themes/${THEME_NAME}"
"${PRIVILEGE[@]}" install -d -m 0755 "$DESTINATION"
"${PRIVILEGE[@]}" cp -a "${SOURCE_DIR}/." "$DESTINATION/"
"${PRIVILEGE[@]}" plymouth-set-default-theme "$THEME_NAME"

if ! plymouth-set-default-theme -l | grep -Fxq "$THEME_NAME"; then
    printf 'Plymouth did not recognise the installed theme: %s\n' "$THEME_NAME" >&2
    exit 1
fi

printf 'Rebuilding initramfs images with %s...\n' "$THEME_NAME"
"${PRIVILEGE[@]}" mkinitcpio -P
printf 'BlackArch %s is now the default Plymouth theme.\n' "$SELECTED_THEME"
