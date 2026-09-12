# SMB and NFS shares

Choose **Choose sections → SMB / NFS shares**, then SMB, NFS, or both.
Only the selected protocols' missing mount helpers are installed. This is a
client setup tool: it connects to existing shares, not a file-server installer.

## What happens

1. Enter a server hostname/IP, share name (SMB) or absolute export path (NFS),
   and a dedicated local directory under `/mnt` or `/media`. SMB also asks for
   a username, password and optional domain/workgroup.
2. PoeDeploy rejects unsafe/ambiguous input, symlink paths, existing mount points,
   existing fstab targets, and directories that already contain files.
3. It creates a temporary, single-entry mount table and tests that entry with a
   30-second mount timeout (plus a five-second termination grace period).
   It checks the actual mounted source and filesystem type, then attempts a
   directory listing as your user with a 15-second timeout. It does not write to
   or delete anything on the server.
4. Only after these checks does it save the entry. The complete candidate fstab
   is checked with `findmnt --verify`, backed up, and replaced atomically while
   holding a PoeDeploy writer lock. A systemd reload follows. A reload failure
   rolls back the new entry if the file still matches what PoeDeploy wrote.
5. A failed attempt removes its temporary configuration and newly generated SMB
   credentials, unmounting its test mount if needed. Choose **Retry** to re-enter
   the details, or **Skip** (the default). Choosing both protocols allows the
   second setup to continue after skipping the first.

SMB credentials are stored in unique, root-owned mode-600 files under
`/etc/samba/credentials/`. Passwords are not placed in fstab or external command
arguments. Existing credential files are never reused or overwritten. Successful
shares keep their credential file for later mounts. Empty local mount directories
may remain after a failed attempt; no recursive directory deletion is used.

## Boot behaviour and limits

Saved entries include `_netdev,nofail,x-systemd.automount,x-systemd.mount-timeout=30s`:
they are network mounts, mount on access, and are not required for boot to
complete. See the [systemd mount documentation](https://man7.org/linux/man-pages/man5/systemd.mount.5.html).
`nosuid,nodev` is also set. SMB currently uses SMB 3.1.1; older servers may fail
the test, and PoeDeploy does not silently downgrade the protocol.

NFS uses `fg,retry=0` to avoid prolonged initial connection retries. It retains
normal hard-mount I/O semantics: `soft` is not enabled to disguise an unavailable
server, because it can risk data corruption. See the
[NFS options documentation](https://man7.org/linux/man-pages/man5/nfs.5.html).

A successful setup does not guarantee a server will remain available or that
you have write permissions. Access to a disconnected share can still wait or
fail. Timeouts cannot guarantee recovery from uninterruptible kernel I/O.
PoeDeploy never runs `mount -a` to test unrelated entries.

Existing bad entries from older runs are deliberately not deleted automatically.
If an entry already uses your target, inspect that entry or choose a new target.
Whitespace, backslashes, commas, control characters and `#` are not supported
in server/share/export/mount fields; IPv6 server addresses require brackets.

## If cleanup or saving fails

Backups are named `/etc/fstab.poedeploy-backup.XXXXXX`; the exact name is printed
after a successful save or when rollback needs manual attention. A failed check
may also leave a backup. These backups contain local configuration and should be
treated accordingly.

If another process changes fstab during saving, PoeDeploy refuses to overwrite
that edit. If it cannot safely undo a new entry, or cannot unmount its test share,
it retains the resources that may still be needed and stops. Do not retry or
reboot blindly: inspect fstab and the reported mount first. Backups are recovery
references, not a reason to overwrite newer unrelated entries wholesale.

Automated tests exercise failed mounts, wrong credentials via mount failure,
timeouts, access failures, duplicate targets, retry/skip, credential cleanup,
backup preservation, and rollback/concurrent-edit handling using local fixtures.
They do not replace testing against your actual NAS/server.

[Back to the README](../README.md)
