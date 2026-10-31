#!/usr/bin/env bash

# Static TTY renderer. It owns the alternate screen while installer output goes
# to the log. It only redraws when state, view, or terminal dimensions change.

_pd_repeat() { local text="$1" count="$2" out=""; while ((count-- > 0)); do out+="$text"; done; printf '%s' "$out"; }
_pd_clean_text() {
    local LC_ALL=C.UTF-8
    export LC_ALL
    local text="$1" prefix rest csi=$'\033''\[[0-?]*[ -/]*[@-~]'
    # Captured commands may contain colours, cursor movement, OSC titles,
    # carriage returns and tabs. Treat log/state values only as visible text.
    while [[ "$text" == *$'\033]'* ]]; do
        prefix=${text%%$'\033]'*}; rest=${text#*$'\033]'}
        if [[ "$rest" == *$'\a'* ]]; then text="$prefix${rest#*$'\a'}"
        elif [[ "$rest" == *$'\033\\'* ]]; then text="$prefix${rest#*$'\033\\'}"
        else text="$prefix"; fi
    done
    while [[ "$text" =~ $csi ]]; do text=${text/"${BASH_REMATCH[0]}"/}; done
    text=${text//$'\t'/ }
    while [[ "$text" =~ [[:cntrl:]] ]]; do text=${text//"${BASH_REMATCH[0]}"/}; done
    printf '%s' "$text"
}

_pd_clip() {
    local LC_ALL=C.UTF-8
    export LC_ALL
    local text width="$2" display_width low=0 high middle candidate
    text=$(_pd_clean_text "$1")
    ((width > 0)) || return 0
    display_width=$(printf '%s' "$text" | wc -L)
    if ((display_width <= width)); then printf '%s' "$text"; return 0; fi
    # wc measures terminal columns, including wide Unicode and combining marks.
    # Binary search avoids repeatedly scanning long package/log messages.
    high=${#text}
    while ((low < high)); do
        middle=$(((low + high + 1) / 2))
        candidate=${text:0:middle}
        display_width=$(printf '%s' "$candidate" | wc -L)
        if ((display_width < width)); then low=$middle; else high=$((middle - 1)); fi
    done
    printf '%s.' "${text:0:low}"
}

_pd_terminal_size() {
    PD_TERM_ROWS=24 PD_TERM_COLS=80
    local rows cols
    if read -r rows cols < <(stty size 2>/dev/null </dev/tty) &&
       [[ "$rows" =~ ^[1-9][0-9]*$ && "$cols" =~ ^[1-9][0-9]*$ ]]; then
        PD_TERM_ROWS="$rows" PD_TERM_COLS="$cols"
    fi
}
_pd_row() {
    local LC_ALL=C.UTF-8
    export LC_ALL
    local text="$1" inner="$2" colour="${3:-}" clipped reset="" display_width
    clipped=$(_pd_clip "$text" "$inner")
    display_width=$(printf '%s' "$clipped" | wc -L)
    [[ -z "$colour" ]] || reset="${NC:-}"
    # Bash printf pads strings by bytes; UTF-8 bars and markers use several
    # bytes per character. Compute padding before adding colour escapes.
    printf '%s %s%s%s%*s %s\033[K\r\n' "$PD_BORDER_SIDE" "$colour" "$clipped" \
        "$reset" "$((inner - display_width))" '' "$PD_BORDER_SIDE"
}

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

_pd_compact_frame() {
    local cols="$1" rows="$2" i=0 line
    shift 2
    printf '\033[H'
    for line in "$@"; do
        ((i < rows)) || break
        ((i == 0)) || printf '\r\n'
        _pd_clip "$line" "$((cols > 1 ? cols - 1 : 1))"
        printf '\033[K'
        i=$((i + 1))
    done
    printf '\033[J'
}

_pd_dashboard_frame() {
    _pd_load_state || return 0
    local cols lines width inner percent filled empty bar i item status label marker
    _pd_terminal_size
    cols="$PD_TERM_COLS"; lines="$PD_TERM_ROWS"
    if ((cols < 32 || lines < 15)); then
        percent=0; ((PD_VIEW_TOTAL == 0)) || percent=$((PD_VIEW_COMPLETED * 100 / PD_VIEW_TOTAL))
        _pd_compact_frame "$cols" "$lines" "POEDEPLOY $percent%" \
            "Stage: ${PD_VIEW_STAGE:-Preparing}" "Current: ${PD_VIEW_OPERATION:-Preparing installation}" '[L] Log  [Q] Abort'
        return 0
    fi
    width=$((cols - 1)); ((width > 72)) && width=72; ((width < 24)) && width=24
    inner=$((width - 4))
    percent=0; ((PD_VIEW_TOTAL == 0)) || percent=$((PD_VIEW_COMPLETED * 100 / PD_VIEW_TOTAL))
    filled=$((percent * (inner - 7) / 100)); empty=$((inner - 7 - filled))
    bar="$(_pd_repeat "$PD_BAR_FULL" "$filled")$(_pd_repeat "$PD_BAR_EMPTY" "$empty")  ${percent}%"

    printf '\033[H%s%s%s\033[K\r\n' "$PD_BORDER_TOP_LEFT" "$(_pd_repeat "$PD_BORDER_HORIZONTAL" "$((width - 2))")" "$PD_BORDER_TOP_RIGHT"
    _pd_row "POEDEPLOY  $PD_SEPARATOR  Arch Linux installer" "$inner" "${BLUE:-}${UI_BOLD:-}"
    _pd_row "" "$inner"
    _pd_row "$bar" "$inner" "${BLUE:-}"
    _pd_row "Step ${PD_VIEW_CURRENT:-0} of ${PD_VIEW_TOTAL:-0}  $PD_SEPARATOR  ${PD_VIEW_COMPLETED:-0} completed" "$inner"
    _pd_row "Stage:   ${PD_VIEW_STAGE:-Preparing}" "$inner"
    _pd_row "Current: ${PD_VIEW_OPERATION:-Preparing installation}" "$inner"
    _pd_row "" "$inner"

    local available=$((lines - 14))
    local start=0
    if ((PD_VIEW_CURRENT > available)); then start=$((PD_VIEW_CURRENT - available)); fi
    for ((i = start; i < ${#PD_VIEW_ITEMS[@]} && i < start + available; i++)); do
        item=${PD_VIEW_ITEMS[$i]}; status=${item%%|*}; label=${item#*|}
        case "$status" in complete) marker="$PD_GLYPH_COMPLETE" ;; running) marker="$PD_GLYPH_RUNNING" ;; warning) marker='[!]' ;; failed) marker="$PD_GLYPH_FAILED" ;; *) marker="$PD_GLYPH_PENDING" ;; esac
        local colour="${UI_DIM:-}"
        case "$status" in complete) colour="${GREEN:-}" ;; running) colour="${BLUE:-}" ;; warning) colour="${YELLOW:-}" ;; failed) colour="${RED:-}" ;; esac
        _pd_row "$marker $label" "$inner" "$colour"
    done
    _pd_row "" "$inner"
    _pd_row "Warnings: ${PD_VIEW_WARNINGS:-0}  Errors: ${PD_VIEW_ERRORS:-0}" "$inner"
    _pd_row "[L] Live Log  $PD_SEPARATOR  [Q] Abort" "$inner"
    _pd_row "Log: ${PD_VIEW_LOG:-unknown}" "$inner"
    printf '%s%s%s' "$PD_BORDER_BOTTOM_LEFT" "$(_pd_repeat "$PD_BORDER_HORIZONTAL" "$((width - 2))")" "$PD_BORDER_BOTTOM_RIGHT"
    printf '\033[J'
}

