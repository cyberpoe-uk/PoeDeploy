# Bundled dashboard applications

PoeDash and PenDash are shipped with PoeDeploy so their installation does not
depend on separate websites or GitHub repositories. These directories contain
the program files, assets and focused tests required by each installer.

`poedash/` is the general dashboard with system, process, power, VPN, and
mounted-share monitoring. `pendash/` is the laptop-specific pentesting
dashboard. PenDash supports a dashboard-only mode that skips BlackArch, Burp
Suite, NVIDIA configuration and laptop power configuration.

Dashboard updates are delivered by updating and rerunning PoeDeploy.
