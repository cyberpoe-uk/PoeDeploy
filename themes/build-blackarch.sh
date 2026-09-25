#!/usr/bin/env bash
# Build the BlackArch Plymouth themes represented by one or more frame packs.
set -euo pipefail

THEMES=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
SOURCE_DIR="${THEMES}/blackarch"
FRAME_PACKS=("$@")

if ((${#FRAME_PACKS[@]} == 0)) && [[ -n "${BLACKARCH_FRAME_PACK:-}" ]]; then
    FRAME_PACKS=("$BLACKARCH_FRAME_PACK")
fi
if ((${#FRAME_PACKS[@]} == 0)); then
    printf 'Usage: %s FRAME_PACK.zip [FRAME_PACK.zip ...]\n' "$0" >&2
    printf 'You can also set BLACKARCH_FRAME_PACK.\n' >&2
    exit 2
fi
for frame_pack in "${FRAME_PACKS[@]}"; do
    if [[ ! -f "$frame_pack" ]]; then
        printf 'Frame pack not found: %s\n' "$frame_pack" >&2
        exit 1
    fi
done

for dependency in magick unzip python3; do
    command -v "$dependency" >/dev/null 2>&1 || {
        printf 'Missing build dependency: %s\n' "$dependency" >&2
        exit 1
    }
done

BUILD=$(mktemp -d -t blackarch-themes-XXXXXX)
trap 'rm -rf -- "$BUILD"' EXIT
for frame_pack in "${FRAME_PACKS[@]}"; do
    unzip -qo "$frame_pack" -d "$BUILD/source"
done
unzip -q "$THEMES/poedeploy/plymouth/poedeploy.zip" -d "$BUILD/template"

write_archive() {
    python3 - "$1" "$2" <<'PY'
from pathlib import Path
import sys
from zipfile import ZIP_DEFLATED, ZipFile, ZipInfo

source, output = map(Path, sys.argv[1:])
with ZipFile(output, "w", compression=ZIP_DEFLATED, compresslevel=9) as archive:
    for path in sorted(source.rglob("*")):
        if path.is_file():
            entry = ZipInfo(str(path.relative_to(source.parent)), (2026, 1, 1, 0, 0, 0))
            entry.compress_type = ZIP_DEFLATED
            entry.external_attr = 0o100644 << 16
            archive.writestr(entry, path.read_bytes())
PY
    unzip -tq "$2"
}

for colour in green orange purple red blue white; do
    case "$colour" in
        green)  accent='#55EF00'; highlight='#CAFFB0' ;;
        orange) accent='#FF7000'; highlight='#FFE0A3' ;;
        purple) accent='#AE24FF'; highlight='#EAC2FF' ;;
        red)    accent='#FF2020'; highlight='#FFC0B8' ;;
        blue)   accent='#0289FB'; highlight='#B8E2FF' ;;
        white)  accent='#F2F2F2'; highlight='#FFFFFF' ;;
    esac

    # Only the original four colours have corresponding static source artwork.
    if [[ -d "$BUILD/source/$colour" && \
          -f "$THEMES/blackarch-$colour-static/logo.png" ]]; then
    static_name="blackarch-$colour-static"
    static_destination="$THEMES/$static_name"
    static_theme="$BUILD/$static_name"
    static_resources="$static_theme/resources"
    mkdir -p "$static_resources" "$static_destination/plymouth"

    for asset in entry capslock bullet keymap-render lock keyboard; do
        cp "$BUILD/template/poedeploy/resources/$asset.png" "$static_resources/"
    done
    sed -e "s/poedeploy/$static_name/g" \
        -e "s/Name=PoeDeploy/Name=BlackArch ${colour^} Static/" \
        -e "s/Description=.*/Description=Static BlackArch ${colour^} with a matching luminous progress bar./" \
        -e 's/ProgressBarWidth=350/ProgressBarWidth=460/' \
        -e 's/ProgressBarHeight=5/ProgressBarHeight=6/' \
        -e "s/ProgressBarForegroundColor=.*/ProgressBarForegroundColor=0x${accent#\#}/" \
        "$BUILD/template/poedeploy/poedeploy.plymouth" > \
        "$static_theme/$static_name.plymouth"

    bounds=$(magick "$static_destination/logo.png" -alpha extract -threshold 1% -format '%@' info:)
    magick "$static_destination/logo.png" -crop "$bounds" +repage \
        -resize '480x354' "$BUILD/static-logo.png"
    logo_height=$(magick identify -format '%h' "$BUILD/static-logo.png")
    logo_y=$((404 - 26 - logo_height))
    magick -size 528x460 xc:none "$BUILD/static-logo.png" \
        -gravity north -geometry "+0+$logo_y" -composite \
        -fill '#232323' -draw 'roundrectangle 34,404 493,409 3,3' \
        "PNG32:$BUILD/static-base.png"

    for ((frame = 0; frame <= 50; frame++)); do
        printf -v output '%s/progress-%02d.png' "$static_resources" "$frame"
        filled=$((460 * frame / 50))
        if ((filled == 0)); then
            cp "$BUILD/static-base.png" "$output"
            continue
        fi
        end=$((34 + filled - 1))
        magick -size 528x460 xc:none -fill "$accent" \
            -draw "roundrectangle 34,404 $end,409 3,3" "$BUILD/static-fill.png"
        magick "$BUILD/static-fill.png" -channel A -blur 0x8 -evaluate multiply 1.3 \
            -channel RGB -fill "$accent" -colorize 100 +channel "$BUILD/static-outer.png"
        magick "$BUILD/static-fill.png" -channel A -blur 0x3 \
            -channel RGB -fill "$accent" -colorize 100 +channel "$BUILD/static-inner.png"
        magick "$BUILD/static-base.png" "$BUILD/static-outer.png" -composite \
            "$BUILD/static-inner.png" -composite "$BUILD/static-fill.png" -composite \
            -fill "$highlight" -draw "rectangle 35,405 $((end - 1)),405" \
            "PNG32:$output"
    done
    cp "$static_resources/progress-50.png" "$static_resources/animation-00.png"
    magick -size 1920x1080 xc:black "$static_resources/progress-25.png" \
        -gravity center -composite "$static_destination/preview.png"
    write_archive "$static_theme" \
        "$static_destination/plymouth/$static_name.zip"
    printf 'Built %s: static artwork and 51 progress states (%s).\n' \
        "$static_name" "$accent"
    fi

    # A pack may contain only a subset, such as the blue and white addition.
    [[ -d "$BUILD/source/$colour" ]] || continue

    # Build each available animation as an independently selectable theme.
    animated_name="blackarch-$colour-animated"
    animated_destination="$THEMES/$animated_name"
    animated_theme="$BUILD/$animated_name"
    frames="$animated_theme/frames"
    progress="$animated_theme/progress"
    dialog="$animated_theme/dialog"
    mkdir -p "$frames" "$progress" "$dialog" "$animated_destination/plymouth"

    for ((frame = 0; frame < 96; frame++)); do
        printf -v source_frame '%s/source/%s/frame-%03d.png' "$BUILD" "$colour" "$frame"
        printf -v output_frame '%s/frame-%03d.png' "$frames" "$frame"
        [[ -f "$source_frame" ]] || {
            printf 'Missing source frame: %s\n' "$source_frame" >&2
            exit 1
        }
        dimensions=$(magick identify -format '%wx%h' "$source_frame")
        [[ "$dimensions" == 960x540 ]] || {
            printf 'Unexpected dimensions for %s: %s (expected 960x540)\n' \
                "$source_frame" "$dimensions" >&2
            exit 1
        }
        # Keep the complete 16:9 alpha canvas. At 640x360 the visible emblem is
        # close to the static artwork's scale, with room for smoke and embers.
        magick "$source_frame" -filter Lanczos -resize 640x360 \
            "PNG32:$output_frame"
    done

    for asset in entry lock bullet; do
        cp "$BUILD/template/poedeploy/resources/$asset.png" "$dialog/"
    done
    sed -e "s/Name=BlackArch$/Name=BlackArch ${colour^} Animated/" \
        -e "s#themes/blackarch\$#themes/$animated_name#" \
        -e "s#blackarch/blackarch.script#$animated_name/$animated_name.script#" \
        "$SOURCE_DIR/blackarch.plymouth" > "$animated_theme/$animated_name.plymouth"
    cp "$SOURCE_DIR/blackarch.script" "$animated_theme/$animated_name.script"

    magick -size 500x32 xc:none \
        -fill '#232323' -draw 'roundrectangle 20,13 479,18 3,3' \
        "PNG32:$BUILD/animated-base.png"
    for ((frame = 0; frame <= 50; frame++)); do
        printf -v output '%s/progress-%02d.png' "$progress" "$frame"
        filled=$((460 * frame / 50))
        if ((filled == 0)); then
            cp "$BUILD/animated-base.png" "$output"
            continue
        fi
        end=$((20 + filled - 1))
        magick -size 500x32 xc:none -fill "$accent" \
            -draw "roundrectangle 20,13 $end,18 3,3" "$BUILD/animated-fill.png"
        magick "$BUILD/animated-fill.png" -channel A -blur 0x8 -evaluate multiply 1.3 \
            -channel RGB -fill "$accent" -colorize 100 +channel "$BUILD/animated-outer.png"
        magick "$BUILD/animated-fill.png" -channel A -blur 0x3 \
            -channel RGB -fill "$accent" -colorize 100 +channel "$BUILD/animated-inner.png"
        magick "$BUILD/animated-base.png" "$BUILD/animated-outer.png" -composite \
            "$BUILD/animated-inner.png" -composite "$BUILD/animated-fill.png" -composite \
            -fill "$highlight" -draw "rectangle 21,14 $((end - 1)),14" \
            "PNG32:$output"
    done

    magick -size 1920x1080 xc:black \
        "$frames/frame-048.png" -gravity center -geometry +0-25 -composite \
        "$progress/progress-25.png" -gravity center -geometry +0+189 -composite \
        "$animated_destination/preview.png"
    write_archive "$animated_theme" \
        "$animated_destination/plymouth/$animated_name.zip"
    printf 'Built %s: 96 frames at 24 fps and 51 progress states (%s).\n' \
        "$animated_name" "$accent"
done