_pd_log_frame() {
    _pd_load_state || return 0
    local cols lines width inner log_lines line
    _pd_terminal_size
    cols="$PD_TERM_COLS"; lines="$PD_TERM_ROWS"
    if ((cols < 32 || lines < 8)); then
        local -a compact_lines=('POEDEPLOY LIVE LOG')
        while IFS= read -r line; do compact_lines+=("$line"); done < <(tail -n "$((lines > 3 ? lines - 3 : 1))" -- "$PD_VIEW_LOG" 2>/dev/null || true)
        compact_lines+=('[Q] or [Esc] Return')
        _pd_compact_frame "$cols" "$lines" "${compact_lines[@]}"
        return 0
    fi
    width=$((cols - 1)); ((width > 100)) && width=100; ((width < 24)) && width=24
    inner=$((width - 4)); log_lines=$((lines - 7))
    printf '\033[H%s%s%s\033[K\r\n' "$PD_BORDER_TOP_LEFT" "$(_pd_repeat "$PD_BORDER_HORIZONTAL" "$((width - 2))")" "$PD_BORDER_TOP_RIGHT"
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
    printf '\033[J'
}

# Assemble each frame before writing it. Explicit CR/LF also works after an
# installer has disabled the terminal's automatic newline translation.
_pd_dashboard_draw() { local frame; frame=$(_pd_dashboard_frame); printf '%s' "$frame"; }
_pd_log_draw() { local frame; frame=$(_pd_log_frame); printf '%s' "$frame"; }

