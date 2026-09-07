# PoeDeploy

<p align="center">
  <img src="assets/poedeploy-logo.png" alt="PoeDeploy logo" width="500">
</p>

PoeDeploy is a personal automated post-installation setup script for Arch Linux.

The goal of this project is to make a fresh Arch Linux installation reproducible without creating a complete custom Arch ISO.

PoeDeploy detects the existing system and installs and configures only what is required.

## Current Features

- Arch Linux detection
- Internet connectivity check
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
- Official PoeDeploy Plymouth theme
- Timeshift installation
- Optional ML4W installation
- Optional SDDM installation and configuration
- Interactive application selection
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
- Timeshift
- Visual Studio Code
- VLC

Applications are selected interactively before installation.

When VLC is selected, the VLC plugin package is also installed.

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

## Network Shares

The installer can optionally configure:

- SMB/CIFS shares
- NFS shares

Local mount points are created automatically and persistent entries can be added to /etc/fstab.

## Usage

Clone the [PoeDeploy repository](https://github.com/cyberpoe-uk/PoeDeploy), make the script executable, and run it:

```bash
git clone https://github.com/cyberpoe-uk/PoeDeploy.git
cd PoeDeploy
chmod +x poedeploy.sh
./poedeploy.sh
```

## ML4W

ML4W is optional and is installed using the official ML4W installer:

```bash
bash <(curl -fsSL https://ml4w.com/os/stable)
```
