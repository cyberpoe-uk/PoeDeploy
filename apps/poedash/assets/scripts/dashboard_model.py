"""Persistent dashboard profiles, edit transactions, geometry and local history.

This module has no GUI dependencies so validation and layout behaviour can be
checked without a running compositor.
"""
from copy import deepcopy
import json
import math
import os
from pathlib import Path
import sqlite3
import tempfile
import time

CARDS = {
    'arch': ('Arch', 'Packages, updates and uptime'),
    'system': ('System', 'Hardware and operating system'),
    'performance': ('Performance', 'Usage, temperatures and history'),
    'processes': ('Top Processes', 'Sort, filter and inspect running processes'),
    'connectivity': ('Connectivity', 'Addresses, VPNs and network traffic'),
    'player': ('Player', 'Media controls, artwork and audio visualiser'),
    'shares': ('Mounted Shares', 'Open mounted SMB and NFS folders'),
    'session': ('Session & Idle', 'Screen, lock and suspend timers'),
    'power': ('Power', 'Source, profile, battery and consumption'),
    'calendar': ('Calendar', 'Month and Thunderbird agenda'),
    'notes': ('Notes', 'A private note saved on this machine'),
    'tasks': ('Tasks', 'A local checklist'),
    'weather': ('Weather', 'Forecast for coordinates you choose'),
    'feeds': ('RSS Feeds', 'Headlines from your RSS or Atom feeds'),
    'containers': ('Containers', 'Local Docker container status'),
    'nas': ('NAS', 'Storage and status from a configured JSON endpoint'),
    'remote': ('Remote Machine', 'Metrics from a configured JSON endpoint'),
}
BASE_CARDS = list(CARDS)[:10]
REFRESH = {'cpu': 2, 'cpu_temperature': 5, 'ram': 3, 'gpu': 5,
           'network': 5, 'vpn': 5, 'power': 5, 'processes': 3,
           'shares': 15, 'arch': 60, 'media': 5, 'system_info': 300,
           'packages': 1800, 'updates': 1800, 'calendar': 60, 'session': 5,
           'health': 30, 'weather': 900, 'feeds': 600, 'containers': 15,
           'nas': 30, 'remote': 30}
SOURCES = {
    'arch': ('arch', 'packages', 'updates'), 'system': ('system_info',),
    'performance': ('cpu', 'cpu_temperature', 'ram', 'gpu'),
    'processes': ('processes',), 'connectivity': ('network', 'vpn'),
    'player': ('media',), 'shares': ('shares',), 'session': ('session',),
    'power': ('power',), 'calendar': ('calendar',),
    **{key: (key,) for key in ('weather', 'feeds', 'containers', 'nas', 'remote')},
}
SOURCE_TITLES = {'cpu': 'CPU usage', 'cpu_temperature': 'CPU temperature', 'ram': 'RAM',
                 'gpu': 'GPU usage / temperature', 'network': 'Network / traffic',
                 'vpn': 'VPNs', 'arch': 'Kernel / uptime', 'packages': 'Package count',
                 'updates': 'Available updates', 'media': 'Player metadata',
                 'system_info': 'Specifications', 'calendar': 'Agenda', 'health': 'Health checks'}
DEFAULT_APPEARANCE = {'scale': 1.0, 'opacity': .70, 'font_size': 14, 'spacing': 10, 'graphs': True,
                      'history_minutes': 15, 'snap': True, 'grid_size': 12}


def atomic_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix='.' + path.name, dir=path.parent)
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, 'w') as stream:
            json.dump(value, stream, ensure_ascii=False, allow_nan=False, indent=2)
            stream.write('\n')
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)


def read_json(path, fallback=None):
    try:
        return json.loads(Path(path).read_text())
    except (OSError, ValueError):
        return deepcopy(fallback)


def defaults():
    profiles = {}
    for name in ('Daily', 'Monitoring', 'Minimal'):
        visible = BASE_CARDS.copy()
        if name == 'Minimal':
            visible = ['arch', 'performance', 'calendar', 'player', 'power']
        profiles[name] = {'visible': visible, 'layouts': {}, 'refresh': deepcopy(REFRESH),
                          'appearance': deepcopy(DEFAULT_APPEARANCE)}
    return {'version': 1, 'active_profile': 'Daily', 'profiles': profiles,
            'integrations': {'weather': {'latitude': '', 'longitude': ''},
                             'feeds': {'urls': ''}, 'nas': {'url': '', 'token': ''},
                             'remote': {'url': '', 'token': ''}},
            'expected_shares': [], 'expected_vpns': [], 'notes': '', 'tasks': []}


