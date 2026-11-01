#!/usr/bin/env python3
"""Persistent density and monitor-aware geometry shared by both dashboards."""
import argparse
import fcntl
import json
import math
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
    value = load(root / 'layout.json').get('density', 'comfortable')
    return value if value in ('compact', 'comfortable') else 'comfortable'


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


def geometry(width, height, mode='comfortable'):
    comfortable = mode == 'comfortable'
    padding, gap = (20, 10) if comfortable else (14, 8)
    if width < 600:
        padding, gap = 10, 8
    rail_width = (112 if comfortable else 100) if width >= 900 else (64 if width >= 600 else 52)
    minimum = 350 if comfortable else 320
    content = max(180, width - 2 * padding - rail_width - gap - 4)
    columns = min(3, max(1, (content + gap) // (minimum + gap)))
    cell_width = max(180, (content - (columns - 1) * gap) // columns)
    font_size = min(20, max(16, round(cell_width / 34))) if comfortable else min(17, max(14, round(cell_width / 38)))
    small_size = font_size - 2
    app_name_size = 11 if comfortable else 10
    heading_size = font_size + 2
    row_gap = 6 if comfortable else 4
    line_height = math.ceil(font_size * 1.35)
    header_height = 90 if comfortable else 80
    card_padding = 14 if comfortable else 10
    card_width = max(120, cell_width - 2 * card_padding - 4)
    calendar_size = font_size if card_width >= 450 else font_size - 2
    month_width = math.ceil(21 * calendar_size * 0.63)
    calendar_inline = card_width >= month_width + font_size * 8 + gap
    agenda_width = card_width - month_width - gap if calendar_inline else card_width
    agenda_height = max(90, 6 * font_size)
    calendar_height = (8 * math.ceil(calendar_size * 1.35) + heading_size + 2 * card_padding + 3 * row_gap + 4
                       + (0 if calendar_inline else agenda_height + 2 * line_height))
    available = max(400, height - 2 * padding - header_height - 2 * gap - 12)
    # System specifications can wrap onto two lines. Connectivity has seven rows.
    minimum_heights = (max(calendar_height, 2 * card_padding + heading_size + 7 * line_height + 6 * row_gap),
                       2 * card_padding + heading_size + 7 * (line_height + row_gap),
                       220 if comfortable else 195)
    heights = [max(minimum_height, round(available * ratio))
               for minimum_height, ratio in zip(minimum_heights, (0.32, 0.39, 0.29))]
    # Leave room for CSS padding when GTK calculates a card's minimum width.
    char_width = font_size * 0.62
    key_width = math.ceil(small_size * 0.62 * 9)
    media_control = 34 if comfortable else 28
    album_size = min(192 if comfortable else 144, round(card_width * 0.34),
                     heights[2] - 2 * card_padding - heading_size - media_control - 4 * row_gap - 16)
    album_size = max(64 if comfortable else 56, album_size)
    media_text_width = max(80, card_width - album_size - 16)
    rail_content_width = max(24, rail_width - 2 * card_padding - 4)
    return {
        'density': mode, 'columns': columns, 'gap': gap, 'row_gap': row_gap, 'padding': padding,
        'rail_width': rail_width, 'rail_labels': width >= 900,
        'rail_content_width': rail_content_width,
        'app_name_size': app_name_size,
        'rail_name_chars': max(3, int(rail_content_width / (app_name_size * 0.62)) - 3),
        'card_width': card_width, 'card_padding': card_padding, 'top_height': heights[0],
        'middle_height': heights[1], 'bottom_height': heights[2],
        'list_height': max(90, heights[1] - 2 * card_padding - 2 * line_height - row_gap),
        'share_height': max(75, heights[2] - 2 * card_padding - 2 * line_height - row_gap),
        'power_height': max(75, heights[2] - 2 * card_padding - line_height - row_gap),
        'font_size': font_size, 'small_size': small_size, 'heading_size': heading_size,
        'title_size': font_size + (16 if comfortable else 14), 'media_title_size': font_size + 4,
        'media_control': media_control, 'album_size': album_size,
        'media_text_width': media_text_width,
        'process_name_chars': max(6, int((card_width - small_size * 0.62 * 12) / char_width)),
        'key_width': key_width,
        'calendar_size': calendar_size, 'calendar_inline': calendar_inline,
        'month_width': month_width, 'agenda_width': agenda_width, 'agenda_height': agenda_height,
        'hostname_width': max(6, min(63, int((width - rail_width - gap - 2 * padding - (360 if columns > 1 else 0)) / ((font_size + 16) * 0.62)))),
        'stat_key_chars': max(6, min(15, int(card_width / (2 * char_width)))),
        'text_width': max(4, min(72, int((card_width - 15 * char_width - 10) / char_width))),
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
