#!/usr/bin/env bash

set -euo pipefail

# ============================================================
# Arch Linux Personal Setup Script
# ============================================================

ML4W_URL="https://ml4w.com/os/stable"

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

    sudo pacman -Syu --needed

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

    sudo pacman -S --needed git base-devel

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

    sudo pacman -S --needed \
        git \
        curl \
        wget \
        jq \
        zip \
        unzip \
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
        whois

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

        GPU_MODEL=$(echo "$gpu_info" |
            sed -E 's/.*NVIDIA Corporation //')

    elif echo "$gpu_info" | grep -qi "AMD"; then

        GPU_VENDOR="AMD"

        GPU_MODEL=$(echo "$gpu_info" |
            sed -E 's/.*AMD\/ATI //')

    elif echo "$gpu_info" | grep -qi "Intel"; then

        GPU_VENDOR="Intel"

        GPU_MODEL=$(echo "$gpu_info" |
            sed -E 's/.*Intel Corporation //')

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

        sudo pacman -S --needed \
            nvidia-open-dkms \
            nvidia-utils \
            dkms

        if pacman -Q linux &>/dev/null; then
            sudo pacman -S --needed linux-headers
        fi

        if pacman -Q linux-lts &>/dev/null; then
            sudo pacman -S --needed linux-lts-headers
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

    # --------------------------------------------------------
    # systemd-boot
    # --------------------------------------------------------

    if [[ -f /boot/EFI/systemd/systemd-bootx64.efi ]] ||
       [[ -f /boot/EFI/SYSTEMD/SYSTEMD-BOOTX64.EFI ]]; then

        BOOTLOADER="systemd-boot"

    # --------------------------------------------------------
    # GRUB
    # --------------------------------------------------------

    elif [[ -f /boot/grub/grub.cfg ]] ||
         [[ -f /etc/default/grub ]]; then

        BOOTLOADER="GRUB"

    # --------------------------------------------------------
    # Fallback: bootctl
    # --------------------------------------------------------

    elif bootctl status 2>/dev/null |
         grep -qi "Product: systemd-boot"; then

        BOOTLOADER="systemd-boot"
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

        sudo pacman -S --needed networkmanager
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

        sudo pacman -S --needed plymouth

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

    local hooks_content
    hooks_content="${hooks_line#HOOKS=(}"
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

    local new_hooks_line
    new_hooks_line="HOOKS=(${new_hooks[*]})"

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


select_plymouth_theme() {

    echo

    local themes=()

    mapfile -t themes < <(
        plymouth-set-default-theme -l
    )

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
        ((i++))
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

            local selected_theme
            selected_theme="${themes[$((choice - 1))]}"

            info "Applying Plymouth theme: $selected_theme"

            sudo plymouth-set-default-theme -R "$selected_theme"

            success "Plymouth theme configured."

            break
        fi

        warning "Invalid selection."
    done
}


setup_plymouth() {

    install_plymouth

    configure_mkinitcpio_plymouth

    configure_bootloader_plymouth

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

    read -rp "Install Timeshift? [Y/n]: " answer

    if [[ -z "$answer" || "$answer" =~ ^[Yy]$ ]]; then

        info "Installing Timeshift..."

        sudo pacman -S --needed timeshift

        success "Timeshift installed."

        if [[ "$ROOT_FILESYSTEM" == "btrfs" ]]; then

            info "Btrfs detected."
            info "Timeshift can use native Btrfs snapshots when the"
            info "root layout uses @ and @home subvolumes."

        else

            info "Non-Btrfs filesystem detected."
            info "Timeshift can use rsync snapshot mode."
        fi

    else

        info "Timeshift skipped."
    fi
}

# ============================================================
# 11. SYSTEM SUMMARY
# ============================================================

show_summary() {

    echo
    echo "========================================"
    echo "          SYSTEM ASSESSMENT"
    echo "========================================"
    echo
    echo "OS:              Arch Linux"
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

    if [[ "$HYPRLAND_STATUS" != "Unknown" ]]; then
        echo "Hyprland:        $HYPRLAND_STATUS"
    fi

    if [[ "$SDDM_STATUS" != "Unknown" ]]; then
        echo "SDDM:            $SDDM_STATUS"
    fi

    if [[ "$SDDM_THEME_STATUS" != "Unknown" ]]; then
        echo "ML4W SDDM theme: $SDDM_THEME_STATUS"
    fi

    echo
}

