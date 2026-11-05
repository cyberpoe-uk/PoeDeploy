# Bundled PoeDash application

PoeDash is the only dashboard shipped with PoeDeploy. Its source, assets and
focused tests live in `poedash/`. Shared helpers live in `shared/`.

PoeDash displays the current hostname above a narrow, themed application rail.
Right-click applications to pin or unpin them. Pins appear above recent apps,
separated by a subtle line. History and pins persist across dashboard updates.

The default wide layout places Arch, System, Connectivity, Session & Idle and
Power on the left; Performance, Top Processes and Mounted Shares in the middle;
and Calendar and Player on the right. Mounted Shares takes space from the
scrolling process list as its content grows.

**Edit** beside Packages opens layout editing, refresh intervals, appearance,
card visibility/integration settings and profile management. Cards can be moved,
resized from all edges/corners, or swapped. Save/Cancel, undo/redo, alignment
guides and optional snapping support editing. Profiles retain separate layouts
for each monitor. Zoom uses − / percentage / + / reset instead of density modes.

History graphs, a clickable health summary, per-card freshness/error reporting,
local Notes and Tasks, plus optional Weather, RSS, Containers, NAS and Remote
Machine cards are included. See the [PoeDash guide](poedash/README.md) for the
full feature list and setup details.

The dashboard uses GTK 3 and GTK Layer Shell directly. Eww is not required.
Refresh intervals are configurable per data source and persist across restarts.
Hidden dashboards pause collectors and UI feeds on battery; AC-powered dashboards
continue refreshing. Lightweight visibility/power checks and the separate
power-policy service remain active. Media has an independent worker. Laptop
GPU monitoring defaults to passive telemetry. Battery estimates appear only
when supplied by the operating system.

The player supports MPRIS artwork, track details, a seekable progress/wave slider
and transport controls. The multicolour wave grows with the played portion and
replaces the progress dot. The real output-monitor wave uses Cava when installed,
otherwise parec from libpulse. It never selects a microphone or saves audio.
Animation is capped at 12 fps on battery and 24 fps on AC, stops on pause, and
releases the monitor while a battery-powered dashboard is hidden.
With no player, Play offers background Spotify startup and saved-context resume.
Missing Spotify opens an approval dialog, then a prefilled package search.
The Player’s Open button activates the playing application. The calendar
reads Thunderbird's enabled local calendars and cached events without modifying
them. Titles wrap and the agenda scrolls. With no connected calendar, it shows
an empty agenda. Clicking the calendar opens Thunderbird Calendar. The agenda
covers the next 14 days, with up to eight events. CalDAV and other remote calendars
need Thunderbird's Offline Support and a completed sync. The card reports
uncached calendars explicitly. Every dashboard startup/reload/update checks for
installed Thunderbird and prompts through Rofi before enabling missing offline
caches. Consent is remembered per profile and calendar in
`state/calendar-consent.json`. Newly added calendars need approval, concurrent
refreshes share one dialog, and headless sessions never imply consent. The
one-minute agenda poll stays read-only. Opt in manually with
`~/.config/poedash/scripts/thunderbird-calendar.py --enable-offline-cache`, then
restart Thunderbird and synchronize. This writes only the affected calendar
cache preferences to `user.js` and backs up an existing file. Normal polls are
read-only. Exclusively locked databases use a bounded private copy with its WAL
and rollback journal, validated before use and removed afterward. Copies that
change during reading are retried up to three times. Locked databases larger
than 64 MiB including journals are reported as unavailable rather than copied.

## Package search

The header's **Packages** button uses the current Rofi configuration, with the
same popup size and theme as the application launcher. It searches repositories
and the AUR immediately, refreshing catalogs automatically on opening. Alt+R
or Choose repository filters a specific source while retaining the query.
Icon-backed entries precede plain entries, alphabetically within each group.
Repository and installed/update labels appear below each package name. Short descriptions appear inline. Alt+D or Full description opens the full text.
Repository descriptions use cached pacman metadata. AUR descriptions use a bulk
feed cached for an hour, avoiding per-hover or per-keystroke requests.
Only confirmed actions open an interactive Kitty transaction.
See [package search](../docs/package-search.md) for update checks, caching,
network limitations and the separate package-only and full-system-upgrade choices.

## Power and idle settings

Power has its own card beneath Session & Idle. Source, Profile and Selected by
identify power status, alongside battery consumption and remaining time. Supported
power profiles can be selected there or through QuickShell’s existing menu.
Screen Off, Lock Screen and Auto Suspend use independent minute controls, with
zero disabling a timer. Apply backs up and updates the discovered Hypridle config,
restarts the existing daemon and verifies registered timers. Other listeners,
source files, symlinks, before-sleep locks and resume hooks are retained. Unsupported
custom actions require manual review. Missing Hypridle/autostart configuration is
reported. No new idle service or privileged dashboard process is introduced.

The installer configures a single user service that listens for
power-supply events independently of the dashboard. Battery selects Power Saver,
AC and desktops select Performance, with a reported supported fallback when needed.
Manual overrides last until the next real power-source transition and survive
UI restarts. A new boot restores the automatic default at user-session startup.
Existing power-profiles or tuned backends are reused. Competing managers are never
installed. Use `poedash power disable`/`enable` to manage this feature separately
from dashboard visibility. Reinstall retains a disabled preference.

## Install and refresh

Install from this checkout with `bash apps/poedash/install.sh`. The public
`poedash-latest` launcher downloads the maintained bundled source from PoeDeploy
main. Refresh with the dashboard control, `poedash update`, or
`bash poedeploy.sh --install-dashboard poedash`.

Refreshes replace managed dashboard files and bar controls without installing
packages or configuring repositories. Preferences, colours, pins and state are
retained. The installer backs up recognised legacy Eww configurations before
retiring them. Unrecognised Eww setups are left alone. Recognised retired dashboard launchers,
workers, startup entries and theme hooks are removed, with bar controls rewired
to PoeDash. Integration files are backed up alongside the retired configuration.
Installed security tools and browser data remain intact.

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