def number(value, low, high):
    return type(value) in (int, float) and math.isfinite(value) and low <= value <= high


def validate(data):
    if not isinstance(data, dict) or data.get('version') != 1:
        raise ValueError('Unsupported dashboard settings version')
    profiles = data.get('profiles')
    if not isinstance(profiles, dict) or not 1 <= len(profiles) <= 30:
        raise ValueError('Keep between 1 and 30 profiles')
    if data.get('active_profile') not in profiles:
        raise ValueError('Choose an existing profile')
    for name, profile in profiles.items():
        if not isinstance(name, str) or not name.strip() or len(name) > 40 or any(ord(c) < 32 for c in name):
            raise ValueError('Profile names must contain 1–40 printable characters')
        visible = profile.get('visible')
        if not isinstance(visible, list) or len(visible) != len(set(visible)) or any(c not in CARDS for c in visible):
            raise ValueError('Unknown or repeated card')
        for source, seconds in profile.get('refresh', {}).items():
            if source not in REFRESH or type(seconds) is not int or not 1 <= seconds <= 86400:
                raise ValueError('Refresh intervals must be whole seconds from 1 to 86400')
        appearance = profile.get('appearance', {})
        appearance.setdefault('scale', 1.0)
        for key, low, high in [('scale', .5, 2), ('opacity', .15, 1), ('font_size', 9, 24), ('spacing', 4, 24), ('grid_size', 4, 40)]:
            if not number(appearance.get(key), low, high):
                raise ValueError('Invalid appearance setting: ' + key)
        if appearance.get('history_minutes') not in (5, 15, 30, 60):
            raise ValueError('History range must be 5, 15, 30 or 60 minutes')
        if any(type(appearance.get(key)) is not bool for key in ('graphs', 'snap')):
            raise ValueError('Graph and snap settings must be enabled or disabled')
        layouts = profile.get('layouts', {})
        if not isinstance(layouts, dict):
            raise ValueError('Invalid saved monitor layouts')
        for display, layout in layouts.items():
            if not isinstance(display, str) or not isinstance(layout, dict):
                raise ValueError('Invalid display layout')
            for card, rect in layout.items():
                if card not in CARDS or not valid_rect(rect):
                    raise ValueError('Invalid card position or size')
    integrations = data.get('integrations', {})
    for key in ('nas', 'remote'):
        cfg = integrations.get(key, {})
        url = cfg.get('url', '')
        if not isinstance(url, str) or (url and not url.startswith(('http://', 'https://'))):
            raise ValueError('Endpoint must start with http:// or https://')
        if not isinstance(cfg.get('token', ''), str) or len(cfg.get('token', '')) > 4096:
            raise ValueError('Invalid endpoint token')
    weather = integrations.get('weather', {})
    for key, low, high in [('latitude', -90, 90), ('longitude', -180, 180)]:
        value = weather.get(key, '')
        if value != '':
            try:
                if not number(float(value), low, high): raise ValueError()
            except (TypeError, ValueError):
                raise ValueError('Invalid weather ' + key) from None
    urls = integrations.get('feeds', {}).get('urls', '')
    if not isinstance(urls, str) or any(not url.startswith(('http://', 'https://')) for url in urls.splitlines() if url.strip()):
        raise ValueError('Use one http:// or https:// feed URL per line')
    if len(urls.splitlines()) > 20:
        raise ValueError('Use at most 20 feeds')
    if not isinstance(data.get('notes', ''), str) or len(data.get('notes', '')) > 100000:
        raise ValueError('Note is too long')
    tasks = data.get('tasks', [])
    if not isinstance(tasks, list) or len(tasks) > 500 or any(not isinstance(t, dict) or not isinstance(t.get('text'), str) or not 1 <= len(t['text']) <= 1000 or type(t.get('done')) is not bool for t in tasks):
        raise ValueError('Invalid task list')
    if not isinstance(data.get('expected_vpns', []), list) or any(v not in ('tailscale', 'proton') for v in data.get('expected_vpns', [])):
        raise ValueError('Unknown monitored VPN')
    expected = data.get('expected_shares', [])
    if not isinstance(expected, list) or any(not isinstance(p, str) or not p.startswith('/') for p in expected):
        raise ValueError('Expected shares must be absolute mount paths')
    return data


