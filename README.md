# PoeDeploy

<p align="center">
  <img src="assets/poedeploy-logo.png" alt="PoeDeploy logo" width="500">
</p>

**Set up Arch Linux. Or just the part you need.**

PoeDeploy is a guided Bash toolkit for fresh installations and everyday configuration.
Build out a desktop, connect an SMB/NFS share, change your boot theme, or work
through UKI and Secure Boot setup without running the whole installer.

## Get started

Run as your regular user on Arch Linux, with internet access and sudo available:

```bash
bash <(curl -fsSL https://cyberpoe.uk/latest-release)
```

The launcher downloads the latest stable tagged release and shows its version.
If Git is missing, it explains the prerequisite and asks permission before
installing it. PoeDeploy then offers:

- **Choose sections:** select specific tasks; this is the default.
- **Full setup:** visit every section, with optional choices along the way.
- **Exit:** leave before setup begins.

Either mode works on a first or later run. Review your selected sections before
confirming changes. Missing dependencies for those sections may also be installed.

Prefer to inspect the code first? Clone the
[PoeDeploy repository](https://github.com/cyberpoe-uk/PoeDeploy), review
`poedeploy.sh`, then run it with Bash.

## What can I use it for?

- **A fresh desktop:** system updates, base tools, GPU drivers, NetworkManager,
  optional ML4W/Hyprland, and SDDM.
- **One useful task:** connect an SMB/NFS share, choose a Plymouth theme, install
  apps, change your default browser, or configure Tailscale.
- **Boot configuration:** guided UKI creation and Secure Boot key enrollment,
  signing and verification on supported UEFI/systemd-boot systems.
- **Recovery preparation:** install Timeshift as its own section.

For example, choose **Choose sections → SMB / NFS shares** to configure a NAS.
You do not need to install a desktop, change your theme, or run a full update.

With `gum`, use **↑/↓** to navigate, **x** to toggle checklist items, and **Enter**
to continue. **Esc/Ctrl+C** cancels the menu. Without it, startup uses numbered
menus; no package is installed just to show those menus.

## Optional apps, not a bundle

All apps start unchecked, even during full setup:

7-Zip, Discord, Firefox, GIMP, HyprMod, LibreOffice, LocalSend, OBS Studio,
PowerTOP, Spotify, Tailscale, Thunderbird, Visual Studio Code, and VLC.

Official Arch packages are preferred, with `yay` used for AUR packages.
HyprMod follows the Arch package route used by ML4W; it is not launched
automatically. Selecting VLC also installs its plugins.

During an optional app install, press **Ctrl+C** once. After the package command
exits, choose **Skip**, **Retry**, or **Quit**. Installed dependencies are kept;
cancellation is not an uninstall or rollback.

## Network shares: test before saving

SMB and NFS setup tests the mount and checks that your user can list the share
**before adding it to `/etc/fstab`**. If a test fails, its temporary configuration
is cleaned up and you can retry with corrected details or skip.

Successful entries use on-demand mounting, `nofail`, and a mount timeout.
Existing entries, mounts and credentials are not overwritten. Use a dedicated,
empty directory under `/mnt` or `/media`; system directories and symlink paths
are rejected. The script backs up `fstab` before saving.

This checks connectivity and read access now, not future server availability or
write permissions. Cleanup failures stop the run for inspection rather than
claiming everything is safe. [Share setup and safety details](docs/network-shares.md).

## Before changing boot settings

PoeDeploy changes real system configuration; keep backups and recovery media.
Automated UKI/Secure Boot setup requires UEFI and systemd-boot. A newly configured
UKI must be booted successfully before enrollment/signing proceeds.

Creating keys, enrolling keys and signing files have separate confirmations.
Firmware Setup Mode is required for new enrollment; custom mode alone may not
be sufficient. A Plymouth-only rerun does not repeat key enrollment, but rebuilt
UKIs still need valid signatures when Secure Boot is enabled.

Read the [UKI, Plymouth and Secure Boot guide](docs/boot-and-secure-boot.md) before
using those sections. Boot verification failures must be resolved before rebooting.

## Guides and development

- [SMB/NFS validation, persistence and cleanup](docs/network-shares.md)
- [UKI, Plymouth and Secure Boot](docs/boot-and-secure-boot.md)
- [Testing a real kernel upgrade](docs/kernel-update-check.md)
- [PoeDeploy theme assets](themes/README.md)

ML4W installation is optional. Its installer is downloaded completely and checked
for empty content/Bash syntax errors before execution; download and installer
failures are reported separately. This is not a security audit of upstream code.

Run the local checks:

```bash
bash -n poedeploy.sh
python3 -m unittest discover -s tests -v
```

Tests mock privileged operations and network mounts; they do not change your
host's shares, packages, boot images or firmware. Real server and reboot testing
is still needed for your machine.
