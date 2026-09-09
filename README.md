# PoeDeploy

<p align="center">
  <img src="assets/poedeploy-logo.png" alt="PoeDeploy logo" width="500">
</p>

PoeDeploy is a personal automated post-installation setup script for Arch Linux.

The goal of this project is to make a fresh Arch Linux installation reproducible without creating a complete custom Arch ISO.

PoeDeploy detects the existing system and installs and configures only what is required.

## Current Features

- Arch Linux detection
- First-run setup and selectable sections for repeat runs
- Internet connectivity check
- Active Pacman operation waiting and stale database-lock recovery
- Full system update
- `yay` installation
- Base system and network tools
- GPU detection
- NVIDIA open DKMS driver detection/installation
- Bootloader detection
- Optional UKI creation for systemd-boot installations
- Existing boot images and loader entries retained as recovery options
- UKI boot verification before Secure Boot configuration
- Persistent plain-black UKI splash across kernel upgrades
- NetworkManager detection and configuration
- Filesystem detection
- Plymouth installation and configuration
- Interactive Plymouth theme selection
- Plymouth theme discovery from the PoeDeploy repository
- Initramfs and UKI rebuilding after a theme change
- Generated UKI inspection for Plymouth hook order, theme, command line and firmware splash
- Official PoeDeploy Plymouth theme
- Timeshift installation
- Optional ML4W installation
- Optional SDDM installation and configuration
- Interactive application selection
- Cancel, skip or retry individual optional application installations with Ctrl+C
- Interactive default-browser selection
- Official Arch repositories preferred
- AUR fallback when required
- VLC plugin installation
- Tailscale installation
- Tailscale service configuration
- Optional Secure Boot setup with `sbctl`
- Explicit Secure Boot key creation, enrollment and signing confirmations
- Microsoft certificate preservation during key enrollment
- systemd-boot and UKI signing and verification
- Optional SMB share configuration
- Optional NFS share configuration
- Persistent `/etc/fstab` entries for network shares
- Idempotent installation

## Requirements

- Arch Linux
- Internet connection
- `sudo` access
- UEFI with systemd-boot for automated UKI setup
- UEFI Setup Mode when enrolling new Secure Boot keys

## Applications

The optional application menu currently includes:

- 7-Zip
- Discord
- Firefox
- GIMP
- LibreOffice
- LocalSend
- OBS Studio
- PowerTOP
- Spotify
- Tailscale
- Thunderbird
- Visual Studio Code
- VLC

Applications are selected interactively before installation.

When VLC is selected, the VLC plugin package is also installed.

Timeshift is available as its own setup section.

During an optional application's installation, press **Ctrl+C** once. After the
package manager or AUR build exits, PoeDeploy offers **Skip**, **Retry**, or
**Quit**. Skip continues with the next package; Retry attempts the same package;
Quit stops PoeDeploy. Skipped packages appear separately from failures in the
summary and can be selected again on a later run.

Cancellation does not roll back changes or uninstall dependencies that have
already been installed. The package manager may need time to finish its current
transaction and exit. This skip prompt applies to optional app installations;
Ctrl+C elsewhere retains its normal stop behaviour. Skipping VLC also skips its
plugins, and skipping Tailscale prevents its service section from reinstalling it.

## Package Sources

The script follows this priority:

1. Official Arch Linux repositories
2. AUR when the package is not available in the official repositories

`yay` is used as the AUR helper.

## Plymouth Themes

PoeDeploy-managed themes use the following repository layout:

```text
themes/<theme-name>/plymouth/<theme-name>.zip
```

Themes matching this structure are detected automatically. PoeDeploy does not download third-party theme collections at runtime. Any curated theme must first be added to this repository using the structure above.

## UKI and Secure Boot

On UEFI systems using systemd-boot, PoeDeploy can create a normal UKI for each installed kernel under the boot partition's `EFI/Linux` directory. It discovers the boot partition with `bootctl`, creates a persistent `/etc/kernel/cmdline` only after showing it for confirmation, and keeps the existing traditional initramfs and loader entries intact.

After generating the UKIs, PoeDeploy verifies that they are PE executables and asks for a reboot through the new UKI entry. Secure Boot configuration remains blocked until a later run confirms that the current system was successfully booted from a UKI. Mkinitcpio preset backups are stored beside the originals with the `.poedeploy.bak` suffix.

Secure Boot configuration is optional and uses `sbctl`. PoeDeploy requires separate typed confirmation before creating keys, enrolling keys, or signing EFI files. New key enrollment is only attempted when the firmware reports Setup Mode, and Microsoft certificates are included with `sbctl enroll-keys --microsoft`.

