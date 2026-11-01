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
    local files_only=false option
    for option in "$@"; do
        case "$option" in --skip-deps|--skip-packages|--update-dashboard) files_only=true ;; esac
    done
    if [[ "$files_only" == true ]]; then
        if ! command -v python3 >/dev/null 2>&1; then
            warning "$name needs Python 3. Install the missing dependency before refreshing dashboard files."
            FAILED_PACKAGES+=("$name")
            return 0
        fi
    else
        ensure_command_dependencies python3:python
    fi
    if ui_run_interactive bash "$source_dir/install.sh" "$@"; then
        INSTALLED_PACKAGES+=("$name")
        success "$name installed successfully from the PoeDeploy bundle."
    else
        if [[ -n "${POEDEPLOY_LOG:-}" ]]; then
            warning "$name installation failed. Review $POEDEPLOY_LOG."
        else
            warning "$name installation failed. See the terminal output above."
        fi
        FAILED_PACKAGES+=("$name")
    fi
}

validate_dashboard_update_target() {
    local requested="$1" selected_file="${XDG_CONFIG_HOME:-$HOME/.config}/poedeploy/dashboard"
    local selected
    [[ -f "$selected_file" ]] || return 0
    selected=$(< "$selected_file")
    case "$selected" in
        poedash) ;;
        *) warning "Unrecognised saved dashboard selection. Reinstall the intended dashboard."; return 1 ;;
    esac
    if [[ "$selected" != "$requested" ]]; then
        warning "The selected dashboard is $selected, but this control requested $requested. Use the $selected updater to repair the bar controls."
        return 1
    fi
}
