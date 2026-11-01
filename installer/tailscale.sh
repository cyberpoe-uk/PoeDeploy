#!/usr/bin/env bash
# Optional desktop integration for the existing Tailscale installation flow.

tailscale_desktop_user() {
    local candidate record shell current_uid
    current_uid=$(id -u) || return 1
    if [[ "$current_uid" == 0 ]]; then
        candidate=${SUDO_USER:-}
    else
        candidate=$(id -un) || return 1
    fi
    [[ "$candidate" =~ ^[a-zA-Z_][a-zA-Z0-9_.-]*\$?$ && "$candidate" != root && "$candidate" != nobody ]] || return 1
    record=$(getent passwd "$candidate") || return 1
    local passwd_name ignored gid gecos
    IFS=: read -r passwd_name ignored TS_UID gid gecos TS_HOME shell <<< "$record"
    [[ "$passwd_name" == "$candidate" && "$TS_UID" =~ ^[0-9]+$ && "$TS_UID" -ge 1000 && "$TS_UID" != 65534 && "$TS_HOME" == /* && -d "$TS_HOME" ]] || return 1
    case "$shell" in */nologin|*/false|'') return 1 ;; esac
    TS_USER=$candidate
    TS_CONFIG="$TS_HOME/.config"
    if [[ "$current_uid" == "$TS_UID" && -n "${XDG_CONFIG_HOME:-}" && "$XDG_CONFIG_HOME" == /* ]]; then
        TS_CONFIG=$XDG_CONFIG_HOME
    fi
}

tailscale_as_user() {
    local -a identity=()
    if [[ "$(id -u)" != "$TS_UID" ]]; then
        identity=(sudo -H -u "$TS_USER" --)
    fi
    "${identity[@]}" env HOME="$TS_HOME" USER="$TS_USER" LOGNAME="$TS_USER" \
        XDG_CONFIG_HOME="$TS_CONFIG" XDG_RUNTIME_DIR="/run/user/$TS_UID" \
        DBUS_SESSION_BUS_ADDRESS="unix:path=/run/user/$TS_UID/bus" "$@"
}

tailscale_has_graphical_desktop() {
    if [[ "$(id -u)" == "$TS_UID" && ( -n "${WAYLAND_DISPLAY:-}" || -n "${DISPLAY:-}" ) ]]; then
        return 0
    fi
    # Covers installing ML4W before the first graphical login.
    [[ -f "$TS_CONFIG/hypr/hyprland.lua" || -f "$TS_CONFIG/hypr/hyprland.conf" ]] && return 0
    local session user type
    while read -r session _ user _; do
        [[ "$user" == "$TS_USER" ]] || continue
        type=$(loginctl show-session "$session" -p Type --value 2>/dev/null) || continue
        [[ "$type" == wayland || "$type" == x11 ]] && return 0
    done < <(loginctl list-sessions --no-legend 2>/dev/null || true)
    return 1
}

configure_tailscale_desktop() {
    [[ "$POEDEPLOY_IN_CHROOT" != true ]] || {
        info "Tailscale desktop integration deferred until boot. Rerun the Tailscale setup after logging in."
        return 0
    }
    if ! command -v tailscale >/dev/null 2>&1; then
        warning "Tailscale binary is missing. Reinstall tailscale and rerun its setup."
        return 0
    fi
    if ! systemctl is-active --quiet tailscaled; then
        warning "tailscaled is not running. Start it with sudo systemctl start tailscaled, then rerun setup."
        return 0
    fi
    if ! tailscale_desktop_user; then
        warning "No suitable desktop user found. Run setup as the desktop user, or set its operator explicitly with sudo tailscale set --operator=USERNAME."
        return 0
    fi
    if ! tailscale_has_graphical_desktop; then
        info "No graphical desktop found for $TS_USER. Skipping desktop operator and systray integration."
        return 0
    fi
    if sudo tailscale set "--operator=$TS_USER"; then
        success "$TS_USER can manage the local Tailscale connection without sudo (operator permission)."
    else
        warning "Could not set the Tailscale operator. Retry: sudo tailscale set --operator=$TS_USER"
    fi
    local version major minor
    version=$(tailscale version 2>/dev/null) || version=''
    if [[ "$version" =~ ^([0-9]+)\.([0-9]+)\. ]]; then
        major=${BASH_REMATCH[1]}
        minor=${BASH_REMATCH[2]}
    else
        major=0 minor=0
    fi
    if ! (( major > 1 || major == 1 && minor >= 88 )) ||
       ! tailscale systray --help >/dev/null 2>&1 ||
       ! tailscale configure systray --help >/dev/null 2>&1; then
        warning "Official systray support requires Tailscale 1.88 or newer with systray commands. Upgrade tailscale and rerun setup."
        return 0
    fi
    # Respect existing alternative launch methods rather than adding a second one.
    if [[ -f "$TS_CONFIG/autostart/tailscale-systray.desktop" ]] ||
       grep -REq -- '^[^#]*tailscale[[:space:]]+systray' "$TS_CONFIG/hypr" 2>/dev/null; then
        warning "An existing Tailscale tray autostart was found. Keep it, or remove it and rerun setup to use the official systemd service."
        return 0
    fi
    local unit="$TS_CONFIG/systemd/user/tailscale-systray.service"
    if [[ -f "$unit" ]]; then
        if ! grep -Eq '^ExecStart=.*tailscale[[:space:]]+systray([[:space:]]|$)' "$unit"; then
            warning "A custom tailscale-systray.service exists. Leaving it unchanged. Review it before enabling official tray startup."
            return 0
        fi
    elif ! tailscale_as_user tailscale configure systray --enable-startup=systemd; then
        warning "Optional tray configuration failed. Tailscale remains installed. Retry tailscale configure systray --enable-startup=systemd as $TS_USER."
        return 0
    fi
    # Keep the official unit and its D-Bus dependency. Retry if the session bus or
    # tray host starts later under Hyprland. A single named service owns the process.
    if ! tailscale_as_user sh -c '
        set -eu
        directory="$XDG_CONFIG_HOME/systemd/user/tailscale-systray.service.d"
        mkdir -p "$directory"
        printf "%s\n" "[Unit]" "After=dbus.service graphical-session-pre.target" "StartLimitIntervalSec=0" "" "[Service]" "Restart=on-failure" "RestartSec=5s" > "$directory/poedeploy.conf"
    '; then
        warning "Could not configure optional tray startup recovery. Rerun Tailscale setup."
        return 0
    fi
    if tailscale_as_user systemctl --user daemon-reload; then
        if ! tailscale_as_user systemctl --user enable tailscale-systray.service; then
            warning "Could not enable the tray. As $TS_USER, run systemctl --user enable --now tailscale-systray.service."
            return 0
        fi
        # Do not start a second instance if a manually launched tray already exists.
        if pgrep -u "$TS_UID" -f '(^|/)tailscale systray([[:space:]]|$)' >/dev/null &&
           ! tailscale_as_user systemctl --user is-active --quiet tailscale-systray.service; then
            warning "A manually started Tailscale tray is running. Automatic startup is enabled for next login."
        elif ! tailscale_as_user systemctl --user start tailscale-systray.service; then
            warning "Tray startup failed. Check journalctl --user -u tailscale-systray.service. Tailscale networking is unchanged."
        fi
    else
        # systemctl --user enable also needs the bus on some systemd versions.
        # Create the standard enablement link for the official default.target unit.
        if tailscale_as_user sh -c '
            set -eu
            units="$XDG_CONFIG_HOME/systemd/user"
            grep -Eq "^WantedBy=.*default.target" "$units/tailscale-systray.service"
            mkdir -p "$units/default.target.wants"
            link="$units/default.target.wants/tailscale-systray.service"
            if [ -e "$link" ] || [ -L "$link" ]; then
                test "$(readlink -f "$link")" = "$(readlink -f "$units/tailscale-systray.service")"
            else
                ln -s ../tailscale-systray.service "$link"
            fi
        '; then
            info "User D-Bus/systemd session is unavailable. The enabled tray service will start at the next desktop login."
        else
            warning "User session is unavailable. At desktop login, run systemctl --user daemon-reload and systemctl --user enable --now tailscale-systray.service."
        fi
    fi
}
