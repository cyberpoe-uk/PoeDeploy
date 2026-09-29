#!/usr/bin/env bash

# Logging and command execution. This file deliberately contains no terminal UI.

pd_logger_init() {
    local preferred_log=/var/log/poedeploy.log
    local state_root="${XDG_STATE_HOME:-$HOME/.local/state}/poedeploy"

    if [[ -w /var/log && ( ! -e "$preferred_log" || -w "$preferred_log" ) ]]; then
        POEDEPLOY_LOG="$preferred_log"
    else
        mkdir -p -- "$state_root"
        chmod 700 -- "$state_root" 2>/dev/null || true
        POEDEPLOY_LOG="$state_root/poedeploy.log"
    fi

    touch -- "$POEDEPLOY_LOG"
    chmod 600 -- "$POEDEPLOY_LOG" 2>/dev/null || true
    printf '\n[%(%Y-%m-%d %H:%M:%S)T] PoeDeploy %s started\n' -1 "${SCRIPT_VERSION:-unknown}" >>"$POEDEPLOY_LOG"
}

pd_log() {
    local level="$1"
    shift
    [[ -n "${POEDEPLOY_LOG:-}" ]] || return 0
    printf '[%(%H:%M:%S)T] [%s] %s\n' -1 "$level" "$*" >>"$POEDEPLOY_LOG"
}

run_cmd() {
    local description="$1"
    shift
    ui_set_operation "$description"
    pd_log COMMAND "$description"
    if "$@" >>"$POEDEPLOY_LOG" 2>&1; then
        pd_log OK "$description"
        return 0
    fi
    local status=$?
    pd_log ERROR "$description (exit code $status)"
    return "$status"
}

run_cmd_capture() {
    local output_name="$1" description="$2"
    shift 2
    local output status
    ui_set_operation "$description"
    pd_log COMMAND "$description"
    if output=$("$@" 2>>"$POEDEPLOY_LOG"); then
        printf -v "$output_name" '%s' "$output"
        pd_log OK "$description"
        return 0
    fi
    status=$?
    pd_log ERROR "$description (exit code $status)"
    return "$status"
}
