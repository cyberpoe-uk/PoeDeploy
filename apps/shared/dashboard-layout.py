#!/usr/bin/env python3
"""Persistent density and monitor-aware geometry shared by both dashboards."""
import argparse
import fcntl
import json
import os
from pathlib import Path
import select
import socket
import subprocess
import tempfile
import time


ROOT = Path(__file__).resolve().parent.parent


def load(path):
    try:
        data = json.loads(path.read_text())
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def density(root):
    value = load(root / 'layout.json').get('density', 'compact')
    return value if value in ('compact', 'comfortable') else 'compact'


def monitor_size(root):
    """Return logical pixels, accounting for rotation, scaling and reserved bars."""
    selector = load(root / 'settings.json').get('monitor', 0)
    try:
        result = subprocess.run(['hyprctl', 'monitors', '-j'], capture_output=True,
                                text=True, timeout=2, check=True)
        monitors = json.loads(result.stdout)
        if type(selector) is int:
            monitor = monitors[selector] if 0 <= selector < len(monitors) else monitors[0]
        else:
            monitor = next((item for item in monitors if item.get('name') == selector), monitors[0])
        width, height = float(monitor['width']), float(monitor['height'])
        if int(monitor.get('transform', 0)) % 2:
            width, height = height, width
        scale = float(monitor.get('scale', 1))
        left, top, right, bottom = monitor.get('reserved', [0, 0, 0, 0])
        return max(320, round(width / scale - left - right)), max(320, round(height / scale - top - bottom))
    except (OSError, ValueError, TypeError, KeyError, IndexError, StopIteration,
            ZeroDivisionError, subprocess.SubprocessError):
        return 1920, 1080


def geometry(width, height, mode='compact'):
    comfortable = mode == 'comfortable'
    padding, gap = (28, 16) if comfortable else (20, 10)
    minimum = 390 if comfortable else 350
    content = max(240, width - 2 * padding - 4)
    columns = min(3, max(1, (content + gap) // (minimum + gap)))
    cell_width = max(260, (content - (columns - 1) * gap) // columns)
    available = max(400, height - 2 * padding - (96 if comfortable else 78) - 2 * gap - 12)
    minimum_heights = (240, 275, 205) if comfortable else (195, 225, 175)
    heights = [max(minimum_height, round(available * ratio))
               for minimum_height, ratio in zip(minimum_heights, (0.32, 0.39, 0.29))]
    card_padding = 20 if comfortable else 14
    # Leave room for CSS padding when GTK calculates a card's minimum width.
    card_width = max(200, cell_width - 2 * card_padding - 4)
    return {
        'density': mode, 'columns': columns, 'gap': gap, 'row_gap': 12 if comfortable else 6, 'padding': padding,
        'card_width': card_width, 'card_padding': card_padding, 'top_height': heights[0],
        'middle_height': heights[1], 'bottom_height': heights[2],
        'list_height': max(90, heights[1] - 2 * card_padding - 62),
        'share_height': max(75, heights[2] - 2 * card_padding - 40),
        'power_height': max(75, heights[2] - 2 * card_padding - 40),
        'key_width': min(70, max(40, round(cell_width * 0.15))),
        'calendar_size': 16 if comfortable else (12 if height < 900 else 14),
        'hostname_width': max(10, min(63, (width - 2 * padding - (300 if columns > 1 else 0)) // 20)),
        'text_width': max(18, min(72, (cell_width - 2 * card_padding - 100) // (9 if comfortable else 8))),
    }


def snapshot(root):
    data = geometry(*monitor_size(root), density(root))
    data['hostname'] = socket.gethostname() or 'localhost'
    return data


def toggle(root):
    """Update Eww variables in place; no reload or collector restart is needed."""
    root.mkdir(parents=True, exist_ok=True)
    with (root / '.layout.lock').open('w') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        mode = 'comfortable' if density(root) == 'compact' else 'compact'
        preferences = load(root / 'layout.json')
        preferences['density'] = mode
        fd, temporary = tempfile.mkstemp(dir=root, prefix='.layout-')
        try:
            with os.fdopen(fd, 'w') as stream:
                json.dump(preferences, stream)
                stream.write('\n')
            os.replace(temporary, root / 'layout.json')
        finally:
            Path(temporary).unlink(missing_ok=True)
        data = snapshot(root)
        subprocess.run(['eww', '--config', str(root), 'update', 'layout=' + json.dumps(data)],
                       check=True, timeout=3)
        return data


def listen(root):
    previous = None

    def emit():
        nonlocal previous
        data = json.dumps(snapshot(root))
        if data != previous:
            print(data, flush=True)
            previous = data

    while True:
        emit()
        try:
            path = f"{os.environ['XDG_RUNTIME_DIR']}/hypr/{os.environ['HYPRLAND_INSTANCE_SIGNATURE']}/.socket2.sock"
            with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as connection:
                connection.settimeout(2)
                connection.connect(path)
                buffer = ''
                while True:
                    ready, _, _ = select.select([connection], [], [], 30)
                    if ready:
                        chunk = connection.recv(65536)
                        if not chunk:
                            break
                        buffer += chunk.decode(errors='replace')
                        lines = buffer.split('\n')
                        buffer = lines.pop()
                        if any(line.partition('>>')[0] in (
                                'monitoradded', 'monitoraddedv2', 'monitorremoved',
                                'configreloaded', 'focusedmon', 'focusedmonv2') for line in lines):
                            emit()
                    else:
                        emit()  # Also picks up hostname changes without a desktop restart.
        except (OSError, KeyError):
            pass
        time.sleep(2 if os.environ.get('HYPRLAND_INSTANCE_SIGNATURE') else 30)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('read', 'toggle', 'listen'), nargs='?', default='read')
    parser.add_argument('--root', type=Path, default=ROOT)
    args = parser.parse_args()
    if args.action == 'listen':
        listen(args.root)
    else:
        print(json.dumps(toggle(args.root) if args.action == 'toggle' else snapshot(args.root)))


if __name__ == '__main__':
    try:
        main()
    except (BrokenPipeError, KeyboardInterrupt):
        pass