# ============================================================
# 12. ML4W
# ============================================================

install_ml4w() {

    echo
    echo "========================================"
    echo "          PRE-ML4W CHECKPOINT"
    echo "========================================"

    show_summary

    echo
    echo "The Arch system checks have completed."
    echo "The next stage will launch the ML4W installer."
    echo
    echo "ML4W is an external installer and will take"
    echo "control of the terminal while it runs."
    echo

    read -rp "Press Enter to continue to ML4W..."

    echo
    info "Starting ML4W installer..."
    echo

    bash <(curl -fsSL "$ML4W_URL")

    echo
    echo "========================================"
    echo "         ML4W INSTALLER FINISHED"
    echo "========================================"
    echo

    read -rp "Press Enter to continue to application selection..."
}


# ============================================================
# 13. SDDM / GRAPHICAL LOGIN
# ============================================================

HYPRLAND_STATUS="Unknown"
SDDM_STATUS="Unknown"
SDDM_THEME_STATUS="Unknown"

setup_sddm() {

    echo
    echo "========================================"
    echo "       GRAPHICAL LOGIN (SDDM)"
    echo "========================================"
    echo

    # --------------------------------------------------------
    # Verify Hyprland was installed by ML4W
    # --------------------------------------------------------

    if pacman -Q hyprland &>/dev/null; then
        HYPRLAND_STATUS="installed"
        success "Hyprland is installed."
    else
        HYPRLAND_STATUS="missing"
        warning "Hyprland is not installed after ML4W."
        warning "SDDM will still be configured, but Hyprland may not be available."
    fi

    # --------------------------------------------------------
    # Install SDDM and required ML4W dependencies
    # --------------------------------------------------------

    if pacman -Q sddm &>/dev/null; then
        success "SDDM is already installed."
    else
        info "Installing SDDM and required Qt components..."

        if sudo pacman -S --needed \
            sddm \
            qt6-svg \
            qt6-virtualkeyboard \
            qt6-multimedia-ffmpeg; then
            success "SDDM installed successfully."
        else
            warning "Failed to install SDDM."
            SDDM_STATUS="installation failed"
            return
        fi
    fi

    # --------------------------------------------------------
    # Disable conflicting display managers
    # --------------------------------------------------------

    local conflicting_dms=(gdm lightdm lxdm xdm mdm slim wdm)

    for dm in "${conflicting_dms[@]}"; do
        if systemctl is-enabled --quiet "$dm" 2>/dev/null; then
            info "Disabling conflicting display manager: $dm"
            sudo systemctl disable "$dm" || \
                warning "Could not disable $dm."
        fi
    done

    # --------------------------------------------------------
    # Enable and start SDDM
    # --------------------------------------------------------

    if systemctl is-enabled --quiet sddm; then
        success "SDDM service is already enabled."
    else
        info "Enabling SDDM service..."

        if sudo systemctl enable sddm; then
            success "SDDM service enabled."
        else
            warning "Failed to enable SDDM."
            SDDM_STATUS="enable failed"
            return
        fi
    fi

    # Start it now where possible. On a running graphical session,
    # SDDM may not take over immediately; the important part is that
    # it is enabled for the next boot.
    if systemctl is-active --quiet sddm; then
        success "SDDM service is already running."
    else
        if sudo systemctl start sddm; then
            success "SDDM service started."
        else
            warning "SDDM could not be started in the current session."
            warning "It should start automatically after reboot."
        fi
    fi

    # --------------------------------------------------------
    # Install ML4W SDDM theme if it is missing
    # --------------------------------------------------------

    local theme_dir="/usr/share/sddm/themes/ml4w"
    local sddm_config="/etc/sddm.conf"
    local temp_dir

    if [[ -d "$theme_dir" ]]; then
        success "ML4W SDDM theme is already installed."
        SDDM_THEME_STATUS="installed"
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
            SDDM_THEME_STATUS="installed"
        else
            rm -rf "$temp_dir"
            warning "Failed to download the ML4W SDDM theme."
            SDDM_THEME_STATUS="installation failed"
        fi
    fi

    # --------------------------------------------------------
    # Configure the ML4W SDDM theme
    # --------------------------------------------------------

    if [[ -d "$theme_dir" ]]; then

        info "Checking SDDM configuration..."

        if [[ -f "$sddm_config" ]]; then
            sudo cp -n "$sddm_config" "${sddm_config}.bak" 2>/dev/null || true
        else
            sudo touch "$sddm_config"
        fi

        # Ensure [Theme] exists and Current=ml4w is configured.
        if grep -q '^\[Theme\]' "$sddm_config"; then
            if grep -q '^Current=' "$sddm_config"; then
                sudo sed -i '/^\[Theme\]$/{n;s/^Current=.*/Current=ml4w/;}' "$sddm_config"
            else
                sudo sed -i '/^\[Theme\]$/a Current=ml4w' "$sddm_config"
            fi
        else
            printf '\n[Theme]\nCurrent=ml4w\n' | sudo tee -a "$sddm_config" >/dev/null
        fi

        # Configure the Qt virtual keyboard required by the ML4W theme.
        if ! grep -q '^InputMethod=qtvirtualkeyboard' "$sddm_config"; then
            printf '\n[General]\nInputMethod=qtvirtualkeyboard\n' | sudo tee -a "$sddm_config" >/dev/null
        fi

        if ! grep -q '^GreeterEnvironment=.*QML2_IMPORT_PATH=/usr/share/sddm/themes/ml4w/components/' "$sddm_config"; then
            printf 'GreeterEnvironment=QML2_IMPORT_PATH=/usr/share/sddm/themes/ml4w/components/,QT_IM_MODULE=qtvirtualkeyboard\n' |
                sudo tee -a "$sddm_config" >/dev/null
        fi

        success "ML4W SDDM theme configured."
    fi

    if systemctl is-enabled --quiet sddm; then
        SDDM_STATUS="enabled"
    else
        SDDM_STATUS="not enabled"
    fi
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
    ["Timeshift"]="timeshift"
    ["Spotify"]="spotify-launcher"
    ["OBS Studio"]="obs-studio"
)


