#!/usr/bin/env bash

# Static TTY renderer. It owns the alternate screen while installer output goes
# to the log. It only redraws when state, view, or terminal dimensions change.

_pd_repeat() { local text="$1" count="$2" out=""; while ((count-- > 0)); do out+="$text"; done; printf '%s' "$out"; }
_pd_clip() { local text="$1" width="$2"; ((${#text} <= width)) && printf '%s' "$text" || printf '%s' "${text:0:$((width - 1))}."; }
_pd_row() { local text="$1" inner="$2" clipped; clipped=$(_pd_clip "$text" "$inner"); printf '%s %-*s %s\n' "$PD_BORDER_SIDE" "$inner" "$clipped" "$PD_BORDER_SIDE"; }

_pd_set_glyphs() {
    if [[ "${LC_ALL:-${LC_CTYPE:-${LANG:-}}}" == *UTF-8* || "${LC_ALL:-${LC_CTYPE:-${LANG:-}}}" == *utf8* ]]; then
        PD_GLYPH_COMPLETE='✓'; PD_GLYPH_RUNNING='→'; PD_GLYPH_PENDING='○'; PD_GLYPH_FAILED='✗'
        PD_BAR_FULL='█'; PD_BAR_EMPTY='░'
        PD_BORDER_TOP_LEFT='╭'; PD_BORDER_TOP_RIGHT='╮'; PD_BORDER_BOTTOM_LEFT='╰'; PD_BORDER_BOTTOM_RIGHT='╯'
        PD_BORDER_SIDE='│'; PD_BORDER_HORIZONTAL='─'
        PD_SEPARATOR='·'
    else
        PD_GLYPH_COMPLETE='[OK]'; PD_GLYPH_RUNNING='[>>]'; PD_GLYPH_PENDING='[ ]'; PD_GLYPH_FAILED='[X]'
        PD_BAR_FULL='#'; PD_BAR_EMPTY='-'
        PD_BORDER_TOP_LEFT='+'; PD_BORDER_TOP_RIGHT='+'; PD_BORDER_BOTTOM_LEFT='+'; PD_BORDER_BOTTOM_RIGHT='+'
        PD_BORDER_SIDE='|'; PD_BORDER_HORIZONTAL='-'
        PD_SEPARATOR='-'
    fi
}

_pd_load_state() {
    local line key value
    PD_VIEW_ITEMS=()
    [[ -r "$PD_UI_DIR/state" ]] || return 1
    while IFS= read -r line; do
        key=${line%%=*}; value=${line#*=}
        case "$key" in
            current_stage) PD_VIEW_CURRENT="$value" ;;
            completed) PD_VIEW_COMPLETED="$value" ;;
            total) PD_VIEW_TOTAL="$value" ;;
            warnings) PD_VIEW_WARNINGS="$value" ;;
            errors) PD_VIEW_ERRORS="$value" ;;
            stage_name) PD_VIEW_STAGE="$value" ;;
            operation) PD_VIEW_OPERATION="$value" ;;
            log) PD_VIEW_LOG="$value" ;;
            item) PD_VIEW_ITEMS+=("$value") ;;
        esac
    done <"$PD_UI_DIR/state"
}

