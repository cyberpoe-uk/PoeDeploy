Arch Personal Setup

A personal Arch Linux setup and configuration toolkit for building a repeatable desktop installation from a fresh Arch Linux system.

The main installer is designed to detect what is already present, install missing components, ask before optional configuration, and continue safely when an optional component cannot be completed.

What the installer does

The installer follows this general flow:

Start
  ↓
Show version + safety warning
  ↓
Check Arch Linux
  ↓
Check Internet
  ↓
Synchronise/update Arch
  ↓
Check/install yay
  ↓
Check/install base utilities
  ↓
Detect GPU and required NVIDIA driver
  ↓
Detect bootloader
  ↓
Check NetworkManager
  ↓
Detect root filesystem
  ↓
Check graphical environment
  ↓
Plymouth configuration
  ↓
Timeshift
  ↓
Optional ML4W installation
  ↓
Optional SDDM configuration
  ↓
Optional application selection
  ↓
Optional SMB/NFS setup
  ↓
Optional Tailscale configuration
  ↓
Final system + installation summary

Requirements

The installer is intended for:

Arch Linux

A working Internet connection

A user account with sudo access

A UEFI or other supported bootloader configuration that the script can detect

The installer installs most of its own dependencies as it runs.

Safety and idempotency

The installer asks for confirmation before making system changes.

Where practical, it checks whether a component is already installed or configured before changing it.

Examples include:

yay

base utilities

NVIDIA drivers

Plymouth

Timeshift

Hyprland

SDDM

ML4W SDDM theme

selected applications

/etc/fstab network-share entries

The installer does not automatically start SDDM during the installation. SDDM is enabled for the next boot so that the installer can finish without handing the current graphical session to the display manager.

Versioning

The installer reads its version from the VERSION file.

Example:

0.3.0

Release tags use the same version with a v prefix:

v0.3.0

Keep VERSION, the release tag, and the documented release version aligned when creating a release.

Base system and networking tools

The installer checks and installs common tools including:

Git

curl

wget

jq

zip

unzip

less

iproute2

iputils

bind

OpenSSH

netcat

traceroute

mtr

tcpdump

ethtool

rsync

NFS utilities

CIFS/SMB utilities

smbclient

whois

Git is treated as a base utility rather than an optional application because it is also useful for the installer itself and for ongoing system administration.

AUR support

The installer prefers the official Arch repositories.

If yay is not installed, it is built from the AUR.

When an optional application cannot be found in the official repositories, the installer checks the AUR instead.

This means optional applications can come from:

Official Arch repositories

AUR, only when required

GPU and NVIDIA support

The installer detects the installed GPU vendor.

For NVIDIA systems, it checks for:

nvidia-open-dkms
nvidia-utils

and installs the open DKMS driver when required.

Kernel headers are also checked for installed kernels.

The script does not hard-code a particular NVIDIA driver release, so it uses the packages currently available from the configured repositories.

Bootloader detection

The installer checks the current bootloader and currently supports Plymouth configuration for:

systemd-boot

GRUB

For systemd-boot, the script uses bootctl status to identify the active loader.

NetworkManager

NetworkManager is checked and installed when missing.

The service is enabled and started when necessary.

The installer also reports whether NetworkManager is currently active.

Plymouth

Plymouth is installed when required.

The installer:

Checks for the Plymouth package

Adds the Plymouth mkinitcpio hook when required

Configures the bootloader with quiet and splash

Rebuilds the initramfs when a Plymouth theme is changed

Lists themes available on the current system

Allows the user to select a theme

Allows 0 to keep the current theme

Custom Plymouth theme

A custom theme can be stored in this repository:

assets/
└── plymouth-themes/
    └── arch-mac-style.zip

The installer downloads it from:

https://raw.githubusercontent.com/cyberpoe-hub/arch-personal-setup/main/assets/plymouth-themes/arch-mac-style.zip

The custom theme is optional. If it cannot be downloaded or is invalid, the installer continues and still offers the built-in Plymouth themes already available on the system.

Timeshift

Timeshift is installed if it is not already present.

The installer detects whether the root filesystem is Btrfs and reports the appropriate Timeshift snapshot approach.

It does not automatically create snapshots or decide how the user wants to structure their Timeshift retention policy.

ML4W

ML4W is optional.

The installer asks:

Install ML4W Hyprland? [Y/n]

Pressing Enter accepts the default of Yes.

If ML4W is selected, the installer launches the ML4W stable installer:

https://ml4w.com/os/stable

If ML4W is skipped, the rest of the installer continues.

SDDM

SDDM configuration is a separate choice.

After the ML4W question, the installer asks whether SDDM should be installed/configured.

When selected, the installer:

Checks Hyprland

Installs SDDM if required

