# PoeDash

PoeDash is a local desktop dashboard for Hyprland. Choose either a standalone
GTK window or an Eww-owned window hosting the same GTK card/editor tree. Both
backends share `dashboard.json`, collectors, profiles, calendar, weather, card
interval controls, layout rules, history, idle and power integration.

```bash
poedash backend gtk
poedash backend eww
poedash backend status
```

Save pending edits before switching: the command restarts the surface. The
choice is preserved by dashboard updates. Eww mode requires Eww plus the common
`python-gobject`, `python-cairo`, `gtk-layer-shell` and GTK 3 dependencies, and
`gcc`/`pkgconf` to compile its small local host adapter. The installer includes
these packages. The adapter is cached per Python/platform/library version and
rebuilt when necessary. It does not hook global input or emulate a second UI.
There is no automatic downgrade to the older, feature-limited Eww renderer.

## Zoom

Use **− / percentage / +** beside the profile selector to scale the dashboard
from 50% to 200% in 5% steps. **↶** restores 100%. Cards stay within the screen
width and fit within the visible board. Card contents can scroll inside a
card; adding a card never extends the dashboard vertically. The header stays compact so zoom and profile
controls remain accessible. Zoom is saved per profile. During an editing session
it remains a preview until Save. Your saved card arrangement returns when there
is enough room; zoom alone does not replace it.

Resolution changes update the view live. Saved layouts are separate for each
display, resolution and display scale.

## Edit

The **Edit** button beside **Packages** provides:

- **Move & resize cards**: drag inside a card to move it; drag any edge or corner
  to resize. Only releasing within the central 65% of another card exchanges
  their slots, fitting each card to its new space; hovering or dropping on an
  edge does not swap cards. Expanding an edge into a neighbour shrinks that
  neighbour along the affected side. Resizing stops at usable minimum sizes.
  Nearby edge/gap snapping and alignment guides are optional. Moving/resizing
  uses the configured card spacing as the minimum gap; live measurements show
  when the spacing matches. Invalid placements roll back. Use **Save**, **Cancel**,
  **Undo**, **Redo**, or **Reset layout**. Ctrl+Z and Ctrl+Shift+Z/Ctrl+Y work in
  layout mode; Escape cancels the editing session.
- **Refresh intervals**: each card lists its data sources with seconds and
  increment/decrement controls. Performance has separate CPU, temperature, GPU
  and RAM intervals. Intervals range from 1 second to 24 hours. Restore defaults
  is available. Changes take effect when saved.
- **Appearance**: preview background opacity, font size, spacing, history graphs,
  graph range and snap grid. Save keeps changes; Cancel restores the saved view.
- **Add / hide cards**: control visibility and configure optional cards.
- **Profiles**: duplicate, rename, delete or reset profiles. Daily, Monitoring and
  Minimal are supplied. Each profile has its own card selection, appearance,
  intervals and separate layouts for each display/resolution.

Adding or hiding cards generates a new balanced layout on the current display.
Other display layouts remain saved. Short displays scroll the board; individual
cards also scroll when their content exceeds their chosen height. Recent Apps
remains in its own sidebar. Layout editing temporarily captures clicks so that
moving a card does not activate its normal controls.

## History and health

Performance displays CPU/RAM and CPU-temperature graphs, Connectivity displays
upload/download history, and Power displays battery-consumption history.
Performance and Connectivity readings and graph legends share their line colours.
Choose 5, 15, 30 or 60 minutes in Appearance. History is stored locally and limited to
one hour; collection gaps are not filled with invented samples.

The health strip reports disks at least 90% full, failed system/user services,
network disconnection, low battery, disconnected monitored shares and selected
VPNs. Select **Health/Details** to inspect issues or jump to a card. Use **Monitor
these mounts** on Mounted Shares, or enter expected paths and choose monitored
VPNs in Edit → Cards. Monitoring a VPN is opt-in.

Hover over a card's ↻ button to see its last update time. Collection errors and
stale readings change the button to a warning indicator, with details on hover.
Cards reserve their full body height for content, without an update footer.
The shared audio visualiser pauses whenever the dashboard is hidden. While
visible, it draws orange, red, purple and blue waveforms directly at 15 fps on
AC or 10 fps on battery in both backends, avoiding per-frame SVG file decoding.
On battery, collectors also pause while the dashboard
is hidden. On AC, collection continues. Custom refresh intervals are retained
across power-source changes. A card's ↻ button requests an immediate update.

Click a calendar date to show cached Thunderbird events for that day. Clicking
today restores the next-two-weeks agenda. Returning to the dashboard workspace
automatically returns the calendar to today. Date selection is temporary and
does not change Thunderbird or your saved dashboard settings.

## Card actions

- Mounted Shares opens a mount in the file manager and can monitor its presence.
- Top Processes filters/sorts its list and opens process details without exposing
  command-line arguments. btop remains available for deeper inspection.
- Connectivity opens addresses/routes; System expands storage/service details.
- Failed units in the health summary and System card open their exact system or
  user status and recent journal entries. Details load in the background and can
  be refreshed; opening them does not change the unit.
- Player scales artwork to the available card space and keeps the audio visualiser,
  seeking and playback controls at the bottom.
- Session & Idle adjusts and applies the existing Hypridle configuration.
- Power reads the existing power-profile policy and offers supported profiles.
- Notes saves locally after typing; Tasks saves a local checklist.