_pd_dashboard_draw() {
    _pd_load_state || return 0
    local cols lines width inner percent filled empty bar i item status label marker
    cols=$(tput cols 2>/dev/null || printf 80); lines=$(tput lines 2>/dev/null || printf 24)
    [[ "$cols" =~ ^[0-9]+$ ]] || cols=80
    [[ "$lines" =~ ^[0-9]+$ ]] || lines=24
    if ((cols < 32 || lines < 12)); then
        percent=0; ((PD_VIEW_TOTAL == 0)) || percent=$((PD_VIEW_COMPLETED * 100 / PD_VIEW_TOTAL))
        tput cup 0 0 2>/dev/null || printf '\033[H'
        printf 'POEDEPLOY %s%%\n' "$percent"
        _pd_clip "Stage: ${PD_VIEW_STAGE:-Preparing}" "$cols"; printf '\n'
        _pd_clip "Current: ${PD_VIEW_OPERATION:-Preparing installation}" "$cols"; printf '\n'
        printf '[L] Log  [Q] Abort\n'
        tput ed 2>/dev/null || printf '\033[J'
        return 0
    fi
    width=$((cols - 1)); ((width > 72)) && width=72; ((width < 24)) && width=24
    inner=$((width - 4))
    percent=0; ((PD_VIEW_TOTAL == 0)) || percent=$((PD_VIEW_COMPLETED * 100 / PD_VIEW_TOTAL))
    filled=$((percent * (inner - 7) / 100)); empty=$((inner - 7 - filled))
    bar="$(_pd_repeat "$PD_BAR_FULL" "$filled")$(_pd_repeat "$PD_BAR_EMPTY" "$empty")  ${percent}%"

    tput cup 0 0 2>/dev/null || printf '\033[H'
    printf '%s%s%s\n' "$PD_BORDER_TOP_LEFT" "$(_pd_repeat "$PD_BORDER_HORIZONTAL" "$((width - 2))")" "$PD_BORDER_TOP_RIGHT"
    _pd_row "POEDEPLOY  $PD_SEPARATOR  Arch Linux installer" "$inner"
    _pd_row "" "$inner"
    _pd_row "$bar" "$inner"
    _pd_row "Step ${PD_VIEW_CURRENT:-0} of ${PD_VIEW_TOTAL:-0}  $PD_SEPARATOR  ${PD_VIEW_COMPLETED:-0} completed" "$inner"
    _pd_row "Stage:   ${PD_VIEW_STAGE:-Preparing}" "$inner"
    _pd_row "Current: ${PD_VIEW_OPERATION:-Preparing installation}" "$inner"
    _pd_row "" "$inner"

    local available=$((lines - 14)); ((available < 2)) && available=2
    local start=0
    if ((PD_VIEW_CURRENT > available)); then start=$((PD_VIEW_CURRENT - available)); fi
    for ((i = start; i < ${#PD_VIEW_ITEMS[@]} && i < start + available; i++)); do
        item=${PD_VIEW_ITEMS[$i]}; status=${item%%|*}; label=${item#*|}
        case "$status" in complete) marker="$PD_GLYPH_COMPLETE" ;; running) marker="$PD_GLYPH_RUNNING" ;; warning) marker='[!]' ;; failed) marker="$PD_GLYPH_FAILED" ;; *) marker="$PD_GLYPH_PENDING" ;; esac
        _pd_row "$marker $label" "$inner"
    done
    _pd_row "" "$inner"
    _pd_row "Warnings: ${PD_VIEW_WARNINGS:-0}  Errors: ${PD_VIEW_ERRORS:-0}" "$inner"
    _pd_row "[L] Live Log  $PD_SEPARATOR  [Q] Abort" "$inner"
    _pd_row "Log: ${PD_VIEW_LOG:-unknown}" "$inner"
    printf '%s%s%s' "$PD_BORDER_BOTTOM_LEFT" "$(_pd_repeat "$PD_BORDER_HORIZONTAL" "$((width - 2))")" "$PD_BORDER_BOTTOM_RIGHT"
    tput ed 2>/dev/null || printf '\033[J'
}

