# Fingerprint authentication

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