PoeDeploy builds configured UKIs before signing systemd-boot and the final UKIs, then runs `sbctl verify`. Firmware configuration and recovery knowledge are still the administrator's responsibility.

The UKI contains two distinct splash stages. Its PE `.splash` section is a static
firmware image shown by `systemd-stub`; PoeDeploy replaces the default Arch image
with plain black. Plymouth is stored inside the UKI's embedded initramfs and then
shows the selected animated theme. Building or signing a UKI does not replace the
Plymouth theme.

PoeDeploy writes the static splash using mkinitcpio's supported
`<preset>_options="--splash ..."` format, places `plymouth` after `systemd` or
`udev` in the hook list, and refreshes an already-installed PoeDeploy theme from
the current release. After building, it inspects each UKI and refuses Secure Boot
signing when the selected theme, `splash` kernel option or hook order is wrong, or
when the default Arch firmware splash remains embedded.

Rebuilding a UKI changes its signed contents. When firmware Secure Boot is already
enabled and the user selects Plymouth or UKI, PoeDeploy automatically adds the
Secure Boot section so the rebuilt images are signed and verified in the same run.

If the summary reports **keys created but not enrolled**, use the firmware's
documented procedure to enter Secure Boot Setup Mode. Custom mode by itself may
not enable Setup Mode; check using `sudo sbctl status` after returning to Arch.
Rerun PoeDeploy, answer **yes** to the previous-run question, and select only
**Secure Boot** to complete enrollment and signing. Existing key files are not
treated as proof of enrollment: when Setup Mode is disabled, PoeDeploy asks
whether those exact keys have already been enrolled before proceeding to sign.

If the UKI reboot test is still pending, first boot through the UKI entry and then
rerun the Secure Boot section. After enrollment and signing, check
`sudo sbctl status` and `sudo sbctl verify` before enabling Secure Boot enforcement
in firmware. See the [sbctl workflow](https://github.com/Foxboron/sbctl/blob/master/docs/sbctl.8.txt).

## Network Shares

The installer can optionally configure:

- SMB/CIFS shares
- NFS shares

Local mount points are created automatically and persistent entries can be added to /etc/fstab.

## Usage

Run the latest stable release with the public bootstrapper:

```bash
bash <(curl -fsSL https://cyberpoe.uk/latest-release)
```

The bootstrapper verifies that it is running on Arch Linux, installs Git when
needed, finds the highest stable version tag in the GitHub repository, displays
the selected version, and downloads it into a temporary directory. Temporary
files are removed automatically when PoeDeploy exits.

Alternatively, clone the [PoeDeploy repository](https://github.com/cyberpoe-uk/PoeDeploy), make the script executable, and run it:

```bash
git clone https://github.com/cyberpoe-uk/PoeDeploy.git
cd PoeDeploy
chmod +x poedeploy.sh
./poedeploy.sh
```

## First and subsequent runs

At startup PoeDeploy asks:

```text
Have you run PoeDeploy before on this Arch installation? [y/N]:
```

Answer **no** for the complete setup, including the existing optional prompts.
Answer **yes** to choose specific sections. This also works after an interrupted
first run; there is no requirement for a previous run to have completed.

The repeat-run menu starts with no sections selected. Enter numbers separated by
spaces or commas to toggle them, `all` or `none` to change the whole selection,
`run` to proceed, or `quit` to leave before making system changes. For example:

```text
Selection: 15
Selection: run
```

This selects only **Secure Boot**. Option **11** selects optional applications;
on repeat runs its application checklist also starts with nothing selected.

The sections are system update, yay, base tools, GPU drivers, NetworkManager,
Plymouth, UKI, Timeshift, ML4W, SDDM, applications, default browser, SMB/NFS shares,
Tailscale service, and Secure Boot. Selected sections run in dependency order.
System detection is read-only. Unselected sections do not run; in particular a
Secure Boot-only run does not perform a full update, install desktop applications,
or change Plymouth. Missing packages required by a selected section may still be
installed, and the Secure Boot section still rebuilds and signs the configured UKIs.

## Development checks

```bash
bash -n poedeploy.sh
python3 -m unittest discover -s tests -v
```

The tests use mocked privileged operations and a harmless package-process fixture
in a pseudo-terminal to exercise real Ctrl+C handling. They do not install
packages, change firmware, or rebuild this machine's boot images.

## ML4W

ML4W is optional and is installed using the official ML4W installer:

```bash
bash <(curl -fsSL https://ml4w.com/os/stable)
```
