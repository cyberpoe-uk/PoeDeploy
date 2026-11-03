#!/usr/bin/env python3
"""Read CPU package/core sensors without waking discrete graphics."""
import json
from pathlib import Path


def reading(root=Path('/sys')):
    values = []
    for hwmon in (root / 'class/hwmon').glob('hwmon*'):
        try:
            name = (hwmon / 'name').read_text().strip()
        except OSError:
            continue
        if name not in ('coretemp', 'k10temp', 'zenpower', 'cpu_thermal'):
            continue
        for sensor in hwmon.glob('temp*_input'):
            try:
                value = int(sensor.read_text()) / 1000
                if 0 < value < 150:
                    values.append(value)
            except (OSError, ValueError):
                pass
    if not values:
        for zone in (root / 'class/thermal').glob('thermal_zone*'):
            try:
                if (zone / 'type').read_text().strip().lower() not in ('x86_pkg_temp', 'cpu-thermal', 'cpu_thermal'):
                    continue
                value = int((zone / 'temp').read_text()) / 1000
                if 0 < value < 150:
                    values.append(value)
            except (OSError, ValueError):
                pass
    return f'{max(values):.0f}°C' if values else '--'


if __name__ == '__main__':
    print(json.dumps(reading()))
