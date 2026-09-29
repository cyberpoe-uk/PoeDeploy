#!/usr/bin/env python3
"""Passive laptop telemetry; no NVIDIA queries and no privileged polling."""
import json
import os
from pathlib import Path
import subprocess
import time


def read(p):
    try: return Path(p).read_text().strip()
    except OSError: return ''


def number(p):
    try: return float(read(p))
    except ValueError: return None


def battery_info(root=Path('/sys/class/power_supply')):
    batteries = [p for p in root.glob('*') if read(p / 'type') == 'Battery'
                 and read(p / 'scope') != 'Device' and read(p / 'present') != '0']
    if not batteries:
        return dict(laptop=False, battery='No system battery', draw='--', remaining='--', status='Desktop')
    now = full = watts = 0.0
    energy_ok = rate_ok = True
    capacities = []
    statuses = []
    for b in batteries:
        statuses.append(read(b / 'status'))
        e, f = number(b / 'energy_now'), number(b / 'energy_full')
        voltage = number(b / 'voltage_now')
        if e is None or f is None:
            q, qf = number(b / 'charge_now'), number(b / 'charge_full')
            if None not in (q, qf, voltage):
                e, f = q * voltage / 1e6, qf * voltage / 1e6
        if e is None or f is None:
            energy_ok = False
        else:
            now += e / 1e6
            full += f / 1e6
        cap = number(b / 'capacity')
        if cap is not None: capacities.append(cap)
        w = number(b / 'power_now')
        if w is None:
            current = number(b / 'current_now')
            if current is not None and voltage is not None: w = abs(current * voltage) / 1e6
        if w is None: rate_ok = False
        else: watts += abs(w) / 1e6
    pct = now / full * 100 if energy_ok and full else sum(capacities) / len(capacities) if capacities else None
    discharging = all(s == 'Discharging' for s in statuses)
    status = 'Battery' if discharging else 'Charging' if 'Charging' in statuses else 'AC / full'
    remaining = '--'
    if discharging and energy_ok and rate_ok and watts > 0.1:
        minutes = int(now / watts * 60)
        remaining = f'~{minutes // 60}h {minutes % 60:02d}m left'
    # Charging battery watts are not whole-system power draw.
    draw = f'{watts:.1f} W' if discharging and rate_ok else 'AC · draw unavailable'
    return dict(laptop=True, battery=f'{pct:.0f}%' if pct is not None else '--', draw=draw,
                remaining=remaining, status=status)


def app_activity(cache):
    timestamp = time.monotonic()
    snap = {}
    for p in Path('/proc').glob('[0-9]*'):
        try:
            if p.stat().st_uid != os.getuid() or int(p.name) == os.getpid(): continue
            raw = (p / 'stat').read_text()
            end = raw.rfind(')')
            fields = raw[end + 2:].split()
            snap[p.name] = [raw[raw.index('(') + 1:end], int(fields[11]) + int(fields[12]), fields[19]]
        except (OSError, ValueError, IndexError): pass
    try: old = json.loads(cache.read_text())
    except (OSError, ValueError): old = {}
    cache.parent.mkdir(parents=True, exist_ok=True)
    cache.write_text(json.dumps({'time': timestamp, 'processes': snap}))
    elapsed = timestamp - old.get('time', timestamp)
    if not 0.5 < elapsed < 20: return ['Sampling…', '', '']
    groups = {}
    for pid, (name, ticks, start) in snap.items():
        before = old.get('processes', {}).get(pid)
        if not before or before[2] != start: continue
        delta = max(0, ticks - before[1])
        groups[name] = groups.get(name, 0) + delta
    hz = os.sysconf('SC_CLK_TCK')
    top = sorted(groups.items(), key=lambda item: item[1], reverse=True)[:3]
    rows = [f'{name}: {ticks / hz / elapsed * 100:.1f}% CPU' for name, ticks in top if ticks > 0]
    return (rows + ['Idle', '', ''])[:3]


def main():
    data = battery_info()
    data.update(profile='--', effects='--', top1='', top2='', top3='', pt_label='PowerTOP scan',
                pt_detail='Measure application wakeups on demand; no per-app watts are inferred.')
    if data['laptop']:
        runtime = Path(os.environ.get('XDG_RUNTIME_DIR', '/tmp')) / f'poedash-{os.getuid()}'
        runtime.mkdir(mode=0o700, exist_ok=True)
        for key, value in zip(('top1', 'top2', 'top3'), app_activity(runtime / 'apps.json')):
            data[key] = value
        try:
            data['profile'] = subprocess.check_output(['powerprofilesctl', 'get'], text=True, timeout=2).strip()
        except (OSError, subprocess.SubprocessError): pass
        base = Path.home() / '.config/hypr/hyprmod'
        try:
            meta = json.loads((base / 'profiles' / read(base / 'active_profile') / 'meta.json').read_text())
            data['effects'] = meta['name'].replace('CyberProfile - ', '')
        except (OSError, ValueError, KeyError): pass
        pt = Path.home() / '.cache/eww/powertop.json'
        try:
            report = json.loads(pt.read_text())
            age = max(0, int((time.time() - report['timestamp']) / 60))
            data['pt_label'] = f'PowerTOP · {age}m ago'
            rows = report.get('apps', [])
            data['pt_detail'] = 'Last measured app wakeups (not watts):\n' + '\n'.join(
                f'{row["name"]}: {row["wakeups"]:.1f}/s' for row in rows)
        except (OSError, ValueError, KeyError): pass
    print(json.dumps(data))


if __name__ == '__main__': main()
