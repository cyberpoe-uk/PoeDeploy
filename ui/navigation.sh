#!/usr/bin/env bash
# Planning is reversible. These screens never run installers or change the host.
can_use_navigation_menu() {
    [[ -t 2 && "${TERM:-dumb}" != dumb ]] && (: </dev/tty) 2>/dev/null
}

ui_nav_key() {
    local key='' suffix=''
    IFS= read -rsn1 key </dev/tty || return 130
    if [[ "$key" == $'\e' ]]; then
        if IFS= read -rsn1 -t .05 suffix </dev/tty; then
            if [[ "$suffix" == '[' || "$suffix" == O ]]; then
                IFS= read -rsn1 -t .05 suffix </dev/tty || :
                case "$suffix" in A) printf up ;; B) printf down ;; *) printf ignored ;; esac
            else
                printf ignored
            fi
        else
            printf back
        fi
    else
        case "$key" in
            $'\177'|$'\b') printf backspace ;;
            $'\003') return 130 ;;
            '') printf enter ;;
            ' '|x) printf toggle ;;
            j) printf down ;;
            k) printf up ;;
            *) printf ignored ;;
        esac
    fi
}

ui_nav_header() {
    local rows="$1" cols="$2" title="$3"
    # Render on the terminal rather than captured selection stdout, so the
    # shared header detects colour support and honours NO_COLOR correctly.
    initialise_ui
    printf '\033[H\033[2J'
    if ((rows >= 24 && cols >= 54)); then
        show_header
    fi
    printf '%bPoeDeploy · %s%b\n\n' "${BLUE}${UI_BOLD}" "$title" "$NC"
}