class Settings:
    def __init__(self, root):
        self.path = Path(root) / 'dashboard.json'
        raw = read_json(self.path)
        self.error = ''
        try:
            self.data = validate(raw) if raw is not None else defaults()
        except (ValueError, TypeError, KeyError, AttributeError) as exc:
            self.error = str(exc)
            self.data = defaults()
            # Preserve an invalid configuration for recovery before a later save.
            if self.path.exists():
                recovery = self.path.with_name('dashboard.invalid-' + str(time.time_ns()) + '.json')
                recovery.write_bytes(self.path.read_bytes())
                recovery.chmod(0o600)

    def save(self, data=None):
        value = deepcopy(data if data is not None else self.data)
        validate(value)
        atomic_json(self.path, value)
        self.data = value

    @property
    def profile(self):
        return self.data['profiles'][self.data['active_profile']]


class Transaction:
    """Undo/redo across all changes in an editing session; save is explicit."""
    def __init__(self, data):
        self.original = deepcopy(data)
        self.data = deepcopy(data)
        self.undo_stack, self.redo_stack = [], []

    def checkpoint(self):
        self.undo_stack.append(deepcopy(self.data))
        self.undo_stack = self.undo_stack[-100:]
        self.redo_stack.clear()

    def undo(self):
        if self.undo_stack:
            self.redo_stack.append(deepcopy(self.data))
            self.data = self.undo_stack.pop()
            return True
        return False

    def redo(self):
        if self.redo_stack:
            self.undo_stack.append(deepcopy(self.data))
            self.data = self.redo_stack.pop()
            return True
        return False


def valid_rect(rect):
    return (isinstance(rect, (list, tuple)) and len(rect) == 4
            and all(number(n, 0, 1) for n in rect) and rect[2] > 0 and rect[3] > 0
            and rect[0] + rect[2] <= 1.000001 and rect[1] + rect[3] <= 1.000001)


def overlaps(a, b, tolerance=.0005):
    return (a[0] < b[0] + b[2] - tolerance and a[0] + a[2] > b[0] + tolerance
            and a[1] < b[1] + b[3] - tolerance and a[1] + a[3] > b[1] + tolerance)


def valid_move(card, rect, layout):
    return valid_rect(rect) and all(not overlaps(rect, other) for key, other in layout.items() if key != card)


def swap_target(card, proposed, layout):
    """Dropping onto one occupied slot swaps complete slots without overlaps."""
    cx, cy = proposed[0]+proposed[2]/2, proposed[1]+proposed[3]/2
    target = next((key for key,rect in layout.items() if key != card and rect[0] <= cx <= rect[0]+rect[2] and rect[1] <= cy <= rect[1]+rect[3]), None)
    if target is None: return None
    result = deepcopy(layout)
    result[card], result[target] = result[target], result[card]
    return target if all(valid_move(key,rect,result) for key,rect in result.items()) else None