_pd_restore_terminal() {
    [[ -z "${PD_TTY_STATE:-}" ]] || stty "$PD_TTY_STATE" 2>/dev/null </dev/tty || true
}

_pd_enter_screen() {
    _pd_restore_terminal
    tput smcup 2>/dev/null || true
    tput civis 2>/dev/null || true
    printf '\033[2J\033[H'
    PD_SCREEN_ENTERED=true
}

_pd_leave_screen() {
    _pd_restore_terminal
    if [[ "${PD_SCREEN_ENTERED:-false}" == true ]]; then
        tput cnorm 2>/dev/null || true
        tput rmcup 2>/dev/null || true
        PD_SCREEN_ENTERED=false
    fi
}

_pd_dashboard_loop() {
    local view=dashboard key fingerprint="" next pause_token=""
    trap '_pd_leave_screen' EXIT
    trap 'exit 0' INT TERM
    _pd_set_glyphs
    _pd_enter_screen
    while [[ ! -e "$PD_UI_DIR/stop" ]]; do
        if [[ -e "$PD_UI_DIR/pause" ]]; then
            _pd_leave_screen
            while [[ -e "$PD_UI_DIR/pause" && ! -e "$PD_UI_DIR/stop" ]]; do
                if read -r pause_token <"$PD_UI_DIR/pause"; then
                    printf '%s\n' "$pause_token" >"$PD_UI_DIR/paused"
                fi
                sleep 0.02
            done
            [[ ! -e "$PD_UI_DIR/stop" ]] || break
            _pd_enter_screen
            fingerprint=""
        fi
        _pd_terminal_size
        next="$(stat -c '%y:%s' "$PD_UI_DIR/state" 2>/dev/null):$PD_TERM_COLS:$PD_TERM_ROWS:$view"
        if [[ "$next" != "$fingerprint" || "$view" == log ]]; then
            if [[ "$view" == log ]]; then _pd_log_draw; else _pd_dashboard_draw; fi
            fingerprint="$next"
        fi
        # Resume is acknowledged only after the new screen is fully drawn.
        rm -f -- "$PD_UI_DIR/paused"
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
    PD_TTY_STATE=$(stty -g </dev/tty)
    chmod 700 -- "$PD_UI_DIR"
    export PD_UI_DIR POEDEPLOY_LOG
    _pd_state_write
    _pd_dashboard_loop &
    PD_DASHBOARD_PID=$!
}

