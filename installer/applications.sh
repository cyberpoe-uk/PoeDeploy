#!/usr/bin/env bash

POEDASH_INSTALLER_URL="https://cyberpoe.uk/poedash-latest"
PENDASH_INSTALLER_URL="https://cyberpoe.uk/pendash-latest"

install_dashboard_application() {
    local name="$1" url="$2" installer_file
    ui_set_operation "Downloading the $name installer"
    if ! installer_file=$(mktemp -t "poedeploy-${name,,}-XXXXXXXX"); then
        warning "Could not create a temporary file for $name."
        FAILED_PACKAGES+=("$name")
        return 0
    fi
    if ! curl --fail --show-error --silent --location \
        --proto '=https' --proto-redir '=https' \
        --connect-timeout 15 --max-time 180 --retry 2 \
        --output "$installer_file" "$url"; then
        warning "$name installer download failed. No downloaded code was run."
        FAILED_PACKAGES+=("$name")
    elif [[ ! -s "$installer_file" ]] || ! bash -n "$installer_file"; then
        warning "$name installer download is empty or invalid. No downloaded code was run."
        FAILED_PACKAGES+=("$name")
    elif bash "$installer_file"; then
        INSTALLED_PACKAGES+=("$name")
        success "$name installed successfully."
    else
        warning "$name installation failed. Review $POEDEPLOY_LOG."
        FAILED_PACKAGES+=("$name")
    fi
    rm -f -- "$installer_file"
}
