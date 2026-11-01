# Bundled dashboard applications

PoeDash and PenDash are shipped with PoeDeploy so their installation does not
depend on separate websites or GitHub repositories. These directories contain
the program files, assets and focused tests required by each installer.

`poedash/` is the general workstation dashboard. `pendash/` provides the same
monitoring features alongside laptop telemetry and installs Chromium and a
curated set of BlackArch security tools. PenDash no longer includes Quick Launch,
CTF sessions, a target field, or readiness checks. Launch applications through
your desktop as usual; configure Chromium and Burp manually.

Initial PenDash installation obtains Burp directly from PortSwigger's current
native Linux download, checks its published SHA-256, and installs it under
`~/.local/share/pendash/burp`. It selects x64 or ARM64 to match the machine,
uses the bundled Java runtime, and creates `~/.local/bin/burpsuite`. Choose
Community Edition, or activate an existing Professional license.
The `burpsuite` package is excluded from pacman and AUR installation. Existing
native PortSwigger installations are retained. Run `apps/pendash/install.sh
--install-burp` to install only Burp on an existing setup. Dashboard refreshes
do not install or upgrade Burp. Existing repository packages are retained.

Both dashboards show:

- CPU, GPU and memory status, system specifications, load, and home disk usage.
- The ten busiest processes, including PID, CPU usage, and memory usage.
- Network state, route interface, local IPv4 and Tailscale addresses, Tailscale
  and Proton VPN client states, active tunnels, and mounted SMB/NFS shares.
- A media player with artwork, title, artist, playback progress, elapsed time,
  and previous/play-pause/next controls. Playing MPRIS players take priority over
  paused players. Artwork and song names focus the playing application's window,
  using MPRIS activation when needed. With no active player, the artwork can open
  an installed Spotify client. Spotify installation is optional.
- Arch package counts and update indicators, kernel, uptime, and a calendar.
- A narrow themed app card below the hostname and dashboard name. Right-click
  apps to pin or unpin them. Pinned apps appear above recents with a subtle divider.
- An upcoming-events area beside or below the month grid. The calendar card
  opens Thunderbird's Calendar tab.

PenDash retains passive GPU monitoring and its laptop power card, including
battery discharge, remaining time, CPU profile, app activity and on-demand
PowerTOP scans. Its collectors pause when the dashboard is hidden and refresh
less often on battery. The content area scrolls on smaller screens. Missing
players, mounts or sensors show an empty state.

Both dashboards use the local hostname as their main heading and provide a live
Compact/Comfortable toggle. The grid is Arch/System/Calendar, then
Performance/Top Processes/Connectivity, then Player/Mounted Shares/Power. On
narrow displays it adapts to two or one columns. Text size and internal spacing
change immediately without restarting Eww or its collectors. Compact uses
16–20 px body text and Comfortable uses 20–24 px, with larger headings and controls.
Artwork scales with its card and song names wrap. App captions stay short, with
full names on hover. The density choice
is saved in each installed dashboard's `layout.json` and preserved during updates.
The shared `shared/dashboard-layout.py` helper is installed as `scripts/layout.py`
for both dashboards. It measures logical monitor dimensions and reserved bars,
and refreshes the layout when monitor configuration changes. Legacy PoeDash
pixel-size settings are retained for compatibility while the responsive grid
sets card widths automatically. The configured PoeDash name appears as a subtitle.

The shared `shared/desktop-actions.py` helper is installed as `scripts/desktop.py`
for both dashboards. It resolves desktop entries using XDG precedence, focuses
existing windows, and launches closed applications through GIO. New applications
open away from workspace 1. The Recent list shows up to 12 installed applications
and stores up to 20 desktop IDs in `$XDG_STATE_HOME/poedeploy/recent-apps.json`
(normally `~/.local/state/poedeploy/recent-apps.json`). Window titles, document
names, and command arguments are not stored. History survives dashboard updates.
Pins are stored alongside it in `pinned-apps.json` and shared between dashboards
on the same machine. A pin/unpin action updates the dashboard immediately.
Thunderbird is the default calendar application. The optional `calendar` setting
in `layout.json` accepts a desktop ID, `auto`, or `google`. Missing applications
produce a notification without installing packages.

The shared `thunderbird-calendar.py` reader selects Thunderbird's default profile,
reads enabled calendar registry entries, and opens `local.sqlite` and `cache.sqlite`
in read-only mode. It displays up to eight ongoing/upcoming events over 14 days,
including all-day events and daily, weekly, monthly and yearly recurrence,
exclusions and moved/cancelled occurrences. Calendar timestamps respect timezones
and daylight-saving changes. The display uses Thunderbird's cached data and
does not initiate synchronization or read account credentials. Unconfigured,
missing or unavailable calendars leave the events area empty. Calendars without
an offline cache need Thunderbird to cache their events before they can appear.
Recurrence support is bundled under `shared/calendar-vendor` with its licenses
and source checksums, so refreshing a dashboard does not install dependencies.

Workspace changes show and hide the widgets directly, without dashboard-wide
opacity rules that can leave an invisible surface with active tooltips. Both
dashboards use the shared workspace observer, matching Eww's monitor index or
connector name rather than assuming monitor ID 0. It preserves confirmed state
during IPC failures and rechecks periodically to recover missed events. The
Wayland bottom layer keeps the dashboard above wallpapers and below applications,
and startup recreates its surface so updated layer settings apply immediately.

Both dashboard update buttons download PoeDeploy's latest `main` branch, where
these applications are maintained, rather than waiting for a stable release tag.
The public `poedash-latest` and `pendash-latest` launchers also use the bundled
applications from PoeDeploy `main`. Run a current launcher once on older laptops
to replace an updater that still uses stable tags or a standalone repository.

Dashboard updates are also available through the PoeDeploy bootstrapper with
`--install-dashboard pendash` or `--install-dashboard poedash`; those actions
select `main` while normal full setup uses a stable release. Refreshes replace
dashboard files and bar controls without changing repositories or packages.
Colours, saved state, and the dashboard's enabled/disabled setting are retained,
along with existing browser data and user-configured proxy or certificate settings.
Initial installation can install the dashboard's dependencies, and the explicit
initial PenDash installation also configures its security tools.

Each installed dashboard carries a `dashboard-id` marker. The selected dashboard
is recorded in the XDG config directory under `poedeploy/dashboard`. Controls and
the update dispatcher reject identity mismatches, and update tooltips and terminal
titles name the dashboard they will update. Reinstalling PoeDash repairs a stale
QuickShell binding and backs up and retires the recognised legacy Eww dashboard.
