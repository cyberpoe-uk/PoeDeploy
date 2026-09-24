#!/usr/bin/env bash
# Build the four BlackArch two-step themes from the supplied, unmodified logos.
set -euo pipefail

THEMES=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
for dependency in magick unzip python3; do
    command -v "$dependency" >/dev/null || {
        printf 'Missing build dependency: %s\n' "$dependency" >&2
        exit 1
    }
done
BUILD=$(mktemp -d -t blackarch-themes-XXXXXX)
trap 'rm -rf -- "$BUILD"' EXIT
unzip -q "$THEMES/poedeploy/plymouth/poedeploy.zip" -d "$BUILD/template"

# At most 10 px of artwork overhang on either side of the 460 px bar.
# The padded frame fits even a 640x480 display at Plymouth scale 1.
WIDTH=528
HEIGHT=460
BAR_X=34
BAR_Y=404
BAR_END=493
BAR_BOTTOM=409

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
    resources="$theme/resources"
    mkdir -p "$resources" "$destination/plymouth"
    # Keep the proven password, keyboard and caps-lock UI from PoeDeploy.
    for asset in entry capslock bullet keymap-render lock keyboard; do
        cp "$BUILD/template/poedeploy/resources/$asset.png" "$resources/"
    done
    sed -e "s/poedeploy/$name/g" \
        -e "s/Name=PoeDeploy/Name=BlackArch ${colour^}/" \
        -e "s/Description=.*/Description=BlackArch ${colour^} with a matching luminous progress bar./" \
        -e 's/ProgressBarWidth=350/ProgressBarWidth=460/' \
        -e 's/ProgressBarHeight=5/ProgressBarHeight=6/' \
        -e "s/ProgressBarForegroundColor=.*/ProgressBarForegroundColor=0x${accent#\#}/" \
        "$BUILD/template/poedeploy/poedeploy.plymouth" > "$theme/$name.plymouth"

    # Measure visible artwork, retaining all original pixels within the bounds.
    bounds=$(magick "$destination/logo.png" -alpha extract -threshold 1% -format '%@' info:)
    magick "$destination/logo.png" -crop "$bounds" +repage -resize '480x354' "$BUILD/logo.png"
    logo_height=$(magick identify -format '%h' "$BUILD/logo.png")
    logo_y=$((BAR_Y - 26 - logo_height))
    magick -size "${WIDTH}x${HEIGHT}" xc:none "$BUILD/logo.png" \
        -gravity north -geometry "+0+$logo_y" -composite \
        -fill '#232323' -draw "roundrectangle $BAR_X,$BAR_Y $BAR_END,$BAR_BOTTOM 3,3" \
        "$BUILD/base.png"

    for ((frame = 0; frame <= 50; frame++)); do
        printf -v output '%s/progress-%02d.png' "$resources" "$frame"
        filled=$((460 * frame / 50))
        if ((filled == 0)); then
            cp "$BUILD/base.png" "$output"
            continue
        fi
        end=$((BAR_X + filled - 1))
        magick -size "${WIDTH}x${HEIGHT}" xc:none -fill "$accent" \
            -draw "roundrectangle $BAR_X,$BAR_Y $end,$BAR_BOTTOM 3,3" "$BUILD/fill.png"
        # Two soft halos surround a crisp colour core; ample padding avoids clipping.
        magick "$BUILD/fill.png" -channel A -blur 0x8 -evaluate multiply 1.3 \
            -channel RGB -fill "$accent" -colorize 100 +channel "$BUILD/outer.png"
        magick "$BUILD/fill.png" -channel A -blur 0x3 \
            -channel RGB -fill "$accent" -colorize 100 +channel "$BUILD/inner.png"
        magick "$BUILD/base.png" "$BUILD/outer.png" -composite \
            "$BUILD/inner.png" -composite "$BUILD/fill.png" -composite \
            -fill "$highlight" -draw "rectangle $((BAR_X + 1)),$((BAR_Y + 1)) $((end - 1)),$((BAR_Y + 1))" \
            "PNG32:$output"
    done
    # A single completed frame holds the full bar during the end animation.
    cp "$resources/progress-50.png" "$resources/animation-00.png"
    magick -size 1920x1080 xc:black "$resources/progress-25.png" \
        -gravity center -composite "$destination/preview.png"

    # Use a stable file order, ZIP timestamps and permissions.
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
    printf 'Built %s (%s).\n' "$name" "$accent"
done
