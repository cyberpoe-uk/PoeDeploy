# Testing a kernel update

Use a normal package update to test the persistent configuration. Do not rerun
PoeDeploy, select Plymouth again, manually run `mkinitcpio -P`, or manually sign
files between the update and verification. That could hide a failed update hook.
The menu/summary cleanup does not require reinstalling the existing boot setup.

Before updating, save your work, have backups and recovery media available, and
confirm `/boot` is mounted read-write without unresolved filesystem errors.
Record the baseline:

```bash
uname -r
pacman -Q linux
findmnt /boot
plymouth-set-default-theme
```

Then run `sudo pacman -Syu` directly and retain its output. Confirm that the
transaction actually upgrades the kernel. Otherwise this is not a kernel-upgrade
test. Watch for successful initramfs generation and, on a UKI system, UKI creation
and automatic signing. If the update or boot-image hooks fail, stop before
rebooting and investigate. Do not use a standalone `pacman -Sy`.

Before rebooting, check the generated image for the selected theme. For the
traditional `linux` initramfs and PoeDeploy theme:

```bash
sudo lsinitcpio /boot/initramfs-linux.img |
    grep -F 'usr/share/plymouth/themes/poedeploy/poedeploy.plymouth'
```

On a UKI machine, use its configured UKI path instead of the initramfs path and
verify the active loader, rebuilt UKI and fallback with explicit paths:

```bash
sudo timeout --kill-after=5s 30s sbctl verify \
    /boot/EFI/systemd/systemd-bootx64.efi \
    /boot/EFI/Linux/arch-linux.efi \
    /boot/EFI/BOOT/BOOTX64.EFI
```

These are example paths for the previously tested x64 laptop. Use the machine's
actual configured paths. Read each file's result, not just the command exit code.
An ordinary initramfs system does not exercise UKI generation or Secure Boot
signing, and does not need converting to UKI just for this test.

After a successful update and pre-reboot checks, reboot normally. Confirm
`uname -r` reports the new kernel, `/proc/cmdline` still contains `splash`, and the
full PoeDeploy theme appears with its blue progress bar. On the UKI laptop also
check the expected black early splash, Secure Boot status, and signatures again.
Review `sudo journalctl -k -b -p warning --no-pager` for new kernel faults. A clean
update/reboot does not by itself resolve the earlier kernel fault or establish
whether suspend or resume was involved. That is a separate test.

[Back to the README](../README.md)
