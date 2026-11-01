#!/usr/bin/env python3
"""Return the ten busiest processes without exposing their arguments."""
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
            rows.append(f'{command[:16]:16} {pid:>7} {cpu:>6}% {memory:>6}%')
        if len(rows) == 10:
            break
except (OSError, subprocess.SubprocessError):
    rows = []
print(json.dumps(rows or ['No process data available']))
