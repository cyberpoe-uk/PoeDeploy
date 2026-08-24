# Arch Linux Setup

A personal automated post-installation setup script for Arch Linux.

The goal of this project is to make a fresh Arch Linux installation reproducible without creating a complete custom Arch ISO.

The script detects the existing system and installs/configures only what is required.

## Current Features

- Arch Linux detection
- Internet connectivity check
- Full system update
- `yay` installation
- Base system and network tools
- GPU detection
- NVIDIA open DKMS driver detection/installation
- Bootloader detection
- NetworkManager detection and configuration
- Filesystem detection
- Plymouth installation and configuration
- Interactive Plymouth theme selection
- Optional custom Plymouth theme from this repository
- Timeshift installation
- Optional ML4W installation
- Optional SDDM installation and configuration
- Interactive application selection
- Official Arch repositories preferred
- AUR fallback when required
- VLC plugin installation
- Tailscale installation
- Tailscale service configuration
- Optional SMB share configuration
- Optional NFS share configuration
- Persistent `/etc/fstab` entries for network shares
- Idempotent installation

## Requirements

- Arch Linux
- Internet connection
- `sudo` access

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

## Network Shares

The installer can optionally configure:

- SMB/CIFS shares
- NFS shares

Local mount points are created automatically and persistent entries can be added to /etc/fstab.

## Usage
Run directly from GitHub:

```bash
bash <(curl -fsSL https://raw.githubusercontent.com/cyberpoe-hub/arch-personal-setup/main/install.sh)

## ML4W

ML4W is optional and is installed using the official ML4W installer:

```bash
bash <(curl -fsSL https://ml4w.com/os/stable)