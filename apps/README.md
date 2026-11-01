# Bundled dashboard applications

PoeDash and PenDash are shipped with PoeDeploy so their installation does not
depend on separate websites or GitHub repositories. These directories contain
the program files, assets and focused tests required by each installer.

`poedash/` is the general workstation dashboard. `pendash/` provides the same
monitoring features alongside laptop telemetry and installs Chromium and a
curated set of BlackArch security tools. PenDash no longer includes Quick Launch,
CTF sessions, a target field, or readiness checks. Launch applications through
your desktop as usual; configure Chromium and Burp manually.

Both dashboards show:

- CPU, GPU and memory status, system specifications, load, and home disk usage.
- The ten busiest processes, including PID, CPU usage, and memory usage.
- Network state, route interface, local IPv4 and Tailscale addresses, Tailscale
  and Proton VPN client states, active tunnels, and mounted SMB/NFS shares.
- A media player with artwork, title, artist, playback progress, elapsed time,
  and previous/play-pause/next controls. Playing MPRIS players take priority over
  paused players. The logo opens an installed Spotify client on an unused
  workspace; Spotify installation is optional.
- Arch package counts and update indicators, kernel, uptime, and a calendar.

PenDash retains passive GPU monitoring and its laptop power card, including
battery discharge, remaining time, CPU profile, app activity and on-demand
PowerTOP scans. Its collectors pause when the dashboard is hidden and refresh
less often on battery. The content area scrolls on smaller screens. Missing
players, mounts or sensors show an empty state.

Dashboard updates are delivered by updating and rerunning PoeDeploy with
`--install-dashboard pendash`. Updates install missing dashboard dependencies,
including `playerctl`, and preserve colours, saved state, and the dashboard's
enabled/disabled setting. Existing browser data and user-configured proxy or
certificate settings are retained.
