# PoeDeploy

<p align="center">
  <img src="assets/poedeploy-logo.png" alt="PoeDeploy logo" width="500">
</p>

## Set up Arch Linux, or just the part you need

I made PoeDeploy to help me set up my Arch Linux machines without having to
remember every command each time. It can guide you through a full setup, but you
do not have to use it that way.

You can also open PoeDeploy when you only want help with one job, such as:

- connecting an SMB or NFS network share
- setting up a Plymouth boot theme
- creating a Unified Kernel Image, also known as a UKI
- setting up Secure Boot
- installing a few optional applications
- setting your default browser
- configuring Tailscale

PoeDeploy shows what it plans to run before it starts. You can use it on a new
installation or come back later and choose another section.

## Start PoeDeploy

PoeDeploy is made for Arch Linux. Run it as your normal user. It will ask for
your sudo password only when a task needs administrator access.

```bash
bash <(curl -fsSL https://cyberpoe.uk/poedeploy-latest)
```

This command downloads the latest stable release and shows its version number. If
Git is missing, PoeDeploy explains why it is needed and asks before installing it.

You will then see three choices:

- **Choose sections:** pick only the jobs you want to run. This is the default.
- **Full setup:** go through the complete Arch setup with optional choices.
- **Exit:** close PoeDeploy without starting the setup.

If you are unsure, choose **Choose sections**. Nothing is selected at first and
nothing starts until you review your choices and confirm them.

