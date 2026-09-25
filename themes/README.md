# PoeDeploy Plymouth themes

Repository-managed themes use this layout:

```text
themes/<theme-name>/plymouth/<theme-name>.zip
```

PoeDeploy discovers archives matching that layout automatically. A theme archive must contain its `.plymouth` file and all referenced assets.

## Included themes

| Theme | Loading bar | Preview |
| --- | --- | --- |
| [PoeDeploy](poedeploy/) | Blue | [Layout preview](poedeploy/preview.png) |
| [BlackArch Green Static](blackarch-green-static/) | Lime green, `#55EF00` | [Layout preview](blackarch-green-static/preview.png) |
| [BlackArch Green Animated](blackarch-green-animated/) | Lime green, `#55EF00` | [Layout preview](blackarch-green-animated/preview.png) |
| [BlackArch Orange Static](blackarch-orange-static/) | Ember orange, `#FF7000` | [Layout preview](blackarch-orange-static/preview.png) |
| [BlackArch Orange Animated](blackarch-orange-animated/) | Ember orange, `#FF7000` | [Layout preview](blackarch-orange-animated/preview.png) |
| [BlackArch Purple Static](blackarch-purple-static/) | Violet, `#AE24FF` | [Layout preview](blackarch-purple-static/preview.png) |
| [BlackArch Purple Animated](blackarch-purple-animated/) | Violet, `#AE24FF` | [Layout preview](blackarch-purple-animated/preview.png) |
| [BlackArch Red Static](blackarch-red-static/) | Scarlet, `#FF2020` | [Layout preview](blackarch-red-static/preview.png) |
| [BlackArch Red Animated](blackarch-red-animated/) | Scarlet, `#FF2020` | [Layout preview](blackarch-red-animated/preview.png) |
| [BlackArch Blue Static](blackarch-blue-static/) | Electric blue, `#0289FB` | [Layout preview](blackarch-blue-static/preview.png) |
| [BlackArch Blue Animated](blackarch-blue-animated/) | Electric blue, `#0289FB` | [Layout preview](blackarch-blue-animated/preview.png) |
| [BlackArch White Static](blackarch-white-static/) | Ice white, `#F2F2F2` | [Layout preview](blackarch-white-static/preview.png) |
| [BlackArch White Animated](blackarch-white-animated/) | Ice white, `#F2F2F2` | [Layout preview](blackarch-white-animated/preview.png) |

All six colours are available in both forms. Static retains the original logo
layout. Animated themes use the supplied 96-frame transparent animation at its
authored 24 fps on a black background. Its seamless four-second loop rotates the
ring by only 30 degrees. It uses Plymouth's script plugin, so animation
timing is independent of real boot progress. Both forms keep the 460×6 px
progress bar with matching colour, two soft outer glows, and a fine highlight.

The animated artwork is reduced from 960×540 to 640×360 without cropping its
smoke or embers. Its visible emblem remains close to the static theme's scale.
With its 18 px gap and padded bar, it forms one centred 640×410 layout. The
artwork is never enlarged. The complete composition scales down proportionally
on smaller displays.

Animated archives contain 96 animation frames, 51 progress states, the theme
definition, script, and password-entry resources. Static archives retain the
original two-step renderer and 51 combined logo/progress states.

Run PoeDeploy from this checkout, select the Plymouth setup module, and choose
the `-static` or `-animated` form of each BlackArch colour.
Local archives are discovered without needing to publish them to GitHub.

To rebuild all twelve archives and their deterministic 50% layout previews from
the supplied frame-pack ZIPs:

```bash
# Requires ImageMagick 7, unzip and Python 3.
bash themes/build-blackarch.sh \
  /path/to/blackarch-plymouth-frame-packs-v3.zip \
  /path/to/blackarch-plymouth-blue-white-v3.zip
```

The builder discovers the colours present in the supplied packs, verifies that
all 96 animation frames exist at 960×540, and reduces them to the selected
640×360 presentation size. It rebuilds a static theme only where matching
`logo.png` artwork exists. The existing PoeDeploy archive supplies the two-step
template and password resources. ZIP entries have stable ordering, permissions,
and timestamps.

`preview.png` files are deterministic 1920×1080 layouts using animation frame 48
and exactly 50% progress. The shared definition, script, installer, and detailed
usage notes live in [`blackarch/`](blackarch/).

Artwork provenance: the BlackArch static artwork and animation frames were
supplied by the repository owner for these themes. The source artist, original
source URL and artwork licence were not supplied. No additional licence is
asserted for the artwork. Existing PoeDeploy prompt resources are retained from
this repository.

Themes created for PoeDeploy belong under `themes/`. PoeDeploy does not download third-party theme collections during installation. Curated third-party themes must be reviewed and added to this repository individually.

Do not add a third-party archive without also including its licence, source URL, author attribution, and any notices required by its licence.
