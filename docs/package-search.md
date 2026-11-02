# PoeDash package search

Click **Packages** beside the Compact/Comfortable button. Choose repositories,
AUR, or both, then type a package name. Escape closes the popup. No packages are
changed while searching.

The popup uses Rofi's current `config.rasi`, including its size, font, colors,
wallpaper, border and icon theme. It does not modify the launcher configuration.
On systems using a different launcher, this feature still uses PoeDash's Rofi
dependency and the installed Rofi theme.

## Results and updates

Names and suggestions stay alphabetical while typing. Repository packages take
priority over duplicate AUR names, following pacman's repository order. The AUR
package-name index is downloaded from its official endpoint and cached for 24
hours. All filtering happens locally, so even single-letter searches do not send
network requests. Initial loading may take a moment. Offline operation uses the
last cached AUR index and labels it as cached. Without any cached index, AUR
results are unavailable and repository search remains usable.

Each result shows its repository/source and one of:

- Not installed.
- Installed version and up-to-date status.
- Update available, with installed and available versions.
- Installed with a newer local version.
- Update status unknown when remote metadata is unavailable.

`checkupdates` checks repository updates using its separate temporary database.
Results are cached for five minutes. Search never runs `pacman -Sy` or modifies
the system's sync databases. If the check fails, the popup explicitly reports
that it is using existing local pacman metadata. AUR versions for installed
packages are fetched from the official RPC API when opening AUR search. A
selected AUR package is checked again before offering an action. Versions use
libalpm's Arch version comparison, including epochs and package release numbers.
VCS packages whose upstream commits changed without an AUR version change may
need a separate development-package upgrade through yay.

Icons are taken from available desktop-entry metadata and application aliases.
Uninstalled applications and libraries often have no local icon metadata and
receive a generic package icon. Icons are not downloaded per keystroke.

## Installing and updating

Selecting a missing package offers **Install** first and **Install and upgrade**
second, followed by Cancel. Outdated packages offer **Update** and **Update and
upgrade** in the same order. A current installed package shows its status and
returns to the search without reinstalling it. Kitty opens an interactive
terminal and asks for confirmation before running the selected command.

Install/Update uses the existing system repository databases without refreshing
them and changes only the selected package and its required dependencies:

```text
sudo pacman -S --needed -- repository/package
yay -S --needed -- aur-package
```

Install/Update and upgrade refreshes databases and includes a full system upgrade:

```text
sudo pacman -Syu --needed -- repository/package
yay -Syu --needed -- aur-package
```

Neither action performs an isolated `pacman -Sy`. If old repository metadata
references unavailable packages, choose the second option to refresh and upgrade.
Review the complete transaction before accepting pacman's or
yay's own prompts. Dependency changes and AUR PKGBUILD review remain interactive.
There is no `--noconfirm`. Yay runs as the desktop user, using its normal privilege
escalation when needed. The feature refuses to run as root and reports a missing
yay installation with instructions to install it through PoeDeploy.

Only validated catalog selections are passed as arguments. Shell commands are
not constructed from the search text. Repeated clicks share one browser lock.
The transaction uses the package manager's normal lock and progress output.

## Diagnostics

```bash
~/.config/poedash/scripts/packages.py open
```

Catalog and update caches are under `~/.cache/poedash/packages`, or the matching
`XDG_CACHE_HOME` directory. Removing `aur-names.json` or `repo-updates.json`
forces a fresh lookup next time. This does not remove any installed package.

References: [Rofi dmenu](https://davatorium.github.io/rofi/current/rofi-dmenu.5/),
[pacman](https://man.archlinux.org/man/pacman.8.en),
[yay](https://github.com/Jguer/yay).
