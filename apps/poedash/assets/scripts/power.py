#!/usr/bin/env python3
"""Report measured battery discharge power and battery state when available."""
import json
from pathlib import Path


def number(path):
    try:
        return float(path.read_text().strip())
    except (OSError, ValueError):
        return None


data = {'watts': '--', 'battery': '--', 'status': 'Power sensor unavailable'}
for battery in sorted(Path('/sys/class/power_supply').glob('BAT*')):
    status_path = battery / 'status'
    try:
        status = status_path.read_text().strip()
    except OSError:
        status = 'Unknown'
    watts = number(battery / 'power_now')
    if watts is None:
        current = number(battery / 'current_now')
        voltage = number(battery / 'voltage_now')
        watts = current * voltage / 1_000_000 if current is not None and voltage is not None else None
    capacity = number(battery / 'capacity')
    data = {
        'watts': f'{watts / 1_000_000:.1f} W' if watts is not None else '--',
        'battery': f'{capacity:.0f}%' if capacity is not None else '--',
        'status': status,
    }
    break
print(json.dumps(data))
