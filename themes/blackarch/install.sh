#!/usr/bin/env bash
# Install or switch to one of the packaged BlackArch Plymouth colour themes.
set -euo pipefail

PACKAGE_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
COLOURS=(green orange purple red)

usage() {
    cat <<'EOF'
Usage: ./install.sh [green|orange|purple|red]
       ./install.sh --list

Installs the selected BlackArch Plymouth colour, makes it the default, and
rebuilds the initramfs. With no colour argument, an interactive menu is shown.
Run as your normal user; sudo is requested only for the system changes.
EOF
}

is_colour() {
    local candidate="$1" colour
    for colour in "${COLOURS[@]}"; do
        [[ "$candidate" == "$colour" ]] && return 0
    done
    return 1
}

choose_colour() {
    local index
    printf 'BlackArch Plymouth colours:\n\n'
    for index in "${!COLOURS[@]}"; do
        printf '  [%d] %s\n' "$((index + 1))" "${COLOURS[$index]}"
    done
    printf '\n'
    while true; do
        read -rp "Choose a colour [1-${#COLOURS[@]}]: " index
        if [[ "$index" =~ ^[1-4]$ ]]; then
            SELECTED_COLOUR="${COLOURS[$((index - 1))]}"
            return
        fi
        printf 'Please enter a number from 1 to 4.\n' >&2
    done
}

case "${1:-}" in
    -h|--help)
        usage
        exit 0
        ;;
    --list)
        printf '%s\n' "${COLOURS[@]}"
        exit 0
        ;;
    '')
        choose_colour
        ;;
    *)
        SELECTED_COLOUR="${1,,}"
        if ! is_colour "$SELECTED_COLOUR"; then
            printf 'Unknown colour: %s\n\n' "$1" >&2
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

THEME_NAME="blackarch-${SELECTED_COLOUR}"
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
[[ -f "$DEFINITION" && -f "${SOURCE_DIR}/${THEME_NAME}.script" ]] || {
    printf 'The %s archive is missing its Plymouth definition or script.\n' "$THEME_NAME" >&2
    exit 1
}

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
printf 'BlackArch %s is now the default Plymouth theme.\n' "$SELECTED_COLOUR"