_pd_log_draw() {
    _pd_load_state || return 0
    local cols lines width inner log_lines
    cols=$(tput cols 2>/dev/null || printf 80); lines=$(tput lines 2>/dev/null || printf 24)
    if ((cols < 32 || lines < 8)); then
        tput cup 0 0 2>/dev/null || printf '\033[H'
        printf 'POEDEPLOY LIVE LOG\n'
        tail -n "$((lines > 3 ? lines - 3 : 1))" -- "$PD_VIEW_LOG" 2>/dev/null || true
        printf '[Q] or [Esc] Return\n'
        tput ed 2>/dev/null || printf '\033[J'
        return 0
    fi
    width=$((cols - 1)); ((width > 100)) && width=100; ((width < 24)) && width=24
    inner=$((width - 4)); log_lines=$((lines - 7)); ((log_lines < 3)) && log_lines=3
    tput cup 0 0 2>/dev/null || printf '\033[H'
    printf '%s%s%s\n' "$PD_BORDER_TOP_LEFT" "$(_pd_repeat "$PD_BORDER_HORIZONTAL" "$((width - 2))")" "$PD_BORDER_TOP_RIGHT"
    _pd_row "POEDEPLOY LIVE LOG" "$inner"
    _pd_row "" "$inner"
    if [[ -r "$PD_VIEW_LOG" ]]; then
        while IFS= read -r line; do _pd_row "$line" "$inner"; done < <(tail -n "$log_lines" -- "$PD_VIEW_LOG")
    else
        _pd_row "The log is not available yet." "$inner"
    fi
    _pd_row "" "$inner"
    _pd_row "[Q] or [Esc] Return" "$inner"
    printf '%s%s%s' "$PD_BORDER_BOTTOM_LEFT" "$(_pd_repeat "$PD_BORDER_HORIZONTAL" "$((width - 2))")" "$PD_BORDER_BOTTOM_RIGHT"
    tput ed 2>/dev/null || printf '\033[J'
}

_pd_dashboard_loop() {
    local view=dashboard key fingerprint="" next
    trap 'tput cnorm 2>/dev/null || true; tput rmcup 2>/dev/null || true; exit 0' EXIT INT TERM
    _pd_set_glyphs
    tput smcup 2>/dev/null || true
    tput civis 2>/dev/null || true
    while [[ ! -e "$PD_UI_DIR/stop" ]]; do
        if [[ -e "$PD_UI_DIR/pause" ]]; then
            tput cnorm 2>/dev/null || true
            tput rmcup 2>/dev/null || true
            : >"$PD_UI_DIR/paused"
            while [[ -e "$PD_UI_DIR/pause" && ! -e "$PD_UI_DIR/stop" ]]; do sleep 0.05; done
            rm -f -- "$PD_UI_DIR/paused"
            [[ ! -e "$PD_UI_DIR/stop" ]] || break
            tput smcup 2>/dev/null || true
            tput civis 2>/dev/null || true
            fingerprint=""
        fi
        next="$(stat -c '%y:%s' "$PD_UI_DIR/state" 2>/dev/null):$(tput cols 2>/dev/null):$(tput lines 2>/dev/null):$view"
        if [[ "$next" != "$fingerprint" || "$view" == log ]]; then
            if [[ "$view" == log ]]; then _pd_log_draw; else _pd_dashboard_draw; fi
            fingerprint="$next"
        fi
        key=$(_pd_read_key) || key=""
        if [[ "$view" == log ]]; then
            case "$key" in q|Q|$'\e') view=dashboard; fingerprint="" ;; esac
        else
            case "$key" in l|L) view=log; fingerprint="" ;; q|Q) _pd_request_abort ;; esac
        fi
    done
}

ui_dashboard_start() {
    [[ -t 0 && -t 1 && "${TERM:-dumb}" != dumb ]] || return 0
    PD_UI_ACTIVE=true
    PD_UI_DIR=$(mktemp -d -t poedeploy-ui-XXXXXXXX)
    PD_UI_OWNER_PID=$BASHPID
    chmod 700 -- "$PD_UI_DIR"
    export PD_UI_DIR POEDEPLOY_LOG PD_UI_OWNER_PID
    _pd_state_write
    _pd_dashboard_loop &
    PD_DASHBOARD_PID=$!
}

