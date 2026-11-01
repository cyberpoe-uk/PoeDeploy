#!/usr/bin/env bash
# Optional hardware workaround; all codec access is gated again in the service.
matebook_audio_product_matches() {
    [[ -r /sys/class/dmi/id/product_name && "$(</sys/class/dmi/id/product_name)" == HKF-WXX ]]
}

matebook_audio_subsystem_matches() {
    # Preflight with Bash before installing even Python on unsupported hardware.
    local path line count=0
    for path in "${1:-/proc/asound}"/card[0-9]*/codec\#*; do
        [[ -r "$path" ]] || continue
        while IFS= read -r line || [[ -n "$line" ]]; do
            if [[ "$line" =~ ^Subsystem\ Id:[[:space:]]*(0x[[:xdigit:]]+)[[:space:]]*$ ]] &&
               [[ "${BASH_REMATCH[1],,}" == 0x19e53285 ]]; then
                count=$((count + 1))
            fi
        done < "$path"
    done
    ((count == 1))
}

matebook_audio_codec_matches() {
    python3 "$SCRIPT_DIR/installer/matebook-audio/routing.py" --check
}

setup_matebook_audio() {
    local answer
    ui_heading "Huawei MateBook 14s audio workaround"
    if [[ "${POEDEPLOY_IN_CHROOT:-false}" == true ]]; then
        warning "MateBook audio setup needs the running laptop. Rerun this section after first boot."
        return 0
    fi
    if ! matebook_audio_product_matches; then
        info "MateBook audio workaround skipped: product is not HKF-WXX."
        return 0
    fi
    if ! matebook_audio_subsystem_matches; then
        warning "No unique codec with subsystem ID 0x19e53285 found. Nothing changed; rerun after audio hardware is available."
        return 0
    fi
    info "Optional speaker/headphone routing for HKF-WXX + codec subsystem 0x19e53285 only."
    info "Keeps SOF, PulseAudio/PipeWire policy, microphones and audio power saving intact."
    ui_prompt answer "Install the MateBook 14s audio routing workaround? [y/N]: "
    [[ "$answer" =~ ^[Yy]$ ]] || return 0
    ensure_command_dependencies python3:python hda-verb:alsa-tools
    if ! matebook_audio_codec_matches; then
        warning "Codec verification failed or hardware changed. No routing service installed."
        return 0
    fi
    # libasound is an alsa-tools runtime dependency on Arch; no AUR components.
    sudo install -d -o root -g root -m 0755 /usr/local/lib/poedeploy /etc/systemd/system /usr/lib/systemd/system-sleep
    sudo install -o root -g root -m 0755 "$SCRIPT_DIR/installer/matebook-audio/routing.py" /usr/local/lib/poedeploy/matebook-audio.py
    sudo install -o root -g root -m 0644 "$SCRIPT_DIR/installer/matebook-audio/poedeploy-matebook-audio.service" /etc/systemd/system/poedeploy-matebook-audio.service
    sudo install -o root -g root -m 0755 "$SCRIPT_DIR/installer/matebook-audio/resume.sh" /usr/lib/systemd/system-sleep/poedeploy-matebook-audio
    sudo systemctl daemon-reload
    sudo systemctl enable poedeploy-matebook-audio.service
    # Restart even if enabled already: refreshed code/unit files take effect now.
    sudo systemctl restart poedeploy-matebook-audio.service
    success "MateBook audio event listener enabled. Physical headphone/resume testing is still required."
    info "Logs: journalctl -u poedeploy-matebook-audio.service -b"
}
