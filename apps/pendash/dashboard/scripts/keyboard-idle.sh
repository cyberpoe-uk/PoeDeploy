#!/usr/bin/env bash
set -eu
state="${XDG_RUNTIME_DIR:?}/poedash-keyboard-brightness"
case "${1:-}" in
  off)
    for path in /sys/class/leds/*kbd_backlight; do
      [ -r "$path/brightness" ] || continue
      name=${path##*/}
      # This Lenovo's binary interface hides the physical low/high level.
      # Off/on cannot reliably restore it, so preserve the manual setting.
      if [ "$name" = "platform::kbd_backlight" ] && [ "$(cat "$path/max_brightness")" = 1 ]; then
        exit 0
      fi
      [ -e "$state" ] || printf '%s %s\n' "$name" "$(cat "$path/brightness")" > "$state"
      brightnessctl -q -d "$name" set 0
      break
    done ;;
  restore)
    if [ -r "$state" ]; then
      read -r name value < "$state"
      if [ "$name" = "platform::kbd_backlight" ] && [ "$(cat "/sys/class/leds/$name/max_brightness")" = 1 ]; then
        rm -f "$state"
        exit 0
      fi
      if [ -r "/sys/class/leds/$name/brightness" ] && [ "$(cat "/sys/class/leds/$name/brightness")" = 0 ]; then
        brightnessctl -q -d "$name" set "$value"
      fi
      rm -f "$state"
    fi ;;
  *) exit 2 ;;
esac
