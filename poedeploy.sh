#!/usr/bin/env bash

set -Eeuo pipefail

# ============================================================

# PoeDeploy - Arch Linux Setup Script

# ============================================================

ML4W_URL="https://ml4w.com/os/stable"

GITHUB_RAW_BASE="https://raw.githubusercontent.com/cyberpoe-uk/PoeDeploy/main"

VERSION_URL="${GITHUB_RAW_BASE}/VERSION"

POEDEPLOY_PLYMOUTH_THEME_URL="${GITHUB_RAW_BASE}/themes/poedeploy/plymouth/poedeploy.zip"

GITHUB_THEMES_API="https://api.github.com/repos/cyberpoe-uk/PoeDeploy/git/trees/main?recursive=1"

UKI_BLACK_SPLASH_URL="${GITHUB_RAW_BASE}/assets/uki/poedeploy-black.bmp"

# ------------------------------------------------------------

# Colours

# ------------------------------------------------------------

GREEN='\033[0;32m'

YELLOW='\033[1;33m'

RED='\033[0;31m'

BLUE='\033[0;34m'

CYAN='\033[0;36m'

NC='\033[0m'

# ------------------------------------------------------------

# Installation tracking

# ------------------------------------------------------------

FAILED_PACKAGES=()

SKIPPED_PACKAGES=()

INSTALLED_PACKAGES=()

SELECTED_PACKAGES=()

SELECTED_APPS=()

ML4W_ENABLED=false

CONFIGURE_ML4W_SDDM=false

DEFAULT_BROWSER_ACTION="not selected"

SECURE_BOOT_ACTION="not selected"
SECURE_BOOT_VERIFY_STATUS="not run"
SECURE_BOOT_OTHER_FILES_WARNING=false
SECURE_BOOT_AUTOMATIC_ACTION="none"
BOOT_IMAGE_ACTION="not rebuilt"
declare -A VERIFIED_PLYMOUTH_UKIS=()

UKI_ACTION="not selected"

RUN_MODE="full"
SETUP_MODULE_IDS=(update yay base gpu network plymouth uki timeshift ml4w sddm applications browser shares tailscale secure_boot)
declare -A SETUP_MODULE_LABELS=(
    [update]="System update"
    [yay]="AUR helper (yay)"
    [base]="Base system and network tools"
    [gpu]="GPU drivers"
    [network]="NetworkManager"
    [plymouth]="Plymouth boot theme"
    [uki]="Unified kernel images (UKI)"
    [timeshift]="Timeshift"
    [ml4w]="ML4W desktop"
    [sddm]="SDDM login screen"
    [applications]="Optional applications"
    [browser]="Default browser"
    [shares]="SMB / NFS shares"
    [tailscale]="Tailscale service"
    [secure_boot]="Secure Boot: keys, enrollment and signing"
)
declare -A SELECTED_SETUP_MODULES=()
PROCESSED_SETUP_MODULES=()

# ------------------------------------------------------------

# Version

# ------------------------------------------------------------

SCRIPT_VERSION="unknown"

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" 2>/dev/null && pwd || true)"

load_version() {

    local local_version_file="${SCRIPT_DIR}/VERSION"

    if [[ -f "$local_version_file" ]]; then

        SCRIPT_VERSION=$(tr -d '[:space:]' < "$local_version_file")

    elif command -v curl >/dev/null 2>&1; then

        SCRIPT_VERSION=$(curl -fsSL "$VERSION_URL" 2>/dev/null | tr -d '[:space:]' || true)

    elif command -v wget >/dev/null 2>&1; then

        SCRIPT_VERSION=$(wget -qO- "$VERSION_URL" 2>/dev/null | tr -d '[:space:]' || true)

    fi

    [[ -n "$SCRIPT_VERSION" ]] || SCRIPT_VERSION="unknown"

}

# ------------------------------------------------------------

# Output helpers

# ------------------------------------------------------------

info() {

    echo -e "${BLUE}[INFO]${NC} $1"

}

success() {

    echo -e "${GREEN}[ OK ]${NC} $1"

}

warning() {

    echo -e "${YELLOW}[WARN]${NC} $1"

}

error() {

    echo -e "${RED}[ERROR]${NC} $1"

}

die() {

    error "$1"

    exit 1

}

unexpected_error() {

    local exit_code="$1"
    local line_number="$2"

    error "Unexpected failure near line $line_number (exit code $exit_code)."
    error "PoeDeploy stopped before continuing with dependent steps."
}

trap 'unexpected_error "$?" "$LINENO"' ERR

# ============================================================

# 0. SAFETY / VERSION

# ============================================================

show_header() {

    clear || true

    echo

    echo "========================================"

    echo "              POEDEPLOY"

    echo "========================================"

    echo "Version: $SCRIPT_VERSION"

    echo "========================================"

    echo

}

confirm_start() {

    warning "This script will make changes to your Arch Linux system."

    warning "It may install packages, drivers and system services."

    echo

    read -rp "Continue with PoeDeploy? [Y/n]: " answer

    if [[ -z "$answer" || "$answer" =~ ^[Yy]$ ]]; then
        :
    else

        info "Installation cancelled."

        exit 0

    fi

}

check_not_root() {

    if [[ "$EUID" -eq 0 ]]; then
        die "Run PoeDeploy as a regular user. It will request sudo when required."
    fi

    if ! command -v sudo >/dev/null 2>&1; then
        die "sudo is required to run PoeDeploy."
    fi
}

can_use_checklist() {
    command -v gum >/dev/null 2>&1 &&
        [[ -t 0 && -t 2 && "${TERM:-dumb}" != dumb ]] &&
        (: </dev/tty) 2>/dev/null
}

# Options arrive on stdin; only selected labels are written to stdout.
# Keep both menus consistent and preserve gum's cancellation exit status.
choose_checklist() {
    local header="$1" defaults="${2:-}"
    gum choose --no-limit --selected="$defaults" \
        --cursor='> ' --cursor-prefix '[ ] ' --selected-prefix '[✓] ' \
        --unselected-prefix '[ ] ' --height=15 \
        --cursor.foreground='#004FFE' \
        --selected.foreground='#004FFE' \
        --header.foreground='#004FFE' \
        --header="$header"
}

choose_setup_checklist() {
    local module selection label matched
    local -a options=()
    for module in "${SETUP_MODULE_IDS[@]}"; do
        options+=("${SETUP_MODULE_LABELS[$module]}")
    done

    echo
    info "Choose the setup sections for this run. Nothing starts selected."
    echo "↑/↓ navigate · x toggle · Enter continue · Esc/Ctrl+C cancel"
    while true; do
        if ! selection=$(printf '%s\n' "${options[@]}" |
            choose_checklist "Setup sections"); then
            SELECTED_SETUP_MODULES=()
            return 1
        fi
        if [[ -z "$selection" ]]; then
            warning "Select at least one section, or press Esc to cancel."
            continue
        fi
        SELECTED_SETUP_MODULES=()
        while IFS= read -r label; do
            matched=false
            for module in "${SETUP_MODULE_IDS[@]}"; do
                if [[ "$label" == "${SETUP_MODULE_LABELS[$module]}" ]]; then
                    SELECTED_SETUP_MODULES["$module"]=true
                    matched=true
                    break
                fi
            done
            if [[ "$matched" != true ]]; then
                warning "The checklist returned an unknown section; cancelling."
                SELECTED_SETUP_MODULES=()
                return 1
            fi
        done <<< "$selection"
        return 0
    done
}

