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
bash <(curl -fsSL https://cyberpoe.uk/latest-release)
```

This command downloads the latest stable release and shows you its version. If
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

## A few examples

If you only want to connect your NAS, choose **Choose sections**, select
**SMB / NFS shares**, and continue. PoeDeploy will not install the desktop or
change your boot setup.

If you want to change the boot animation, select **Plymouth boot theme**.

If you are setting up a fresh machine, **Full setup** takes you through every
section. Optional applications still start unselected, so you choose what you
actually want.

## Optional applications

The application list includes:

7-Zip, Discord, Firefox, GIMP, HyprMod, LibreOffice, LocalSend, OBS Studio,
PowerTOP, Spotify, Tailscale, Thunderbird, Visual Studio Code, and VLC.

PoeDeploy prefers packages from the official Arch repositories. It uses `yay`
when an application is only available from the Arch User Repository, usually
called the AUR.

If an optional application is taking too long, press **Ctrl+C** once. You can
then skip that application, retry it, or stop PoeDeploy. Skipping an application
does not remove anything that was already installed.

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
bash -n poedeploy.sh
python3 -m unittest discover -s tests -v
```
