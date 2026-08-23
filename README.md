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
- Timeshift installation
- ML4W installation
- Interactive application selection
- Official Arch repositories preferred
- AUR fallback when required
- Tailscale installation
- Tailscale service configuration
- Idempotent installation

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

## Package Sources

The script follows this priority:

1. Official Arch Linux repositories
2. AUR when the package is not available in the official repositories

`yay` is used as the AUR helper.

## ML4W

The script installs ML4W using the official ML4W installer:

```bash
bash <(curl -fsSL https://ml4w.com/os/stable)