choose_setup_modules() {
    local answer module input token index marker
    local valid
    local -a tokens=()
    SELECTED_SETUP_MODULES=()

    while true; do
        if ! read -rp "Have you run PoeDeploy before on this Arch installation? [y/N]: " answer; then
            return 1
        fi
        case "$answer" in
            [Nn]|[Nn][Oo]|"")
                RUN_MODE="full"
                for module in "${SETUP_MODULE_IDS[@]}"; do
                    SELECTED_SETUP_MODULES["$module"]=true
                done
                return 0
                ;;
            [Yy]|[Yy][Ee][Ss]) RUN_MODE="selected"; break ;;
            *) warning "Please answer yes or no." ;;
        esac
    done

    if can_use_checklist; then
        choose_setup_checklist
        return $?
    fi

    info "Using the numbered menu (the interactive checklist needs gum and a terminal)."
    while true; do
        echo
        info "Choose the setup sections for this run. [x] marks selected sections."
        for index in "${!SETUP_MODULE_IDS[@]}"; do
            module="${SETUP_MODULE_IDS[$index]}"
            marker=" "
            if [[ "${SELECTED_SETUP_MODULES[$module]:-false}" == true ]]; then
                marker="x"
            fi
            printf '  [%s] %2d. %s\n' "$marker" "$((index + 1))" "${SETUP_MODULE_LABELS[$module]}"
        done
        echo "Enter numbers to toggle, e.g. 6 11; or all, none, run, quit."
        if ! read -rp "Selection: " input; then
            return 1
        fi
        case "${input,,}" in
            run|r)
                if ((${#SELECTED_SETUP_MODULES[@]} == 0)); then
                    warning "Select at least one section, or enter quit."
                else
                    return 0
                fi
                ;;
            quit|q) return 1 ;;
            all|a)
                for module in "${SETUP_MODULE_IDS[@]}"; do
                    SELECTED_SETUP_MODULES["$module"]=true
                done
                ;;
            none|n) SELECTED_SETUP_MODULES=() ;;
            *)
                read -r -a tokens <<< "${input//,/ }"
                valid=true
                ((${#tokens[@]} > 0)) || valid=false
                for token in "${tokens[@]}"; do
                    if [[ ! "$token" =~ ^[0-9]{1,2}$ ]] ||
                       ((10#$token < 1 || 10#$token > ${#SETUP_MODULE_IDS[@]})); then
                        valid=false
                        break
                    fi
                done
                if [[ "$valid" != true ]]; then
                    warning "Enter section numbers between 1 and ${#SETUP_MODULE_IDS[@]}, or a menu command."
                    continue
                fi
                for token in "${tokens[@]}"; do
                    module="${SETUP_MODULE_IDS[$((10#$token - 1))]}"
                    if [[ "${SELECTED_SETUP_MODULES[$module]:-false}" == true ]]; then
                        unset 'SELECTED_SETUP_MODULES[$module]'
                    else
                        SELECTED_SETUP_MODULES["$module"]=true
                    fi
                done
                ;;
        esac
    done
}

show_selected_setup_modules() {
    local module
    info "Setup sections selected for this run:"
    for module in "${SETUP_MODULE_IDS[@]}"; do
        if [[ "${SELECTED_SETUP_MODULES[$module]:-false}" == true ]]; then
            printf '  - %s\n' "${SETUP_MODULE_LABELS[$module]}"
        fi
    done
    info "Only selected sections and their missing package dependencies will run."
}

firmware_secure_boot_enabled() {
    local variable value
    for variable in /sys/firmware/efi/efivars/SecureBoot-*; do
        [[ -r "$variable" ]] || continue
        value=$(od -An -t u1 -j 4 -N 1 "$variable" 2>/dev/null | tr -d '[:space:]')
        [[ "$value" == 1 ]] && return 0
    done
    return 1
}

ensure_command_dependencies() {
    local dependency command_name package
    local -a missing=()
    for dependency in "$@"; do
        command_name="${dependency%%:*}"
        package="${dependency#*:}"
        if ! command -v "$command_name" >/dev/null 2>&1; then
            missing+=("$package")
        fi
    done
    if ((${#missing[@]} > 0)); then
        info "Installing missing dependencies for this section: ${missing[*]}"
        wait_for_pacman_lock
        sudo pacman -S --needed --noconfirm "${missing[@]}"
    fi
}

# ============================================================

# 1. ENVIRONMENT CHECKS

# ============================================================

check_arch() {

    info "Checking operating system..."

    if [[ ! -f /etc/arch-release ]]; then

        die "This script can only be run on Arch Linux."

    fi

    success "Arch Linux detected."

}

check_internet() {

    info "Checking internet connectivity..."

    local online=false

    if command -v ping >/dev/null 2>&1 && ping -c 1 -W 3 archlinux.org &>/dev/null; then
        online=true
    elif command -v curl >/dev/null 2>&1 && curl -fsSI --max-time 8 https://archlinux.org/ >/dev/null; then
        online=true
    elif command -v wget >/dev/null 2>&1 && wget -q --spider --timeout=8 https://archlinux.org/; then
        online=true
    fi

    if [[ "$online" != true ]]; then

        die "Internet connection is unavailable."

    fi

    success "Internet connection available."

}

wait_for_pacman_lock() {

    local lock_file="/var/lib/pacman/db.lck"
    local waited_seconds=0
    local owners owner_status process_status identity stale_identity=""

    while [[ -e "$lock_file" ]]; do
        # libalpm may close its lock descriptor during a transaction: an empty
        # fuser result alone is not evidence of a stale lock.
        if ! command -v pgrep >/dev/null 2>&1 || ! command -v fuser >/dev/null 2>&1; then
            error "Cannot safely inspect the Pacman lock; pgrep (procps-ng) and fuser (psmisc) are required."
            error "The lock has been left intact. Check running package operations before removing it manually."
            return 1
        fi
        if pgrep -x 'pacman|yay|paru|makepkg|packagekitd|pamac-daemon' >/dev/null; then
            process_status=0
        else
            process_status=$?
        fi
        if ((process_status > 1)); then
            error "Could not inspect running package managers. Leaving the Pacman lock intact."
            return 1
        fi
        if owners=$(sudo fuser "$lock_file" 2>&1); then
            process_status=0
        else
            owner_status=$?
            if [[ ! -e "$lock_file" ]]; then
                break
            fi
            if ((owner_status != 1)) || [[ -n "$owners" ]]; then
                error "Could not inspect the Pacman lock (exit code $owner_status): $owners"
                return 1
            fi
        fi

        if ((process_status == 0)); then
            stale_identity=""

            if ((waited_seconds == 0)); then
                warning "Another package operation is using the Pacman database."
                info "Waiting for it to finish; do not close PoeDeploy..."
            elif ((waited_seconds % 30 == 0)); then
                info "Pacman is still busy; waited ${waited_seconds} seconds..."
            fi

            sleep 5
            ((waited_seconds += 5))
            continue

        fi

        # Recheck the same lock after a grace period before treating it as stale.
        if ! identity=$(stat -c '%d:%i:%Y:%s' -- "$lock_file"); then
            [[ ! -e "$lock_file" ]] && continue
            return 1
        fi
        if [[ "$identity" != "$stale_identity" ]]; then
            stale_identity="$identity"
            sleep 2
            continue
        fi

        warning "Found a stale Pacman lock left by an interrupted package operation."
        sudo rm -f -- "$lock_file"
        success "Removed the stale Pacman database lock."

    done

    if ((waited_seconds > 0)); then
        success "The other package operation has finished."
    fi

}

update_system() {

    info "Synchronising and updating Arch Linux..."

    while true; do

        wait_for_pacman_lock

        if sudo pacman -Syu --needed --noconfirm; then
            break
        fi

        if [[ -e /var/lib/pacman/db.lck ]]; then
            warning "The Pacman database became locked before the update started. Retrying..."
            continue
        fi

        return 1

    done

    success "Arch Linux is up to date."

}

# ============================================================

# 2. YAY

# ============================================================

install_yay() {

    if command -v yay &>/dev/null; then

        success "yay is already installed."

        return

    fi

    info "yay is not installed."

    sudo pacman -S --needed --noconfirm git base-devel

    local temp_dir

    temp_dir=$(mktemp -d)

    info "Building yay from the AUR..."

    git clone https://aur.archlinux.org/yay.git "$temp_dir/yay"

    (

        cd "$temp_dir/yay"

        makepkg -si --noconfirm

    )

    rm -rf "$temp_dir"

    command -v yay &>/dev/null ||

        die "yay installation failed."

    success "yay installed."

}

# ============================================================

# 3. BASE TOOLS

# ============================================================

install_base_tools() {

    info "Checking base system/network tools..."

    sudo pacman -S --needed --noconfirm \
        git \
        curl \
        wget \
        jq \
        zip \
        unzip \
        less \
        iproute2 \
        iputils \
        bind \
        openssh \
        openbsd-netcat \
        traceroute \
        mtr \
        tcpdump \
        ethtool \
        rsync \
        nfs-utils \
        cifs-utils \
        smbclient \
        whois \
        nano \
        pciutils \
        procps-ng \
        psmisc \
        xdg-utils

    success "Base tools checked."

}

# ============================================================

# 4. HARDWARE DETECTION

# ============================================================

GPU_VENDOR="Unknown"

GPU_MODEL="Unknown"

detect_gpu() {

    info "Detecting GPU..."

    local gpu_info

    if ! command -v lspci >/dev/null 2>&1; then
        GPU_MODEL="not checked (pciutils not installed)"
        return 0
    fi

    gpu_info=$(
        lspci | grep -Ei \
            '^[[:xdigit:]]{2,4}(:[[:xdigit:]]{2})?:[[:xdigit:]]{2}\.[[:xdigit:]][[:space:]]+(VGA compatible controller|3D controller|Display controller):' ||
            true
    )

    if [[ -z "$gpu_info" ]]; then

        warning "No GPU detected."

        return

    fi

    printf '%s\n' "$gpu_info"

    GPU_MODEL=$(
        sed -E \
            -e 's/^[^[:space:]]+[[:space:]]+(VGA compatible controller|3D controller|Display controller):[[:space:]]*//' \
            -e 's/^(NVIDIA Corporation|Intel Corporation|Advanced Micro Devices, Inc\. \[AMD\/ATI\]|AMD\/ATI)[[:space:]]+//' \
            <<< "$gpu_info" |
            awk 'NF { printf "%s%s", separator, $0; separator=" + " } END { print "" }'
    )

    if grep -qi "NVIDIA" <<< "$gpu_info"; then

        GPU_VENDOR="NVIDIA"

    elif grep -qi "AMD" <<< "$gpu_info"; then

        GPU_VENDOR="AMD"

    elif grep -qi "Intel" <<< "$gpu_info"; then

        GPU_VENDOR="Intel"

    fi

    success "GPU vendor: $GPU_VENDOR"

}

# ============================================================

# 5. NVIDIA

# ============================================================

install_nvidia_driver() {

    if [[ "$GPU_VENDOR" != "NVIDIA" ]]; then

        return

    fi

    echo

    info "Checking NVIDIA driver..."

    local needs_driver=false

    if ! pacman -Q nvidia-open-dkms &>/dev/null; then

        needs_driver=true

    fi

    if ! pacman -Q nvidia-utils &>/dev/null; then

        needs_driver=true

    fi

    if [[ "$needs_driver" == true ]]; then

        info "Installing NVIDIA open DKMS driver..."

        sudo pacman -S --needed --noconfirm \
            nvidia-open-dkms \
            nvidia-utils \
            dkms

        local kernel

        for kernel in linux linux-lts linux-zen linux-hardened; do
            if pacman -Q "$kernel" &>/dev/null; then
                sudo pacman -S --needed --noconfirm "${kernel}-headers"
            fi
        done

        success "NVIDIA open DKMS driver installed."

    else

        success "NVIDIA open DKMS driver already installed."

    fi

    if command -v nvidia-smi &>/dev/null; then

        if nvidia-smi &>/dev/null; then

            success "NVIDIA driver is working."

        else

            warning "nvidia-smi exists but the driver is not currently responding."

            warning "A reboot may be required."

        fi

    fi

}

# ============================================================

# 6. BOOTLOADER

# ============================================================

BOOTLOADER="Unknown"

UKI_ENABLED=false

UKI_BOOTED=false

UKI_STATUS="not configured"

UKI_BOOT_ROOT=""

UKI_SPLASH_PATH=""

UKI_CMDLINE_WRITE_ATTEMPTED=false

detect_bootloader() {

    info "Detecting bootloader..."

    BOOTLOADER="Unknown"

    if command -v bootctl &>/dev/null; then

        local loader_path

        # The full status report also inspects boot entries and UKIs. It is not
        # needed to identify the loader and can fail independently of booting.
        if loader_path=$(run_boot_verification_check "Locating the active bootloader" bootctl --print-loader-path) &&
           [[ "$loader_path" == /* ]] && is_systemd_boot_binary "$loader_path"; then

            BOOTLOADER="systemd-boot"

        fi

    fi

    if [[ "$BOOTLOADER" == "Unknown" ]]; then

        if find /boot/EFI -type f \( \
            -iname 'systemd-bootx64.efi' -o \
            -iname 'systemd-bootia32.efi' -o \
            -iname 'systemd-bootaa64.efi' \
        \) -print -quit 2>/dev/null | grep -q .; then

            BOOTLOADER="systemd-boot"

        fi

    fi

    if [[ "$BOOTLOADER" == "Unknown" ]]; then

        if [[ -f /boot/grub/grub.cfg ]] ||

           [[ -f /etc/default/grub ]]; then

            BOOTLOADER="GRUB"

        fi

    fi

    if [[ "$BOOTLOADER" == "Unknown" ]]; then

        warning "Could not automatically identify the bootloader."

    else

        success "Bootloader: $BOOTLOADER"

    fi

}

install_uki_black_splash() {

    local destination_dir="/usr/share/poedeploy/uki"
    local destination="${destination_dir}/poedeploy-black.bmp"
    local local_splash="${SCRIPT_DIR}/assets/uki/poedeploy-black.bmp"
    local temp_dir downloaded_splash

    if [[ -f "$destination" ]]; then
        UKI_SPLASH_PATH="$destination"
        return 0
    fi

    temp_dir=$(mktemp -d -t poedeploy-uki-XXXXXX)
    downloaded_splash="${temp_dir}/poedeploy-black.bmp"

    if [[ -f "$local_splash" ]]; then
        cp "$local_splash" "$downloaded_splash"
    elif ! curl -fL --silent --show-error \
        --output "$downloaded_splash" \
        "$UKI_BLACK_SPLASH_URL"; then
        rm -rf "$temp_dir"
        warning "The plain black UKI splash could not be obtained."
        return 1
    fi

    if [[ "$(head -c 2 "$downloaded_splash" 2>/dev/null)" != "BM" ]]; then
        rm -rf "$temp_dir"
        warning "The UKI splash asset is not a valid BMP file."
        return 1
    fi

    if ! sudo install -Dm644 "$downloaded_splash" "$destination"; then
        rm -rf "$temp_dir"
        warning "The plain black UKI splash could not be installed."
        return 1
    fi

    rm -rf "$temp_dir"
    UKI_SPLASH_PATH="$destination"

    success "Plain black UKI splash installed."
}

detect_uki() {

    UKI_ENABLED=false
    UKI_BOOTED=false
    UKI_STATUS="not configured"
    UKI_SPLASH_PATH=""

    local preset line value

    for preset in /etc/mkinitcpio.d/*.preset; do
        [[ -f "$preset" ]] || continue

        while IFS= read -r line; do
            [[ "$line" =~ ^[[:space:]]*[[:alnum:]_]+_uki[[:space:]]*= ]] || continue

            value="${line#*=}"
            value="${value%%#*}"
            value="${value#"${value%%[![:space:]]*}"}"
            value="${value%"${value##*[![:space:]]}"}"
            value="${value#\"}"
            value="${value%\"}"
            value="${value#\'}"
            value="${value%\'}"

            if [[ "$value" == /* ]]; then
                UKI_ENABLED=true
                break 2
            fi
        done < "$preset"
    done

    if [[ "$UKI_ENABLED" != true ]]; then
        info "Unified kernel images (UKIs): not detected"
        return 0
    fi

    if command -v bootctl >/dev/null 2>&1; then
        local stub_path

        stub_path=$(bootctl --print-stub-path 2>/dev/null || true)

        if [[ -n "$stub_path" && "$stub_path" == /* ]]; then
            UKI_BOOTED=true
        fi
    fi

    if [[ "$UKI_BOOTED" != true ]] &&
       compgen -G '/sys/firmware/efi/efivars/StubInfo-*' >/dev/null; then
        UKI_BOOTED=true
    fi

    if [[ "$UKI_BOOTED" == true ]]; then
        UKI_STATUS="configured and current boot verified"
        success "Unified kernel image is configured and in use for the current boot."
    else
        UKI_STATUS="configured; reboot test pending"
        success "Unified kernel image configuration detected."
        info "The current boot has not been verified as a UKI boot."
    fi

}

get_uki_boot_root() {
    UKI_BOOT_ROOT=""

    if command -v bootctl >/dev/null 2>&1; then
        UKI_BOOT_ROOT=$(bootctl -x 2>/dev/null || true)

        if [[ -z "$UKI_BOOT_ROOT" ]]; then
            UKI_BOOT_ROOT=$(bootctl -p 2>/dev/null || true)
        fi
    fi

    [[ "$UKI_BOOT_ROOT" == /* ]] || return 1
    [[ -d "$UKI_BOOT_ROOT" ]] || return 1
}

get_mkinitcpio_preset_names() {
    local preset="$1"
    local declaration name
    local -a names=()

    declaration=$(sed -nE \
        's/^[[:space:]]*PRESETS[[:space:]]*=[[:space:]]*\((.*)\)[[:space:]]*$/\1/p' \
        "$preset" | head -n 1)

    declaration="${declaration//\'/}"
    declaration="${declaration//\"/}"
    read -r -a names <<< "$declaration"

    for name in "${names[@]}"; do
        if [[ "$name" =~ ^[[:alpha:]_][[:alnum:]_]*$ ]]; then
            printf '%s\n' "$name"
        fi
    done
}

prepare_uki_kernel_cmdline() {
    UKI_CMDLINE_WRITE_ATTEMPTED=false

    local source_file=""
    local source_cmdline=""
    local normalized_source candidate argument
    local -a arguments=()
    local -a filtered_arguments=()

    if [[ -s /etc/kernel/cmdline ]]; then
        source_file="/etc/kernel/cmdline"
    elif [[ -s /usr/lib/kernel/cmdline ]]; then
        source_file="/usr/lib/kernel/cmdline"
    elif [[ -r /proc/cmdline ]]; then
        source_file="/proc/cmdline"
    else
        warning "No safe source for the UKI kernel command line was found."
        return 1
    fi

    source_cmdline=$(<"$source_file")
    read -r -a arguments <<< "$source_cmdline"
    normalized_source="${arguments[*]}"

    for argument in "${arguments[@]}"; do
        case "$argument" in
            BOOT_IMAGE=*|initrd=*)
                ;;
            *)
                filtered_arguments+=("$argument")
                ;;
        esac
    done

    for argument in quiet splash bgrt_disable; do
        if ! printf '%s\n' "${filtered_arguments[@]}" | grep -Fxq "$argument"; then
            filtered_arguments+=("$argument")
        fi
    done

    candidate="${filtered_arguments[*]}"

    if [[ -z "$candidate" ]]; then
        warning "The generated UKI kernel command line is empty."
        return 1
    fi

    if [[ "$source_file" == "/etc/kernel/cmdline" &&
          "$candidate" == "$normalized_source" ]]; then
        success "Keeping the existing persistent kernel command line."
        return 0
    fi

    echo
    info "The following persistent UKI kernel command line was derived from $source_file:"
    echo
    printf '  %s\n' "$candidate"
    echo
    info "Plymouth requires 'quiet splash'; 'bgrt_disable' suppresses the firmware/default Arch logo."
    info "Root and filesystem arguments will be preserved; legacy BOOT_IMAGE/initrd references are omitted for the UKI."
    info "Updating /etc/kernel/cmdline; sudo may request your password."

    if [[ -e /etc/kernel/cmdline ]] && ! sudo test -e /etc/kernel/cmdline.poedeploy.bak; then
        if ! sudo cp -n /etc/kernel/cmdline /etc/kernel/cmdline.poedeploy.bak; then
            warning "Could not preserve the kernel command line backup; leaving the file unchanged."
            return 1
        fi
    fi

    UKI_CMDLINE_WRITE_ATTEMPTED=true

    if ! printf '%s\n' "$candidate" | sudo tee /etc/kernel/cmdline >/dev/null ||
       ! sudo chmod 644 /etc/kernel/cmdline; then
        warning "The persistent kernel command line could not be written."
        return 1
    fi

    success "Persistent UKI kernel command line configured."
}

restore_failed_uki_setup() {
    local backup_dir="$1"
    local cmdline_existed="$2"
    shift 2

    local preset backup

    for preset in "$@"; do
        backup="${backup_dir}/$(basename "$preset")"

        if [[ -f "$backup" ]]; then
            if ! sudo cp "$backup" "$preset"; then
                warning "Could not restore $preset from the temporary backup."
            fi
        fi
    done

    if [[ "$cmdline_existed" == true ]]; then
        if ! sudo cp "${backup_dir}/kernel-cmdline" /etc/kernel/cmdline; then
            warning "Could not restore /etc/kernel/cmdline from the temporary backup."
        fi
    else
        if ! sudo rm -f /etc/kernel/cmdline; then
            warning "Could not remove the kernel command line created by the failed setup."
        fi
    fi

    warning "The mkinitcpio presets and kernel command line were restored."
}

remove_failed_uki_files() {
    local uki_path

    for uki_path in "$@"; do
        [[ "$uki_path" == */EFI/Linux/poedeploy-*.efi ]] || continue

        if [[ -e "$uki_path" ]] && ! sudo rm -f "$uki_path"; then
            warning "Could not remove the incomplete UKI: $uki_path"
        fi
    done
}

setup_uki() {
    echo
    echo "========================================"
    echo "          OPTIONAL UKI SETUP"
    echo "========================================"
    echo

    if [[ "$UKI_ENABLED" == true ]]; then
        if [[ "$UKI_BOOTED" == true ]]; then
            success "UKI setup is already configured and verified for the current boot."
            UKI_ACTION="already configured and verified"
        else
            info "UKI setup already exists, but this boot has not verified it yet."
            info "Select the UKI entry from the systemd-boot menu on the next reboot."
            UKI_ACTION="configured; reboot test pending"
        fi

        return 0
    fi

    local answer
    read -rp "Create UKIs alongside the existing boot images? [y/N]: " answer

    if [[ ! "$answer" =~ ^[Yy]$ ]]; then
        info "UKI setup skipped."
        UKI_ACTION="skipped"
        return 0
    fi

    if [[ ! -d /sys/firmware/efi ]]; then
        warning "The system was not booted in UEFI mode; UKI setup is unavailable."
        UKI_ACTION="not available (non-UEFI boot)"
        return 0
    fi

    if [[ "$BOOTLOADER" != "systemd-boot" ]]; then
        warning "Automated UKI setup currently supports systemd-boot only."
        UKI_ACTION="not available for $BOOTLOADER"
        return 0
    fi

    if ! get_uki_boot_root; then
        warning "The systemd-boot boot partition could not be located safely."
        UKI_ACTION="boot partition not found"
        return 0
    fi

    if ! sudo test -w "$UKI_BOOT_ROOT"; then
        warning "The boot partition is not writable: $UKI_BOOT_ROOT"
        UKI_ACTION="boot partition not writable"
        return 0
    fi

    local -a preset_files=(/etc/mkinitcpio.d/*.preset)

    if [[ ! -e "${preset_files[0]}" ]]; then
        warning "No mkinitcpio preset files were found."
        UKI_ACTION="no mkinitcpio presets"
        return 0
    fi

    info "Boot partition: $UKI_BOOT_ROOT"
    info "Traditional initramfs images and loader entries will be preserved."

    if ! install_uki_black_splash; then
        warning "UKI setup stopped because the persistent splash could not be installed."
        UKI_ACTION="splash installation failed"
        return 0
    fi

    local backup_dir
    local cmdline_existed=false
    local cmdline_backup=""
    local preset kernel_name selected_preset name uki_path
    local configured_count=0
    local -a preset_names=()
    local -a modified_presets=()
    local -a created_uki_paths=()

    backup_dir=$(mktemp -d -t poedeploy-uki-config-XXXXXX)

    if [[ -e /etc/kernel/cmdline ]]; then
        cmdline_existed=true
        cmdline_backup="${backup_dir}/kernel-cmdline"

        if ! sudo cp /etc/kernel/cmdline "$cmdline_backup" ||
           ! sudo chown "$(id -u):$(id -g)" "$cmdline_backup"; then
            warning "The existing kernel command line could not be backed up."
            rm -rf "$backup_dir"
            UKI_ACTION="backup failed"
            return 0
        fi
    fi

    if ! prepare_uki_kernel_cmdline; then
        if [[ "$UKI_CMDLINE_WRITE_ATTEMPTED" == true ]]; then
            restore_failed_uki_setup "$backup_dir" "$cmdline_existed"
        fi

        rm -rf "$backup_dir"
        UKI_ACTION="cancelled before configuration"
        return 0
    fi

    if ! sudo mkdir -p "${UKI_BOOT_ROOT}/EFI/Linux"; then
        restore_failed_uki_setup "$backup_dir" "$cmdline_existed"
        rm -rf "$backup_dir"
        UKI_ACTION="could not create EFI/Linux"
        return 0
    fi

    for preset in "${preset_files[@]}"; do
        [[ -f "$preset" ]] || continue

        mapfile -t preset_names < <(get_mkinitcpio_preset_names "$preset")
        selected_preset=""

        for name in "${preset_names[@]}"; do
            if [[ "$name" == "default" ]]; then
                selected_preset="$name"
                break
            fi

            if [[ -z "$selected_preset" && "$name" != "fallback" ]]; then
                selected_preset="$name"
            fi
        done

        if [[ -z "$selected_preset" ]]; then
            warning "No normal build preset was found in $preset; skipping it."
            continue
        fi

        if grep -Eq "^[[:space:]]*${selected_preset}_uki[[:space:]]*=" "$preset"; then
            info "A UKI path already exists for $(basename "$preset"); preserving it."
            continue
        fi

        kernel_name="$(basename "$preset" .preset)"
        kernel_name="${kernel_name//[^[:alnum:]._-]/-}"
        uki_path="${UKI_BOOT_ROOT}/EFI/Linux/poedeploy-${kernel_name}.efi"

        if [[ -e "$uki_path" ]]; then
            warning "A file already exists at the planned UKI path; preserving it: $uki_path"
            continue
        fi

        if ! sudo cp "$preset" "${backup_dir}/$(basename "$preset")" ||
           ! sudo chown "$(id -u):$(id -g)" "${backup_dir}/$(basename "$preset")" ||
           ! sudo cp -n "$preset" "${preset}.poedeploy.bak"; then
            warning "Could not safely back up $preset. Restoring earlier changes..."
            restore_failed_uki_setup "$backup_dir" "$cmdline_existed" "${modified_presets[@]}"
            rm -rf "$backup_dir"
            UKI_ACTION="preset backup failed"
            return 0
        fi

        modified_presets+=("$preset")

        if ! {
            printf '\n# PoeDeploy UKI configuration\n'
            printf '%s_uki="%s"\n' "$selected_preset" "$uki_path"
        } | sudo tee -a "$preset" >/dev/null; then
            warning "Could not update $preset. Restoring the previous configuration..."
            restore_failed_uki_setup "$backup_dir" "$cmdline_existed" "${modified_presets[@]}"
            rm -rf "$backup_dir"
            UKI_ACTION="preset update failed"
            return 0
        fi

        created_uki_paths+=("$uki_path")
        ((configured_count += 1))
    done

    if (( configured_count == 0 )); then
        restore_failed_uki_setup "$backup_dir" "$cmdline_existed" "${modified_presets[@]}"
        rm -rf "$backup_dir"
        warning "No mkinitcpio preset could be configured for UKI generation."
        UKI_ACTION="no compatible presets"
        return 0
    fi

    UKI_ENABLED=true

    if ! configure_uki_splash; then
        warning "The UKI splash configuration failed. Restoring the previous configuration..."
        restore_failed_uki_setup "$backup_dir" "$cmdline_existed" "${modified_presets[@]}"
        rm -rf "$backup_dir"
        detect_uki
        UKI_ACTION="splash configuration failed; configuration restored"
        return 0
    fi

    info "Building the new UKIs while keeping the existing boot images..."

    if ! sudo mkinitcpio -P; then
        warning "UKI generation failed. Restoring the previous configuration..."
        remove_failed_uki_files "${created_uki_paths[@]}"
        restore_failed_uki_setup "$backup_dir" "$cmdline_existed" "${modified_presets[@]}"
        sudo mkinitcpio -P || warning "The recovery initramfs rebuild also reported a failure."
        rm -rf "$backup_dir"
        detect_uki
        UKI_ACTION="build failed; configuration restored"
        return 0
    fi

    local verification_failed=false

    for uki_path in "${created_uki_paths[@]}"; do
        if [[ ! -s "$uki_path" ]] ||
           [[ "$(sudo head -c 2 "$uki_path" 2>/dev/null)" != "MZ" ]]; then
            warning "Generated UKI could not be verified: $uki_path"
            verification_failed=true
        else
            success "Generated UKI verified: $uki_path"
        fi
    done

    if [[ "$verification_failed" != true ]] && ! verify_uki_plymouth_setup; then
        verification_failed=true
    fi

    if [[ "$verification_failed" != true ]] && ! verify_secure_boot_after_uki_rebuild; then
        verification_failed=true
    fi

    if [[ "$verification_failed" == true ]]; then
        warning "UKI verification failed. Restoring the previous configuration..."
        remove_failed_uki_files "${created_uki_paths[@]}"
        restore_failed_uki_setup "$backup_dir" "$cmdline_existed" "${modified_presets[@]}"
        sudo mkinitcpio -P || warning "The recovery initramfs rebuild also reported a failure."
        rm -rf "$backup_dir"
        detect_uki
        UKI_ACTION="verification failed; configuration restored"
        return 0
    fi

    if sudo install -d -m 755 /var/lib/poedeploy && {
        printf 'created_at=%s\n' "$(date --iso-8601=seconds)"
        printf 'boot_root=%s\n' "$UKI_BOOT_ROOT"

        for uki_path in "${created_uki_paths[@]}"; do
            printf 'uki=%s\n' "$uki_path"
        done
    } | sudo tee /var/lib/poedeploy/uki-pending >/dev/null; then
        success "Recorded the pending UKI reboot test."
    else
        warning "The UKIs were created, but the reboot-test marker could not be written."
    fi

    rm -rf "$backup_dir"
    detect_uki
    UKI_ACTION="created; reboot test pending"

    echo
    success "UKI setup completed without removing the traditional boot images."
    warning "Reboot and select the new UKI entry from the systemd-boot menu."
    warning "Secure Boot will remain unavailable until PoeDeploy verifies that UKI boot."
}

# ============================================================

# 7. NETWORKMANAGER

# ============================================================

check_networkmanager() {

    info "Checking NetworkManager..."

    if ! pacman -Q networkmanager &>/dev/null; then

        info "NetworkManager is not installed."

        sudo pacman -S --needed --noconfirm networkmanager

    fi

    if ! systemctl is-enabled NetworkManager &>/dev/null; then

        sudo systemctl enable NetworkManager

    fi

    if ! systemctl is-active NetworkManager &>/dev/null; then

        sudo systemctl start NetworkManager

    fi

    success "NetworkManager is installed and enabled."

}

# ============================================================

# 8. FILESYSTEM

# ============================================================

ROOT_FILESYSTEM="Unknown"

detect_filesystem() {

    info "Detecting root filesystem..."

    ROOT_FILESYSTEM=$(findmnt -n -o FSTYPE /)

    success "Root filesystem: $ROOT_FILESYSTEM"

}

# ============================================================

# 9. PLYMOUTH

# ============================================================

install_plymouth() {

    echo

    info "Checking Plymouth..."

    if pacman -Q plymouth &>/dev/null; then

        success "Plymouth is already installed."

    else

        info "Installing Plymouth..."

        sudo pacman -S --needed --noconfirm plymouth

        success "Plymouth installed."

    fi

}

configure_mkinitcpio_plymouth() {

    local config="/etc/mkinitcpio.conf"

    info "Checking mkinitcpio Plymouth hook..."

    local hooks_line

    hooks_line=$(grep '^HOOKS=' "$config" | head -n 1)

    [[ -n "$hooks_line" ]] ||

        die "Could not find HOOKS in $config."

    local hooks_content="${hooks_line#HOOKS=(}"

    hooks_content="${hooks_content%)}"

    read -r -a hooks <<< "$hooks_content"

    local new_hooks_line
    new_hooks_line="HOOKS=($(order_mkinitcpio_plymouth_hook "${hooks[@]}"))"

    if [[ "$new_hooks_line" == "$hooks_line" ]]; then
        success "Plymouth hook is correctly ordered."
        return 0
    fi

    info "Configuring the Plymouth hook after the active init hook..."

    sudo cp "$config" "${config}.bak"

    sudo sed -i \
        "s|^HOOKS=.*|$new_hooks_line|" \
        "$config"

    success "Plymouth hook added to mkinitcpio."

}

order_mkinitcpio_plymouth_hook() {
    local hook anchor="" inserted=false
    local -a source_hooks=("$@")
    local -a ordered_hooks=()

    if printf '%s\n' "${source_hooks[@]}" | grep -Fxq systemd; then
        anchor=systemd
    elif printf '%s\n' "${source_hooks[@]}" | grep -Fxq udev; then
        anchor=udev
    fi

    for hook in "${source_hooks[@]}"; do
        [[ "$hook" == plymouth ]] && continue
        ordered_hooks+=("$hook")
        if [[ "$hook" == "$anchor" ]]; then
            ordered_hooks+=(plymouth)
            inserted=true
        fi
    done
    if [[ "$inserted" != true ]]; then
        ordered_hooks=(plymouth "${ordered_hooks[@]}")
    fi
    printf '%s ' "${ordered_hooks[@]}"
}

configure_systemd_boot_plymouth() {

    local changed=false

    for entry in /boot/loader/entries/*.conf; do

        [[ -f "$entry" ]] || continue

        if grep -q '^options ' "$entry"; then

            if ! grep -qE '^options .*(^| )quiet( |$)' "$entry"; then

                sudo sed -i '/^options / s/$/ quiet/' "$entry"

                changed=true

            fi

            if ! grep -qE '^options .*(^| )splash( |$)' "$entry"; then

                sudo sed -i '/^options / s/$/ splash/' "$entry"

                changed=true

            fi

        fi

    done

    if [[ "$changed" == true ]]; then

        success "systemd-boot splash parameters configured."

    else

        success "systemd-boot splash parameters already configured."

    fi

}

configure_grub_plymouth() {

    local config="/etc/default/grub"

    local changed=false

    if [[ ! -f "$config" ]]; then

        warning "GRUB configuration file not found."

        return

    fi

    local params

    params=$(grep '^GRUB_CMDLINE_LINUX_DEFAULT=' "$config" || true)

    if [[ -z "$params" ]]; then

        warning "GRUB_CMDLINE_LINUX_DEFAULT not found."

        return

    fi

    if ! echo "$params" | grep -qw quiet; then

        sudo sed -i \
            's/^GRUB_CMDLINE_LINUX_DEFAULT="/GRUB_CMDLINE_LINUX_DEFAULT="quiet /' \
            "$config"

        changed=true

    fi

    if ! grep '^GRUB_CMDLINE_LINUX_DEFAULT=' "$config" |

        grep -qw splash; then

        sudo sed -i \
            's/^GRUB_CMDLINE_LINUX_DEFAULT="/GRUB_CMDLINE_LINUX_DEFAULT="splash /' \
            "$config"

        changed=true

    fi

    if [[ "$changed" == true ]]; then

        sudo grub-mkconfig -o /boot/grub/grub.cfg

        success "GRUB splash parameters configured."

    else

        success "GRUB splash parameters already configured."

    fi

}

configure_bootloader_plymouth() {

    case "$BOOTLOADER" in

        systemd-boot)

            configure_systemd_boot_plymouth

            ;;

        GRUB)

            configure_grub_plymouth

            ;;

        *)

            warning "Unknown bootloader. Kernel parameters were not modified."

            ;;

    esac

}

get_remote_plymouth_themes() {

    {
        local archive theme_name

        while IFS= read -r archive; do
            theme_name=$(basename "$(dirname "$(dirname "$archive")")")

            if [[ "$(basename "$archive")" == "${theme_name}.zip" ]]; then
                printf '%s\n' "$theme_name"
            fi
        done < <(
            find "${SCRIPT_DIR}/themes" -mindepth 3 -maxdepth 3 \
                -type f -path '*/plymouth/*.zip' -print 2>/dev/null || true
        )

        curl -fsSL "$GITHUB_THEMES_API" 2>/dev/null |
            jq -r '.tree[]?.path' 2>/dev/null |
            awk -F/ '
                $1 == "themes" && $3 == "plymouth" && $4 == $2 ".zip" {
                    print $2
                }
            ' || true
    } | sort -u
}

install_remote_plymouth_theme() {

    local theme_name="$1"
    local theme_url="${GITHUB_RAW_BASE}/themes/${theme_name}/plymouth/${theme_name}.zip"
    local local_archive="${SCRIPT_DIR}/themes/${theme_name}/plymouth/${theme_name}.zip"
    local theme_dir="/usr/share/plymouth/themes/${theme_name}"
    local temp_dir archive extracted_dir plymouth_file

    if [[ ! "$theme_name" =~ ^[[:alnum:]_.-]+$ ]]; then
        warning "Invalid repository theme name: $theme_name"
        return 1
    fi

    temp_dir=$(mktemp -d -t poedeploy-theme-XXXXXX)
    archive="${temp_dir}/${theme_name}.zip"
    extracted_dir="${temp_dir}/extracted"
    mkdir -p "$extracted_dir"

    if [[ -f "$local_archive" ]]; then
        cp "$local_archive" "$archive"
    elif ! curl -fL --silent --show-error --output "$archive" "$theme_url"; then
        rm -rf "$temp_dir"
        return 1
    fi

    if ! unzip -t "$archive" >/dev/null 2>&1 ||
       ! unzip -q "$archive" -d "$extracted_dir"; then
        rm -rf "$temp_dir"
        return 1
    fi

    plymouth_file=$(find "$extracted_dir" -type f -name '*.plymouth' -print -quit 2>/dev/null)

    if [[ -z "$plymouth_file" ]]; then
        rm -rf "$temp_dir"
        return 1
    fi

    sudo mkdir -p "$theme_dir"
    sudo cp -rf "$(dirname "$plymouth_file")/." "$theme_dir/"
    rm -rf "$temp_dir"

    success "Repository Plymouth theme '$theme_name' installed."
}

configure_uki_splash() {

    if [[ "$UKI_ENABLED" != true ]]; then
        return 0
    fi

    if [[ -z "$UKI_SPLASH_PATH" || ! -f "$UKI_SPLASH_PATH" ]]; then
        warning "UKI detected, but no compatible BMP splash is available."
        return 0
    fi

    local preset name
    local -a preset_names=()
    local configured=false

    for preset in /etc/mkinitcpio.d/*.preset; do
        [[ -f "$preset" ]] || continue
        if ! sudo cp -n "$preset" "${preset}.poedeploy.bak"; then
            warning "Could not back up $preset before configuring the UKI splash."
            return 1
        fi

        mapfile -t preset_names < <(get_mkinitcpio_preset_names "$preset")
        for name in "${preset_names[@]}"; do
            grep -Eq "^[[:space:]]*${name}_uki[[:space:]]*=" "$preset" || continue
            if ! set_mkinitcpio_preset_splash "$preset" "$name" "$UKI_SPLASH_PATH"; then
                warning "Could not update UKI splash options in $preset."
                return 1
            fi
            configured=true
        done
    done

    if [[ "$configured" == true ]]; then
        success "UKI splash configured: $UKI_SPLASH_PATH"
    fi
}

set_mkinitcpio_preset_splash() {
    local preset="$1" name="$2" splash="$3"
    local line value token skip_next=false
    local -a options=()
    local -a current_options=()
    local native_splash=false
    if grep -Eq "^[[:space:]]*(ALL|${name})_splash[[:space:]]*=" "$preset"; then
        native_splash=true
    fi

    line=$(grep -E "^[[:space:]]*${name}_options[[:space:]]*=" "$preset" | tail -n 1 || true)
    if [[ -n "$line" ]]; then
        value="${line#*=}"
        value="${value#"${value%%[![:space:]]*}"}"
        value="${value%"${value##*[![:space:]]}"}"
        if [[ "$value" == \(* ]]; then
            warning "Array-style options in $preset require manual splash configuration; leaving the preset unchanged."
            return 1
        fi
        value="${value#\"}"
        value="${value%\"}"
        value="${value#\'}"
        value="${value%\'}"
        read -r -a current_options <<< "$value"
        for token in "${current_options[@]}"; do
            if [[ "$skip_next" == true ]]; then
                skip_next=false
                continue
            fi
            case "$token" in
                --splash) skip_next=true ;;
                --splash=*) ;;
                *) options+=("$token") ;;
            esac
        done
    fi
    if [[ "$native_splash" != true ]]; then
        options+=(--splash "$splash")
    fi

    local replacement="${name}_options=\"${options[*]}\""
    local staged
    staged=$(mktemp -t poedeploy-preset-XXXXXX)
    if ! awk -v variable="${name}_options" -v replacement="$replacement" \
        -v native="$native_splash" -v splash_variable="${name}_splash" \
        -v splash_replacement="${name}_splash=\"${splash}\"" '
        BEGIN { replaced = 0 }
        $0 ~ "^[[:space:]]*" variable "[[:space:]]*=" {
            if (!replaced) print replacement
            replaced = 1
            next
        }
        native == "true" && $0 ~ "^[[:space:]]*" splash_variable "[[:space:]]*=" {
            if (!splash_replaced) print splash_replacement
            splash_replaced = 1
            next
        }
        { print }
        END {
            if (!replaced) print replacement
            if (native == "true" && !splash_replaced) print splash_replacement
        }
    ' "$preset" > "$staged" || ! sudo cp "$staged" "$preset"; then
        rm -f "$staged"
        return 1
    fi
    rm -f "$staged"
}

get_configured_uki_paths() {
    local preset name line value
    local -a preset_names=()

    for preset in /etc/mkinitcpio.d/*.preset; do
        [[ -f "$preset" ]] || continue

        mapfile -t preset_names < <(get_mkinitcpio_preset_names "$preset")
        for name in "${preset_names[@]}"; do
            line=$(grep -E "^[[:space:]]*${name}_uki[[:space:]]*=" "$preset" | tail -n 1 || true)
            [[ -n "$line" ]] || continue
            value="${line#*=}"
            value="${value%%#*}"
            value="${value#"${value%%[![:space:]]*}"}"
            value="${value%"${value##*[![:space:]]}"}"
            value="${value#\"}"
            value="${value%\"}"
            value="${value#\'}"
            value="${value%\'}"
            [[ "$value" == /* ]] && printf '%s\n' "$value"
        done
    done
}

stage_uki_for_verification() {
    local source="$1" destination="$2"

    sudo install \
        -m 600 \
        -o "$(id -u)" \
        -g "$(id -g)" \
        -- "$source" "$destination"
}

extract_uki_section() {
    local uki="$1" section="$2" destination="$3"
    # objcopy needs a regular output file for PE images, even for --dump-section.
    # /dev/null can report "file truncated" after successfully dumping a section.
    local result=0
    if ! objcopy --dump-section "${section}=${destination}" "$uki" "${destination}.efi" ||
       [[ ! -s "$destination" ]]; then
        result=1
    fi
    rm -f -- "${destination}.efi"
    return "$result"
}

uki_contains_plymouth_theme() {
    local uki="$1" theme="$2"

    # Do not use grep -q here. With pipefail enabled, an early grep exit can
    # give lsinitcpio SIGPIPE and incorrectly turn a successful match into 141.
    lsinitcpio "$uki" 2>/dev/null |
        grep -Fx "usr/share/plymouth/themes/${theme}/${theme}.plymouth" >/dev/null
}

plymouth_theme_is_available() {
    local theme="$1"

    # Consume the complete list so plymouth-set-default-theme cannot be marked
    # as failed by SIGPIPE after grep finds an early match.
    plymouth-set-default-theme -l 2>/dev/null |
        grep -Fx "$theme" >/dev/null
}

is_systemd_boot_binary() {
    local path="$1"
    sudo test -f "$path" || return 1
    [[ "$(sudo head -c 2 -- "$path")" == MZ ]] || return 1
    # systemd embeds this LoaderInfo marker to identify its own EFI binaries.
    # This identifies the product, NOT its signature; sbctl verifies that later.
    LC_ALL=C sudo grep -aE -- \
        '#### LoaderInfo: systemd-boot [^#[:cntrl:]]{1,256} ####' "$path" >/dev/null
}

run_boot_verification_check() {
    local label="$1" status
    shift
    info "$label (timeout: 30 seconds)" >&2
    if sudo timeout --kill-after=5s 30s "$@"; then
        return 0
    else
        status=$?
    fi
    case "$status" in
        124|137)
            warning "$label timed out or was killed (exit $status). Verification is incomplete." >&2
            warning "Do not repeat the installer if kernel faults recur; inspect the kernel journal." >&2
            ;;
        *) warning "$label failed (exit $status)." >&2 ;;
    esac
    return "$status"
}

get_present_fallback_boot_paths() {
    local esp="${1:-}" architecture path
    if [[ -z "$esp" ]]; then
        esp=$(run_boot_verification_check "Locating the EFI partition" bootctl --print-esp-path) || return 1
    fi
    [[ "$esp" == /* ]] || return 1
    esp=$(realpath -ms -- "$esp") || return 1
    for architecture in X64 IA32 AA64; do
        path="${esp%/}/EFI/BOOT/BOOT${architecture}.EFI"
        if sudo test -f "$path"; then printf '%s\n' "$path"; fi
    done
    return 0
}

get_systemd_boot_files() {
    local esp="${1:-}" current="${2:-}" path architecture
    local -a paths=()
    if [[ -z "$esp" ]] && ! esp=$(run_boot_verification_check "Locating the EFI partition" bootctl --print-esp-path); then
        warning "Could not read the ESP path (bootctl --print-esp-path)." >&2
        return 1
    fi
    if [[ -z "$current" ]] && ! current=$(run_boot_verification_check "Locating the active bootloader" bootctl --print-loader-path); then
        warning "Could not read the active loader path (bootctl --print-loader-path)." >&2
        return 1
    fi
    if [[ "$esp" != /* || "$current" != /* ]]; then
        warning "bootctl returned an invalid ESP or active loader path." >&2
        return 1
    fi
    esp=$(realpath -ms -- "$esp") || return 1
    current=$(realpath -ms -- "$current") || return 1

    if [[ "$current" != "${esp%/}"/EFI/* ]] || ! is_systemd_boot_binary "$current"; then
        warning "Could not identify the current systemd-boot binary on the ESP." >&2
        return 1
    fi
    paths+=("$current")
    # Inspect only the small loader binaries, never the full bootctl status
    # report. A filename alone must not authorize signing a shim/GRUB fallback.
    for architecture in x64 ia32 aa64; do
        for path in "${esp%/}/EFI/systemd/systemd-boot${architecture}.efi" \
                    "${esp%/}/EFI/BOOT/BOOT${architecture^^}.EFI"; do
            [[ "$path" != "$current" ]] || continue
            if is_systemd_boot_binary "$path"; then
                paths+=("$path")
            fi
        done
    done
    printf '%s\n' "${paths[@]}" | sort -u
}

read_sbctl_signature_report() {
    local report file entry combined='[]'
    local -A seen=()
    if (( $# == 0 )); then
        warning "Refusing an untargeted Secure Boot signature scan." >&2
        return 1
    fi
    for file in "$@"; do
        [[ "$file" == /* ]] || return 1
        file=$(realpath -ms -- "$file") || return 1
        [[ "${seen[$file]:-false}" != true ]] || continue
        seen["$file"]=true
        report=$(run_boot_verification_check "Checking signature: $file" \
            sbctl --json verify "$file") || return 1
        # A zero command exit is not proof of a signature. Require an explicit,
        # well-formed result for this file; never accept a partial/other report.
        if ! entry=$(jq -ce --arg path "$file" '
            if type != "array" then error("expected array") else . end |
            map(.file_name |= gsub("/+"; "/")) |
            map(select(.file_name == $path)) |
            if length == 1 and
                (.[0].is_signed == 1 or .[0].is_signed == 0 or .[0].is_signed == -1)
            then . else error("missing or invalid per-file result") end' <<< "$report" 2>/dev/null); then
            warning "Invalid signature report for: $file" >&2
            return 1
        fi
        combined=$(jq -cn --argjson old "$combined" --argjson new "$entry" '$old + $new') || return 1
    done
    printf '%s\n' "$combined"
}

sbctl_report_has_signature() {
    local report="$1" path="$2"
    path=$(realpath -ms -- "$path") || return 1
    jq -e --arg path "$path" '[.[] | select(.file_name == $path)] |
        length > 0 and all(.[]; .is_signed == 1)' <<< "$report" >/dev/null
}

verify_secure_boot_files() {
    local report file failed=false
    SECURE_BOOT_VERIFY_STATUS="verification failed"
    SECURE_BOOT_OTHER_FILES_WARNING=false
    if (( $# == 0 )); then
        warning "No required boot files were found for signature verification."
        return 1
    fi
    if ! command -v sbctl >/dev/null 2>&1 || ! command -v jq >/dev/null 2>&1; then
        warning "sbctl and jq are required to inspect boot file signatures."
        return 1
    fi

    # sbctl can exit zero even when files are unsigned or missing.
    # Inspect its structured per-file results instead of trusting that exit code.
    if ! report=$(read_sbctl_signature_report "$@"); then
        warning "Could not read a valid per-file signature report from sbctl."
        return 1
    fi

    for file in "$@"; do
        if sbctl_report_has_signature "$report" "$file"; then
            success "Signature verified: $file"
        else
            warning "Required boot file is unsigned, missing, or unverified: $file"
            failed=true
        fi
    done

    info "Only the listed boot files were checked; unrelated EFI files were not scanned."
    [[ "$failed" == false ]] || return 1
    SECURE_BOOT_VERIFY_STATUS="selected boot files verified"
}

verify_secure_boot_after_uki_rebuild() {
    info "Verifying Secure Boot configuration..."
    if ! firmware_secure_boot_enabled; then
        SECURE_BOOT_VERIFY_STATUS="not run (Secure Boot not detected as enabled)"
        return 0
    fi
    success "Secure Boot is enabled."
    if [[ "${BOOTLOADER:-}" == systemd-boot && "${UKI_BOOTED:-false}" == true ]]; then
        verify_active_secure_boot_chain
        return $?
    fi
    local -a uki_paths=()
    mapfile -t uki_paths < <(get_configured_uki_paths | sort -u)
    local loader_paths path
    if [[ "${BOOTLOADER:-}" == systemd-boot ]]; then
        if ! loader_paths=$(get_systemd_boot_files); then
            SECURE_BOOT_VERIFY_STATUS="boot loader discovery failed"
            warning "Could not identify the systemd-boot files to verify."
            return 1
        fi
        while IFS= read -r path; do
            [[ -n "$path" ]] && uki_paths+=("$path")
        done <<< "$loader_paths"
    fi
    info "Verifying signatures of the rebuilt UKIs and identified boot loaders..."
    verify_secure_boot_files "${uki_paths[@]}" || return 1
    SECURE_BOOT_VERIFY_STATUS="UKI and identified boot loader signatures verified"
    if [[ "$SECURE_BOOT_OTHER_FILES_WARNING" == true ]]; then
        SECURE_BOOT_VERIFY_STATUS+="; additional boot file warnings"
    fi
    success "UKI and identified boot loader signatures verified; existing keys were not changed."
}

verify_active_secure_boot_chain() {
    SECURE_BOOT_VERIFY_STATUS="verification failed"
    SECURE_BOOT_OTHER_FILES_WARNING=false
    local esp loaders loader uki report path repaired_report fallbacks fallback_report image_type
    local -a uki_paths=()
    if ! esp=$(run_boot_verification_check "Locating the EFI partition" bootctl --print-esp-path); then
        warning "Could not read the ESP path (bootctl --print-esp-path)."
        return 1
    fi
    if ! loader=$(run_boot_verification_check "Locating the active bootloader" bootctl --print-loader-path); then
        warning "Could not read the active loader path (bootctl --print-loader-path)."
        return 1
    fi
    # Reuse this check's discovered paths, not a cache from a previous run.
    if ! loaders=$(get_systemd_boot_files "$esp" "$loader"); then
        warning "Could not identify the active boot chain."
        return 1
    fi
    if ! uki=$(run_boot_verification_check "Locating the current UKI" bootctl --print-stub-path); then
        warning "Could not read the current UKI path (bootctl --print-stub-path)."
        return 1
    fi
    [[ "$loader" == /* && "$uki" == /* ]] || return 1
    loader=$(realpath -ms -- "$loader") || return 1
    uki=$(realpath -ms -- "$uki") || return 1
    if ! grep -Fx "$loader" <<< "$loaders" >/dev/null; then
        warning "The active loader was not identified as systemd-boot."
        return 1
    fi
    if ! image_type=$(run_boot_verification_check "Identifying the current UKI: $uki" bootctl kernel-identify "$uki") ||
       [[ "$image_type" != uki ]]; then
        warning "The current boot image could not be identified as a UKI: $uki"
        return 1
    fi
    mapfile -t uki_paths < <(get_configured_uki_paths | sort -u)
    if ! report=$(read_sbctl_signature_report "$loader" "$uki" "${uki_paths[@]}"); then
        warning "Could not read a valid signature report."
        return 1
    fi

    success "Active bootloader: systemd-boot"
    if ! sbctl_report_has_signature "$report" "$loader"; then
        warning "Active bootloader is unsigned or unverified: $loader"
        return 1
    fi
    success "Active bootloader is signed:"
    printf '       %s\n' "$loader"
    success "Current boot entry uses UKI:"
    printf '       %s\n' "$uki"
    if ! sbctl_report_has_signature "$report" "$uki"; then
        warning "Current UKI is unsigned or unverified: $uki"
        return 1
    fi
    success "Current UKI is signed."
    if [[ "${VERIFIED_PLYMOUTH_UKIS[$uki]:-false}" != true ]]; then
        warning "Current UKI contents have not passed Plymouth verification in this run."
        return 1
    fi
    success "Current UKI contains the required persistent kernel command line."
    success "Plymouth 'splash' kernel option and theme verified in the current UKI."
    for path in "${uki_paths[@]}"; do
        if ! sbctl_report_has_signature "$report" "$path"; then
            warning "Rebuilt UKI is unsigned or unverified: $path"
            return 1
        fi
    done

    # Repair only identified fallback copies after the active loader and UKI
    # verify with the existing key. This never creates or enrolls keys.
    if ! fallbacks=$(get_present_fallback_boot_paths "$esp"); then
        SECURE_BOOT_OTHER_FILES_WARNING=true
        warning "Fallback discovery failed; fallback protection is unverified."
        fallbacks=""
    fi
    while IFS= read -r path; do
        [[ "$path" == */EFI/BOOT/BOOT*.EFI && "$path" != "$loader" ]] || continue
        if ! grep -Fx "$path" <<< "$loaders" >/dev/null; then
            SECURE_BOOT_OTHER_FILES_WARNING=true
            warning "Fallback is not identified as systemd-boot; not checked or signed: $path"
            continue
        fi
        if ! fallback_report=$(read_sbctl_signature_report "$path"); then
            SECURE_BOOT_OTHER_FILES_WARNING=true
            warning "Fallback signature check failed; not attempting signing: $path"
            continue
        fi
        if sbctl_report_has_signature "$fallback_report" "$path"; then
            success "Fallback bootloader is signed:"
        elif jq -e '.[0].is_signed == 0' <<< "$fallback_report" >/dev/null; then
            info "Signing and registering the systemd-boot fallback with the existing key:"
            printf '       %s\n' "$path"
            if sudo sbctl sign -s "$path" &&
               repaired_report=$(read_sbctl_signature_report "$path") &&
               sbctl_report_has_signature "$repaired_report" "$path"; then
                SECURE_BOOT_AUTOMATIC_ACTION="systemd-boot fallback signed and registered"
                success "Fallback bootloader is signed:"
            else
                SECURE_BOOT_OTHER_FILES_WARNING=true
                SECURE_BOOT_AUTOMATIC_ACTION="fallback signing or verification failed"
                warning "Fallback bootloader remains unsigned or unverified:"
            fi
        else
            SECURE_BOOT_OTHER_FILES_WARNING=true
            warning "Fallback bootloader is missing; not attempting signing:"
        fi
        printf '       %s\n' "$path"
    done < <(printf '%s\n' "$loaders" "$fallbacks" | sort -u)

    info "Standalone /boot/vmlinuz-* kernels are not checked or signed separately for this UKI boot."
    info "Unrelated EFI files were not scanned."

    SECURE_BOOT_VERIFY_STATUS="active Secure Boot chain verified"
    if [[ "$SECURE_BOOT_OTHER_FILES_WARNING" == true ]]; then
        SECURE_BOOT_VERIFY_STATUS+="; additional boot file warnings"
    fi
    success "Active Secure Boot chain verified."
}

uki_cmdline_matches_file() {
    local embedded="$1" persistent="$2" tokens argument expected
    [[ -s "$embedded" && -r "$persistent" ]] || return 1
    tokens=$(tr '\0[:space:]' '\n' < "$embedded") || return 1
    expected=$(awk '!/^[[:space:]]*#/ && NF' "$persistent") || return 1
    [[ -n "$expected" ]] || return 1
    while IFS= read -r argument; do
        [[ -n "$argument" ]] || continue
        grep -Fx -- "$argument" <<< "$tokens" >/dev/null || return 1
    done < <(printf '%s\n' "$expected" | tr '[:space:]' '\n')
    return 0
}

verify_uki_plymouth_setup() {
    VERIFIED_PLYMOUTH_UKIS=()
    [[ "$UKI_ENABLED" == true ]] || return 0

    local hooks_line hooks_content theme uki_path readable_uki cmdline_file splash_file
    local systemd_index=-1 udev_index=-1 plymouth_index=-1 index hook
    local failed=false
    local -a hooks=()
    local -a uki_paths=()
    local verify_dir

    hooks_line=$(grep '^HOOKS=' /etc/mkinitcpio.conf | head -n 1 || true)
    hooks_content="${hooks_line#HOOKS=(}"
    hooks_content="${hooks_content%)}"
    read -r -a hooks <<< "$hooks_content"
    for index in "${!hooks[@]}"; do
        hook="${hooks[$index]}"
        [[ "$hook" == systemd ]] && systemd_index=$index
        [[ "$hook" == udev ]] && udev_index=$index
        [[ "$hook" == plymouth ]] && plymouth_index=$index
    done
    if ((plymouth_index < 0)); then
        warning "Plymouth is missing from the mkinitcpio hooks."
        failed=true
    elif ((systemd_index >= 0 && plymouth_index < systemd_index)); then
        warning "The Plymouth hook is before systemd; it cannot start correctly in this initramfs."
        failed=true
    elif ((systemd_index < 0 && udev_index >= 0 && plymouth_index < udev_index)); then
        warning "The Plymouth hook is before udev; it cannot start correctly in this initramfs."
        failed=true
    fi

    theme=$(plymouth-set-default-theme 2>/dev/null || true)
    if [[ -z "$theme" ]]; then
        warning "No default Plymouth theme is configured."
        failed=true
    fi

    mapfile -t uki_paths < <(get_configured_uki_paths | sort -u)
    if ((${#uki_paths[@]} == 0)); then
        warning "No configured UKI paths were found for Plymouth verification."
        return 1
    fi

    verify_dir=$(mktemp -d -t poedeploy-uki-verify-XXXXXX)
    for index in "${!uki_paths[@]}"; do
        uki_path="${uki_paths[$index]}"
        if ! sudo test -f "$uki_path"; then
            warning "Configured UKI is missing: $uki_path"
            failed=true
            continue
        fi

        readable_uki="$verify_dir/uki-${index}.efi"
        if ! stage_uki_for_verification "$uki_path" "$readable_uki"; then
            warning "Configured UKI could not be read for verification: $uki_path"
            failed=true
            continue
        fi

        cmdline_file="$verify_dir/cmdline-${index}"
        splash_file="$verify_dir/splash-${index}.bmp"
        if ! extract_uki_section "$readable_uki" .cmdline "$cmdline_file"; then
            warning "Could not extract the UKI kernel command line: $uki_path"
            failed=true
        elif ! tr '\0' ' ' < "$cmdline_file" | grep -E '(^|[[:space:]])splash([[:space:]]|$)' >/dev/null; then
            warning "The generated UKI does not contain the splash kernel option: $uki_path"
            failed=true
        elif ! uki_cmdline_matches_file "$cmdline_file" /etc/kernel/cmdline; then
            warning "Could not verify the persistent kernel arguments in the generated UKI: $uki_path"
            failed=true
        fi
        if [[ -n "$theme" ]] &&
           ! uki_contains_plymouth_theme "$readable_uki" "$theme"; then
            warning "The generated UKI does not contain the selected Plymouth theme '$theme': $uki_path"
            failed=true
        fi
        if ! extract_uki_section "$readable_uki" .splash "$splash_file"; then
            warning "Could not extract the UKI splash image: $uki_path"
            failed=true
        elif [[ -f /usr/share/systemd/bootctl/splash-arch.bmp ]] &&
             cmp -s "$splash_file" /usr/share/systemd/bootctl/splash-arch.bmp; then
            warning "The generated UKI still contains the default Arch firmware splash: $uki_path"
            failed=true
        fi
    done
    rm -rf -- "$verify_dir"

    if [[ "$failed" == true ]]; then
        warning "UKI/Plymouth verification failed. Run the Plymouth section before signing Secure Boot files."
        return 1
    fi
    for uki_path in "${uki_paths[@]}"; do
        uki_path=$(realpath -ms -- "$uki_path") || return 1
        VERIFIED_PLYMOUTH_UKIS["$uki_path"]=true
    done
    success "Verified the Plymouth hook, selected theme, kernel option and generated UKIs."
}

install_poedeploy_plymouth_theme() {
    echo

    info "Checking for the PoeDeploy Plymouth theme..."

    local theme_name="poedeploy"
    local theme_dir="/usr/share/plymouth/themes/$theme_name"
    local temp_dir
    local archive
    local local_archive="${SCRIPT_DIR}/themes/${theme_name}/plymouth/${theme_name}.zip"

    if [[ -d "$theme_dir" ]]; then
        info "Refreshing the installed PoeDeploy theme from the repository archive..."
    fi

    if ! command -v curl >/dev/null 2>&1; then
        warning "curl is unavailable; skipping the PoeDeploy Plymouth theme download."
        return 1
    fi

    if ! command -v unzip >/dev/null 2>&1; then
        warning "unzip is unavailable; skipping the PoeDeploy Plymouth theme download."
        return 1
    fi

    temp_dir=$(mktemp -d -t poedeploy-plymouth-XXXXXX)
    archive="$temp_dir/${theme_name}.zip"

    if [[ -f "$local_archive" ]]; then
        cp "$local_archive" "$archive"
    elif ! curl -fL --silent --show-error \
        --output "$archive" \
        "$POEDEPLOY_PLYMOUTH_THEME_URL"; then

        rm -rf "$temp_dir"

        warning "The PoeDeploy Plymouth theme could not be downloaded."
        warning "Built-in Plymouth themes will still be available."
        return 1
    fi

    if ! unzip -t "$archive" >/dev/null 2>&1; then
        rm -rf "$temp_dir"

        warning "The downloaded Plymouth ZIP archive is invalid."
        warning "Built-in Plymouth themes will still be available."
        return 1
    fi

    local extracted_dir="$temp_dir/extracted"

    mkdir -p "$extracted_dir"

    if ! unzip -q "$archive" -d "$extracted_dir"; then
        rm -rf "$temp_dir"

        warning "Failed to extract the PoeDeploy Plymouth theme."
        return 1
    fi

    local plymouth_file

    plymouth_file=$(
        find "$extracted_dir" \
            -type f \
            -name "${theme_name}.plymouth" \
            -print -quit 2>/dev/null
    )

    if [[ -z "$plymouth_file" ]]; then
        rm -rf "$temp_dir"

        warning "The archive does not contain ${theme_name}.plymouth."
        return 1
    fi

    if ! sudo mkdir -p "$theme_dir" ||
       ! sudo cp -rf "$(dirname "$plymouth_file")/." "$theme_dir/"; then
        rm -rf "$temp_dir"
        warning "Failed to copy the PoeDeploy Plymouth theme into $theme_dir."
        return 1
    fi

    rm -rf "$temp_dir"

    if [[ ! -f "${theme_dir}/${theme_name}.plymouth" ]]; then
        warning "The PoeDeploy theme definition is missing after installation."
        return 1
    fi

    if ! plymouth_theme_is_available "$theme_name"; then
        warning "The files were copied, but Plymouth does not recognise the PoeDeploy theme."
        warning "Expected definition: ${theme_dir}/${theme_name}.plymouth"
        return 1
    fi

    success "PoeDeploy was installed and verified in the Plymouth theme list."
    info "Select it in the upcoming theme selector to activate it."
}

select_plymouth_theme() {
    echo

    local themes=()
    local remote_themes=()
    local current_theme
    local remote_theme_output=""

    mapfile -t themes < <(
        plymouth-set-default-theme -l 2>/dev/null || true
    )

    if remote_theme_output=$(get_remote_plymouth_themes); then
        mapfile -t remote_themes <<< "$remote_theme_output"

        local remote_theme
        for remote_theme in "${remote_themes[@]}"; do
            [[ -n "$remote_theme" ]] || continue

            if ! printf '%s\n' "${themes[@]}" | grep -Fxq "$remote_theme"; then
                themes+=("$remote_theme")
            fi
        done
    else
        warning "Repository Plymouth themes could not be retrieved."
    fi

    if [[ ${#themes[@]} -eq 0 ]]; then
        warning "No Plymouth themes were detected."
        return 1
    fi

    current_theme=$(plymouth-set-default-theme 2>/dev/null || true)

    echo "========================================"
    echo "        PLYMOUTH THEME"
    echo "========================================"
    echo
    echo "Current theme: ${current_theme:-unknown}"
    echo
    echo "Available themes:"
    echo
    echo "  [0] None / Keep current theme"

    local i=1

    for theme in "${themes[@]}"; do
        if printf '%s\n' "${remote_themes[@]}" | grep -Fxq "$theme"; then
            echo "  [$i] $theme (repository)"
        else
            echo "  [$i] $theme"
        fi

        ((i += 1))
    done

    echo

    while true; do
        if ! read -rp "Select a theme [0-${#themes[@]}]: " choice; then
            warning "Theme selection cancelled before rebuilding boot images."
            return 1
        fi

        if [[ "$choice" == "0" ]]; then
            info "Keeping current Plymouth theme."
            return
        fi

        if [[ "$choice" =~ ^[0-9]+$ ]] &&
            (( choice >= 1 && choice <= ${#themes[@]} )); then

            local selected_theme="${themes[$((choice - 1))]}"

            info "Applying Plymouth theme: $selected_theme"

            if printf '%s\n' "${remote_themes[@]}" | grep -Fxq "$selected_theme" &&
               ! plymouth_theme_is_available "$selected_theme"; then
                if ! install_remote_plymouth_theme "$selected_theme"; then
                    warning "Failed to install repository theme '$selected_theme'."
                    return 1
                fi
            fi

            if ! sudo plymouth-set-default-theme "$selected_theme"; then
                warning "Failed to set Plymouth theme '$selected_theme'."
                return 1
            fi
            return 0
        fi

        warning "Invalid selection."
    done
}

setup_plymouth() {

    install_plymouth || return 1

    if [[ "$UKI_ENABLED" == true ]]; then
        if ! install_uki_black_splash; then
            warning "Plymouth setup stopped because the UKI splash could not be installed."
            return 1
        fi

        if ! prepare_uki_kernel_cmdline; then
            warning "Plymouth setup stopped because the UKI kernel command line could not be prepared."
            return 1
        fi
    fi

    configure_mkinitcpio_plymouth || return 1

    configure_bootloader_plymouth || return 1

    install_poedeploy_plymouth_theme || return 1

    select_plymouth_theme || return 1
    configure_uki_splash || return 1

    info "Rebuilding initramfs and any configured UKIs with the selected theme..."
    if ! sudo mkinitcpio -P; then
        warning "Plymouth setup failed: boot image rebuild failed. Resolve this before rebooting."
        return 1
    fi
    BOOT_IMAGE_ACTION="rebuilt for Plymouth; signatures checked separately"

    local verification_failed=false
    if ! verify_uki_plymouth_setup; then
        warning "Plymouth setup failed: the rebuilt UKI did not pass theme verification."
        verification_failed=true
    fi
    if ! verify_secure_boot_after_uki_rebuild; then
        warning "Do not reboot with Secure Boot enabled until the UKI signature is verified."
        verification_failed=true
    fi
    [[ "$verification_failed" == false ]] || return 1
    success "Plymouth theme configured and rebuilt boot images verified."

}

# ============================================================

# 10. TIMESHIFT

# ============================================================

check_timeshift() {

    echo

    if pacman -Q timeshift &>/dev/null; then

        success "Timeshift is already installed."

        return

    fi

    info "Installing Timeshift..."

    sudo pacman -S --needed --noconfirm timeshift

    success "Timeshift installed."

    if [[ "$ROOT_FILESYSTEM" == "btrfs" ]]; then

        info "Btrfs detected."

        info "Timeshift can use native Btrfs snapshots when the"

        info "root layout uses @ and @home subvolumes."

    else

        info "Non-Btrfs filesystem detected."

        info "Timeshift can use rsync snapshot mode."

    fi

}

# ============================================================

# 11. SYSTEM SUMMARY

# ============================================================

HYPRLAND_STATUS="not checked"
SDDM_STATUS="not checked"
SDDM_ACTIVE_STATUS="not checked"
SDDM_THEME_STATUS="not checked"

HYPRLAND_INITIAL_STATUS="not checked"
SDDM_INITIAL_STATUS="not checked"
SDDM_ACTIVE_INITIAL_STATUS="not checked"
SDDM_THEME_INITIAL_STATUS="not checked"

ML4W_ACTION="not run"
SDDM_ACTION="not run"
APPLICATIONS_ACTION="not selected"
NETWORK_SHARES_ACTION="not selected"
SMB_ACTION="not selected"
NFS_ACTION="not selected"

check_graphical_environment() {
    info "Checking graphical environment..."

    if pacman -Q hyprland &>/dev/null; then
        HYPRLAND_STATUS="installed"
    else
        HYPRLAND_STATUS="not installed"
    fi

    if pacman -Q sddm &>/dev/null; then
        if systemctl is-enabled --quiet sddm; then
            SDDM_STATUS="enabled for next boot"
        else
            SDDM_STATUS="installed, not enabled"
        fi

        if systemctl is-active --quiet sddm; then
            SDDM_ACTIVE_STATUS="active"
        else
            SDDM_ACTIVE_STATUS="inactive"
        fi
    else
        SDDM_STATUS="not installed"
        SDDM_ACTIVE_STATUS="not installed"
    fi

    if [[ -d /usr/share/sddm/themes/ml4w ]]; then
        SDDM_THEME_STATUS="installed"
    else
        SDDM_THEME_STATUS="not installed"
    fi

    success "Graphical environment checked."
}

save_initial_graphical_status() {
    HYPRLAND_INITIAL_STATUS="$HYPRLAND_STATUS"
    SDDM_INITIAL_STATUS="$SDDM_STATUS"
    SDDM_ACTIVE_INITIAL_STATUS="$SDDM_ACTIVE_STATUS"
    SDDM_THEME_INITIAL_STATUS="$SDDM_THEME_STATUS"
}

format_status_change() {
    local current="$1"
    local initial="$2"

    if [[ "$initial" != "not checked" && "$current" != "$initial" ]]; then
        printf '%s (was %s)' "$current" "$initial"
    else
        printf '%s' "$current"
    fi
}

show_summary() {

    echo

    echo "========================================"

    echo "          SYSTEM ASSESSMENT"

    echo "========================================"

    echo

    echo "OS:              Arch Linux"

    echo "Version:         $SCRIPT_VERSION"

    echo "GPU:             $GPU_VENDOR"

    echo "GPU model:       $GPU_MODEL"

    echo "Bootloader:      $BOOTLOADER"

    echo "UKI:             $UKI_STATUS"

    echo "Root filesystem: $ROOT_FILESYSTEM"

    echo

    if command -v yay &>/dev/null; then

        echo "yay:             installed"

    else

        echo "yay:             missing"

    fi

    if pacman -Q plymouth &>/dev/null; then

        echo "Plymouth:        installed"

    else

        echo "Plymouth:        missing"

    fi

    if pacman -Q timeshift &>/dev/null; then

        echo "Timeshift:       installed"

    else

        echo "Timeshift:       not installed"

    fi

    if systemctl is-active NetworkManager &>/dev/null; then

        echo "NetworkManager:  active"

    else

        echo "NetworkManager:  inactive"

    fi

    printf "%-16s %s\n" "Hyprland:" "$HYPRLAND_STATUS"
    printf "%-16s %s\n" "SDDM:" "$SDDM_STATUS"
    printf "%-16s %s\n" "SDDM now:" "$SDDM_ACTIVE_STATUS"
    printf "%-16s %s\n" "ML4W SDDM theme:" "$SDDM_THEME_STATUS"

    echo

}

# ============================================================

# 12. ML4W

# ============================================================

install_ml4w() {
    echo
    echo "========================================"
    echo "          ML4W INSTALLATION"
    echo "========================================"
    echo

    read -rp "Install ML4W Hyprland? [Y/n]: " answer

    if [[ -n "$answer" && ! "$answer" =~ ^[Yy]$ ]]; then
        info "ML4W installation skipped."
        ML4W_ENABLED=false
        ML4W_ACTION="skipped"
    else
        ML4W_ENABLED=true

        echo
        info "Starting ML4W installer..."
        echo

        if ! bash <(curl -fsSL "$ML4W_URL"); then
            warning "ML4W installer returned a failure."
            warning "Continuing with the rest of the Arch setup."
            ML4W_ACTION="installation failed"
        else
            success "ML4W installer finished."
            ML4W_ACTION="installed successfully"
        fi
    fi

}

choose_sddm_setup() {
    local answer
    read -rp "Install and configure SDDM graphical login? [Y/n]: " answer
    if [[ -n "$answer" && ! "$answer" =~ ^[Yy]$ ]]; then
        CONFIGURE_ML4W_SDDM=false
        SDDM_ACTION="skipped"
        return 0
    fi

    CONFIGURE_ML4W_SDDM=true
    read -rp "Use the ML4W SDDM theme? [Y/n]: " answer
    if [[ -z "$answer" || "$answer" =~ ^[Yy]$ ]]; then
        ML4W_ENABLED=true
        ensure_command_dependencies git:git
    else
        ML4W_ENABLED=false
    fi
    setup_sddm
}

# ============================================================

# 13. SDDM / GRAPHICAL LOGIN

# ============================================================

setup_sddm() {
    if [[ "$CONFIGURE_ML4W_SDDM" != true ]]; then
        info "SDDM configuration was skipped by the user."
        return 0
    fi

    echo
    echo "========================================"
    echo "       GRAPHICAL LOGIN (SDDM)"
    echo "========================================"
    echo

    if pacman -Q sddm &>/dev/null; then
        success "SDDM is already installed."
    else
        info "Installing SDDM and required Qt components..."

        if sudo pacman -S --needed --noconfirm \
            sddm \
            qt6-svg \
            qt6-virtualkeyboard \
            qt6-multimedia-ffmpeg; then
            success "SDDM installed successfully."
        else
            warning "Failed to install SDDM."
            SDDM_ACTION="installation failed"
            return 0
        fi
    fi

    local conflicting_dms=(gdm lightdm lxdm xdm mdm slim wdm)

    for dm in "${conflicting_dms[@]}"; do
        if systemctl is-enabled --quiet "$dm" 2>/dev/null; then
            info "Disabling conflicting display manager: $dm"
            sudo systemctl disable "$dm" ||
                warning "Could not disable $dm."
        fi
    done

    if systemctl is-enabled --quiet sddm; then
        success "SDDM service is already enabled."
    else
        info "Enabling SDDM service for the next boot..."

        if sudo systemctl enable sddm; then
            success "SDDM service enabled for the next boot."
        else
            warning "Failed to enable SDDM."
            SDDM_ACTION="enable failed"
            return 0
        fi
    fi

    if [[ "$ML4W_ENABLED" == true ]]; then
        local theme_dir="/usr/share/sddm/themes/ml4w"
        local sddm_config_dir="/etc/sddm.conf.d"
        local sddm_config="${sddm_config_dir}/poedeploy.conf"
        local temp_dir

        if [[ -d "$theme_dir" ]]; then
            success "ML4W SDDM theme is already installed."
        else
            info "ML4W SDDM theme is not installed."
            info "Downloading the official ML4W SDDM theme..."

            temp_dir=$(mktemp -d -t ml4w-sddm-XXXXXX)

            if git clone --depth 1 \
                https://github.com/mylinuxforwork/ml4w-sddm \
                "$temp_dir/ml4w-sddm"; then

                sudo mkdir -p "$theme_dir"
                sudo cp -rf "$temp_dir/ml4w-sddm/." "$theme_dir/"
                rm -rf "$temp_dir"
                success "ML4W SDDM theme installed."
            else
                rm -rf "$temp_dir"
                warning "Failed to download the ML4W SDDM theme."
                SDDM_ACTION="configured without ML4W theme"
            fi
        fi

        if [[ -d "$theme_dir" ]]; then
            info "Checking SDDM configuration..."

            sudo mkdir -p "$sddm_config_dir"

            if [[ -f "$sddm_config" ]]; then
                sudo cp -n "$sddm_config" "${sddm_config}.bak" 2>/dev/null || true
            fi

            if ! printf '%s\n' \
                '[Theme]' \
                'Current=ml4w' \
                '' \
                '[General]' \
                'InputMethod=qtvirtualkeyboard' \
                'GreeterEnvironment=QML2_IMPORT_PATH=/usr/share/sddm/themes/ml4w/components/,QT_IM_MODULE=qtvirtualkeyboard' |
                sudo tee "$sddm_config" >/dev/null; then
                warning "Failed to write the PoeDeploy SDDM configuration."
                SDDM_ACTION="configuration failed"
                return 0
            fi

            success "ML4W SDDM theme configured."
        fi
    fi

    SDDM_ACTION="configured"
}
# ============================================================

# 14. APPLICATION MENU

# ============================================================

declare -A APPLICATIONS=(

    ["Firefox"]="firefox"

    ["LocalSend"]="localsend"

    ["VLC"]="vlc"

    ["Visual Studio Code"]="visual-studio-code-bin"

    ["7-Zip"]="7zip"

    ["Discord"]="discord"

    ["GIMP"]="gimp"

    ["LibreOffice"]="libreoffice-fresh"

    ["PowerTOP"]="powertop"

    ["Tailscale"]="tailscale"

    ["Thunderbird"]="thunderbird"

    ["Spotify"]="spotify-launcher"

    ["OBS Studio"]="obs-studio"

)

select_applications() {

    if ! command -v gum &>/dev/null; then

        info "Installing gum for the application selector..."

        wait_for_pacman_lock
        sudo pacman -S --needed --noconfirm gum

    fi

    echo

    echo "========================================"

    echo "       APPLICATION SELECTION"

    echo "========================================"

    echo

    echo "Use arrow keys to navigate."

    echo "Press x to select or deselect an application."

    echo "Press Enter when finished, or Esc/Ctrl+C to skip application selection."

    if [[ "$RUN_MODE" == full ]]; then
        echo "All applications start selected."
    else
        echo "No applications start selected; choose only the ones you want to install."
    fi

    echo

    local app selection selection_defaults=""
    local options=()
    SELECTED_APPS=()
    SELECTED_PACKAGES=()

    if [[ "$RUN_MODE" == full ]]; then
        selection_defaults='*'
    fi

    for app in "${!APPLICATIONS[@]}"; do

        options+=("$app")

    done

    mapfile -t options < <(

        printf '%s\n' "${options[@]}" | sort

    )

    if ! selection=$(printf '%s\n' "${options[@]}" |
        choose_checklist "Select applications" "$selection_defaults"); then
        info "Application selection cancelled; skipping optional applications."
        APPLICATIONS_ACTION="selection cancelled"
        return 0
    fi
    if [[ -n "$selection" ]]; then
        mapfile -t SELECTED_APPS <<< "$selection"
    fi

    if [[ ${#SELECTED_APPS[@]} -eq 0 ||
          ( ${#SELECTED_APPS[@]} -eq 1 && -z "${SELECTED_APPS[0]}" ) ]]; then
        info "No optional applications selected."
        SELECTED_APPS=()
        SELECTED_PACKAGES=()
        APPLICATIONS_ACTION="none selected"
        return 0
    fi

    SELECTED_PACKAGES=()

    for app in "${SELECTED_APPS[@]}"; do

        [[ -n "$app" ]] || continue

        SELECTED_PACKAGES+=("${APPLICATIONS[$app]}")

        if [[ "${APPLICATIONS[$app]}" == "vlc" ]]; then

            SELECTED_PACKAGES+=("vlc-plugins-all")

        fi

    done

    echo

    if [[ ${#SELECTED_PACKAGES[@]} -eq 0 ]]; then
        info "No optional applications selected."
        APPLICATIONS_ACTION="none selected"
    else
        info "Selected applications:"
        printf '  - %s\n' "${SELECTED_APPS[@]}"
        APPLICATIONS_ACTION="selected packages processed"
    fi

}

# ============================================================

# 15. APPLICATION INSTALLATION

# ============================================================

package_was_skipped() {
    local skipped
    for skipped in "${SKIPPED_PACKAGES[@]}"; do
        [[ "$skipped" != "$1" ]] || return 0
    done
    return 1
}

install_optional_package() {
    local package="$1"
    shift
    local previous_int_trap interrupted status choice

    while true; do
        wait_for_pacman_lock
        info "Installing $package. Press Ctrl+C to cancel this package and choose what to do next."

        previous_int_trap=$(trap -p INT)
        interrupted=false
        # Keep the package manager in the foreground so it and its build children
        # receive the terminal's Ctrl+C. Bash waits for it to exit before this trap
        # is handled; never kill -9 a package transaction or unlink its lock here.
        trap 'interrupted=true' INT
        if "$@"; then
            status=0
        else
            status=$?
        fi
        if [[ -n "$previous_int_trap" ]]; then
            eval "$previous_int_trap"
        else
            trap - INT
        fi

        if [[ "$interrupted" == true ]] || ((status == 130)); then
            warning "$package was interrupted. The package command has exited."
            info "Already installed dependencies are kept; skipping does not uninstall or roll back files."
            while true; do
                if ! read -rp "[s] Skip this package, [r] Retry, [q] Quit PoeDeploy [s]: " choice; then
                    exit 130
                fi
                case "${choice,,}" in
                    s|skip|"")
                        SKIPPED_PACKAGES+=("$package")
                        warning "Skipped $package; select it in Applications on a later run."
                        return 0
                        ;;
                    r|retry) break ;;
                    q|quit) info "PoeDeploy stopped at your request."; exit 130 ;;
                    *) warning "Choose skip, retry or quit." ;;
                esac
            done
            continue
        fi

        if ((status == 0)); then
            INSTALLED_PACKAGES+=("$package")
            success "$package installed successfully."
        else
            FAILED_PACKAGES+=("$package")
            warning "Failed to install $package (exit code $status)."
        fi
        return 0
    done
}

install_selected_applications() {
    local package
    if ((${#SELECTED_PACKAGES[@]} == 0)); then
        return 0
    fi

    for package in "${SELECTED_PACKAGES[@]}"; do
        if [[ "$package" == vlc-plugins-all ]] && package_was_skipped vlc; then
            SKIPPED_PACKAGES+=("$package")
            info "Skipping VLC plugins because VLC was skipped."
            continue
        fi
        if pacman -Q "$package" &>/dev/null; then
            INSTALLED_PACKAGES+=("$package")
            success "$package is already installed."
            continue
        fi

        if pacman -Si "$package" &>/dev/null; then
            install_optional_package "$package" sudo pacman -S --needed --noconfirm "$package"
        else
            if ! command -v yay >/dev/null 2>&1; then
                info "$package needs an AUR helper; installing yay as a dependency."
                install_yay
            fi
            if yay -Si "$package" &>/dev/null; then
                install_optional_package "$package" yay -S --needed --noconfirm "$package"
            else
                warning "Package not found: $package"
                FAILED_PACKAGES+=("$package")
            fi
        fi
    done
    APPLICATIONS_ACTION="${#INSTALLED_PACKAGES[@]} installed/already present; ${#SKIPPED_PACKAGES[@]} skipped; ${#FAILED_PACKAGES[@]} failed"
}

select_default_browser() {

    echo
    echo "========================================"
    echo "       DEFAULT WEB BROWSER"
    echo "========================================"
    echo

    local browser_entries=(
        "Firefox|firefox.desktop|firefox"
        "Chromium|chromium.desktop|chromium"
        "Google Chrome|google-chrome.desktop|google-chrome-stable"
        "Brave|brave-browser.desktop|brave-browser"
        "LibreWolf|librewolf.desktop|librewolf"
        "Vivaldi|vivaldi-stable.desktop|vivaldi"
        "Zen Browser|zen.desktop|zen-browser"
    )
    local browser_names=()
    local browser_desktops=()
    local entry name desktop command_name

    for entry in "${browser_entries[@]}"; do
        IFS='|' read -r name desktop command_name <<< "$entry"

        if command -v "$command_name" >/dev/null 2>&1; then
            browser_names+=("$name")
            browser_desktops+=("$desktop")
        fi
    done

    if [[ ${#browser_names[@]} -eq 0 ]]; then
        info "No supported web browser is currently installed."
        DEFAULT_BROWSER_ACTION="no supported browser installed"
        return 0
    fi

    echo "  [0] Keep the current default"

    local i
    for i in "${!browser_names[@]}"; do
        echo "  [$((i + 1))] ${browser_names[$i]}"
    done

    local choice
    while true; do
        read -rp "Select the default browser [0-${#browser_names[@]}]: " choice

        if [[ "$choice" == "0" || -z "$choice" ]]; then
            info "Keeping the current default browser."
            DEFAULT_BROWSER_ACTION="kept current default"
            return 0
        fi

        if [[ "$choice" =~ ^[0-9]+$ ]] &&
           (( choice >= 1 && choice <= ${#browser_names[@]} )); then
            break
        fi

        warning "Invalid selection."
    done

    local selected_index=$((choice - 1))
    local selected_name="${browser_names[$selected_index]}"
    local selected_desktop="${browser_desktops[$selected_index]}"

    if xdg-settings set default-web-browser "$selected_desktop" &&
       xdg-mime default "$selected_desktop" x-scheme-handler/http &&
       xdg-mime default "$selected_desktop" x-scheme-handler/https &&
       xdg-mime default "$selected_desktop" text/html; then
        success "Default browser set to $selected_name."
        DEFAULT_BROWSER_ACTION="$selected_name"
    else
        warning "The default browser could not be fully configured."
        DEFAULT_BROWSER_ACTION="configuration failed"
    fi
}

# ============================================================

# 16. SMB / NFS NETWORK SHARES

# ============================================================

validate_mountpoint() {

    local mountpoint="$1"

    if [[ -z "$mountpoint" ]]; then

        warning "Mount point cannot be empty."

        return 1

    fi

    if [[ "$mountpoint" != /* ]]; then

        warning "Mount point must be an absolute path."

        return 1

    fi

    if [[ "$mountpoint" =~ [[:space:]#] ]]; then

        warning "Mount points containing whitespace or # are not supported."

        return 1

    fi

    return 0

}

validate_fstab_value() {

    local label="$1"
    local value="$2"

    if [[ "$value" =~ [[:space:]#] ]]; then
        warning "$label cannot contain whitespace or #."
        return 1
    fi

    return 0
}

fstab_has_mountpoint() {

    local mountpoint="$1"

    awk -v target="$mountpoint" '
        $0 !~ /^[[:space:]]*#/ && NF >= 2 && $2 == target { found = 1 }
        END { exit !found }
    ' /etc/fstab
}



# ============================================================

# 16.1 SMB / NFS Require Input Function

# ============================================================

require_input() {

    local prompt="$1"

    local value

    local retry

    while true; do

        read -rp "$prompt" value

        # Trim leading and trailing whitespace

        value="${value#"${value%%[![:space:]]*}"}"

        value="${value%"${value##*[![:space:]]}"}"

        if [[ -n "$value" ]]; then

            REPLY="$value"

            return 0

        fi

        warning "This field cannot be empty."

        read -rp "Try again? [Y/n]: " retry

        if [[ -n "$retry" && ! "$retry" =~ ^[Yy]$ ]]; then

            return 1

        fi

    done

}

setup_smb_share() {

    echo

    echo "========================================"

    echo "           SMB SHARE SETUP"

    echo "========================================"

    echo

    SMB_ACTION="selected"

    local server share username password domain mountpoint credentials_file fstab_line

    if ! require_input "SMB server IP/hostname: "; then
        info "SMB setup cancelled."
        SMB_ACTION="cancelled"
        return 0
    fi
    server="$REPLY"

    if ! require_input "SMB share name: "; then
        info "SMB setup cancelled."
        SMB_ACTION="cancelled"
        return 0
    fi
    share="$REPLY"

    if ! validate_fstab_value "SMB server" "$server" ||
       ! validate_fstab_value "SMB share name" "$share"; then
        SMB_ACTION="failed"
        return 0
    fi

    if ! require_input "SMB username: "; then
        info "SMB setup cancelled."
        SMB_ACTION="cancelled"
        return 0
    fi
    username="$REPLY"

    while true; do
        read -rsp "SMB password: " password
        echo

        if [[ -n "$password" ]]; then
            break
        fi

        warning "Password cannot be empty."

        read -rp "Try again? [Y/n]: " retry

        if [[ -n "$retry" && ! "$retry" =~ ^[Yy]$ ]]; then
            info "SMB setup cancelled."
            SMB_ACTION="cancelled"
            return 0
        fi
    done

    read -rp "SMB domain/workgroup (optional): " domain

    if ! require_input "Local mount point (for example /mnt/SMB): "; then
        info "SMB setup cancelled."
        SMB_ACTION="cancelled"
        return 0
    fi
    mountpoint="$REPLY"

    if ! validate_mountpoint "$mountpoint"; then
        warning "SMB setup failed because the mount point is invalid."
        SMB_ACTION="failed"
        return 0
    fi

    if ! sudo mkdir -p "$mountpoint" /etc/samba/credentials; then
        warning "Failed to create the SMB mount point or credentials directory."
        SMB_ACTION="failed"
        return 0
    fi

    local safe_name
    safe_name=$(printf '%s_%s' "$server" "$share" |
        tr '/: ' '___' |
        tr -cd '[:alnum:]_.-')

    credentials_file="/etc/samba/credentials/$safe_name"

    if ! {
        printf 'username=%s\n' "$username"
        printf 'password=%s\n' "$password"
        if [[ -n "$domain" ]]; then
            printf 'domain=%s\n' "$domain"
        fi
    } | sudo tee "$credentials_file" >/dev/null; then
        warning "Failed to create the SMB credentials file."
        SMB_ACTION="failed"
        return 0
    fi

    sudo chmod 600 "$credentials_file" || {
        warning "Failed to secure the SMB credentials file."
        SMB_ACTION="failed"
        return 0
    }

    fstab_line="//${server}/${share} ${mountpoint} cifs credentials=${credentials_file},vers=3.1.1,_netdev,x-systemd.automount,nofail,uid=$(id -u),gid=$(id -g),file_mode=0664,dir_mode=0775 0 0"

    if fstab_has_mountpoint "$mountpoint"; then
        warning "An /etc/fstab entry already references $mountpoint."
        warning "Skipping duplicate SMB entry."
    else
        if echo "$fstab_line" | sudo tee -a /etc/fstab >/dev/null; then
            success "SMB entry added to /etc/fstab."
        else
            warning "Failed to add SMB entry to /etc/fstab."
            SMB_ACTION="failed"
            return 0
        fi
    fi

    sudo systemctl daemon-reload

    info "Testing SMB mount..."

    if sudo mount "$mountpoint"; then
        success "SMB share mounted successfully at $mountpoint."
        SMB_ACTION="configured successfully"
    else
        warning "SMB share could not be mounted right now."
        warning "The credentials and fstab entry were still created."
        warning "Check the server, share name, credentials and network."
        SMB_ACTION="configured, mount test failed"
    fi

}

setup_nfs_share() {

    echo

    echo "========================================"

    echo "           NFS SHARE SETUP"

    echo "========================================"

    echo

    NFS_ACTION="selected"

    local server export_path mountpoint fstab_line

    if ! require_input "NFS server IP/hostname: "; then
        info "NFS setup cancelled."
        NFS_ACTION="cancelled"
        return 0
    fi
    server="$REPLY"

    if ! require_input "NFS export path: "; then
        info "NFS setup cancelled."
        NFS_ACTION="cancelled"
        return 0
    fi
    export_path="$REPLY"

    if ! validate_fstab_value "NFS server" "$server" ||
       ! validate_fstab_value "NFS export path" "$export_path"; then
        NFS_ACTION="failed"
        return 0
    fi

    if ! require_input "Local mount point (for example /mnt/NFS): "; then
        info "NFS setup cancelled."
        NFS_ACTION="cancelled"
        return 0

    fi
    mountpoint="$REPLY"

    if ! validate_mountpoint "$mountpoint"; then
        warning "NFS setup failed because the mount point is invalid."
        NFS_ACTION="failed"
        return 0
    fi

    if ! sudo mkdir -p "$mountpoint"; then
        warning "Failed to create the NFS mount point."
        NFS_ACTION="failed"
        return 0
    fi

    fstab_line="${server}:${export_path} ${mountpoint} nfs defaults,_netdev,x-systemd.automount,nofail 0 0"

    if fstab_has_mountpoint "$mountpoint"; then
        warning "An /etc/fstab entry already references $mountpoint."
        warning "Skipping duplicate NFS entry."
    else
        if echo "$fstab_line" | sudo tee -a /etc/fstab >/dev/null; then
            success "NFS entry added to /etc/fstab."
        else
            warning "Failed to add NFS entry to /etc/fstab."
            NFS_ACTION="failed"
            return 0
        fi
    fi

    sudo systemctl daemon-reload

    info "Testing NFS mount..."

    if sudo mount "$mountpoint"; then
        success "NFS share mounted successfully at $mountpoint."
        NFS_ACTION="configured successfully"
    else
        warning "NFS share could not be mounted right now."
        warning "The fstab entry was still created."
        warning "Check the server, export path, NFS version and network."
        NFS_ACTION="configured, mount test failed"
    fi

}

configure_network_shares() {
    echo
    echo "========================================"
    echo "         NETWORK SHARE SETUP"
    echo "========================================"
    echo

    echo "Choose which network shares to configure:"
    echo
    echo "  [0] None"
    echo "  [1] SMB only"
    echo "  [2] NFS only"
    echo "  [3] SMB and NFS"
    echo

    local choice

    SMB_ACTION="not selected"
    NFS_ACTION="not selected"
    NETWORK_SHARES_ACTION="not selected"

    while true; do
        read -rp "Select an option [0-3]: " choice

        case "$choice" in
            0|"")
                info "Network share setup skipped."
                NETWORK_SHARES_ACTION="skipped"
                return 0
                ;;
            1)
                ensure_command_dependencies mount.cifs:cifs-utils
                setup_smb_share
                NETWORK_SHARES_ACTION="completed"
                return 0
                ;;
            2)
                ensure_command_dependencies mount.nfs:nfs-utils
                setup_nfs_share
                NETWORK_SHARES_ACTION="completed"
                return 0
                ;;
            3)
                ensure_command_dependencies mount.cifs:cifs-utils mount.nfs:nfs-utils
                setup_smb_share
                setup_nfs_share
                NETWORK_SHARES_ACTION="completed"
                return 0
                ;;
            *)
                warning "Invalid choice. Please select 0, 1, 2 or 3."
                ;;
        esac
    done
}

# ============================================================

# 17. TAILSCALE

# ============================================================

configure_tailscale() {

    if package_was_skipped tailscale; then
        info "Tailscale service setup skipped because its app installation was cancelled."
        return 0
    fi
    if [[ "$RUN_MODE" == full && ! " ${SELECTED_PACKAGES[*]} " =~ " tailscale " ]]; then
        return 0
    fi

    echo

    info "Configuring Tailscale..."

    if pacman -Q tailscale &>/dev/null; then

        success "Tailscale package is installed."

    else

        info "Installing Tailscale..."

        if sudo pacman -S --needed --noconfirm tailscale; then

            success "Tailscale installed."

        else

            warning "Failed to install Tailscale."

            FAILED_PACKAGES+=("tailscale")

            return

        fi

    fi

    if systemctl is-enabled tailscaled &>/dev/null; then

        success "Tailscale service is already enabled."

    else

        info "Enabling Tailscale service..."

        if sudo systemctl enable tailscaled; then

            success "Tailscale service enabled."

        else

            warning "Failed to enable tailscaled."

            FAILED_PACKAGES+=("tailscaled-service")

            return

        fi

    fi

    if systemctl is-active tailscaled &>/dev/null; then

        success "Tailscale service is already running."

    else

        info "Starting Tailscale service..."

        if sudo systemctl start tailscaled; then

            success "Tailscale service started."

        else

            warning "Failed to start tailscaled."

            FAILED_PACKAGES+=("tailscaled-service")

            return

        fi

    fi

    echo

    info "Tailscale is installed and running."

    warning "This machine has not been authenticated with Tailscale."

    echo

    echo "Run the following command when you are ready:"

    echo

    echo "    sudo tailscale up"

    echo

}

# ============================================================

# 18. OPTIONAL SECURE BOOT

# ============================================================

setup_secure_boot() {

    echo
    echo "========================================"
    echo "       OPTIONAL SECURE BOOT"
    echo "========================================"
    echo

    read -rp "Configure Secure Boot with sbctl? [y/N]: " answer

    if [[ -z "$answer" || ! "$answer" =~ ^[Yy]$ ]]; then
        info "Secure Boot configuration skipped."
        SECURE_BOOT_ACTION="skipped"
        return 0
    fi

    if [[ ! -d /sys/firmware/efi ]]; then
        info "The system was not booted in UEFI mode; Secure Boot setup is unavailable."
        SECURE_BOOT_ACTION="not available (non-UEFI boot)"
        return 0
    fi

    if [[ "$BOOTLOADER" != "systemd-boot" ]]; then
        warning "Automated Secure Boot setup currently supports systemd-boot only."
        SECURE_BOOT_ACTION="not available for $BOOTLOADER"
        return 0
    fi

    if [[ "$UKI_ENABLED" != true ]]; then
        warning "No mkinitcpio UKI preset was detected; Secure Boot setup will not continue."
        SECURE_BOOT_ACTION="unavailable (UKI not configured)"
        return 0
    fi

    if [[ "$UKI_BOOTED" != true ]]; then
        warning "The configured UKI has not been verified as the current boot."
        warning "Reboot through the UKI entry and run PoeDeploy again before configuring Secure Boot."
        SECURE_BOOT_ACTION="waiting for verified UKI boot"
        return 0
    fi

    ensure_command_dependencies mkinitcpio:mkinitcpio

    if ! pacman -Q sbctl &>/dev/null; then
        info "Installing sbctl..."

        if ! sudo pacman -S --needed --noconfirm sbctl; then
            warning "sbctl could not be installed."
            SECURE_BOOT_ACTION="sbctl installation failed"
            return 0
        fi
    fi

    local status_output
    status_output=$(LC_ALL=C sudo sbctl status 2>&1 || true)
    printf '%s\n' "$status_output"

    local setup_mode=false
    local keys_exist=false
    local created_keys=false

    if grep -Eq 'Setup Mode:.*Enabled' <<< "$status_output"; then
        setup_mode=true
    fi

    if sudo test -d /var/lib/sbctl/keys ||
       sudo test -d /usr/share/secureboot/keys; then
        keys_exist=true
    fi

    if [[ "$keys_exist" != true ]]; then
        echo
        warning "Creating Secure Boot keys changes the trust configuration used by this machine."
        warning "Do not continue unless you understand how to recover through the firmware setup."
        read -rp "Type CREATE to create new Secure Boot keys: " create_confirmation

        if [[ "$create_confirmation" != "CREATE" ]]; then
            info "Secure Boot key creation cancelled."
            SECURE_BOOT_ACTION="cancelled before key creation"
            return 0
        fi

        if ! sudo sbctl create-keys; then
            warning "Secure Boot key creation failed."
            SECURE_BOOT_ACTION="key creation failed"
            return 0
        fi

        keys_exist=true
        created_keys=true
    else
        success "Existing sbctl keys detected; no new keys will be created."
    fi

    status_output=$(LC_ALL=C sudo sbctl status 2>&1 || true)

    if grep -Eq 'Setup Mode:.*Enabled' <<< "$status_output"; then
        setup_mode=true
    else
        setup_mode=false
    fi

    if [[ "$setup_mode" == true ]]; then
        echo
        warning "The next step writes Secure Boot keys to firmware variables."
        warning "Microsoft certificates will be retained for Windows and signed option ROM compatibility."
        read -rp "Type ENROLL to enrol the keys with Microsoft certificates: " enroll_confirmation

        if [[ "$enroll_confirmation" != "ENROLL" ]]; then
            info "Firmware key enrollment cancelled. No EFI files will be signed."
            SECURE_BOOT_ACTION="cancelled before enrollment"
            return 0
        fi

        if ! sudo sbctl enroll-keys --microsoft; then
            warning "Secure Boot key enrollment failed."
            SECURE_BOOT_ACTION="key enrollment failed"
            return 0
        fi
    else
        warning "Firmware Setup Mode is not enabled; PoeDeploy will not attempt key enrollment."

        if [[ "$created_keys" == true ]]; then
            warning "The new keys are not enrolled, so PoeDeploy will not sign the boot chain with them."
            SECURE_BOOT_ACTION="keys created but not enrolled"
            return 0
        fi

        warning "Existing key files alone do not prove that these keys are enrolled in firmware."
        local enrolled_confirmation
        read -rp "Have these exact sbctl keys already been enrolled in this machine? [y/N]: " enrolled_confirmation
        if [[ ! "$enrolled_confirmation" =~ ^[Yy]$ ]]; then
            SECURE_BOOT_ACTION="keys created but not enrolled"
            return 0
        fi
    fi

    echo
    warning "Signing replaces or adds signatures on the systemd-boot and UKI files listed below."
    read -rp "Type SIGN to build and sign the boot chain: " sign_confirmation

    if [[ "$sign_confirmation" != "SIGN" ]]; then
        info "Secure Boot signing cancelled."
        SECURE_BOOT_ACTION="cancelled before signing"
        return 0
    fi

    info "Building all configured initramfs images and UKIs before signing..."

    if ! sudo mkinitcpio -P; then
        warning "UKI generation failed; Secure Boot signing was stopped."
        SECURE_BOOT_ACTION="UKI build failed"
        return 0
    fi

    if ! verify_uki_plymouth_setup; then
        warning "Secure Boot signing stopped because Plymouth is not correctly embedded in the UKI."
        warning "Rerun PoeDeploy and select Plymouth and Secure Boot together."
        SECURE_BOOT_ACTION="Plymouth/UKI verification failed"
        return 0
    fi

    local efi_files=()
    local -A seen_efi_files=()
    local search_root efi_file
    local identified_loaders

    if ! identified_loaders=$(get_systemd_boot_files); then
        warning "Secure Boot signing stopped: systemd-boot files could not be identified."
        SECURE_BOOT_ACTION="boot loader discovery failed"
        return 1
    fi
    while IFS= read -r efi_file; do
        [[ -n "$efi_file" ]] || continue
        efi_files+=("$efi_file")
        seen_efi_files["$efi_file"]=1
    done <<< "$identified_loaders"

    for search_root in /boot /efi; do
        [[ -d "$search_root" ]] || continue

        while IFS= read -r efi_file; do
            if [[ -n "$efi_file" && ! -v "seen_efi_files[$efi_file]" ]]; then
                efi_files+=("$efi_file")
                seen_efi_files["$efi_file"]=1
            fi
        done < <(
            sudo find "$search_root" -type f \( \
                -ipath '*/EFI/Linux/*.efi' -o \
                -ipath '*/EFI/systemd/systemd-boot*.efi' \
            \) -print 2>/dev/null
        )
    done

    while IFS= read -r efi_file; do
        if [[ -n "$efi_file" && ! -v "seen_efi_files[$efi_file]" ]]; then
            efi_files+=("$efi_file")
            seen_efi_files["$efi_file"]=1
        fi
    done < <(
        find /usr/lib/systemd/boot/efi -maxdepth 1 -type f \
            -iname 'systemd-boot*.efi' -print 2>/dev/null || true
    )

    if [[ ${#efi_files[@]} -eq 0 ]]; then
        warning "No systemd-boot binaries or UKIs were found to sign."
        SECURE_BOOT_ACTION="no EFI files found"
        return 0
    fi

    local signing_failed=false

    for efi_file in "${efi_files[@]}"; do
        info "Registering and signing: $efi_file"

        if ! sudo sbctl sign -s "$efi_file"; then
            warning "Failed to sign: $efi_file"
            signing_failed=true
        fi
    done

    echo
    info "Verifying Secure Boot signatures..."

    if verify_secure_boot_files "${efi_files[@]}"; then
        if [[ "$signing_failed" == true ]]; then
            SECURE_BOOT_ACTION="verification passed with earlier signing warnings"
        else
            SECURE_BOOT_ACTION="configured and verified"
        fi
        success "Secure Boot verification completed."
    else
        warning "sbctl verification reported unsigned or invalid EFI files."
        SECURE_BOOT_ACTION="verification failed"
        return 1
    fi
}

# ============================================================

# 19. FINAL SUMMARY

# ============================================================

summary_row() {
    printf '  %-18s %b\n' "${1}:" "$2"
}

show_final_summary() {
    check_graphical_environment

    echo
    echo "========================================"
    echo "       INSTALLATION SUMMARY"
    echo "========================================"
    echo

    if [[ "${SELECTED_SETUP_MODULES[applications]:-false}" != true ]]; then
        info "Optional application installation was not selected."
    elif [[ ${#FAILED_PACKAGES[@]} -eq 0 && ${#SKIPPED_PACKAGES[@]} -eq 0 && ${#SELECTED_PACKAGES[@]} -gt 0 ]]; then
        success "All selected packages were installed successfully."
    elif [[ ${#FAILED_PACKAGES[@]} -gt 0 ]]; then
        warning "Some packages could not be installed:"
        echo
        for package in "${FAILED_PACKAGES[@]}"; do
            echo -e "  ${RED}✗${NC} $package"
        done
        echo
        warning "The failed packages can be installed manually later."
    fi

    if ((${#SKIPPED_PACKAGES[@]} > 0)); then
        warning "Packages skipped at your request:"
        printf '  - %s\n' "${SKIPPED_PACKAGES[@]}"
        info "Run PoeDeploy again, answer yes to the previous-run question, and select Applications to retry them."
    fi

    echo
    echo "SYSTEM STATE"
    summary_row "Version" "$SCRIPT_VERSION"
    summary_row "GPU" "$GPU_VENDOR"
    summary_row "Bootloader" "$BOOTLOADER"
    summary_row "UKI" "$UKI_STATUS"
    summary_row "Root filesystem" "$ROOT_FILESYSTEM"
    echo

    if pacman -Q plymouth &>/dev/null; then
        summary_row "Plymouth" "${GREEN}installed${NC}"
    else
        summary_row "Plymouth" "${RED}not installed${NC}"
    fi

    if pacman -Q timeshift &>/dev/null; then
        summary_row "Timeshift" "${GREEN}installed${NC}"
    else
        summary_row "Timeshift" "${YELLOW}not installed${NC}"
    fi

    if command -v yay &>/dev/null; then
        summary_row "yay" "${GREEN}installed${NC}"
    else
        summary_row "yay" "${RED}not installed${NC}"
    fi

    summary_row "Hyprland" "$(format_status_change "$HYPRLAND_STATUS" "$HYPRLAND_INITIAL_STATUS")"
    summary_row "SDDM" "$(format_status_change "$SDDM_STATUS" "$SDDM_INITIAL_STATUS")"
    summary_row "SDDM now" "$SDDM_ACTIVE_STATUS"
    summary_row "ML4W SDDM theme" "$(format_status_change "$SDDM_THEME_STATUS" "$SDDM_THEME_INITIAL_STATUS")"

    echo
    echo "THIS RUN"
    summary_row "Mode" "$RUN_MODE"
    local module
    for module in "${PROCESSED_SETUP_MODULES[@]}"; do
        summary_row "Section visited" "${SETUP_MODULE_LABELS[$module]}"
    done
    summary_row "ML4W" "$ML4W_ACTION"
    summary_row "SDDM setup" "$SDDM_ACTION"
    summary_row "Applications" "$APPLICATIONS_ACTION"
    summary_row "Default browser" "$DEFAULT_BROWSER_ACTION"
    summary_row "UKI setup" "$UKI_ACTION"
    summary_row "SMB" "$SMB_ACTION"
    summary_row "NFS" "$NFS_ACTION"
    summary_row "Secure Boot setup" "$SECURE_BOOT_ACTION"
    summary_row "Signature check" "$SECURE_BOOT_VERIFY_STATUS"
    summary_row "Boot images" "$BOOT_IMAGE_ACTION"
    summary_row "Automatic signing" "$SECURE_BOOT_AUTOMATIC_ACTION"
    echo
}

show_secure_boot_next_steps() {
    case "$SECURE_BOOT_ACTION" in
        "keys created but not enrolled")
            warning "Secure Boot is not ready: the new keys have not been enrolled."
            info "Use your firmware's documented procedure to enter Secure Boot Setup Mode."
            info "Custom mode alone may not enable Setup Mode. Check with: sudo sbctl status"
            info "Boot Arch again, rerun PoeDeploy, answer yes to having run it before, and select only Secure Boot."
            info "Complete ENROLL and SIGN before enabling Secure Boot enforcement."
            ;;
        "waiting for verified UKI boot")
            info "Reboot through the UKI entry first, then rerun only the Secure Boot section."
            ;;
        "configured and verified")
            info "The listed boot files have been signed and individually verified; no full ESP scan is needed."
            info "With your keys enrolled and boot files verified, enable Secure Boot in firmware if needed."
            info "Boot the signed UKI and confirm that sudo sbctl status reports Secure Boot: Enabled."
            ;;
    esac
}

# ============================================================

# 20. MAIN

# ============================================================

run_setup_module() {
    case "$1" in
        update) update_system ;;
        yay) wait_for_pacman_lock; install_yay ;;
        base) wait_for_pacman_lock; install_base_tools ;;
        gpu)
            ensure_command_dependencies lspci:pciutils
            detect_gpu
            wait_for_pacman_lock
            install_nvidia_driver
            ;;
        network) wait_for_pacman_lock; check_networkmanager ;;
        plymouth)
            ensure_command_dependencies curl:curl jq:jq unzip:unzip file:file mkinitcpio:mkinitcpio objcopy:binutils
            wait_for_pacman_lock
            setup_plymouth
            ;;
        uki)
            ensure_command_dependencies curl:curl file:file mkinitcpio:mkinitcpio jq:jq
            setup_uki
            ;;
        timeshift) wait_for_pacman_lock; check_timeshift ;;
        ml4w) ensure_command_dependencies curl:curl; install_ml4w ;;
        sddm) wait_for_pacman_lock; choose_sddm_setup ;;
        applications)
            wait_for_pacman_lock
            select_applications
            install_selected_applications
            ;;
        browser) ensure_command_dependencies xdg-settings:xdg-utils; select_default_browser ;;
        shares) configure_network_shares ;;
        tailscale) wait_for_pacman_lock; configure_tailscale ;;
        secure_boot) ensure_command_dependencies objcopy:binutils jq:jq; wait_for_pacman_lock; setup_secure_boot ;;
        *) die "Unknown setup section: $1" ;;
    esac
}

run_selected_setup_modules() {
    local module
    # Always use dependency order, even when the user selects in another order.
    for module in "${SETUP_MODULE_IDS[@]}"; do
        if [[ "${SELECTED_SETUP_MODULES[$module]:-false}" == true ]]; then
            info "Running section: ${SETUP_MODULE_LABELS[$module]}"
            run_setup_module "$module"
            PROCESSED_SETUP_MODULES+=("$module")
        fi
    done
}

main() {
    load_version
    show_header
    check_not_root
    check_arch

    if ! choose_setup_modules; then
        info "Setup cancelled before making system changes."
        return 0
    fi
    show_selected_setup_modules
    confirm_start

    # Read-only assessment: no packages, services, splash files or presets change.
    detect_gpu
    detect_bootloader
    detect_uki
    detect_filesystem
    check_graphical_environment
    save_initial_graphical_status
    show_summary

    if [[ "$RUN_MODE" == full ]]; then
        check_internet
    fi
    run_selected_setup_modules

    # Final result

    show_final_summary
    show_secure_boot_next_steps

    echo

    echo "========================================"

    echo "       INSTALLATION COMPLETE"

    echo "========================================"

    echo

    if [[ "$SECURE_BOOT_OTHER_FILES_WARNING" == true ]]; then

        warning "Setup completed with additional boot file signature warnings; review the paths reported above."

    elif [[ ${#FAILED_PACKAGES[@]} -gt 0 ]]; then

        warning "Setup completed with some package failures."

    elif [[ ${#SKIPPED_PACKAGES[@]} -gt 0 ]]; then

        warning "Selected setup sections finished with some applications skipped."

    else

        success "PoeDeploy completed successfully."

    fi

    echo

    warning "A reboot is recommended."

    if [[ "$SDDM_ACTION" == "configured" ]]; then
        echo "SDDM is enabled and will start automatically after reboot."
    elif [[ "$SDDM_ACTION" == "skipped" ]]; then
        echo "SDDM configuration was skipped."
    fi

    echo

}

if [[ "${BASH_SOURCE[0]}" == "$0" ]]; then
    main "$@"
fi