ui_dashboard_pause() {
    [[ "$PD_UI_ACTIVE" == true ]] || return 0
    if [[ "$BASHPID" != "${PD_UI_OWNER_PID:-$BASHPID}" ]]; then
        : >"$PD_UI_DIR/pause"
        local attempts=0
        until [[ -e "$PD_UI_DIR/paused" || -e "$PD_UI_DIR/stop" ]]; do
            sleep 0.05
            attempts=$((attempts + 1))
            ((attempts < 100)) || break
        done
        return 0
    fi
    : >"$PD_UI_DIR/stop"
    wait "${PD_DASHBOARD_PID:-}" 2>/dev/null || true
    PD_DASHBOARD_PID=""
}

ui_dashboard_resume() {
    [[ "$PD_UI_ACTIVE" == true ]] || return 0
    if [[ "$BASHPID" != "${PD_UI_OWNER_PID:-$BASHPID}" ]]; then
        rm -f -- "$PD_UI_DIR/pause"
        return 0
    fi
    rm -f -- "$PD_UI_DIR/stop"
    _pd_dashboard_loop &
    PD_DASHBOARD_PID=$!
}

ui_cleanup() {
    local status="${1:-0}"
    if [[ "$PD_UI_ACTIVE" == true ]]; then
        : >"$PD_UI_DIR/stop" 2>/dev/null || true
        [[ -z "${PD_DASHBOARD_PID:-}" ]] || wait "$PD_DASHBOARD_PID" 2>/dev/null || true
        rm -rf -- "$PD_UI_DIR"
        PD_UI_ACTIVE=false
    fi
    tput cnorm 2>/dev/null || true
    stty echo 2>/dev/null || true
    return "$status"
}

ui_prompt() {
    local output_name="$1" prompt="$2" silent="${3:-false}" response=""
    if [[ "$PD_UI_ACTIVE" != true ]]; then
        if [[ "$silent" == true ]]; then
            IFS= read -rsp "$prompt" response
            printf '\n'
        else
            IFS= read -rp "$prompt" response
        fi
        local fallback_status=$?
        printf -v "$output_name" '%s' "$response"
        return "$fallback_status"
    fi
    ui_dashboard_pause
    if [[ "$silent" == true ]]; then
        IFS= read -rsp "$prompt" response </dev/tty
        printf '\n' >/dev/tty
    else
        IFS= read -rp "$prompt" response </dev/tty
    fi
    local status=$?
    printf -v "$output_name" '%s' "$response"
    ui_dashboard_resume
    return "$status"
}

ui_complete() {
    PD_CURRENT_STAGE="$PD_TOTAL_STAGES"
    PD_COMPLETED_STAGES="$PD_TOTAL_STAGES"
    PD_CURRENT_STAGE_NAME="Installation complete"
    PD_CURRENT_OPERATION="System setup finished"
    _pd_state_write
    sleep 1
    ui_dashboard_pause
}

ui_error_screen() {
    local stage="$1" status="$2" safe_skip="${3:-false}" choices='[R]etry, [L]og, [A]bort'
    [[ "$safe_skip" != true ]] || choices='[R]etry, [L]og, [S]kip, [A]bort'
    ui_dashboard_pause
    printf '\nPoeDeploy installation error\nStage: %s\nExit code: %s\nLog: %s\n' "$stage" "$status" "$POEDEPLOY_LOG" >/dev/tty
    printf '%s: ' "$choices" >/dev/tty
    local key
    while IFS= read -rsn1 key </dev/tty; do
        case "$key" in
            r|R) printf '\n' >/dev/tty; ui_dashboard_resume; return 10 ;;
            l|L) less +G -- "$POEDEPLOY_LOG" </dev/tty >/dev/tty 2>&1 || true; printf '\nPress [R] to retry or [A] to abort: ' >/dev/tty ;;
            s|S) [[ "$safe_skip" == true ]] || continue; printf '\n' >/dev/tty; ui_dashboard_resume; return 30 ;;
            a|A|$'\e') printf '\n' >/dev/tty; return 20 ;;
        esac
    done
    return 20
}
