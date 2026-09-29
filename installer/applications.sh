#!/usr/bin/env bash

install_bundled_dashboard_application() {
    local name="$1" relative_source="$2"
    shift 2
    local source_dir="$SCRIPT_DIR/apps/$relative_source"

    ui_set_operation "Installing bundled $name"
    if [[ ! -r "$source_dir/install.sh" ]]; then
        warning "Bundled $name installer is missing: $source_dir/install.sh"
        FAILED_PACKAGES+=("$name")
        return 0
    fi
    if ! bash -n "$source_dir/install.sh"; then
        warning "Bundled $name installer has invalid Bash syntax."
        FAILED_PACKAGES+=("$name")
        return 0
    fi
    if bash "$source_dir/install.sh" "$@"; then
        INSTALLED_PACKAGES+=("$name")
        success "$name installed successfully from the PoeDeploy bundle."
    else
        warning "$name installation failed. Review $POEDEPLOY_LOG."
        FAILED_PACKAGES+=("$name")
    fi
}

dashboard_application_selection_count() {
    local selected count=0
    for selected in "$@"; do
        case "${APPLICATIONS[$selected]:-}" in
            @poedash|@pendash-dashboard|@pendash-full) count=$((count + 1)) ;;
        esac
    done
    printf '%s\n' "$count"
}