Installs the required Qt components

Disables conflicting display managers

Enables SDDM for the next boot

Does not start SDDM during the installation

Downloads the ML4W SDDM theme if required

Configures /etc/sddm.conf

The SDDM theme is installed under:

/usr/share/sddm/themes/ml4w

Because SDDM is only enabled and not started, the installer can continue running in the current terminal session.

Optional applications

The installer provides an interactive application selector.

Current applications include:

Application

Package

Source

Firefox

firefox

Official

LocalSend

localsend

AUR fallback

VLC

vlc

Official

Visual Studio Code

visual-studio-code-bin

AUR

7-Zip

7zip

Official

Discord

discord

Official

GIMP

gimp

Official

LibreOffice

libreoffice-fresh

Official

PowerTOP

powertop

Official

Tailscale

tailscale

Official

Thunderbird

thunderbird

Official

Spotify

spotify-launcher

Official

OBS Studio

obs-studio

Official

All applications start selected in the selector.

Use the arrow keys to navigate and the available selection keys to toggle applications, then press Enter to confirm.

If nothing is selected, the application-installation stage is skipped.

VLC

Selecting VLC also installs:

vlc-plugins-all

so the complete VLC plugin package is installed alongside VLC.

SMB network shares

The installer can configure a persistent SMB/CIFS share.

The user is asked for:

SMB server IP or hostname

SMB share name

SMB username

SMB password

Optional domain/workgroup

Local mount point

The script:

Installs the required SMB client utilities

Validates required input

Creates the local mount-point directory

Creates a protected SMB credentials file

Adds a persistent /etc/fstab entry

Reloads systemd

Attempts to mount the share

Continues if the immediate mount test fails

SMB credentials are stored separately from /etc/fstab.

NFS network shares

The installer can configure a persistent NFS share.

The user is asked for:

NFS server IP or hostname

NFS export path

NFS version, with version 4 as the default

Local mount point

The script:

Installs the required NFS utilities

Validates required input

Creates the local mount-point directory

Adds a persistent /etc/fstab entry

Reloads systemd

Attempts to mount the share

Continues if the immediate mount test fails

Network share selection

The installer allows:

[0] None
[1] SMB only
[2] NFS only
[3] SMB and NFS

SMB and NFS are tracked independently in the final summary, so a cancelled SMB configuration does not make the NFS result appear successful and vice versa.

Tailscale

If Tailscale is selected:

The package is installed if needed

tailscaled is enabled

tailscaled is started

The installer reminds the user to authenticate with:

sudo tailscale up

Authentication is intentionally left to the user.

Final assessment

The installer shows two different types of information.

System state

This reports what is currently installed/configured on the machine, for example:

Hyprland:         installed
SDDM:             enabled for next boot
SDDM now:         active
ML4W SDDM theme:  installed

This run

This records what happened during the current execution, for example:

ML4W:             installed successfully
SDDM setup:       configured
Applications:     13 selected
SMB:              cancelled
NFS:              configured successfully

This distinction is useful when rerunning the installer on a machine that already has some of the components installed.

Running the installer

Download first

For a fresh Arch installation:

curl -fsSL \
  https://raw.githubusercontent.com/cyberpoe-hub/arch-personal-setup/main/install.sh \
  -o install.sh

Make it executable:

chmod +x install.sh

Check the script before running it:

bash -n install.sh

Then run:

./install.sh

One-line execution

The installer can also be run directly:

bash <(curl -fsSL https://raw.githubusercontent.com/cyberpoe-hub/arch-personal-setup/main/install.sh)

The script displays its version and asks for confirmation before making changes.

Git and releases

The repository uses Git for development and tagged releases.

Typical development workflow:

git status
git diff
git add <files>
git diff --cached
git commit -m "Describe the change"
git push origin main

For a release:

echo "0.3.0" > VERSION

git add install.sh VERSION README.md
git diff --cached

git commit -m "Release 0.3.0"
git push origin main

git tag -a v0.3.0 -m "Release 0.3.0"
git push origin v0.3.0

main represents the latest development state, while version tags identify specific releases.

Project structure

arch-personal-setup/
├── install.sh
├── VERSION
├── README.md
├── LICENSE
│
└── assets/
    └── plymouth-themes/
        └── arch-mac-style.zip

As the project grows, additional scripts and utilities can be organised into separate directories rather than keeping every script in the repository root.

Current status

This project is actively developed and tested against real Arch Linux installations.

The current focus is on making a fresh Arch installation repeatable while keeping the process interactive enough to adapt to different hardware, applications, storage configurations, and future changes.

Future ideas are intentionally kept separate from the current installer until they are implemented and tested.

License

This project is licensed under the MIT License.

See LICENSE for the full licence text.