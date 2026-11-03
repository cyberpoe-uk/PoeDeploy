#!/usr/bin/env python3
"""Persistent density and monitor-aware geometry for PoeDash."""
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


def _geometry(width, height, mode='comfortable'):
    comfortable = mode == 'comfortable'
    padding, gap = (16, 10) if comfortable else (12, 8)
    if height < 900:
        padding, gap = (12, 8) if comfortable else (10, 6)
    if width < 600:
        padding, gap = 6, 4
    rail_width = (100 if comfortable else 88) if width >= 900 else (56 if width >= 600 else 44)
    content = max(180, width - 2 * padding - rail_width - gap - 12)
    columns = 3 if width >= 960 else 2 if width >= 600 else 1
    cell_width = max(180, (content - (columns - 1) * gap) // columns)
    font_size = min(24, max(16, round(cell_width / 34))) if comfortable else min(22, max(14, round(cell_width / 38)))
    if height < 900: font_size -= 4 if comfortable else 3
    if height < 740: font_size -= 1
    if columns < 3: font_size = min(font_size, 10 if comfortable else 9)
    if cell_width < 320: font_size = min(font_size, 11 if comfortable else 10)
    font_size = max(9, font_size)
    small_size = max(8, font_size - 2)
    app_name_size = min(11 if comfortable else 10, small_size)
    heading_size = font_size + 2
    row_gap = (6 if comfortable else 4) if height >= 900 else (4 if comfortable else 3)
    line_height = math.ceil(font_size * 1.35)
    title_size = font_size + (12 if comfortable else 10)
    header_height = math.ceil(title_size * 1.35) + math.ceil(small_size * 1.35) + 14
    if columns == 1:
        header_height = 2 * (math.ceil(title_size * 1.35) + math.ceil(small_size * 1.35) + 4) + math.ceil(font_size * 1.35) + (16 if comfortable else 12) + 46
    card_padding = (12 if comfortable else 9) if height >= 900 else (10 if comfortable else 8)
    if columns < 3:
        row_gap, card_padding = 2, 6
    card_width = max(120, cell_width - 2 * card_padding - 4)
    calendar_size = font_size if card_width >= 450 else max(9, font_size - 2)
    month_width = math.ceil(21 * calendar_size * 0.63)
    calendar_inline = card_width >= month_width + 65 + gap
    agenda_width = card_width - month_width - gap if calendar_inline else card_width
    rows = 3 if columns == 3 else 5 if columns == 2 else 9
    available = max(90, height - 2 * padding - header_height - gap - (rows - 1) * gap - 64)
    if columns == 3:
        arch_height = 2 * card_padding + heading_size + 4 * line_height + 4 * row_gap + 4
        performance_height = max(2 * card_padding + heading_size + 5 * line_height + 5 * row_gap + 4, round(available * .31))
        player_height = available - arch_height - performance_height
        system_height = 2 * card_padding + heading_size + 7 * line_height + 4 * row_gap + 4
        processes_height = round(available * .43)
        shares_height = available - system_height - processes_height
        power_height = min(round(available * .42), 14 * font_size + 2 * card_padding + 32)
        connectivity_height = max(2 * card_padding + heading_size + 7 * line_height + 6 * row_gap + 4, round(available * .27))
        calendar_height = available - power_height - connectivity_height
    else:
        row_height = available // rows
        arch_height = system_height = calendar_height = performance_height = row_height
        processes_height = connectivity_height = player_height = shares_height = power_height = row_height
    heights = [min(arch_height, system_height, calendar_height), min(performance_height, processes_height, connectivity_height), player_height]
    agenda_height = max(30, calendar_height - 2 * card_padding - heading_size - 2 * line_height - 3 * row_gap)
    # Leave room for CSS padding when GTK calculates a card's minimum width.
    char_width = font_size * 0.62
    key_width = math.ceil(small_size * 0.62 * 9)
    media_control = 34 if comfortable else 28
    album_size = min(round(card_width * .48),
                     player_height - 2 * card_padding - heading_size - media_control - 4 * row_gap - 16)
    album_size = max(28, album_size)
    media_text_width = max(80, card_width - album_size - 16)
    rail_content_width = max(24, rail_width - 2 * card_padding - 4)
    grid = '(box :space-evenly true :spacing {layout.gap} :vexpand true'
    card_columns = [('arch','performance','player'),('system','processes','shares'),('calendar','connectivity','power')] if columns == 3 else [tuple(['arch','system','calendar','performance','processes','connectivity','player','shares','power'][i::columns]) for i in range(columns)]
    for cards in card_columns:
        grid += '(box :orientation \"v\" :space-evenly false :spacing {layout.gap} :vexpand true'
        for card in cards:
            key = 'management' if card == 'power' else card
            widget = f'({card}-card :height {{layout.{key}_height}})'
            if columns < 3:
                widget = f'(scroll :hscroll false :vscroll true :width 0 :height {{layout.{key}_height}} {widget})'
            grid += widget
        grid += ')'
    grid += ')'
    return {
        'grid': grid, 'density': mode, 'columns': columns, 'gap': gap, 'row_gap': row_gap, 'padding': padding,
        'rail_width': rail_width, 'rail_labels': width >= 900,
        'rail_content_width': rail_content_width,
        'app_name_size': app_name_size,
        'rail_name_chars': max(3, int(rail_content_width / (app_name_size * 0.62)) - 3),
        'card_width': card_width, 'card_padding': card_padding,
        'arch_height': arch_height, 'system_height': system_height, 'calendar_height': calendar_height,
        'performance_height': performance_height, 'processes_height': processes_height,
        'connectivity_height': connectivity_height, 'player_height': player_height,
        'shares_height': shares_height, 'management_height': power_height, 'header_height': header_height,
        'top_height': heights[0],
        'middle_height': heights[1], 'bottom_height': heights[2],
        'list_height': max(20, processes_height - 2 * card_padding - 2 * line_height - row_gap),
        'share_height': max(20, shares_height - 2 * card_padding - 2 * line_height - row_gap),
        'power_height': max(20, power_height - 2 * card_padding - heading_size - 3 * line_height - 3 * row_gap),
        'font_size': font_size, 'small_size': small_size, 'heading_size': heading_size,
        'title_size': title_size, 'media_title_size': font_size + 4,
        'media_control': media_control, 'album_size': album_size,
        'media_text_width': media_text_width,
        'process_name_chars': max(6, int((card_width - small_size * 0.62 * 12) / char_width)),
        'key_width': key_width,
        'calendar_size': calendar_size, 'calendar_inline': calendar_inline,
        'month_width': month_width, 'agenda_width': agenda_width, 'agenda_height': agenda_height,
        'hostname_width': max(6, min(63, int((width - rail_width - gap - 2 * padding - (360 if columns > 1 else 0)) / (title_size * 0.62)))),
        'stat_key_chars': max(6, min(15, int(card_width / (2 * char_width)))),
        'text_width': max(4, min(72, int((card_width - 15 * char_width - 10) / char_width))),
    }



def geometry(width, height, mode='comfortable'):
    # Preserve established card bounds and spacing. Only typography changes:
    # Comfortable inherits the original Compact sizes; Compact is six px smaller.
    data = _geometry(width, height, mode)
    previous = _geometry(width, height, 'compact')
    reduction = 6 if mode == 'compact' else 0
    for key in ('font_size', 'small_size', 'heading_size', 'title_size',
                'media_title_size', 'app_name_size', 'calendar_size'):
        floor = 8 if key in ('small_size', 'app_name_size') else 9
        data[key] = max(floor, previous[key] - reduction)
    # Preserve recent/pinned app captions exactly as in v1.5.7.
    data['app_name_size'] = max(8, previous['app_name_size'] - 2) if mode == 'compact' else previous['app_name_size']
    char_width = data['font_size'] * .62
    data['rail_name_chars'] = max(3, int(data['rail_content_width'] / (data['app_name_size'] * .62)) - 3)
    data['process_name_chars'] = max(6, int((data['card_width'] - data['small_size'] * .62 * 12) / char_width))
    data['key_width'] = math.ceil(data['small_size'] * .62 * 9)
    data['wave_height'] = min(42, max(24, data['font_size'] * 2))
    data['album_size'] = max(28, data['album_size'] - data['wave_height'] + 6)
    data['media_text_width'] = max(80, data['card_width'] - data['album_size'] - 16)
    data['session_width'] = max(24, int((data['card_width'] - 16 - 2 * data['row_gap']) // 3))
    data['stat_key_chars'] = max(6, min(15, int(data['card_width'] / (2 * char_width))))
    data['text_width'] = max(4, min(72, int((data['card_width'] - 15 * char_width - 10) / char_width)))
    data['hostname_width'] = max(6, min(63, int((width - data['rail_width'] - data['gap'] - 2 * data['padding']
                                              - (500 if data['columns'] > 1 else 0)) / (data['title_size'] * .62))))
    return data


def poedash_geometry(width, height, mode='comfortable', share_count=0, share_rows=None):
    """Balance the PoeDash columns; smaller displays scroll each card."""
    data = geometry(width, height, mode)
    gap = data['gap']
    # Give the middle column 20% more width, drawing equally from each side.
    base_width = data['card_width']
    donation = round(base_width * .10) if data['columns'] == 3 else 0
    data['card_width'] = base_width - donation
    data['middle_width'] = base_width + 2 * donation
    budget = max(100, height - 2 * data['padding'] - data['header_height'] - gap - 32)
    line = math.ceil(data['font_size'] * 1.35) + data['row_gap']
    chrome = 2 * data['card_padding'] + data['heading_size'] + 8
    columns = [('arch', 'system', 'connectivity', 'session', 'power'),
               ('performance', 'processes', 'shares'), ('calendar', 'player')]
    desired = {'arch': chrome + 4 * line, 'system': chrome + 7 * line,
               'connectivity': chrome + 7 * line, 'session': chrome + 6 * line,
               'power': chrome + 7 * line}
    if data['columns'] == 3:
        room = budget - 4 * gap
        # Reserve usable heights and scroll card contents when space is tight.
        factor = min(1, room / sum(desired.values()))
        for name, size in desired.items():
            data[name + '_height'] = max(1, int(size * factor))
        # Power consumes all space left below the other left-column cards.
        data['power_height'] = room - sum(data[name + '_height'] for name in ('arch', 'system', 'connectivity', 'session'))
        data['performance_height'] = chrome + 6 * line
        room = budget - 2 * gap
        data['performance_height'] = min(data['performance_height'], int(room * .45))
        chars = max(12, int((data['middle_width'] - 32) / (data['font_size'] * .65)))
        # Allow extra lines for word wrapping and the row's CSS padding.
        share_lines = sum(max(2, math.ceil(len(row) / chars) + 1) for row in share_rows) if share_rows else max(1, share_count) * 3
        wanted = chrome + (2 + share_lines) * line + max(1, share_count) * 8
        process_minimum = max(100, int(room * .22))
        data['shares_height'] = min(room - data['performance_height'] - process_minimum,
                                    max(int(room * .26), wanted))
        data['processes_height'] = room - data['performance_height'] - data['shares_height']
        data['calendar_height'] = int((budget - gap) * .60)
        data['player_height'] = budget - gap - data['calendar_height']
    else:
        ordered = ['arch', 'system', 'connectivity', 'session', 'power',
                   'performance', 'processes', 'shares', 'calendar', 'player']
        columns = [tuple(ordered[i::data['columns']]) for i in range(data['columns'])]
        for cards in columns:
            size = max(1, (budget - (len(cards) - 1) * gap) // len(cards))
            for name in cards:
                data[name + '_height'] = size
    grid = '(box :space-evenly false :spacing {layout.gap} :vexpand true'
    for cards in columns:
        column_width = 'middle_width' if 'performance' in cards and data['columns'] == 3 else 'card_width'
        grid += (f'(box :orientation "v" :space-evenly false :spacing {{layout.gap}} :vexpand true'
                 f' :width {{layout.{column_width} + 2 * layout.card_padding + 4}}')
        for card in cards:
            # Bound minimum widget sizes so tall content cannot push cards off screen.
            expand = 'true' if card == cards[-1] else 'false'
            grid += (f'(scroll :hscroll false :vscroll true :vexpand {expand} :width 0 :height {{layout.{card}_height}}'
                     f' ({card}-card :height {{layout.{card}_height}}))')
        grid += ')'
    data['grid'] = grid + ')'
    data['management_height'] = data['power_height']
    data['idle_height'] = max(20, data['session_height'] - chrome)
    data['list_height'] = max(20, data['processes_height'] - chrome - line)
    data['share_height'] = max(20, data['shares_height'] - chrome - line)
    data['session_width'] = max(24, int((data['card_width'] - 16 - 2 * data['row_gap']) // 3))
    data['calendar_inline'] = data['card_width'] >= data['month_width'] + 65 + gap
    data['agenda_width'] = data['card_width'] - data['month_width'] - gap if data['calendar_inline'] else data['card_width']
    data['process_name_chars'] = max(6, int((data['middle_width'] - data['small_size'] * .62 * 12) / (data['font_size'] * .62)))
    data['agenda_height'] = max(30, data['calendar_height'] - chrome - 2 * line)
    data['album_size'] = max(28, min(data['album_size'], data['player_height'] - chrome - data['media_control'] - data['wave_height'] - 3 * gap))
    data['media_text_width'] = max(80, data['card_width'] - data['album_size'] - 16)
    return data


def snapshot(root):
    size, mode = monitor_size(root), density(root)
    if (root / 'dashboard-id').exists() and (root / 'dashboard-id').read_text().strip() == 'poedash':
        shares = load(root / 'state/share-count.json')
        data = poedash_geometry(*size, mode, share_count=shares.get('count', 0), share_rows=shares.get('rows'))
    else:
        data = geometry(*size, mode)
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



def ui_paused(root):
    try:
        return (root / 'state/refresh-paused').read_text().strip() == 'true'
    except OSError:
        return False

def listen(root):
    previous, previous_grid = None, None

    def emit():
        nonlocal previous, previous_grid
        if previous is not None and ui_paused(root):
            return
        data = snapshot(root)
        encoded = json.dumps(data)
        grid = data['grid']
        if previous_grid is not None and grid != previous_grid and (root / 'scripts/start.sh').is_file():
            # Eww 0.5 retains widget scopes when literal children are replaced.
            # A topology change uses the existing scoped startup/reload path.
            subprocess.Popen([str(root / 'scripts/start.sh')], stdout=subprocess.DEVNULL,
                             stderr=subprocess.DEVNULL, start_new_session=True)
            return
        if encoded != previous:
            try:
                state = root / 'state'
                state.mkdir(parents=True, exist_ok=True)
                (state / 'wave-size.json').write_text(json.dumps({'width': data['card_width'], 'height': data['wave_height']}))
            except OSError:
                pass
            try:
                subprocess.run(['eww','--config',str(root),'update','layout='+encoded], check=True, timeout=3)
            except (OSError, subprocess.SubprocessError):
                return
            previous = encoded
        if grid != previous_grid:
            print(grid, flush=True)
            previous_grid = grid

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