def transform(rect, dx, dy, edge, width, height, grid=0, others=()):
    """Move/resize in pixels, snap edges, return a bounded normalised rectangle."""
    x, y, w, h = [rect[0]*width, rect[1]*height, rect[2]*width, rect[3]*height]
    left, top, right, bottom = x, y, x+w, y+h
    if not edge:
        left += dx; right += dx; top += dy; bottom += dy
    else:
        if 'w' in edge: left += dx
        if 'e' in edge: right += dx
        if 'n' in edge: top += dy
        if 's' in edge: bottom += dy
    guides = []
    if grid:
        anchors_x, anchors_y = [0, width], [0, height]
        for other in others:
            anchors_x += [other[0]*width, (other[0]+other[2])*width]
            anchors_y += [other[1]*height, (other[1]+other[3])*height]
        def snap(value, anchors, axis):
            nearest = min(anchors, key=lambda p: abs(value-p))
            if abs(nearest-value) <= 7:
                guides.append((axis, nearest))
                return nearest
            return round(value/grid)*grid
        if not edge:
            sx, sy = snap(left, anchors_x, 'x'), snap(top, anchors_y, 'y')
            right += sx-left; bottom += sy-top; left, top = sx, sy
        else:
            if 'w' in edge: left = snap(left, anchors_x, 'x')
            if 'e' in edge: right = snap(right, anchors_x, 'x')
            if 'n' in edge: top = snap(top, anchors_y, 'y')
            if 's' in edge: bottom = snap(bottom, anchors_y, 'y')
    minw, minh = min(180, width), min(100, height)
    if not edge:
        left = min(max(0, left), max(0, width-w)); top = min(max(0, top), max(0, height-h))
        right, bottom = left+w, top+h
    else:
        if 'w' in edge: left = max(0, min(left, right-minw))
        if 'e' in edge: right = min(width, max(right, left+minw))
        if 'n' in edge: top = max(0, min(top, bottom-minh))
        if 's' in edge: bottom = min(height, max(bottom, top+minh))
    return [left/width, top/height, (right-left)/width, (bottom-top)/height], guides


def default_layout(visible, width, height, gap=10, preset='Daily'):
    """Three balanced columns or a narrow-screen list; all cards fit the canvas."""
    if not visible: return {}
    columns = 3 if width >= 850 else 2 if width >= 550 else 1
    groups = [['arch','system','connectivity','session','power'],
              ['performance','processes','shares'], ['calendar','player']]
    optional = [c for c in visible if c not in BASE_CARDS]
    if columns < 3:
        groups = [visible[i::columns] for i in range(columns)]
    else:
        groups = [[c for c in group if c in visible] for group in groups]
        for card in optional:
            groups[min(range(3), key=lambda i: len(groups[i]))].append(card)
    ratios = [.30, .40, .30] if columns == 3 else [1/columns]*columns
    result, x = {}, 0
    weights = {'arch': 1.1, 'system': 1.5, 'connectivity': 1.8, 'session': 1.6,
               'power': 2.0, 'performance': 1.6, 'processes': 3.5, 'shares': 2.2,
               'calendar': 3, 'player': 2}
    if preset == 'Monitoring':
        weights.update(performance=3, processes=3, shares=2)
    for group, ratio in zip(groups, ratios):
        cw = (width-(columns-1)*gap)*ratio
        if group:
            room = height-(len(group)-1)*gap
            total = sum(weights.get(c, 1.6) for c in group)
            y = 0
            for card in group:
                ch = room*weights.get(card, 1.6)/total
                result[card] = [x/width, y/height, cw/width, ch/height]
                y += ch+gap
        x += cw+gap
    return result


class History:
    """Local, bounded one-hour history; timestamps are wall-clock seconds."""
    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(self.path)
        self.path.chmod(0o600)
        self.db.execute('PRAGMA journal_mode=WAL')
        self.db.execute('CREATE TABLE IF NOT EXISTS samples (metric TEXT, time INTEGER, value REAL, PRIMARY KEY(metric,time))')
        self.db.execute('CREATE INDEX IF NOT EXISTS samples_time ON samples(time)')
        self.last_prune = 0

    def add(self, values, now=None):
        now = int(time.time() if now is None else now)
        for metric, value in values.items():
            if number(value, -1e15, 1e15):
                self.db.execute('INSERT OR REPLACE INTO samples VALUES (?,?,?)', (metric, now, value))
        if now-self.last_prune >= 60:
            self.db.execute('DELETE FROM samples WHERE time < ?', (now-3600,))
            self.last_prune = now
        self.db.commit()

    def series(self, metric, minutes=15, now=None, limit=240):
        now = time.time() if now is None else now
        rows = self.db.execute('SELECT time,value FROM samples WHERE metric=? AND time>=? ORDER BY time', (metric, now-minutes*60)).fetchall()
        step = max(1, math.ceil(len(rows)/limit))
        return [(rows[i][0], sum(v for _,v in rows[i:i+step])/len(rows[i:i+step])) for i in range(0,len(rows),step)]

    def close(self):
        self.db.close()
