#!/usr/bin/env bash

_pd_read_key() {
    local key=""
    IFS= read -rsn1 -t 0.2 key </dev/tty || return 1
    printf '%s' "$key"
}

_pd_request_abort() {
    [[ -n "${PD_UI_DIR:-}" ]] || return 0
    : >"$PD_UI_DIR/abort"
    local task_pid=""
    [[ ! -r "$PD_UI_DIR/task_pid" ]] || read -r task_pid <"$PD_UI_DIR/task_pid"
    [[ -z "$task_pid" ]] || _pd_terminate_tree "$task_pid"
}

_pd_terminate_tree() {
    local parent="$1" child
    while IFS= read -r child; do
        [[ -z "$child" ]] || _pd_terminate_tree "$child"
    done < <(pgrep -P "$parent" 2>/dev/null || true)
    kill -TERM "$parent" 2>/dev/null || true
}
