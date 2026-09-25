# BlackArch animated Plymouth package

This is the shared source for the four BlackArch Plymouth colour variants. Each
variant uses its 24 supplied 720×720 RGBA frames at 18 fps on a black background.
The script centres the animation and the loading bar as one composition. It
keeps the artwork at its native size on normal displays and proportionally
scales the complete layout down to 92% of the available width or height on small
displays.

The progress indicator retains PoeDeploy's static-screen design: a 460×6 px bar,
matching colour, a fine top highlight, and two layers of soft outer glow. Its 51
states are driven by Plymouth's real boot progress and do not affect the 24-frame
animation timing.

Install or switch colour from the repository checkout:

```bash
bash themes/blackarch/install.sh green
bash themes/blackarch/install.sh orange
bash themes/blackarch/install.sh purple
bash themes/blackarch/install.sh red
```

With no colour argument, the installer shows a four-item menu. It installs the
selected package, selects it with `plymouth-set-default-theme`, and runs
`mkinitcpio -P`. PoeDeploy's Plymouth theme selector can also install and switch
the four `blackarch-*` packages.

`blackarch.plymouth` and `blackarch.script` are the canonical package sources.
The builder adjusts their installed paths and display names for each colour.

To rebuild the packages from the supplied frame pack:

```bash
bash themes/build-blackarch.sh /path/to/blackarch-plymouth-frame-packs.zip
```
