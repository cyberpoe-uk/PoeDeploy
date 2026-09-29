#!/usr/bin/env bash

# Central installer state. State is copied atomically for the renderer.

PD_UI_ACTIVE=false
PD_CURRENT_STAGE=0
PD_COMPLETED_STAGES=0
PD_TOTAL_STAGES=0
PD_CURRENT_STAGE_NAME="Preparing"
PD_CURRENT_OPERATION="Preparing installation"
PD_WARNING_COUNT=0
PD_ERROR_COUNT=0
PD_UI_DIR=""
PD_TASK_PID=""
PD_STAGE_NAMES=()
PD_STAGE_STATUS=()

_pd_state_write() {
    [[ "$PD_UI_ACTIVE" == true && -n "$PD_UI_DIR" ]] || return 0
    local target="$PD_UI_DIR/state" temporary="$PD_UI_DIR/state.new.$$" i
    {
        printf 'current_stage=%s\ncompleted=%s\ntotal=%s\nwarnings=%s\nerrors=%s\n' \
            "$PD_CURRENT_STAGE" "$PD_COMPLETED_STAGES" "$PD_TOTAL_STAGES" \
            "$PD_WARNING_COUNT" "$PD_ERROR_COUNT"
        printf 'stage_name=%s\noperation=%s\nlog=%s\n' \
            "${PD_CURRENT_STAGE_NAME//$'\n'/ }" "${PD_CURRENT_OPERATION//$'\n'/ }" "${POEDEPLOY_LOG//$'\n'/ }"
        for ((i = 0; i < PD_TOTAL_STAGES; i++)); do
            printf 'item=%s|%s\n' "${PD_STAGE_STATUS[$i]}" "${PD_STAGE_NAMES[$i]//$'\n'/ }"
        done
    } >"$temporary"
    mv -f -- "$temporary" "$target"
}

ui_progress_init() {
    PD_STAGE_NAMES=("$@")
    PD_TOTAL_STAGES=${#PD_STAGE_NAMES[@]}
    PD_STAGE_STATUS=()
    local i
    for ((i = 0; i < PD_TOTAL_STAGES; i++)); do PD_STAGE_STATUS+=(pending); done
    PD_CURRENT_STAGE=0
    PD_COMPLETED_STAGES=0
    PD_CURRENT_STAGE_NAME="Preparing"
    PD_CURRENT_OPERATION="Starting installer"
    PD_WARNING_COUNT=0
    PD_ERROR_COUNT=0
    _pd_state_write
}

ui_step_start() {
    local index="$1" name="$2"
    PD_CURRENT_STAGE="$index"
    PD_CURRENT_STAGE_NAME="$name"
    PD_CURRENT_OPERATION="Starting $name"
    PD_STAGE_STATUS[$((index - 1))]=running
    _pd_state_write
}

ui_set_operation() {
    PD_CURRENT_OPERATION="$1"
    _pd_state_write
}

ui_step_complete() {
    local index="$1"
    PD_STAGE_STATUS[$((index - 1))]=complete
    PD_COMPLETED_STAGES="$index"
    PD_CURRENT_OPERATION="Completed ${PD_STAGE_NAMES[$((index - 1))]}"
    _pd_state_write
}

ui_step_warning() {
    PD_WARNING_COUNT=$((PD_WARNING_COUNT + 1))
    PD_CURRENT_OPERATION="$1"
    _pd_state_write
}

ui_step_failed() {
    local index="$1" message="$2"
    PD_STAGE_STATUS[$((index - 1))]=failed
    PD_ERROR_COUNT=$((PD_ERROR_COUNT + 1))
    PD_CURRENT_OPERATION="$message"
    _pd_state_write
}
