# BlackArch Plymouth package

This is the shared source for four static and four animated BlackArch Plymouth
themes. Animated variants use 96 supplied frames reduced from 960×540 to
640×360 and play at their authored 24 fps on black. Each seamless four-second
loop turns the ring by only 30 degrees. The script centres the artwork and bar
as a 640×410 composition. The complete 16:9 alpha canvas preserves the smoke
and embers while keeping the visible emblem close to the static logo's scale.

The progress indicator retains PoeDeploy's static-screen design: a 460×6 px bar,
matching colour, a fine top highlight, and two layers of soft outer glow. Its 51
states are driven by Plymouth's real boot progress and do not affect the 96-frame
animation timing.

Install or switch colour from the repository checkout:

```bash
bash themes/blackarch/install.sh green-static
bash themes/blackarch/install.sh green-animated
bash themes/blackarch/install.sh orange-static
bash themes/blackarch/install.sh orange-animated
```

Purple and red use the same `colour-static` or `colour-animated` naming. With no
argument, the installer shows all eight choices. It installs the
selected package, selects it with `plymouth-set-default-theme`, and runs
`mkinitcpio -P`. PoeDeploy's Plymouth theme selector can also install and switch
all eight `blackarch-*` packages.

`blackarch.plymouth` and `blackarch.script` are the canonical package sources.
The builder adjusts their installed paths and display names for each colour.

To rebuild the packages from the supplied frame pack:

```bash
bash themes/build-blackarch.sh /path/to/blackarch-plymouth-frame-packs-v3.zip
```
