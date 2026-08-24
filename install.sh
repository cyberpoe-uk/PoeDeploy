#!/usr/bin/env bash

set -euo pipefail

# ============================================================

# Arch Linux Personal Setup Script

# ============================================================

ML4W_URL="https://ml4w.com/os/stable"

GITHUB_RAW_BASE="https://raw.githubusercontent.com/cyberpoe-hub/arch-personal-setup/main"

VERSION_URL="${GITHUB_RAW_BASE}/VERSION"

# Place your custom Plymouth archive here:

# assets/plymouth-themes/arch-mac-style.zip

CUSTOM_PLYMOUTH_THEME_URL="${GITHUB_RAW_BASE}/assets/plymouth-themes/arch-mac-style.zip"

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

SELECTED_PACKAGES=()

SELECTED_APPS=()

ML4W_ENABLED=false

CONFIGURE_ML4W_SDDM=false

NETWORK_SHARES_ENABLED=false

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

# ============================================================

# 0. SAFETY / VERSION

# ============================================================

show_header() {

    clear || true

    echo

    echo "========================================"

    echo "       ARCH LINUX SETUP SCRIPT"

    echo "========================================"

    echo "Version: $SCRIPT_VERSION"

    echo "========================================"

    echo

}

confirm_start() {

    warning "This script will make changes to your Arch Linux system."

    warning "It may install packages, drivers and system services."

    echo

    read -rp "Continue with Arch Linux setup? [Y/n]: " answer

    if [[ -z "$answer" || "$answer" =~ ^[Yy]$ ]]; then
        :
    else

        info "Installation cancelled."

        exit 0

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

    if ! ping -c 1 -W 3 archlinux.org &>/dev/null; then

        die "Internet connection is unavailable."

    fi

    success "Internet connection available."

}

