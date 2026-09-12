# SMB and NFS shares

This section helps you connect an Arch Linux computer to a folder that is already
shared by another computer or NAS.

SMB is commonly used by Windows and many NAS devices. NFS is commonly used
between Linux systems. PoeDeploy connects to an existing share. It does not turn
your computer into a file server.

Choose **Choose sections**, select **SMB / NFS shares**, then choose SMB, NFS, or
both. PoeDeploy installs a missing connection tool only for the share type you
choose.

## What happens

1. Enter the server name or IP address.
2. Enter the SMB share name or the full NFS export path.
3. Choose a new, empty local folder under `/mnt` or `/media`. For example, use
   `/mnt/NAS`.
4. For SMB, enter the username, password, and optional domain or workgroup.
5. PoeDeploy tries the connection for up to 30 seconds. It also checks that your
   normal user can list the files. It does not write to or delete files on the
   server.
6. Only a successful share is saved to `/etc/fstab`. This is the system file that
   tells Linux which filesystems should be available after startup.

If the test fails, choose **Retry** to enter the details again or **Skip** to leave
the share out. Skip is the default. If you chose both SMB and NFS, skipping one
does not stop you from setting up the other.

SMB credentials are stored in unique, root-owned mode-600 files under
`/etc/samba/credentials/`. Passwords are not placed in fstab or external command
arguments. Existing credential files are never reused or overwritten. Successful
shares keep their credential file for later mounts. Empty local mount directories
may remain after a failed attempt. PoeDeploy does not recursively delete the
folder.

## How the saved share behaves

Saved entries include `_netdev,nofail,x-systemd.automount,x-systemd.mount-timeout=30s`:
they are network mounts, mount on access, and are not required for boot to
complete. See the [systemd mount documentation](https://man7.org/linux/man-pages/man5/systemd.mount.5.html).
`nosuid,nodev` is also set. SMB currently uses SMB 3.1.1. Older servers may fail
the test, and PoeDeploy does not silently downgrade the protocol.

NFS uses `fg,retry=0` to avoid prolonged initial connection retries. It retains
normal hard-mount behaviour. The `soft` option is not enabled to hide an unavailable
server, because it can risk data corruption. See the
[NFS options documentation](https://man7.org/linux/man-pages/man5/nfs.5.html).

A successful setup does not guarantee a server will remain available or that
you have write permissions. Access to a disconnected share can still wait or
fail. Timeouts cannot guarantee recovery from uninterruptible kernel I/O.
PoeDeploy never runs `mount -a` to test unrelated entries.

Existing bad entries from older runs are deliberately not deleted automatically.
If an entry already uses your target, inspect that entry or choose a new target.
Whitespace, backslashes, commas, control characters and `#` are not supported
in server, share, export, or mount fields. IPv6 server addresses require brackets.

## If cleanup or saving fails

Backups are named `/etc/fstab.poedeploy-backup.XXXXXX`. The exact name is printed
after a successful save or when rollback needs manual attention. A failed check
may also leave a backup. These backups contain local configuration and should be
treated accordingly.

If another process changes fstab during saving, PoeDeploy refuses to overwrite
that edit. If it cannot safely undo a new entry, or cannot unmount its test share,
it retains the resources that may still be needed and stops. Do not retry or
reboot without checking. Inspect fstab and the reported mount first. Backups are recovery
references, not a reason to overwrite newer unrelated entries wholesale.

Automated tests exercise failed mounts, wrong credentials via mount failure,
timeouts, access failures, duplicate targets, retry/skip, credential cleanup,
backup preservation, and rollback/concurrent-edit handling using local fixtures.
They do not replace testing against your actual NAS/server.

[Back to the README](../README.md)
