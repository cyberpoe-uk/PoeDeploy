#!/usr/bin/env python3
"""Run a collector at AC/battery-specific ages and return its cached value."""
import hashlib
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time


def on_ac(root=Path('/sys/class/power_supply')):
    battery = False
    sources = []
    for supply in root.glob('*'):
        try:
            kind = (supply / 'type').read_text().strip()
            scope = (supply / 'scope').read_text().strip() if (supply / 'scope').exists() else 'System'
            if kind == 'Battery' and scope != 'Device':
                battery = True
            elif (supply / 'online').exists():
                sources.append((supply / 'online').read_text().strip() == '1')
        except OSError:
            continue
    return any(sources) if battery else True


def main():
    if len(sys.argv) < 5:
        raise SystemExit('usage: adaptive-run.py KEY AC_SECONDS BATTERY_SECONDS COMMAND...')
    key, ac_age, battery_age, *command = sys.argv[1:]
    age = int(ac_age if on_ac() else battery_age)
    cache_dir = Path(os.environ.get('XDG_RUNTIME_DIR', '/tmp')) / f'poedash-{os.getuid()}' / 'adaptive'
    cache_dir.mkdir(parents=True, exist_ok=True)
    safe = hashlib.sha256(key.encode()).hexdigest()[:16]
    cache = cache_dir / safe
    try:
        if time.time() - cache.stat().st_mtime < age:
            print(cache.read_text(), end='')
            return
    except OSError:
        pass
    result = subprocess.run(command, capture_output=True, text=True, timeout=max(5, age))
    if result.returncode == 0 and result.stdout:
        fd, temporary = tempfile.mkstemp(dir=cache_dir, prefix='.' + safe)
        with os.fdopen(fd, 'w') as stream:
            stream.write(result.stdout)
        os.replace(temporary, cache)
        print(result.stdout, end='')
    elif cache.exists():
        print(cache.read_text(), end='')
    else:
        raise SystemExit(result.returncode or 1)


if __name__ == '__main__':
    main()
