#!/usr/bin/env bash
# Build the four script-plugin themes from the supplied BlackArch frame pack.
set -euo pipefail

THEMES=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
SOURCE_DIR="${THEMES}/blackarch"
FRAME_PACK="${1:-${BLACKARCH_FRAME_PACK:-}}"

if [[ -z "$FRAME_PACK" ]]; then
    printf 'Usage: %s /path/to/blackarch-plymouth-frame-packs.zip\n' "$0" >&2
    printf 'You can also set BLACKARCH_FRAME_PACK.\n' >&2
    exit 2
fi
if [[ ! -f "$FRAME_PACK" ]]; then
    printf 'Frame pack not found: %s\n' "$FRAME_PACK" >&2
    exit 1
fi

for dependency in magick unzip python3; do
    command -v "$dependency" >/dev/null 2>&1 || {
        printf 'Missing build dependency: %s\n' "$dependency" >&2
        exit 1
    }
done

BUILD=$(mktemp -d -t blackarch-themes-XXXXXX)
trap 'rm -rf -- "$BUILD"' EXIT
unzip -q "$FRAME_PACK" -d "$BUILD/source"
unzip -q "$THEMES/poedeploy/plymouth/poedeploy.zip" -d "$BUILD/template"

for colour in green orange purple red; do
    case "$colour" in
        green)  accent='#55EF00'; highlight='#CAFFB0' ;;
        orange) accent='#FF7000'; highlight='#FFE0A3' ;;
        purple) accent='#AE24FF'; highlight='#EAC2FF' ;;
        red)    accent='#FF2020'; highlight='#FFC0B8' ;;
    esac

    name="blackarch-$colour"
    destination="$THEMES/$name"
    theme="$BUILD/$name"
    frames="$theme/frames"
    progress="$theme/progress"
    dialog="$theme/dialog"
    mkdir -p "$frames" "$progress" "$dialog" "$destination/plymouth"

    # Verify and retain the supplied animation frames without resizing them.
    for ((frame = 0; frame < 24; frame++)); do
        printf -v source_frame '%s/source/%s/frame-%02d.png' "$BUILD" "$colour" "$frame"
        printf -v output_frame '%s/frame-%02d.png' "$frames" "$frame"
        [[ -f "$source_frame" ]] || {
            printf 'Missing source frame: %s\n' "$source_frame" >&2
            exit 1
        }
        dimensions=$(magick identify -format '%wx%h' "$source_frame")
        [[ "$dimensions" == 720x720 ]] || {
            printf 'Unexpected dimensions for %s: %s (expected 720x720)\n' \
                "$source_frame" "$dimensions" >&2
            exit 1
        }
        cp "$source_frame" "$output_frame"
    done

    # Reuse the compact, proven password-entry artwork from PoeDeploy.
    for asset in entry lock bullet; do
        cp "$BUILD/template/poedeploy/resources/$asset.png" "$dialog/"
    done

    # Derive each installed theme from the canonical, directly usable sources.
    sed -e "s/Name=BlackArch$/Name=BlackArch ${colour^}/" \
        -e "s#themes/blackarch\$#themes/$name#" \
        -e "s#blackarch/blackarch.script#$name/$name.script#" \
        "$SOURCE_DIR/blackarch.plymouth" > "$theme/$name.plymouth"
    cp "$SOURCE_DIR/blackarch.script" "$theme/$name.script"

    # Keep the static-screen progress bar dimensions and glow treatment. The
    # extra transparent padding prevents the 8 px outer glow from clipping.
    magick -size 500x32 xc:none \
        -fill '#232323' -draw 'roundrectangle 20,13 479,18 3,3' \
        "PNG32:$BUILD/bar-base.png"
    for ((frame = 0; frame <= 50; frame++)); do
        printf -v output '%s/progress-%02d.png' "$progress" "$frame"
        filled=$((460 * frame / 50))
        if ((filled == 0)); then
            cp "$BUILD/bar-base.png" "$output"
            continue
        fi

        end=$((20 + filled - 1))
        magick -size 500x32 xc:none -fill "$accent" \
            -draw "roundrectangle 20,13 $end,18 3,3" "$BUILD/bar-fill.png"
        magick "$BUILD/bar-fill.png" -channel A -blur 0x8 -evaluate multiply 1.3 \
            -channel RGB -fill "$accent" -colorize 100 +channel "$BUILD/bar-outer.png"
        magick "$BUILD/bar-fill.png" -channel A -blur 0x3 \
            -channel RGB -fill "$accent" -colorize 100 +channel "$BUILD/bar-inner.png"
        magick "$BUILD/bar-base.png" "$BUILD/bar-outer.png" -composite \
            "$BUILD/bar-inner.png" -composite "$BUILD/bar-fill.png" -composite \
            -fill "$highlight" -draw "rectangle 21,14 $((end - 1)),14" \
            "PNG32:$output"
    done

    # Produce a deterministic layout preview using animation frame 12 and a
    # half-complete bar. The actual theme chooses frames and progress at runtime.
    magick -size 1920x1080 xc:black \
        "$frames/frame-12.png" -gravity center -geometry +0-25 -composite \
        "$progress/progress-25.png" -gravity center -geometry +0+351 -composite \
        "$destination/preview.png"

    # Stable ordering, permissions and timestamps keep rebuilds reproducible.
    python3 - "$theme" "$destination/plymouth/$name.zip" <<'PY'
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
    unzip -tq "$destination/plymouth/$name.zip"
    printf 'Built %s: 24 animation frames, 51 progress states (%s).\n' "$name" "$accent"
done
