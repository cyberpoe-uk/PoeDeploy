# UKI and Secure Boot

On UEFI systems using systemd-boot, PoeDeploy can create a normal UKI for each installed kernel under the boot partition's `EFI/Linux` directory. It discovers the boot partition with `bootctl`, preserves the existing kernel arguments, adds the options required by Plymouth, backs up an existing `/etc/kernel/cmdline`, and keeps the existing traditional initramfs and loader entries intact. The proposed persistent command line is displayed with an explanation before the privileged write.

After generating the UKIs, PoeDeploy verifies that they are PE executables and asks for a reboot through the new UKI entry. Secure Boot configuration remains blocked until a later run confirms that the current system was successfully booted from a UKI. Mkinitcpio preset backups are stored beside the originals with the `.poedeploy.bak` suffix.

Secure Boot configuration is optional and uses `sbctl`. PoeDeploy requires separate typed confirmation before creating keys, enrolling keys, or signing EFI files. New key enrollment is only attempted when the firmware reports Setup Mode, and Microsoft certificates are included with `sbctl enroll-keys --microsoft`.

PoeDeploy builds configured UKIs before signing systemd-boot and the final UKIs, then runs `sbctl verify`. Firmware configuration and recovery knowledge are still the administrator's responsibility.

The UKI contains two distinct splash stages. Its PE `.splash` section is a static
firmware image shown by `systemd-stub`. PoeDeploy replaces the default Arch image
with plain black. Plymouth is stored inside the UKI's embedded initramfs and then
shows the selected animated theme. Building or signing a UKI does not replace the
Plymouth theme.

PoeDeploy updates an existing native `<preset>_splash` setting (including an
override of `ALL_splash`), or uses `<preset>_options="--splash ..."` when native
splash settings are absent. It removes duplicate splash options while keeping
unrelated options and other presets intact. It places `plymouth` after `systemd` or
`udev` in the hook list, and refreshes an already-installed PoeDeploy theme from
the current release. After building, it inspects each UKI and refuses Secure Boot
signing when the selected theme, `splash` kernel option or hook order is wrong, or
when the default Arch firmware splash remains embedded.

A Plymouth run selects the theme before rebuilding boot images once. Keeping the
current theme still rebuilds to apply refreshed assets and boot parameters. Build
or verification failures stop the run with an error instead of reporting success
or recommending a reboot. UKI extraction failures are reported separately from a
missing `splash` kernel argument.

Rebuilding a UKI changes its signed contents. When firmware Secure Boot is already
enabled, the mkinitcpio `sbctl` post-hook signs the rebuilt image and PoeDeploy runs
`sbctl verify` afterward. The full key creation and enrollment section runs only
when the user explicitly selects Secure Boot.

Signature verification calls `sbctl --json verify FILE` separately for each
target, never an unqualified scan of the entire ESP or signing database. A
successful command exit alone does not mean the file is signed. A Plymouth rebuild requires
every configured active UKI to have a signed result. With systemd-boot, it also
checks the current loader and identified fallback copies on the ESP. Discovery
uses targeted `bootctl` path queries and the embedded systemd-boot `LoaderInfo`
marker in the EFI binaries, not the full `bootctl status` report. The marker only
identifies the product. Signatures are still checked separately with `sbctl`.
The Secure Boot setup section registers and signs these identified copies,
including `EFI/BOOT/BOOTX64.EFI`. PoeDeploy does not register or separately sign
standalone `/boot/vmlinuz-*` kernels. Its signing commands target bootloaders and UKIs.
After an already-enabled Secure Boot system rebuilds its UKIs, PoeDeploy can also
automatically sign and register an unsigned identified systemd-boot fallback. It
first verifies the active loader and current UKI against the existing signing key
and confirms the current UKI's Plymouth configuration. It never signs an unknown
fallback merely because its filename matches, and does not reopen key enrollment.
It verifies the fallback again after signing. A failure remains a separate warning
without claiming that fallback protection passed.
Present standard fallback paths are checked individually when identified as
systemd-boot. Unknown fallback loaders are reported but never automatically signed.
A failed or timed-out fallback check is not treated as permission to sign it.
Unrelated EFI files and standalone `/boot/vmlinuz-*` kernels are not scanned.
The summary explicitly states this scope rather than claiming their signatures
were checked. A standalone kernel still requires a signature if explicitly passed
to the required-file verifier.
The report identifies the active loader and current UKI by path, verifies the
persistent kernel arguments embedded in the UKI, and reports fallback and standalone
kernel verification scope separately.
The summary separates Secure Boot setup, signature verification, boot image rebuilds,
and automatic fallback signing. Signing a standalone kernel does not authenticate
an external initramfs or command line. The signed UKI remains the intended boot path.

Read-only bootloader discovery queries, UKI identification, and each signature
check print progress and use a 30-second timeout followed by a five-second kill
grace period. Required-file failures stop verification without reporting success.
fallback failures remain separate warnings. Timeouts do not repair kernel faults
or guarantee recovery from uninterruptible kernel operations. Signing and image
rebuilds are not interrupted by these verification timeouts.

If the summary reports **keys created but not enrolled**, use the firmware's
documented procedure to enter Secure Boot Setup Mode. Custom mode by itself may
not enable Setup Mode. Check using `sudo sbctl status` after returning to Arch.
Rerun PoeDeploy, choose **Choose sections**, and select only
**Secure Boot** to complete enrollment and signing. Existing key files are not
treated as proof of enrollment: when Setup Mode is disabled, PoeDeploy asks
whether those exact keys have already been enrolled before proceeding to sign.

If the UKI reboot test is still pending, first boot through the UKI entry and then
rerun the Secure Boot section. After enrollment and signing, check
`sudo sbctl status` and review PoeDeploy's per-file signature results before
enabling Secure Boot enforcement in firmware. To recheck manually, use
`sudo timeout --kill-after=5s 30s sbctl verify /absolute/path/to/boot-file.efi`
with each actual boot file path, not a full ESP scan. See the
[sbctl workflow](https://github.com/Foxboron/sbctl/blob/master/docs/sbctl.8.txt).

[Back to the README](../README.md)