ui_nav_choose() {
    local header="$1" multiple="${2:-false}" defaults="${3:-}" description="${4:-}" key selected=0 top=0 index label marker rows=24 limit=14 cols=80 extra=0
    local -a options=()
    local -A checked=()
    mapfile -t options
    ((${#options[@]})) || return 1
    while IFS= read -r label; do [[ -z "$label" ]] || checked["$label"]=true; done <<< "$defaults"
    while true; do
        read -r rows cols < <(stty size </dev/tty 2>/dev/null) || rows=24
        [[ "$rows" =~ ^[0-9]+$ ]] || rows=24
        extra=0
        [[ -z "$description" ]] || extra=4
        # Reserve the artwork as well as the footer before sizing the list.
        if ((rows >= 24 && cols >= 54)); then extra=$((extra + 11)); fi
        limit=$((rows > 12 ? rows - 8 - extra : 4))
        ((limit >= 2)) || limit=2
        ((limit <= 17)) || limit=17
        ((selected >= top)) || top=$selected
        ((selected < top + limit)) || top=$((selected - limit + 1))
        ui_nav_header "$rows" "$cols" "$header" >/dev/tty
        if [[ -n "$description" ]]; then
            while IFS= read -r label; do printf '%.*s\n' "$((cols > 8 ? cols - 4 : 20))" "$label" >/dev/tty; done <<< "$description"
            printf '\n' >/dev/tty
        fi
        for ((index=top; index<${#options[@]} && index<top+limit; index++)); do
            marker=' '
            [[ "${checked[${options[$index]}]:-false}" != true ]] || marker=x
            if ((index == selected)); then
                printf '%b> ' "${BLUE}${UI_BOLD}"
            elif [[ "$marker" == x ]]; then
                printf '%b  ' "$CYAN"
            else printf '  '; fi >/dev/tty
            if [[ "$multiple" == true ]]; then printf '[%s] ' "$marker" >/dev/tty; fi
            printf '%s%b\n' "${options[$index]}" "$NC" >/dev/tty
        done
        printf '\n↑/↓ or j/k move · ' >/dev/tty
        [[ "$multiple" != true ]] || printf 'Space/x toggle · ' >/dev/tty
        printf 'Enter continue\nEsc/Backspace previous screen · Ctrl+C cancel\n' >/dev/tty
        if key=$(ui_nav_key); then :; else return 130; fi
        case "$key" in
            up) selected=$(((selected + ${#options[@]} - 1) % ${#options[@]})) ;;
            down) selected=$(((selected + 1) % ${#options[@]})) ;;
            toggle)
                if [[ "${checked[${options[$selected]}]:-false}" == true ]]; then
                    unset 'checked[${options[$selected]}]'
                else checked["${options[$selected]}"]=true; fi
                ;;
            back) return 125 ;;
            backspace) return 126 ;;
            enter)
                if [[ "$multiple" == true ]]; then
                    for label in "${options[@]}"; do [[ "${checked[$label]:-false}" != true ]] || printf '%s\n' "$label"; done
                else printf '%s\n' "${options[$selected]}"; fi
                return 0
                ;;
        esac
    done
}

ui_nav_prompt() {
    local output="$1" prompt="$2" value='' key suffix
    printf '\n%s\nEsc goes back. Backspace edits, or goes back when the field is empty.\n> ' "$prompt" >/dev/tty
    while IFS= read -rsn1 key </dev/tty; do
        case "$key" in
            '') printf '\n' >/dev/tty; printf -v "$output" '%s' "$value"; return 0 ;;
            $'\e')
                if IFS= read -rsn1 -t .05 suffix </dev/tty; then
                    [[ "$suffix" != '[' ]] || IFS= read -rsn1 -t .05 suffix </dev/tty || :
                else return 125; fi ;;
            $'\177'|$'\b')
                if [[ -z "$value" ]]; then return 126; fi
                value=${value%?}; printf '\b \b' >/dev/tty ;;
            $'\003') return 130 ;;
            *)
                if [[ "$key" != [[:cntrl:]] ]]; then value+="$key"; printf '%s' "$key" >/dev/tty; fi ;;
        esac
    done
    return 130
}

interactive_plan() {
    local screen=welcome previous=sections selection status module label defaults name summary
    local -a options=()
    while true; do
        case "$screen" in
            welcome)
                if selection=$(printf '%s\n' 'Choose sections' 'Full setup' 'Exit' | ui_nav_choose 'Welcome'); then
                    case "$selection" in
                        'Choose sections') RUN_MODE=selected; screen=sections ;;
                        'Full setup')
                            RUN_MODE=full; SELECTED_SETUP_MODULES=()
                            for module in "${SETUP_MODULE_IDS[@]}"; do SELECTED_SETUP_MODULES["$module"]=true; done
                            # No dependency installation merely to detect the model/codec.
                            if ! matebook_audio_product_matches || ! matebook_audio_subsystem_matches; then
                                unset 'SELECTED_SETUP_MODULES[matebook_audio]'
                            fi
                            screen=applications ;;
                        *) return 1 ;;
                    esac
                else status=$?; [[ "$status" != 130 ]] || return 130; [[ "$status" != 126 ]] || continue; return 1; fi
                ;;
            sections)
                options=(); defaults=''
                for module in "${SETUP_MODULE_IDS[@]}"; do
                    options+=("${SETUP_MODULE_LABELS[$module]}")
                    [[ "${SELECTED_SETUP_MODULES[$module]:-false}" != true ]] || defaults+="${SETUP_MODULE_LABELS[$module]}"$'\n'
                done
                if selection=$(printf '%s\n' "${options[@]}" | ui_nav_choose 'Setup sections' true "$defaults"); then
                    [[ -n "$selection" ]] || continue
                    SELECTED_SETUP_MODULES=()
                    while IFS= read -r label; do
                        for module in "${SETUP_MODULE_IDS[@]}"; do
                            [[ "$label" != "${SETUP_MODULE_LABELS[$module]}" ]] || SELECTED_SETUP_MODULES["$module"]=true
                        done
                    done <<< "$selection"
                    screen=applications
                else status=$?; [[ "$status" != 130 ]] || return 130; screen=welcome; fi
                ;;
            applications)
                if [[ "${SELECTED_SETUP_MODULES[applications]:-false}" != true ]]; then previous=sections; screen=review; continue; fi
                mapfile -t options < <(printf '%s\n' "${!APPLICATIONS[@]}" | sort)
                defaults=$(printf '%s\n' "${SELECTED_APPS[@]}")
                if selection=$(printf '%s\n' "${options[@]}" | ui_nav_choose 'Optional applications' true "$defaults"); then
                    SELECTED_APPS=(); SELECTED_PACKAGES=()
                    if [[ -n "$selection" ]]; then mapfile -t SELECTED_APPS <<< "$selection"; fi
                    for label in "${SELECTED_APPS[@]}"; do
                        SELECTED_PACKAGES+=("${APPLICATIONS[$label]}")
                        case "${APPLICATIONS[$label]}" in
                            proton-vpn-gtk-app) SELECTED_PACKAGES+=(networkmanager gnome-keyring) ;;
                            vlc) SELECTED_PACKAGES+=(vlc-plugins-all) ;;
                        esac
                    done
                    APPLICATIONS_ACTION='selected packages processed'
                    if [[ " ${SELECTED_PACKAGES[*]} " == *' @poedash '* ]]; then screen=subtitle; else previous=applications; screen=review; fi
                else status=$?; [[ "$status" != 130 ]] || return 130; [[ "$RUN_MODE" != full ]] && screen=sections || screen=welcome; fi
                ;;
            subtitle)
                if ui_nav_prompt name "Dashboard subtitle [${POEDASH_NAME:-PoeDash}]: "; then
                    name=${name:-${POEDASH_NAME:-PoeDash}}
                    (( ${#name} <= 32 )) || continue
                    POEDASH_NAME=$name; previous=subtitle; screen=review
                else status=$?; [[ "$status" != 130 ]] || return 130; screen=applications; fi
                ;;
            review)
                summary="Mode: $RUN_MODE · ${#SELECTED_SETUP_MODULES[@]} setup sections"$'\n'
                summary+="Applications: ${SELECTED_APPS[*]:-none}"$'\n'
                summary+="Install starts system changes. Go back to revise the plan."
                if selection=$(printf '%s\n' 'Install selected sections' 'Edit setup sections' 'Edit applications' 'Back to beginning' | ui_nav_choose 'Review plan' false '' "$summary"); then
                    case "$selection" in
                        'Install selected sections') return 0 ;;
                        'Edit setup sections') RUN_MODE=selected; screen=sections ;;
                        'Edit applications')
                            if [[ "${SELECTED_SETUP_MODULES[applications]:-false}" == true ]]; then screen=applications; else screen=sections; fi ;;
                        *) screen=welcome ;;
                    esac
                else status=$?; [[ "$status" != 130 ]] || return 130; screen=$previous; fi
                ;;
        esac
    done
}
