#!/usr/bin/env bash

# Revision successfully enrolled and verified on a Huawei GDIX51C0 laptop.
GOODIX_SPI_REVISION=505dc7e4602cae828e5a1e80221f3fec8e15411e
GOODIX_SPI_REPOSITORY=https://github.com/berkekbgz/libfprint-goodix-spi.git

fingerprint_uses_goodix_spi() {
    compgen -G '/sys/bus/spi/devices/spi-GDIX51C0:*' >/dev/null
}

install_goodix_fingerprint_driver() {
    local source_dir cache_dir
    cache_dir="${XDG_CACHE_HOME:-$HOME/.cache}/poedeploy"
    mkdir -p "$cache_dir"
    source_dir=$(mktemp -d "$cache_dir/goodix-XXXXXXXX")
    info "Building Goodix SPI driver revision $GOODIX_SPI_REVISION in $source_dir"
    git -C "$source_dir" init --quiet
    git -C "$source_dir" remote add origin "$GOODIX_SPI_REPOSITORY"
    git -C "$source_dir" fetch --depth=1 origin "$GOODIX_SPI_REVISION"
    git -C "$source_dir" checkout --quiet --detach FETCH_HEAD
    [[ "$(git -C "$source_dir" rev-parse HEAD)" == "$GOODIX_SPI_REVISION" ]] || return 1
    # Release mode: no raw biometric capture diagnostics. Installer uses sudo
    # internally and keeps Arch's libfprint intact via /opt shadow builds.
    ui_run_interactive env GOODIX_SPI_DEBUG=0 GOODIX_SPI_DEVELOPER=0 bash "$source_dir/install.sh" --check
    ui_run_interactive env GOODIX_SPI_DEBUG=0 GOODIX_SPI_DEVELOPER=0 bash "$source_dir/install.sh"
    info "Driver sources retained at $source_dir; uninstall with: $source_dir/uninstall.sh"
}

setup_fingerprint() {
    local answer user_name devices
    ui_heading "Fingerprint authentication"
    if [[ "${POEDEPLOY_IN_CHROOT:-false}" == true ]]; then
        warning "Fingerprint setup needs a running system. Run this section after the first boot."
        return 0
    fi
    info "Install a fingerprint reader, enroll a finger, and test recognition before enabling login."
    info "Password authentication remains available. Disk encryption still needs its passphrase."
    ui_prompt answer "Set up fingerprint authentication? [y/N]: "
    [[ "$answer" =~ ^[Yy]$ ]] || return 0
    user_name=$(id -un)
    wait_for_pacman_lock
    if fingerprint_uses_goodix_spi; then
        warning "GDIX51C0 requires an experimental driver tested on a Huawei MateBook 16s."
        warning "Installation provisions a sensor key; dual-boot Windows may replace that key."
        ui_prompt answer "Install the pinned experimental Goodix SPI driver? [y/N]: "
        [[ "$answer" =~ ^[Yy]$ ]] || return 0
        sudo pacman -S --needed --noconfirm fprintd base-devel git meson ninja glib2-devel libgusb libgudev libgpiod openssl polkit gobject-introspection gtk-doc python-cairo python-gobject
        install_goodix_fingerprint_driver
    else
        info "Trying the standard Arch fprintd/libfprint driver. Unsupported sensors will be skipped."
        sudo pacman -S --needed --noconfirm fprintd python
    fi
    if ! devices=$(fprintd-list "$user_name" 2>&1); then
        warning "Fingerprint reader unavailable: $devices"
        warning "Login settings were not changed. Check driver support for this sensor."
        return 0
    fi
    printf '%s\n' "$devices"
    info "Use your right index finger. Touch and lift repeatedly without pressing the power button."
    ui_prompt answer "Enroll your right index finger now (replaces its existing enrollment)? [y/N]: "
    if [[ "$answer" =~ ^[Yy]$ ]]; then
        ui_run_interactive fprintd-enroll -f right-index-finger "$user_name"
    fi
    info "Touch your right index finger to verify recognition."
    # Some fprintd clients exit zero for no-match; require the actual verdict.
    if ! devices=$(LC_ALL=C fprintd-verify -f right-index-finger "$user_name" 2>&1); then
        warning "Fingerprint verification failed: $devices"
        return 0
    fi
    printf '%s\n' "$devices"
    if [[ "$devices" != *'verify-match (done)'* ]]; then
        warning "No successful fingerprint match. Login settings were not changed."
        return 0
    fi
    ui_prompt answer "Enable the verified fingerprint for SDDM and Hyprlock where installed? [y/N]: "
    [[ "$answer" =~ ^[Yy]$ ]] || return 0
    if [[ -f /etc/pam.d/sddm ]]; then
        sudo python3 "$SCRIPT_DIR/installer/fingerprint_config.py" --sddm /etc/pam.d/sddm
    fi
    if [[ -f "$HOME/.config/hypr/hyprlock.conf" ]]; then
        python3 "$SCRIPT_DIR/installer/fingerprint_config.py" --hyprlock "$HOME/.config/hypr/hyprlock.conf"
    fi
    success "Fingerprint verified. Supported login settings configured with timestamped backups."
    info "SDDM: select your user, leave the password blank, press Enter, then touch the sensor."
    info "If scanning fails, wait up to 10 seconds and enter your password."
    info "Hyprlock: lock the screen and touch the sensor, or type your password. No reboot is required."
}