select_applications() {

    if ! command -v gum &>/dev/null; then

        info "Installing gum for the application selector..."

        sudo pacman -S --needed gum
    fi

    echo
    echo "========================================"
    echo "       APPLICATION SELECTION"
    echo "========================================"
    echo
    echo "Use Space to select/deselect."
    echo "Press Enter when finished."
    echo

    local options=()

    for app in "${!APPLICATIONS[@]}"; do
        options+=("$app")
    done

    mapfile -t options < <(
        printf '%s\n' "${options[@]}" | sort
    )

    mapfile -t selected_apps < <(
        printf '%s\n' "${options[@]}" |
            gum choose \
                --no-limit \
                --selected='*' \
                --height=20 \
                --header="Select applications"
    )

    SELECTED_PACKAGES=()

    for app in "${selected_apps[@]}"; do

        [[ -n "$app" ]] || continue

        SELECTED_PACKAGES+=("${APPLICATIONS[$app]}")

    done

    echo

    if [[ ${#SELECTED_PACKAGES[@]} -eq 0 ]]; then

        info "No optional applications selected."

    else

        info "Selected applications:"
        printf '  - %s\n' "${selected_apps[@]}"

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

    # --------------------------------------------------------
    # Official packages
    # --------------------------------------------------------

    if [[ ${#official_packages[@]} -gt 0 ]]; then

        echo
        info "Installing official Arch packages..."

        for package in "${official_packages[@]}"; do

            echo
            info "Installing official package: $package"

            if sudo pacman -S --needed "$package"; then

                success "$package installed successfully."

            else

                warning "Failed to install: $package"
                FAILED_PACKAGES+=("$package")

            fi

        done

    fi

    # --------------------------------------------------------
    # AUR packages
    # --------------------------------------------------------

    if [[ ${#aur_packages[@]} -gt 0 ]]; then

        echo
        info "Installing AUR packages..."

        for package in "${aur_packages[@]}"; do

            echo
            info "Installing AUR package: $package"

            if yay -S --needed "$package"; then

                success "$package installed successfully."

            else

                warning "Failed to install: $package"
                FAILED_PACKAGES+=("$package")

            fi

        done

    fi
}

# ============================================================
# 16. TAILSCALE
# ============================================================

configure_tailscale() {

    if [[ ! " ${SELECTED_PACKAGES[*]} " =~ " tailscale " ]]; then
        return
    fi

    echo
    info "Configuring Tailscale..."

    # --------------------------------------------------------
    # Make sure package is installed
    # --------------------------------------------------------

    if pacman -Q tailscale &>/dev/null; then

        success "Tailscale package is installed."

    else

        info "Installing Tailscale..."

        if sudo pacman -S --needed tailscale; then
            success "Tailscale installed."
        else
            warning "Failed to install Tailscale."
            FAILED_PACKAGES+=("tailscale")
            return
        fi

    fi

    # --------------------------------------------------------
    # Enable tailscaled
    # --------------------------------------------------------

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

    # --------------------------------------------------------
    # Start tailscaled
    # --------------------------------------------------------

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

    # --------------------------------------------------------
    # Authentication
    # --------------------------------------------------------

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
# 17. FINAL SUMMARY
# ============================================================

show_final_summary() {

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
    echo "System:"
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

    if systemctl is-active tailscaled &>/dev/null; then
        echo -e "  Tailscale:       ${GREEN}service running${NC}"
    elif pacman -Q tailscale &>/dev/null; then
        echo -e "  Tailscale:       ${YELLOW}installed, service inactive${NC}"
    else
        echo -e "  Tailscale:       ${YELLOW}not installed${NC}"
    fi

    if pacman -Q hyprland &>/dev/null; then
        echo -e "  Hyprland:        ${GREEN}installed${NC}"
    else
        echo -e "  Hyprland:        ${RED}not installed${NC}"
    fi

    if pacman -Q sddm &>/dev/null && systemctl is-enabled --quiet sddm; then
        echo -e "  SDDM:            ${GREEN}installed and enabled${NC}"
    elif pacman -Q sddm &>/dev/null; then
        echo -e "  SDDM:            ${YELLOW}installed, not enabled${NC}"
    else
        echo -e "  SDDM:            ${RED}not installed${NC}"
    fi

    if [[ -d /usr/share/sddm/themes/ml4w ]]; then
        echo -e "  ML4W SDDM theme: ${GREEN}installed${NC}"
    else
        echo -e "  ML4W SDDM theme: ${YELLOW}not installed${NC}"
    fi

    echo
}

# ============================================================
# 18. MAIN
# ============================================================

main() {

    clear

    echo
    echo "========================================"
    echo "       ARCH LINUX SETUP SCRIPT"
    echo "========================================"
    echo

    # --------------------------------------------------------
    # Initial checks
    # --------------------------------------------------------

    check_arch
    check_internet

    # --------------------------------------------------------
    # Update Arch
    # --------------------------------------------------------

    update_system

    # --------------------------------------------------------
    # Package manager
    # --------------------------------------------------------

    install_yay

    # --------------------------------------------------------
    # Base tools
    # --------------------------------------------------------

    install_base_tools

    # --------------------------------------------------------
    # Hardware
    # --------------------------------------------------------

    detect_gpu
    install_nvidia_driver

    # --------------------------------------------------------
    # System
    # --------------------------------------------------------

    detect_bootloader
    check_networkmanager
    detect_filesystem

    # --------------------------------------------------------
    # Initial assessment
    # --------------------------------------------------------

    show_summary

    echo
    read -rp "Continue with system configuration? [Y/n]: " answer

    if [[ -n "$answer" && ! "$answer" =~ ^[Yy]$ ]]; then
        info "Installation cancelled."
        exit 0
    fi

    # --------------------------------------------------------
    # Plymouth
    # --------------------------------------------------------

    setup_plymouth

    # --------------------------------------------------------
    # Timeshift
    # --------------------------------------------------------

    check_timeshift

    # --------------------------------------------------------
    # ML4W
    # --------------------------------------------------------

    install_ml4w

    # --------------------------------------------------------
    # SDDM / graphical login
    # --------------------------------------------------------

    setup_sddm

    # --------------------------------------------------------
    # Applications
    # --------------------------------------------------------

    select_applications
    install_selected_applications

    # --------------------------------------------------------
    # Tailscale configuration
    # --------------------------------------------------------

    configure_tailscale

    # --------------------------------------------------------
    # Final result
    # --------------------------------------------------------

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
    echo
}


main "$@"