You can also clone the
[PoeDeploy repository](https://github.com/cyberpoe-uk/PoeDeploy) and read the
script before running it.

To see the layout without running any setup tasks, open a terminal in your local
PoeDeploy folder and run:

```bash
bash poedeploy.sh --preview
```

During installation, PoeDeploy uses a static terminal dashboard showing the real
stage count, current operation, completed and pending stages, warnings, errors,
and the log path. Press `L` to switch to the live log and `Q` or Esc to return.
On the main dashboard, `Q` aborts the active task. Normal command output is kept
out of the dashboard and written to the log instead.

Password prompts temporarily restore the normal terminal. AUR builds and external
installers also use the normal terminal for their entire run so their own sudo
prompts can read every keystroke. Their output appears directly in the terminal,
then the progress dashboard returns when they finish.

Sections with menus or confirmations (Plymouth, UKI, ML4W, SDDM, browser,
network shares, fingerprint authentication, and Secure Boot) keep the normal terminal for the whole section.
This keeps descriptions, menu choices, and questions together. The progress
dashboard returns between sections and uses a compact view in small terminals.

The preferred log is `/var/log/poedeploy.log`. When that location is not
writable, PoeDeploy uses `~/.local/state/poedeploy/poedeploy.log`. The normal
terminal screen and cursor are restored after completion, failure, or Ctrl+C.

## A few examples

If you only want to connect your NAS, choose **Choose sections**, select
**SMB / NFS shares**, and continue. PoeDeploy will not install the desktop or
change your boot setup.

If you want to change the boot animation, select **Plymouth boot theme**. The
included choices are PoeDeploy plus static and animated BlackArch Green, Orange,
Purple, Red, Blue, and White themes, alongside any Plymouth themes already
installed on the system.

If you are setting up a fresh machine, **Full setup** takes you through every
section. Optional applications still start unselected, so you choose what you
actually want.

Plymouth themes use an interactive picker: arrows or `j/k` move, `h/l` change
pages, `g/G` jump to the first/last entry, and Enter applies the theme.
Esc cancels. **Keep current theme** leaves the selection unchanged.
The progress dashboard pauses while you choose a theme. If the interactive
picker is unavailable, the numbered theme list and prompt appear together in
the normal terminal.

## Optional applications

The application list includes:

7-Zip, Discord, Firefox, GIMP, HyprMod, LibreOffice, LocalSend, OBS Studio,
PenDash, PoeDash, PowerTOP, Proton VPN, Spotify, Tailscale, Thunderbird,
Visual Studio Code, and VLC.

PoeDash and PenDash are bundled under `apps/` and install directly from the
PoeDeploy release. Choose only one dashboard.

Both dashboards show the current machine's hostname prominently in the top-left
corner. Their Compact/Comfortable button changes text size and internal spacing
immediately, and remembers the choice across restarts and updates. On wide
screens the cards use three aligned rows:

| | | |
| --- | --- | --- |
| Arch | System | Calendar |
| Performance | Top Processes | Connectivity |
| Player | Mounted Shares | Power |

The layout accounts for display scaling and desktop bars, and switches to fewer
columns on narrow displays. Long process, share and laptop activity lists scroll
inside their cards. Comfortable mode can use vertical scrolling on short screens.

PoeDash is the general dashboard. Its installer offers `PoeDash` as the default
subtitle and lets the user enter another subtitle. It shows performance, laptop power
and battery data when available, the top ten processes, host specifications,
MPRIS media controls, active VPN interfaces, mounted
SMB/NFS shares, package updates, and a compact calendar.

PoeDeploy asks for the PoeDash subtitle during the visible application-planning
step. The background installation and dashboard updates are non-interactive, so
they cannot stall behind the static progress screen.

**PenDash (dashboard + security tools)** adds the BlackArch repository using
its [official, checksum-verified bootstrapper](https://blackarch.org/downloads.html)
and installs Burp Suite Community (`burpsuite`), ffuf, Gobuster, Nmap, sqlmap,
Wfuzz, Wireshark, and jwt-tool alongside the dashboard and Chromium.
Chromium launches normally. Configure its Burp proxy and certificates manually.
PenDash does not configure NVIDIA or apply laptop power rules.

When updating an older PenDash setup, the installer backs up and removes known,
unmodified proxy/certificate helper scripts and their exact managed Chromium
flags. Custom flags, browser profiles, and certificate stores are retained.

Both dashboards add enable/disable and update controls to a supported ML4W
QuickShell status bar. The update control downloads the latest PoeDeploy `main`
branch and refreshes the selected dashboard from its maintained bundled copy.
Dashboard changes are available as soon as they are pushed, without a release
tag. The bootstrapper also uses `main` with `--install-dashboard poedash` or
`--install-dashboard pendash`. Normal full setup continues to use stable releases. Selecting
the same dashboard in PoeDeploy performs the same clean refresh: managed
interface files are replaced while Eww itself, dashboard preferences, the
enabled state, colour palette, and browser state are retained. Dashboard refreshes
only replace dashboard files and bar integration. They do not add repositories,
install security tools, or install or upgrade packages. BlackArch and curated
security tools belong to the explicit initial PenDash installation.

Installers record the selected dashboard in `~/.config/poedeploy/dashboard`.
Updates from stale controls for another dashboard are rejected before setup runs.

PoeDeploy prefers packages from the official Arch repositories. It uses `yay`
when an application is only available from the Arch User Repository, usually
called the AUR.

PoeDeploy's full setup installs Tailscale and enables `tailscaled` at boot.
Selecting Tailscale in Optional applications also enables and starts its service.
For a selected-section run, choose Tailscale service to install and enable it.
The user completes authentication with `sudo tailscale up`.
PoeDash and PenDash do not install Tailscale or Proton VPN. They display
`Not installed` when a client is absent, and its connection state when present.

[Proton VPN's Arch installation](https://protonvpn.com/support/linux-vpn-arch)
uses `proton-vpn-gtk-app`. Selecting it also installs NetworkManager and
GNOME Keyring. Start NetworkManager (the **NetworkManager** setup section can
handle this), then open Proton VPN and sign in. Split tunneling additionally
requires `systemd-resolved`. PoeDeploy does not change your DNS configuration.

If an optional application is taking too long, press **Ctrl+C** once. You can
then skip that application, retry it, or stop PoeDeploy. Skipping an application
does not remove anything that was already installed.

## Fingerprint authentication

**Fingerprint authentication** appears immediately after **SDDM login screen**.
You can select it independently or use it during full setup. Installation starts
only after you opt in. Run it on the booted system, not inside an Arch chroot.

PoeDeploy tries Arch's `fprintd` and `libfprint` for standard readers. For the
Goodix **GDIX51C0** SPI sensor, it offers the experimental
[Goodix SPI driver](https://github.com/berkekbgz/libfprint-goodix-spi), pinned to
revision `505dc7e4602cae828e5a1e80221f3fec8e15411e`, which was enrolled and
verified on a Huawei laptop. Other Goodix models are not assumed compatible.
The upstream driver has only been hardware-tested on a MateBook 16s. Other
machines may need GPIO configuration. PoeDeploy does not guess GPIO lines.

The Goodix path installs the build dependencies, including `glib2-devel`,
builds the driver's pinned libfprint/fprintd sources, and installs shadow copies
under `/opt/goodix-spi-driver`. Arch's packaged libfprint is retained. Sources
are retained under `${XDG_CACHE_HOME:-$HOME/.cache}/poedeploy/goodix-*`. Run that
checkout's `uninstall.sh` to remove the custom driver. The upstream installer
keeps protected sensor state under `/var/lib/fprint`. Its normal uninstall
preserves that state. Linux may provision a sensor key. On dual-boot systems,
Windows and Linux can replace each other's key.

The section offers right-index-finger enrollment and then requires a successful
recognition test before offering login changes. You can decline enrollment to
test an existing right-index print. Failed detection or verification leaves
login configuration unchanged. Enrollment requires repeated touches, so prompts
and the external installer run in the normal terminal.

After successful verification, you can enable SDDM sign-in and Hyprlock unlock
where installed. Configuration files receive timestamped backups. Repeating
PoeDeploy's configuration is safe. Unfamiliar existing authentication settings
are left for manual review. This section does not change `sudo`, `su`, SSH, or
the shared system authentication stack.

- **SDDM:** select your user, leave the password blank, press Enter, then touch
  the sensor. After a failed scan or up to ten seconds, use your password.
- **Hyprlock:** touch the sensor at the lock screen or type your password.
  Fingerprint and password authentication run in parallel.

No reboot is needed to test screen unlock. Fingerprints do not unlock encrypted
disks at boot, and a login keyring may still request its password. Fingerprint
setup does not install camera or facial-recognition software.

## Default browser

Choose **Default browser** to see the browsers registered on your desktop,
including exported Flatpak and Snap launchers. PoeDeploy shows your current
settings first. Press Enter or choose **Keep the current default** to leave them
alone.

Choosing a browser also sets and checks the defaults for HTTP and HTTPS links and
HTML files. Email applications that use the system default will open web links in
that browser. Apps with their own browser setting may need that changed separately.
This does not change your default email application.

## Safer network share setup

PoeDeploy checks an SMB or NFS share before saving it for future use. It first
tries to connect and confirms that your user can see the files.

If the check fails, the share is not added to `/etc/fstab`. PoeDeploy removes
the temporary setup and lets you retry with corrected details or skip it. This
helps protect you from a typing mistake causing trouble on the next boot.

Use a new, empty folder under `/mnt` or `/media` for the local mount point. For
example, you could use `/mnt/NAS`. PoeDeploy will not overwrite an existing share
or mount over a folder that already contains files.

For more information, read the
[SMB and NFS share guide](docs/network-shares.md).

## Please read before using the boot sections

The UKI and Secure Boot sections make important changes to how your computer
starts. Keep a backup and recovery USB available before using them.

PoeDeploy checks its work and asks separately before creating keys, enrolling
keys, or signing boot files. However, your firmware settings and hardware can be
different from another machine.

Read the [UKI, Plymouth and Secure Boot guide](docs/boot-and-secure-boot.md) before
using those sections. There is also a separate
[kernel update test guide](docs/kernel-update-check.md).

## More information

- [SMB and NFS share setup](docs/network-shares.md)
- [UKI, Plymouth and Secure Boot](docs/boot-and-secure-boot.md)
- [Testing a kernel update](docs/kernel-update-check.md)
- [PoeDeploy theme files](themes/README.md)

The tests folder is for checking changes before a new release. It is not needed
when you run PoeDeploy through the command above, but keeping it in the GitHub
repository helps make sure the same safety checks are available on every machine.

To run those checks while developing PoeDeploy:

```bash
bash -n poedeploy.sh poedeploy-latest ui/*.sh installer/*.sh
python3 -m unittest discover -s tests -v
```

## Installer architecture

The existing setup functions remain in `poedeploy.sh`, while the new runtime is
split into three layers:

- `installer/applications.sh` dispatches the bundled PoeDash and PenDash installers.
- `apps/poedash/` and `apps/pendash/` contain their program files, assets, and
  focused regression tests.
- `ui/progress.sh` owns stage state and real progress calculations.
- `ui/dashboard.sh` and `ui/keyboard.sh` render the static TTY and handle keys.
- `ui/logger.sh` owns the log and provides `run_cmd` and `run_cmd_capture` for
  new or gradually refactored installer operations.

The ordered `SETUP_MODULE_IDS` and `SETUP_MODULE_LABELS` declarations define the
stages. To add one, add its ID and label, implement its setup function, and add a
dispatcher case in `run_setup_module`. Installer code reports detail with
`info`, `success`, `warning`, or `ui_set_operation`. It never needs to draw the
dashboard itself.

Each selected stage runs as a worker. `setup_module_needs_terminal` marks stages
that need the normal terminal throughout their menus and confirmations. The
renderer acknowledges each handoff before the worker can read input and
acknowledges the completed redraw before the next handoff. External installers
use `ui_run_interactive`, which preserves shell state and warning counts.
The parent restores terminal settings and resumes the dashboard even if a
worker fails. Frames use actual TTY dimensions, explicit carriage returns,
display-column padding, and sanitised log text so command output cannot move
the dashboard cursor.
A failed critical stage offers retry, log, or abort. Explicitly safe
optional stages also offer skip.

Inside an Arch chroot, PoeDeploy allows the chroot's root user, runs privileged
commands directly, and enables services without trying to start them. Tasks that
need a running graphical session or real boot state may still need to be rerun
after the first boot.

## Development note

I developed PoeDeploy with the help of AI tools under my direct supervision.
AI helps me build and test the installer faster and more efficiently while I
work a full-time job and continue learning coding and scripting. I review the
changes, test the workflows, and make the final decisions for the project.