update_system() {

    info "Synchronising and updating Arch Linux..."

    sudo pacman -Syu --needed --noconfirm

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
        nano

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

    gpu_info=$(lspci | grep -Ei 'VGA|3D|Display' || true)

    if [[ -z "$gpu_info" ]]; then

        warning "No GPU detected."

        return

    fi

    echo "$gpu_info"

    if echo "$gpu_info" | grep -qi "NVIDIA"; then

        GPU_VENDOR="NVIDIA"

        GPU_MODEL=$(echo "$gpu_info" | sed -E 's/.*NVIDIA Corporation //')

    elif echo "$gpu_info" | grep -qi "AMD"; then

        GPU_VENDOR="AMD"

        GPU_MODEL=$(echo "$gpu_info" | sed -E 's/.*AMD\\/ATI //')

    elif echo "$gpu_info" | grep -qi "Intel"; then

        GPU_VENDOR="Intel"

        GPU_MODEL=$(echo "$gpu_info" | sed -E 's/.*Intel Corporation //')

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

        if pacman -Q linux &>/dev/null; then

            sudo pacman -S --needed --noconfirm linux-headers

        fi

        if pacman -Q linux-lts &>/dev/null; then

            sudo pacman -S --needed --noconfirm linux-lts-headers

        fi

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

detect_bootloader() {

    info "Detecting bootloader..."

    BOOTLOADER="Unknown"

    if command -v bootctl &>/dev/null; then

        local bootctl_status

        bootctl_status=$(SYSTEMD_PAGER=cat bootctl status 2>&1 || true)

        if grep -qiE 'Product:[[:space:]]*systemd-boot' <<< "$bootctl_status"; then

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

    if grep -Eq '^HOOKS=.*\bplymouth\b' "$config"; then

        success "Plymouth hook already present."

        return

    fi

    info "Adding Plymouth to mkinitcpio hooks..."

    local hooks_line

    hooks_line=$(grep '^HOOKS=' "$config" | head -n 1)

    [[ -n "$hooks_line" ]] ||

        die "Could not find HOOKS in $config."

    local hooks_content="${hooks_line#HOOKS=(}"

    hooks_content="${hooks_content%)}"

    read -r -a hooks <<< "$hooks_content"

    local new_hooks=()

    local inserted=false

    for hook in "${hooks[@]}"; do

        new_hooks+=("$hook")

        if [[ "$hook" == "udev" && "$inserted" == false ]]; then

            new_hooks+=("plymouth")

            inserted=true

        fi

    done

    if [[ "$inserted" == false ]]; then

        new_hooks=("plymouth" "${hooks[@]}")

    fi

    local new_hooks_line="HOOKS=(${new_hooks[*]})"

    sudo cp "$config" "${config}.bak"

    sudo sed -i \
        "s|^HOOKS=.*|$new_hooks_line|" \
        "$config"

    success "Plymouth hook added to mkinitcpio."

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

install_custom_plymouth_theme() {
    echo

    info "Checking for your custom Plymouth theme..."

    local theme_name="arch-mac-style"
    local theme_dir="/usr/share/plymouth/themes/$theme_name"
    local temp_dir
    local archive

    # Theme already installed
    if [[ -d "$theme_dir" ]] &&
       find "$theme_dir" -maxdepth 1 -type f -name '*.plymouth' -print -quit 2>/dev/null |
       grep -q .; then

        success "Custom Plymouth theme '$theme_name' is already installed."
        return 0
    fi

    if ! command -v curl >/dev/null 2>&1; then
        warning "curl is unavailable; skipping custom Plymouth theme download."
        return 0
    fi

    if ! command -v unzip >/dev/null 2>&1; then
        warning "unzip is unavailable; skipping custom Plymouth theme download."
        return 0
    fi

    temp_dir=$(mktemp -d -t poestack-plymouth-XXXXXX)
    archive="$temp_dir/${theme_name}.zip"

    if ! curl -fL --silent --show-error \
        --output "$archive" \
        "$CUSTOM_PLYMOUTH_THEME_URL"; then

        rm -rf "$temp_dir"

        warning "Custom Plymouth theme could not be downloaded."
        warning "Built-in Plymouth themes will still be available."
        return 0
    fi

    if ! unzip -t "$archive" >/dev/null 2>&1; then
        rm -rf "$temp_dir"

        warning "The downloaded Plymouth ZIP archive is invalid."
        warning "Built-in Plymouth themes will still be available."
        return 0
    fi

    local extracted_dir="$temp_dir/extracted"

    mkdir -p "$extracted_dir"

    if ! unzip -q "$archive" -d "$extracted_dir"; then
        rm -rf "$temp_dir"

        warning "Failed to extract the custom Plymouth theme."
        return 0
    fi

    local plymouth_file

    plymouth_file=$(
        find "$extracted_dir" \
            -type f \
            -name '*.plymouth' \
            -print -quit 2>/dev/null
    )

    if [[ -z "$plymouth_file" ]]; then
        rm -rf "$temp_dir"

        warning "No .plymouth theme file was found in the archive."
        return 0
    fi

    sudo mkdir -p "$theme_dir"

    sudo cp -rf "$(dirname "$plymouth_file")/." "$theme_dir/"

    rm -rf "$temp_dir"

    success "Custom Plymouth theme '$theme_name' installed."
}

select_plymouth_theme() {

    echo

    local themes=()

    mapfile -t themes < <(plymouth-set-default-theme -l)

    if [[ ${#themes[@]} -eq 0 ]]; then

        warning "No Plymouth themes were detected."

        return

    fi

    local current_theme

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

        echo "  [$i] $theme"

        ((i += 1))

    done

    echo

    while true; do

        read -rp "Select a theme [0-${#themes[@]}]: " choice

        if [[ "$choice" == "0" ]]; then

            info "Keeping current Plymouth theme."

            return

        fi

        if [[ "$choice" =~ ^[0-9]+$ ]] &&

           (( choice >= 1 && choice <= ${#themes[@]} )); then

            local selected_theme="${themes[$((choice - 1))]}"

            info "Applying Plymouth theme: $selected_theme"

            sudo plymouth-set-default-theme -R "$selected_theme"

            success "Plymouth theme configured."

            return

        fi

        warning "Invalid selection."

    done

}

setup_plymouth() {

    install_plymouth

    configure_mkinitcpio_plymouth

    configure_bootloader_plymouth

    install_custom_plymouth_theme

    select_plymouth_theme

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

    echo
    echo "========================================"
    echo "       SDDM CONFIGURATION"
    echo "========================================"
    echo

    if [[ "$ML4W_ENABLED" == true ]]; then
        read -rp "Configure the ML4W SDDM login screen? [Y/n]: " sddm_answer
    else
        read -rp "Install and configure SDDM graphical login? [Y/n]: " sddm_answer
    fi

    if [[ -z "$sddm_answer" || "$sddm_answer" =~ ^[Yy]$ ]]; then
        CONFIGURE_ML4W_SDDM=true
        info "SDDM configuration selected."
    else
        CONFIGURE_ML4W_SDDM=false
        SDDM_ACTION="skipped"
        info "SDDM configuration skipped."
    fi
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
        local sddm_config="/etc/sddm.conf"
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

            if [[ -f "$sddm_config" ]]; then
                sudo cp -n "$sddm_config" "${sddm_config}.bak" 2>/dev/null || true
            else
                sudo touch "$sddm_config"
            fi

            if grep -q '^\[Theme\]' "$sddm_config"; then
                if grep -q '^Current=' "$sddm_config"; then
                    sudo sed -i '/^\[Theme\]$/{n;s/^Current=.*/Current=ml4w/;}' "$sddm_config"
                else
                    sudo sed -i '/^\[Theme\]$/a Current=ml4w' "$sddm_config"
                fi
            else
                printf '\n[Theme]\nCurrent=ml4w\n' |
                    sudo tee -a "$sddm_config" >/dev/null
            fi

            if ! grep -q '^InputMethod=qtvirtualkeyboard' "$sddm_config"; then
                printf '\n[General]\nInputMethod=qtvirtualkeyboard\n' |
                    sudo tee -a "$sddm_config" >/dev/null
            fi

            if ! grep -q '^GreeterEnvironment=.*QML2_IMPORT_PATH=/usr/share/sddm/themes/ml4w/components/' "$sddm_config"; then
                printf 'GreeterEnvironment=QML2_IMPORT_PATH=/usr/share/sddm/themes/ml4w/components/,QT_IM_MODULE=qtvirtualkeyboard\n' |
                    sudo tee -a "$sddm_config" >/dev/null
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

        sudo pacman -S --needed --noconfirm gum

    fi

    echo

    echo "========================================"

    echo "       APPLICATION SELECTION"

    echo "========================================"

    echo

    echo "Use arrow keys to navigate."

    echo "Press Space, Tab or X to select/deselect."

    echo "Press Enter when finished."

    echo "All applications start selected."

    echo

    local options=()

    for app in "${!APPLICATIONS[@]}"; do

        options+=("$app")

    done

    mapfile -t options < <(

        printf '%s\n' "${options[@]}" | sort

    )

    mapfile -t SELECTED_APPS < <(

        printf '%s\n' "${options[@]}" |

            gum choose \
                --no-limit \
                --selected='*' \
                --cursor-prefix '> ' \
                --selected-prefix '[x] ' \
                --unselected-prefix '[ ] ' \
                --height=20 \
                --header="Select applications"

    )

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

install_selected_applications() {

    if [[ ${#SELECTED_PACKAGES[@]} -eq 0 ]]; then

        return

    fi

    local official_packages=()

    local aur_packages=()

    info "Checking package sources..."

    for package in "${SELECTED_PACKAGES[@]}"; do

        if pacman -Si "$package" &>/dev/null; then

            official_packages+=("$package")

        elif yay -Si "$package" &>/dev/null; then

            aur_packages+=("$package")

        else

            warning "Package not found: $package"

            FAILED_PACKAGES+=("$package")

        fi

    done

    if [[ ${#official_packages[@]} -gt 0 ]]; then

        echo

        info "Installing official Arch packages..."

        for package in "${official_packages[@]}"; do

            echo

            info "Installing official package: $package"

            if sudo pacman -S --needed --noconfirm "$package"; then

                success "$package installed successfully."

            else

                warning "Failed to install: $package"

                FAILED_PACKAGES+=("$package")

            fi

        done

    fi

    if [[ ${#aur_packages[@]} -gt 0 ]]; then

        echo

        info "Installing AUR packages..."

        for package in "${aur_packages[@]}"; do

            echo

            info "Installing AUR package: $package"

            if yay -S --needed --noconfirm "$package"; then

                success "$package installed successfully."

            else

                warning "Failed to install: $package"

                FAILED_PACKAGES+=("$package")

            fi

        done

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

    return 0

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

    if grep -Fq "$mountpoint" /etc/fstab; then
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

    local server export_path mountpoint nfs_version fstab_line

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

    if grep -Fq "$mountpoint" /etc/fstab; then
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
                NETWORK_SHARES_ENABLED=true
                setup_smb_share
                NETWORK_SHARES_ACTION="completed"
                return 0
                ;;
            2)
                NETWORK_SHARES_ENABLED=true
                setup_nfs_share
                NETWORK_SHARES_ACTION="completed"
                return 0
                ;;
            3)
                NETWORK_SHARES_ENABLED=true
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

    if [[ ! " ${SELECTED_PACKAGES[*]} " =~ " tailscale " ]]; then

        return

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

# 18. FINAL SUMMARY

# ============================================================

show_final_summary() {
    check_graphical_environment

    echo
    echo "========================================"
    echo "       INSTALLATION SUMMARY"
    echo "========================================"
    echo

    if [[ ${#FAILED_PACKAGES[@]} -eq 0 ]]; then
        success "All selected packages were installed successfully."
    else
        warning "Some packages could not be installed:"
        echo
        for package in "${FAILED_PACKAGES[@]}"; do
            echo -e "  ${RED}✗${NC} $package"
        done
        echo
        warning "The failed packages can be installed manually later."
    fi

    echo
    echo "SYSTEM STATE"
    echo "  Version:         $SCRIPT_VERSION"
    echo "  GPU:             $GPU_VENDOR"
    echo "  Bootloader:      $BOOTLOADER"
    echo "  Root filesystem: $ROOT_FILESYSTEM"
    echo

    if pacman -Q plymouth &>/dev/null; then
        echo -e "  Plymouth:        ${GREEN}installed${NC}"
    else
        echo -e "  Plymouth:        ${RED}not installed${NC}"
    fi

    if pacman -Q timeshift &>/dev/null; then
        echo -e "  Timeshift:       ${GREEN}installed${NC}"
    else
        echo -e "  Timeshift:       ${YELLOW}not installed${NC}"
    fi

    if command -v yay &>/dev/null; then
        echo -e "  yay:             ${GREEN}installed${NC}"
    else
        echo -e "  yay:             ${RED}not installed${NC}"
    fi

    echo "  Hyprland:         $(format_status_change "$HYPRLAND_STATUS" "$HYPRLAND_INITIAL_STATUS")"
    echo "  SDDM:             $(format_status_change "$SDDM_STATUS" "$SDDM_INITIAL_STATUS")"
    echo "  SDDM now:         $SDDM_ACTIVE_STATUS"
    echo "  ML4W SDDM theme:  $(format_status_change "$SDDM_THEME_STATUS" "$SDDM_THEME_INITIAL_STATUS")"

    echo
    echo "THIS RUN"
    echo "  ML4W:             $ML4W_ACTION"
    echo "  SDDM setup:       $SDDM_ACTION"
    echo "  Applications:     $APPLICATIONS_ACTION"
    echo "  SMB:              $SMB_ACTION"
    echo "  NFS:              $NFS_ACTION"
    echo
}

# ============================================================

# 19. MAIN

# ============================================================

main() {

    load_version

    show_header

    confirm_start

    # Initial checks

    check_arch

    check_internet

    # Update Arch

    update_system

    # Package manager

    install_yay

    # Base tools

    install_base_tools

    # Hardware

    detect_gpu

    install_nvidia_driver

    # System

    detect_bootloader
    check_networkmanager
    detect_filesystem
    check_graphical_environment
    save_initial_graphical_status


    # Initial assessment

    show_summary

    echo

    read -rp "Continue with system configuration? [Y/n]: " answer

    if [[ -n "$answer" && ! "$answer" =~ ^[Yy]$ ]]; then

        info "Installation cancelled."

        exit 0

    fi

    # Plymouth

    setup_plymouth

    # Timeshift

    check_timeshift

    # ML4W (optional)

    install_ml4w

    # SDDM / graphical login

    setup_sddm

    # Applications

    select_applications

    install_selected_applications

    # Network shares

    configure_network_shares

    # Tailscale configuration

    configure_tailscale

    # Final result

    show_final_summary

    echo

    echo "========================================"

    echo "       INSTALLATION COMPLETE"

    echo "========================================"

    echo

    if [[ ${#FAILED_PACKAGES[@]} -gt 0 ]]; then

        warning "Setup completed with some package failures."

    else

        success "Arch Linux setup completed successfully."

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

main "$@"
