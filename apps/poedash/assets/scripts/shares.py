#!/usr/bin/env python3
"""List active SMB and NFS mounts using findmnt's machine-readable JSON."""
import json
import subprocess

try:
    result = subprocess.run(
        ['findmnt', '--json', '--types', 'cifs,nfs,nfs4,smb3', '--output', 'SOURCE,TARGET,FSTYPE'],
        capture_output=True, text=True, check=True, timeout=3)
    mounts = json.loads(result.stdout).get('filesystems', [])
    rows = [f"{item.get('fstype', '--').upper():5} {item.get('target', '--')}  ←  {item.get('source', '--')}"
            for item in mounts[:5]]
except (OSError, ValueError, subprocess.SubprocessError):
    rows = []
print(json.dumps(rows or ['No SMB or NFS shares mounted']))
