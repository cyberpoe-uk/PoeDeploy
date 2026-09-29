#!/usr/bin/env python3
"""Return the five busiest processes without exposing their arguments."""
import json
import subprocess

try:
    result = subprocess.run(
        ['ps', '-eo', 'pid=,comm=,%cpu=,%mem=', '--sort=-%cpu'],
        capture_output=True, text=True, check=True, timeout=3)
    rows = []
    for line in result.stdout.splitlines():
        fields = line.split(None, 3)
        if len(fields) == 4 and fields[1] != 'ps':
            pid, command, cpu, memory = fields
            rows.append(f'{command[:20]:20}  {cpu:>5}% CPU  {memory:>5}% MEM  #{pid}')
        if len(rows) == 5:
            break
except (OSError, subprocess.SubprocessError):
    rows = []
print(json.dumps(rows or ['No process data available']))