ui_dashboard_pause() {
    [[ "$PD_UI_ACTIVE" == true && "${PD_TERMINAL_OWNED:-false}" != true ]] || return 0
    local token="$BASHPID-$RANDOM" acknowledged="" attempts=0
    printf '%s\n' "$token" >"$PD_UI_DIR/pause.new.$BASHPID"
    mv -f -- "$PD_UI_DIR/pause.new.$BASHPID" "$PD_UI_DIR/pause"
    until [[ "$acknowledged" == "$token" ]]; do
        [[ ! -r "$PD_UI_DIR/paused" ]] || read -r acknowledged <"$PD_UI_DIR/paused" || true
        [[ "$acknowledged" != "$token" ]] || break
        if [[ -e "$PD_UI_DIR/stop" ]] || ! kill -0 "$PD_DASHBOARD_PID" 2>/dev/null || ((attempts >= 250)); then
            printf 'PoeDeploy could not hand over the terminal.\n' >/dev/tty
            return 1
        fi
        sleep 0.02
        attempts=$((attempts + 1))
    done
}

ui_dashboard_resume() {
    [[ "$PD_UI_ACTIVE" == true && "${PD_TERMINAL_OWNED:-false}" != true ]] || return 0
    [[ -e "$PD_UI_DIR/pause" || -e "$PD_UI_DIR/paused" ]] || return 0
    _pd_restore_terminal
    rm -f -- "$PD_UI_DIR/pause"
    local attempts=0
    while [[ -e "$PD_UI_DIR/paused" ]]; do
        kill -0 "$PD_DASHBOARD_PID" 2>/dev/null || return 1
        ((attempts < 250)) || return 1
        sleep 0.02
        attempts=$((attempts + 1))
    done
}

ui_cleanup() {
    local status="${1:-0}"
    if [[ "$PD_UI_ACTIVE" == true ]]; then
        if [[ -n "${PD_TASK_PID:-}" ]] && kill -0 "$PD_TASK_PID" 2>/dev/null; then
            _pd_terminate_tree "$PD_TASK_PID"
            wait "$PD_TASK_PID" 2>/dev/null || true
        fi
        # The worker can exit on Ctrl+C before cleanup checks its PID.
        PD_TASK_PID=""
        : >"$PD_UI_DIR/stop" 2>/dev/null || true
        [[ -z "${PD_DASHBOARD_PID:-}" ]] || wait "$PD_DASHBOARD_PID" 2>/dev/null || true
        rm -rf -- "$PD_UI_DIR"
        PD_UI_ACTIVE=false
    fi
    _pd_restore_terminal
    tput cnorm 2>/dev/null || true
    return "$status"
}

ui_prompt() {
    local output_name="$1" prompt="$2" silent="${3:-false}" pd_response="" pd_prompt_status=0
    if [[ "$PD_UI_ACTIVE" == true ]]; then
        ui_dashboard_pause || return $?
        if [[ "$silent" == true ]]; then
            IFS= read -rsp "$prompt" pd_response </dev/tty 2>/dev/tty || pd_prompt_status=$?
            printf '\n' >/dev/tty
        else
            IFS= read -rp "$prompt" pd_response </dev/tty 2>/dev/tty || pd_prompt_status=$?
        fi
        printf -v "$output_name" '%s' "$pd_response"
        ui_dashboard_resume || return $?
        return "$pd_prompt_status"
    fi
    if [[ "$silent" == true ]]; then
        IFS= read -rsp "$prompt" pd_response || pd_prompt_status=$?
        printf '\n'
    else
        IFS= read -rp "$prompt" pd_response || pd_prompt_status=$?
    fi
    printf -v "$output_name" '%s' "$pd_response"
    return "$pd_prompt_status"
}

# External installers and AUR tools invoke their own sudo and input readers.
# Give them the terminal for their entire run, including password retries.
ui_run_interactive() {
    if [[ "$PD_UI_ACTIVE" != true || "${PD_TERMINAL_OWNED:-false}" == true ]]; then
        "$@"
        return $?
    fi
    ui_dashboard_pause || return $?
    local status PD_TERMINAL_OWNED=true
    if "$@" </dev/tty >/dev/tty 2>&1; then status=0; else status=$?; fi
    PD_TERMINAL_OWNED=false
    ui_dashboard_resume || return $?
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
    ui_dashboard_pause || return 20
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
