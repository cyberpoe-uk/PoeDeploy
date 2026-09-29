#!/usr/bin/env python3
"""NVIDIA first, then the first AMD DRM device exposing gpu_busy_percent."""
import json
from pathlib import Path
import subprocess


def reading(sysfs=Path('/sys/class/drm')):
    usage = temperature = None
    try:
        result = subprocess.run(['nvidia-smi', '--query-gpu=utilization.gpu,temperature.gpu', '--format=csv,noheader,nounits'], capture_output=True, text=True, timeout=3)
        if result.returncode == 0:
            fields = result.stdout.splitlines()[0].split(',')
            usage, temperature = (int(x.strip()) for x in fields)
    except (OSError, subprocess.SubprocessError, ValueError, IndexError):
        pass
    if usage is None:
        for device in sorted(sysfs.glob('card[0-9]*/device')):
            try:
                usage = int((device / 'gpu_busy_percent').read_text())
            except (OSError, ValueError):
                continue
            for sensor in sorted(device.glob('hwmon/hwmon*/temp1_input')):
                try:
                    temperature = round(int(sensor.read_text()) / 1000)
                    break
                except (OSError, ValueError):
                    pass
            break
    valid = usage is not None and 0 <= usage <= 100
    return {'usage': usage if valid else 0, 'label': f'{usage}%' if valid else '--',
            'temperature': f'{temperature}°C' if temperature is not None else '--'}


if __name__ == '__main__':
    print(json.dumps(reading()))
