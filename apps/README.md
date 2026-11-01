# Bundled PoeDash application

PoeDash is the only dashboard shipped with PoeDeploy. Its source, assets and
focused tests live in `poedash/`. Shared helpers live in `shared/`.

PoeDash displays the current hostname above a narrow, themed application rail.
Right-click applications to pin or unpin them. Pins appear above recent apps,
separated by a subtle line. History and pins persist across dashboard updates.

The wide layout uses three columns:

| | | |
| --- | --- | --- |
| Arch | System | Calendar |
| Performance | Top Processes | Connectivity |
| Player | Mounted Shares | Power, when a system battery exists |

The layout adapts to display scaling, desktop bars and narrower monitors.
Comfortable is the default with 16–20 px body text. Compact uses 14–17 px.
The dashboard button changes density live and saves the selection. App captions
use smaller text, with icons as their primary visual identifiers.

The Power card hides completely on desktops and the remaining cards reflow.
Remaining time appears only when the OS supplies a valid estimate. General
metrics update every two seconds on battery, with existing intervals preserved
on AC. Playing media updates independently every second. Hidden dashboards
pause metric collectors. Laptop GPU monitoring defaults to passive telemetry.
Set `gpu_monitoring` to `detailed` or `passive` in `layout.json` to override it.

The player supports MPRIS artwork, track details, progress and transport controls.
Clicking artwork or the track title opens the playing application. The calendar
reads Thunderbird's enabled local calendars and cached events without modifying
them. Titles wrap and the agenda scrolls. With no connected calendar, it shows
an empty agenda. Clicking the calendar opens Thunderbird Calendar.

## Install and refresh

Install from this checkout with `bash apps/poedash/install.sh`. The public
`poedash-latest` launcher downloads the maintained bundled source from PoeDeploy
main. Refresh with the dashboard control, `poedash update`, or
`bash poedeploy.sh --install-dashboard poedash`.

Refreshes replace managed dashboard files and bar controls without installing
packages or configuring repositories. Preferences, colours, pins and state are
retained. The installer backs up recognised legacy Eww configurations before
retiring them. Unrecognised Eww setups are left alone.

PoeDash supports ML4W QuickShell and Waybar controls. Its workspace observer
reconnects to Hyprland and hides the dashboard outside workspace 1. The surface
uses the Wayland bottom layer, above wallpaper and below application windows.

## Optional security applications

Security applications are independent of the dashboard. PoeDeploy offers
BlackArch repository setup, the curated security-tool collection and the official
PortSwigger Burp installer as separate choices. Select the BlackArch repository
before installing tools that require it.

From the repository root:

```bash
python3 installer/security-tools.py blackarch
python3 installer/security-tools.py security-tools
python3 installer/security-tools.py burp
```

Burp uses PortSwigger's native Linux installer and verifies the published SHA-256.
New installations use `~/.local/share/poedeploy/burp` and create
`~/.local/bin/burpsuite`. Existing native installations are retained, including
ones discoverable through that launcher. Use Burp's updater for new releases.
No AUR Burp package, browser proxy rules or certificates are installed.

## Validation

Run `python3 -m unittest discover -s tests` from the repository root, then
`python3 -m unittest discover -s apps/poedash/tests` for installer-specific tests.
Security installer tests live in the root suite alongside the dashboard tests.
