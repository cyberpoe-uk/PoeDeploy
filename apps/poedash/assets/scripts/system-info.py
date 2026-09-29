#!/usr/bin/env python3
"""Small, dependency-free system summary for PoeDash."""
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess


def first_line(path, default='--'):
    try:
        return Path(path).read_text(errors='replace').splitlines()[0].strip() or default
    except (OSError, IndexError):
        return default


def os_name():
    values = {}
    try:
        for line in Path('/etc/os-release').read_text().splitlines():
            if '=' in line:
                key, value = line.split('=', 1)
                values[key] = value.strip().strip('"')
    except OSError:
        pass
    return values.get('PRETTY_NAME', platform.system())


def cpu_name():
    try:
        for line in Path('/proc/cpuinfo').read_text(errors='replace').splitlines():
            if line.lower().startswith(('model name', 'hardware')) and ':' in line:
                return line.split(':', 1)[1].strip()
    except OSError:
        pass
    return platform.processor() or '--'


def gpu_name():
    try:
        result = subprocess.run(['lspci'], capture_output=True, text=True, check=True, timeout=3)
        for line in result.stdout.splitlines():
            if 'VGA compatible controller:' in line or '3D controller:' in line:
                return line.split(': ', 1)[-1].strip()
    except (OSError, subprocess.SubprocessError):
        pass
    cards = sorted(Path('/sys/class/drm').glob('card[0-9]*/device'))
    for card in cards:
        vendor = first_line(card / 'vendor', '')
        device = first_line(card / 'device', '')
        if vendor or device:
            return (vendor + ':' + device).strip(':')
    return '--'


usage = shutil.disk_usage(Path.home())
memory = {}
try:
    for line in Path('/proc/meminfo').read_text().splitlines():
        key, value = line.split(':', 1)
        memory[key] = int(value.split()[0]) * 1024
except (OSError, ValueError, IndexError):
    pass

print(json.dumps({
    'host': platform.node() or '--',
    'os': os_name(),
    'kernel': platform.release(),
    'cpu': cpu_name(),
    'gpu': gpu_name(),
    'memory': f"{memory.get('MemTotal', 0) / 2**30:.1f} GiB" if memory else '--',
    'disk': f"{usage.used / 2**30:.0f} / {usage.total / 2**30:.0f} GiB",
    'load': ' '.join(f'{value:.2f}' for value in os.getloadavg()),
}))
