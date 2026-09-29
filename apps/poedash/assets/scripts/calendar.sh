#!/usr/bin/env bash
# Keep cal's Monday-first spacing and accent today using Pango markup.
# Read only validated hex literals, never execute the generated stylesheet.
palette="$(dirname "$(realpath "$0")")/../colors.scss"
accent=$(sed -n 's/^\$accent: \(#[[:xdigit:]]\{6\}\);$/\1/p' "$palette" 2>/dev/null)
muted=$(sed -n 's/^\$muted: \(#[[:xdigit:]]\{6\}\);$/\1/p' "$palette" 2>/dev/null)
LC_ALL=C cal --color=never -m | awk -v accent="${accent:-#8dd5b2}" -v muted="${muted:-#8a938c}" -v day="$(date +%-d)" '
NR == 1 {next}
NR == 2 {print "<span foreground=\"" muted "\">" $0 "</span>"; next}
{for (i=1; i<=length($0); i+=3) {
    cell=substr($0,i,2)
    if (cell+0 == day) printf "<span foreground=\"%s\" weight=\"bold\">%s</span>", accent, cell
    else printf "%s", cell
    printf "%s", substr($0,i+2,1)
} printf "\n"}'
