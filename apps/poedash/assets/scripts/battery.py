#!/usr/bin/env python3
"""System batteries and OS estimates, without deriving remaining time."""
import math
from pathlib import Path
import subprocess

POWER_SUPPLY = Path('/sys/class/power_supply')


def read(path):
    try:
        return path.read_text().strip()
    except OSError:
        return ''


def number(path):
    try:
        value = float(read(path))
        return value if math.isfinite(value) and value >= 0 else None
    except ValueError:
        return None


def estimate(batteries):
    if len(batteries) == 1:
        seconds = number(batteries[0] / 'time_to_empty_now')
        if seconds and 60 <= seconds <= 31_536_000:
            return seconds
    try:
        value = subprocess.run(['busctl', '--system', '--auto-start=no', 'get-property',
            'org.freedesktop.UPower', '/org/freedesktop/UPower/devices/DisplayDevice',
            'org.freedesktop.UPower.Device', 'TimeToEmpty'],
            capture_output=True, text=True, check=True, timeout=0.5).stdout.split()
        if len(value) == 2 and value[0] == 'x' and 60 <= int(value[1]) <= 31_536_000:
            return int(value[1])
    except (OSError, ValueError, subprocess.SubprocessError):
        pass
    return None


def reading(root=POWER_SUPPLY, with_estimate=True):
    result = {'present': False, 'on_battery': False, 'available': False,
              'battery': '--', 'watts': '--', 'status': 'Unavailable', 'remaining': ''}
    try:
        supplies = list(root.iterdir())
    except OSError:
        return result
    batteries = [path for path in supplies if read(path / 'type') == 'Battery'
                 and read(path / 'scope') != 'Device' and read(path / 'present') != '0']
    if not batteries:
        return result
    online = [read(path / 'online') for path in supplies if read(path / 'type') != 'Battery'
              and read(path / 'scope') != 'Device' and (path / 'online').exists()]
    statuses = [read(path / 'status') for path in batteries]
    on_battery = not any(value == '1' for value in online) and (
        'Discharging' in statuses or bool(online) and all(value == '0' for value in online))
    energy, full, capacities, rates = [], [], [], []
    for path in batteries:
        voltage = number(path / 'voltage_now')
        current = number(path / 'current_now')
        now, total = number(path / 'energy_now'), number(path / 'energy_full')
        if now is None or total is None:
            charge, charge_full = number(path / 'charge_now'), number(path / 'charge_full')
            if None not in (charge, charge_full, voltage):
                now, total = charge * voltage / 1e6, charge_full * voltage / 1e6
        if now is not None and total is not None and total > 0:
            energy.append(now)
            full.append(total)
        capacity = number(path / 'capacity')
        if capacity is not None and capacity <= 100:
            capacities.append(capacity)
        rate = number(path / 'power_now')
        if rate is None and None not in (current, voltage):
            rate = current * voltage / 1e6
        if rate is not None:
            rates.append(rate)
    percent = (100 * sum(energy) / sum(full) if len(energy) == len(batteries)
               else sum(capacities) / len(capacities) if capacities else None)
    seconds = estimate(batteries) if with_estimate and on_battery else None
    result.update(present=True, on_battery=bool(on_battery), available=len(rates) == len(batteries),
                  battery=f'{min(100, percent):.0f}%' if percent is not None else '--',
                  watts=f'{sum(rates) / 1e6:.1f} W' if len(rates) == len(batteries) else '--',
                  status='Discharging' if on_battery else 'Charging' if 'Charging' in statuses else 'AC / full' if online or 'Full' in statuses else 'Unknown')
    if seconds:
        minutes = int(seconds // 60)
        result['remaining'] = f'{minutes // 60}h {minutes % 60:02d}m remaining'
    return result
