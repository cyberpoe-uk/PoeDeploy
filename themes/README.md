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
| [BlackArch Green](blackarch-green/) | Lime green, `#55EF00` | [Layout preview](blackarch-green/preview.png) |
| [BlackArch Orange](blackarch-orange/) | Ember orange, `#FF7000` | [Layout preview](blackarch-orange/preview.png) |
| [BlackArch Purple](blackarch-purple/) | Violet, `#AE24FF` | [Layout preview](blackarch-purple/preview.png) |
| [BlackArch Red](blackarch-red/) | Scarlet, `#FF2020` | [Layout preview](blackarch-red/preview.png) |

The BlackArch themes use the supplied 24-frame, 720×720 transparent animations
at their intended 18 fps on a black background. They use Plymouth's script
plugin, so the animation timing is independent of real boot progress. A separate
460×6 px progress bar keeps the static-screen design, with the matching colour,
two layers of soft outer glow, and a fine highlight.

The artwork, 18 px gap, and padded progress bar form one centred 720×770 layout.
The source artwork is never enlarged. On displays too small for its native size,
the entire composition is proportionally fitted within 92% of the screen, so it
remains centred and fully visible even at 640×480.

Each archive contains its colour's 24 animation frames, 51 progress states, the
theme definition, animation script, and password-entry resources. The completed
bar remains visible when Plymouth exits.

Run PoeDeploy from this checkout, select the Plymouth setup module, and choose
`blackarch-green`, `blackarch-orange`, `blackarch-purple`, or `blackarch-red`.
Local archives are discovered without needing to publish them to GitHub.

To rebuild all four archives and their deterministic 50% layout previews from
the supplied frame-pack ZIP:

```bash
# Requires ImageMagick 7, unzip and Python 3.
bash themes/build-blackarch.sh /path/to/blackarch-plymouth-frame-packs.zip
```

The builder verifies that all 24 frames exist at 720×720 and copies them without
resizing. It uses the existing PoeDeploy archive only for its compact password
prompt artwork. ZIP entries have stable ordering, permissions and timestamps.

`preview.png` files are deterministic 1920×1080 layouts using animation frame 12
and exactly 50% progress. The shared definition, script, installer, and detailed
usage notes live in [`blackarch/`](blackarch/).

Artwork provenance: the BlackArch animation frames were supplied by the
repository owner for this addition. The source artist, original source URL and
artwork licence were not supplied. No additional licence is asserted for those
frames. Existing PoeDeploy prompt resources are retained from this repository.

Themes created for PoeDeploy belong under `themes/`. PoeDeploy does not download third-party theme collections during installation. Curated third-party themes must be reviewed and added to this repository individually.

Do not add a third-party archive without also including its licence, source URL, author attribution, and any notices required by its licence.
