#!/usr/bin/env bash

# Rebuild Plymouth's deterministic UI frames using the existing full logo.
set -euo pipefail

THEME_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
ARCHIVE="$THEME_DIR/plymouth/poedeploy.zip"
LOGO="$THEME_DIR/../../assets/poedeploy-logo.png"
BAR_COLOR='#004FFE' # Sampled from the blue D in the full logo.
BAR_BACKGROUND='#333333'
WIDTH=350
GAP=24
BAR_HEIGHT=5

for dependency in magick unzip zip; do
    command -v "$dependency" >/dev/null || {
        printf 'Missing build dependency: %s\n' "$dependency" >&2
        exit 1
    }
done

BUILD_DIR=$(mktemp -d -t poedeploy-theme-build-XXXXXX)
trap 'rm -rf -- "$BUILD_DIR"' EXIT

# Retain the existing two-step theme and password/keyboard prompt resources.
unzip -q "$ARCHIVE" -d "$BUILD_DIR"
RESOURCES="$BUILD_DIR/poedeploy/resources"

# Ignore near-invisible alpha specks when measuring the artwork's layout bounds.
# Keep the original pixels and transparency inside those bounds.
LOGO_BOUNDS=$(magick "$LOGO" -alpha extract -threshold 1% -format '%@' info:)
magick "$LOGO" -crop "$LOGO_BOUNDS" +repage -resize "${WIDTH}x" "$BUILD_DIR/logo.png"
LOGO_HEIGHT=$(magick identify -format '%h' "$BUILD_DIR/logo.png")
BAR_Y=$((LOGO_HEIGHT + GAP))
HEIGHT=$((BAR_Y + BAR_HEIGHT))
magick -size "${WIDTH}x${HEIGHT}" xc:none \
    "$BUILD_DIR/logo.png" -gravity northwest -composite \
    -fill "$BAR_BACKGROUND" \
    -draw "rectangle 0,$BAR_Y $((WIDTH - 1)),$((HEIGHT - 1))" \
    "$BUILD_DIR/base.png"

for ((frame = 0; frame <= 50; frame++)); do
    printf -v output '%s/progress-%02d.png' "$RESOURCES" "$frame"
    filled=$((WIDTH * frame / 50))
    if ((filled == 0)); then
        cp "$BUILD_DIR/base.png" "$output"
    else
        magick "$BUILD_DIR/base.png" -fill "$BAR_COLOR" \
            -draw "rectangle 0,$BAR_Y $((filled - 1)),$((HEIGHT - 1))" "$output"
    fi
done

# Hold the completed bar during the existing end-animation sequence.
for ((frame = 0; frame <= 80; frame++)); do
    printf -v output '%s/animation-%02d.png' "$RESOURCES" "$frame"
    cp "$RESOURCES/progress-50.png" "$output"
done

# Match the native bar used by the update/upgrade screens as well.
sed -i "s/^ProgressBarForegroundColor=.*/ProgressBarForegroundColor=0x${BAR_COLOR#\#}/" \
    "$BUILD_DIR/poedeploy/poedeploy.plymouth"

# Layout preview, using the same centred frame as the two-step renderer.
magick -size 1920x1080 xc:black "$RESOURCES/progress-25.png" \
    -gravity center -composite "$BUILD_DIR/poedeploy/screenshot.png"

(
    cd "$BUILD_DIR"
    zip -qr poedeploy.zip poedeploy
)
unzip -tq "$BUILD_DIR/poedeploy.zip"
cp "$BUILD_DIR/poedeploy.zip" "$ARCHIVE"
cp "$BUILD_DIR/poedeploy/screenshot.png" "$THEME_DIR/preview.png"
printf 'Built %s (full logo, %s bar, %s px gap).\n' "$ARCHIVE" "$BAR_COLOR" "$GAP"
