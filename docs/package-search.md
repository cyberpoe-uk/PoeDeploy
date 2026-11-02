# PoeDash package search

Click **Packages** beside the Compact/Comfortable button and start typing.
The first popup searches all configured repositories and the AUR. There is no
initial source-selection menu. Use **Alt+R** or the **Choose repository** entry
to narrow the search to a particular repository or AUR. Your typed query is
retained when switching. Escape closes the popup. No packages change while
searching.

The popup uses Rofi's current `config.rasi`, including its size, font, colors,
wallpaper, border and icon theme. It does not modify the launcher configuration.
On systems using a different launcher, this feature still uses PoeDash's Rofi
dependency and the installed Rofi theme.

## Results and updates

The search opens immediately and accepts typing while its catalogs refresh.
Every opening automatically refreshes configured repository catalogs in a
separate search database and downloads the latest official AUR package-name
index. Both refreshes run concurrently. A fresh load can take a moment, depending
on the mirrors and network. Results arrive in the current popup and match any
text already typed. Nothing is downloaded per keystroke.

Packages with application icons from available desktop/AppStream metadata appear
first. Entries without a specific icon follow with a generic package icon. Each
group is alphabetical, including while filtering letter by letter. A smaller
second line beneath each name identifies its repository and installed/update
status. Duplicate names from different repositories remain separate, so an
explicit repository filter can show the corresponding version and source.

The AUR index and repository snapshots are kept for offline fallback. If refresh
fails, available cached/local catalogs remain searchable and a notification
reports the fallback. AUR results need a previously cached index when offline.
Changing the repository filter uses the loaded catalog without another refresh.

Each result shows its repository/source and one of:

- Not installed.
- Installed version and up-to-date status.
- Update available, with installed and available versions.
- Installed with a newer local version.
- Update status unknown when remote metadata is unavailable.

`checkupdates` refreshes repository data using `CHECKUPDATES_DB` set to the
browser's own `repo-db` cache. Search never refreshes the system's pacman sync
databases or installs packages. Per-repository package versions are read from
the refreshed search snapshot. If a refresh fails, existing search snapshots or
local system metadata are used. Installed AUR versions are checked against the
official RPC API on opening, and selected AUR packages are checked again before
actions are offered. Versions use libalpm's Arch comparison, including epochs
and package release numbers.
VCS packages whose upstream commits changed without an AUR version change may
need a separate development-package upgrade through yay.

Icons are taken from available desktop entries, application aliases and local
AppStream stock/local/cached icon metadata. Remote images are not fetched.
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
`XDG_CACHE_HOME` directory. Catalogs refresh every time the browser opens. These caches can be removed
if needed to discard offline data. This does not remove any installed package.

References: [Rofi dmenu](https://davatorium.github.io/rofi/current/rofi-dmenu.5/),
[pacman](https://man.archlinux.org/man/pacman.8.en),
[yay](https://github.com/Jguer/yay).
