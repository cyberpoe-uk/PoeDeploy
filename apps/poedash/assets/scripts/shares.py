#!/usr/bin/env python3
"""List active SMB and NFS mounts using findmnt's machine-readable JSON."""
import json
import subprocess
from pathlib import Path

try:
    result = subprocess.run(
        ['findmnt', '--json', '--types', 'cifs,nfs,nfs4,smb3', '--output', 'SOURCE,TARGET,FSTYPE'],
        capture_output=True, text=True, check=True, timeout=3)
    mounts = json.loads(result.stdout).get('filesystems', [])
    rows = [f"{item.get('fstype', '--').upper():5} {item.get('target', '--')}  ←  {item.get('source', '--')}"
            for item in mounts]
except (OSError, ValueError, subprocess.SubprocessError):
    rows = []
try:
    root = Path(__file__).resolve().parent.parent
    if not (root / 'dashboard-id').is_file():
        raise OSError('Not an installed dashboard')
    state = root / 'state'
    state.mkdir(parents=True, exist_ok=True)
    temporary = state / 'share-count.tmp'
    temporary.write_text(json.dumps({'count': len(rows), 'rows': rows}))
    temporary.replace(state / 'share-count.json')
except OSError:
    pass
print(json.dumps(rows or ['No SMB or NFS shares mounted']))