## Optional cards

Enable cards and enter their settings in Edit → Cards:

| Card | Configuration |
| --- | --- |
| Weather | Latitude and longitude; uses Open-Meteo, no key required |
| RSS Feeds | One HTTP(S) RSS/Atom URL per line, up to 20 feeds |
| Containers | Uses existing local `docker ps -a` access; Docker is not installed automatically |
| NAS | HTTP(S) endpoint returning a JSON object; optional bearer token |
| Remote Machine | HTTP(S) endpoint returning a JSON object; optional bearer token |
| Notes / Tasks | No external service required |

NAS and Remote Machine accept an existing service or agent's JSON endpoint, for
example:

```json
{"host":"nas", "status":"healthy", "disk_free_gib":240, "cpu_percent":18}
```

Fields are displayed as readable details. PoeDash does not install a server
agent or discover credentials. Requests occur only for cards that are enabled
and configured. Responses have a 2 MB limit and bounded timeouts. Feed links
open in your browser. Weather data is attributed to
[Open-Meteo](https://open-meteo.com/).

## Settings and recovery

The installation root defaults to `~/.config/poedash`. Profiles, layouts,
integration settings, notes and tasks are stored in `dashboard.json` with
user-only permissions. History is in `state/history.sqlite3`. Existing
`settings.json`, `layout.json`, palette and power/idle state are retained.

Writes are atomic. An invalid dashboard configuration is copied to a dated
`dashboard.invalid-*.json` before defaults are recovered. Installer updates
preserve `dashboard.json` and state, and create a backup as before.

`poedash start`, `stop`, `reload`, `enable` and `disable` handle the native
surface. Its local control socket is user-only. For GUI verification without
changing the installed dashboard, prepare a temporary root and run:

```sh
python scripts/dashboard_native.py --root /tmp/poedash-preview --preview --smoke
```

The offscreen check exercises pointer-driven swapping, resize handles, undo/
redo, settings panels, profile operations, save/cancel and card bounds. Results
and a screenshot are written under that temporary root's `state` directory.

For a compositor-level input regression check, run:

```sh
python apps/poedash/tests/gui/check_wayland.py --run
```

This opt-in check requires `wayland-scanner`, a C compiler and Wayland client
headers. It creates an isolated temporary configuration, briefly overlays a
Wayland test surface, and sends real virtual-pointer events through the
compositor. It checks card actions, Health, drag/swap, corner resize, visible
Save/Cancel controls, refresh interval editing, appearance preview/cancel and
layout saving. The pointer is restored and the temporary surface closes. The
installed dashboard settings are not used or changed.

To check the header against a top status bar's input region, run
`python3 apps/poedash/tests/gui/check_header_wayland.py --run` in Hyprland.
It checks Edit, Packages and zoom with real clicks, reproduces the old overlap,
and verifies the corrected placement. It briefly visits workspace 1 and restores
the original workspace and pointer; application launches are mocked.

Card clicks, seeking and expanded details across refreshes can also be checked
on a separate display without interacting with the desktop:

```sh
POEDASH_GUI_TEST=1 GDK_BACKEND=x11 xvfb-run -a -s '-screen 0 2560x1440x24' \
    python3 -m unittest discover -s tests -p test_dashboard_buttons_ui.py -v
```

Weather locations are chosen in **Edit → Cards → Weather location**. Search for a town or city, select the matching region/country, then Save. Existing coordinate-based settings remain compatible. Search results are provided by Open-Meteo geocoding (GeoNames); locations must exist in its database.

Weather shows original local SVG condition artwork, a condition-coloured current summary and a three-day forecast with high/low temperatures and precipitation probabilities. Clear nights use moon artwork. Icons are static and add no animation timers or image downloads.

Each card’s ⋯ editor includes inline − / + refresh controls for that card only, with a directly editable seconds value and Save/Cancel. The complete interval list remains under the dashboard’s top-right **Edit → Refresh intervals**. Cards such as Notes and Tasks need no polling interval.

Adding or hiding cards preserves the existing layout, including narrow custom cards. New cards use free space first. On a full dashboard, cards in the chosen column share the height reduction equally. Adding a card does not extend the scroll area; additions are refused if minimum usable sizes cannot be maintained. **Edit → Fit cards to screen** compacts an existing tall layout while retaining columns and gaps. Hidden cards remember their previous slot and return there when it is still free.


## Backend parity checks

Both frontends instantiate the same `Dashboard`, `Card`, calendar/weather editors
and layout model, rather than maintaining parallel implementations. Automated
checks cover configuration migration, backend persistence and startup locks.
The GTK offscreen check exercises fixed-height fitting; the Eww integration
check runs the actual shared UI in a separate, transparent, input-pass-through
Eww window and verifies card controls, weather search/Save, calendar dates,
workspace reset, release-only swaps/Undo and close/reopen cleanup.

```bash
python3 apps/poedash/tests/gui/check_fitted_layout.py --size 1440x960
python3 apps/poedash/tests/gui/check_eww_shared.py --run --startup
```

On another workstation, check out the feature branch and install it as your
normal desktop user (the installer backs up the existing dashboard):

```bash
python3 apps/poedash/poedash.py install --non-interactive
poedash backend gtk
# Save your edits, then compare the other backend:
poedash backend eww
```
