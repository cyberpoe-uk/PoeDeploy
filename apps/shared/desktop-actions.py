#!/usr/bin/env python3
"""Recent desktop applications and calendar/MPRIS activation for PoeDash."""
import argparse
import configparser
import fcntl
import json
import os
from pathlib import Path
import re
import select
import shlex
import shutil
import socket
import subprocess
import tempfile
import time

ROOT = Path(__file__).resolve().parent.parent
STATE = Path(os.environ.get('XDG_STATE_HOME', Path.home() / '.local/state')) / 'poedeploy/recent-apps.json'
SAFE_ID = re.compile(r'[A-Za-z0-9_.+\-]+\.desktop')


def call(*argv):
    return subprocess.run(argv, capture_output=True, text=True, check=True, timeout=3).stdout.strip()


def start(*argv):
    # GUI children can inherit their launcher's descriptors and keep pipes open.
    subprocess.run(argv, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True, timeout=5)


def read_json(path, fallback):
    try:
        return json.loads(path.read_text())
    except (OSError, ValueError):
        return fallback


def applications():
    """Read desktop entries with XDG user overrides and hidden-entry masking."""
    roots = [Path(os.environ.get('XDG_DATA_HOME', Path.home() / '.local/share'))]
    roots += [Path(p) for p in os.environ.get('XDG_DATA_DIRS', '/usr/local/share:/usr/share').split(':') if p]
    roots += [Path.home() / '.local/share/flatpak/exports/share', Path('/var/lib/flatpak/exports/share')]
    result, seen = {}, set()
    for root in roots:
        directory = root / 'applications'
        for path in sorted(directory.rglob('*.desktop')):
            identifier = '-'.join(path.relative_to(directory).parts)
            if identifier in seen or not SAFE_ID.fullmatch(identifier):
                continue
            seen.add(identifier)
            parser = configparser.ConfigParser(interpolation=None, strict=False)
            try:
                parser.read_string(path.read_text())
                entry = parser['Desktop Entry']
                if entry.get('Type', 'Application') != 'Application' or entry.getboolean('Hidden', False) or entry.getboolean('NoDisplay', False):
                    continue
                if not entry.get('Name') or not (entry.get('Exec') or entry.getboolean('DBusActivatable', False)):
                    continue
                if entry.get('TryExec') and not shutil.which(entry['TryExec']):
                    continue
                aliases = {identifier[:-8].casefold(), identifier[:-8].split('.')[-1].casefold(),
                           entry.get('StartupWMClass', '').casefold()}
                argv = shlex.split(entry.get('Exec', ''))
                if argv and Path(argv[0]).name not in ('env', 'flatpak', 'sh', 'bash'):
                    aliases.add(Path(argv[0]).name.casefold())
                if 'spotify-launcher' in aliases:
                    aliases.add('spotify')
                result[identifier] = {'id': identifier, 'name': entry['Name'],
                    'icon': entry.get('Icon') or 'application-x-executable',
                    'path': str(path), 'aliases': aliases - {''},
                    'calendar': 'Calendar' in entry.get('Categories', '').split(';')}
            except (OSError, UnicodeError, ValueError, KeyError, configparser.Error):
                continue
    return result


def match_app(apps, *names):
    for name in names:
        normalized = str(name).casefold().removesuffix('.desktop')
        for app in apps.values():
            if normalized and normalized in app['aliases']:
                return app
    return None


def clients():
    try:
        value = json.loads(call('hyprctl', 'clients', '-j'))
        return value if isinstance(value, list) else []
    except (OSError, ValueError, subprocess.SubprocessError):
        return []


def history():
    value = read_json(STATE, [])
    return [item for item in value if isinstance(item, str) and SAFE_ID.fullmatch(item)][:20] if isinstance(value, list) else []


def pinned():
    value = read_json(STATE.with_name('pinned-apps.json'), [])
    return list(dict.fromkeys(item for item in value if isinstance(item, str) and SAFE_ID.fullmatch(item))) if isinstance(value, list) else []


def toggle_pin(identifier):
    path = STATE.with_name('pinned-apps.json')
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.with_suffix('.lock').open('w') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        values = pinned()
        if identifier in values:
            values.remove(identifier)
        else:
            values.append(identifier)
        fd, temporary = tempfile.mkstemp(dir=path.parent, prefix='.pinned-apps-')
        try:
            with os.fdopen(fd, 'w') as stream:
                json.dump(values, stream)
                stream.write('\n')
            os.replace(temporary, path)
        finally:
            Path(temporary).unlink(missing_ok=True)


def remember(identifiers):
    """Store only desktop IDs, never window titles, documents or command arguments."""
    if not identifiers:
        return history()
    STATE.parent.mkdir(parents=True, exist_ok=True)
    with STATE.with_suffix('.lock').open('w') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        old = history()
        updated = list(dict.fromkeys([*identifiers, *old]))[:20]
        if updated != old:
            fd, temporary = tempfile.mkstemp(dir=STATE.parent, prefix='.recent-apps-')
            try:
                with os.fdopen(fd, 'w') as stream:
                    json.dump(updated, stream)
                    stream.write('\n')
                os.replace(temporary, STATE)
            finally:
                Path(temporary).unlink(missing_ok=True)
        return updated


def recent(apps):
    # Hyprland reports the most recently focused client with focusHistoryID 0.
    windows = sorted(clients(), key=lambda window: window.get('focusHistoryID', 100000))
    identifiers = []
    for window in windows:
        app = match_app(apps, window.get('initialClass', ''), window.get('class', ''))
        if app and app['id'] not in identifiers:
            identifiers.append(app['id'])
    # Previously closed applications keep their place unless another app is used.
    saved = history()
    active = identifiers[:1]
    ordered = remember([*active, *saved, *identifiers])
    return [{key: apps[item][key] for key in ('id', 'name', 'icon')}
            for item in ordered if item in apps]


def app_lists(apps):
    pins = [item for item in pinned() if item in apps]
    return {'pinned': [{key: apps[item][key] for key in ('id', 'name', 'icon')} for item in pins],
            'recent': [item for item in recent(apps) if item['id'] not in pins][:12]}


def hypr_eval(code):
    try:
        return call('hyprctl', 'eval', code) == 'ok'
    except (OSError, subprocess.SubprocessError):
        return False


def focus(app):
    for window in sorted(clients(), key=lambda item: item.get('focusHistoryID', 100000)):
        classes = {window.get('class', '').casefold(), window.get('initialClass', '').casefold()}
        address = window.get('address', '')
        if classes & app['aliases'] and re.fullmatch(r'0x[0-9a-fA-F]+', address):
            return hypr_eval('hl.dispatch(hl.dsp.focus({window = "address:' + address + '"}))')
    return False


def leave_home():
    """Launch new applications away from the reserved dashboard workspace."""
    try:
        if json.loads(call('hyprctl', 'activeworkspace', '-j')).get('id') != 1:
            return
        used = {item.get('id') for item in json.loads(call('hyprctl', 'workspaces', '-j'))}
        destination = next(number for number in range(2, 1000) if number not in used)
        hypr_eval(f'hl.dispatch(hl.dsp.focus({{workspace = "{destination}"}}))')
    except (OSError, ValueError, StopIteration, subprocess.SubprocessError):
        pass


def launch(app):
    if not focus(app):
        leave_home()
        # GIO handles Desktop Entry field codes, quoting, Flatpak and Terminal=true.
        start('gio', 'launch', app['path'])
    remember([app['id']])


def notify(message):
    try:
        call('notify-send', 'Dashboard', message)
    except (OSError, subprocess.SubprocessError):
        pass


def selected_player():
    try:
        players = call('playerctl', '-l').splitlines()
        selected = None
        for player in players:
            try:
                status = call('playerctl', '-p', player, 'status')
            except (OSError, subprocess.SubprocessError):
                continue
            selected = selected or player
            if status == 'Playing':
                return player
        return selected
    except (OSError, subprocess.SubprocessError):
        return None


def open_player(apps):
    player = selected_player()
    if not player:
        app = match_app(apps, 'spotify', 'spotify-launcher')
        if app:
            launch(app)
        else:
            notify('No player is running. Start a media application first.')
        return
    service = 'org.mpris.MediaPlayer2.' + player
    desktop = ''
    try:
        fields = shlex.split(call('busctl', '--user', 'get-property', service,
                            '/org/mpris/MediaPlayer2', 'org.mpris.MediaPlayer2', 'DesktopEntry'))
        desktop = fields[1] if len(fields) == 2 else ''
    except (OSError, ValueError, subprocess.SubprocessError):
        pass
    app = match_app(apps, desktop, player.split('.')[0])
    if app and focus(app):
        remember([app['id']])
        return
    try:
        can_raise = call('busctl', '--user', 'get-property', service, '/org/mpris/MediaPlayer2',
                         'org.mpris.MediaPlayer2', 'CanRaise') == 'b true'
        if can_raise:
            call('busctl', '--user', 'call', service, '/org/mpris/MediaPlayer2', 'org.mpris.MediaPlayer2', 'Raise')
            return
    except (OSError, subprocess.SubprocessError):
        pass
    if app:
        launch(app)
    else:
        notify(f'{player} cannot bring its window to the front.')


def open_calendar(apps, root):
    preferences = read_json(root / 'settings.json', {})
    preferred = preferences.get('calendar', 'thunderbird') if isinstance(preferences, dict) else 'thunderbird'
    if preferred == 'google':
        leave_home()
        start('xdg-open', 'https://calendar.google.com/')
        return
    app = (apps.get(preferred) or match_app(apps, preferred)) if preferred != 'auto' else None
    if preferred != 'auto' and not app:
        notify('Thunderbird is not installed.' if preferred == 'thunderbird' else 'The selected calendar application is not installed.')
        return
    if not app:
        calendars = [app for app in apps.values() if app['calendar']]
        app = next((apps[name] for name in ('org.gnome.Calendar.desktop', 'org.kde.korganizer.desktop')
                    if name in apps), calendars[0] if calendars else None)
    if not app:
        app = match_app(apps, 'thunderbird')
    if app:
        launch(app)
        if 'thunderbird' in app['aliases']:
            # Current Thunderbird opens its Calendar tab with Ctrl+3 on Linux.
            for _ in range(20):
                window = next((item for item in clients()
                               if {item.get('class', '').casefold(), item.get('initialClass', '').casefold()} & app['aliases']
                               and re.fullmatch(r'0x[0-9a-fA-F]+', item.get('address', ''))), None)
                if window:
                    address = window['address']
                    hypr_eval('hl.dispatch(hl.dsp.send_shortcut({window = "address:' + address + '", mods = "CTRL", key = "3"}))')
                    break
                time.sleep(0.25)
    else:
        notify('No calendar application was found. Install a calendar app or choose one in settings.json.')


def ui_paused(root):
    try:
        return (root / 'state/refresh-paused').read_text().strip() == 'true'
    except OSError:
        return False

def listen():
    previous, indexed = None, 0
    apps = {}
    def emit():
        nonlocal previous, indexed, apps
        if ui_paused(ROOT):
            return
        if time.monotonic() - indexed > 30 or not apps:
            apps, indexed = applications(), time.monotonic()
        data = json.dumps(app_lists(apps))
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
                    ready, _, _ = select.select([connection], [], [], 10)
                    if ready:
                        chunk = connection.recv(65536)
                        if not chunk:
                            break
                        buffer += chunk.decode(errors='replace')
                        lines = buffer.split('\n')
                        buffer = lines.pop()
                        if not any(line.partition('>>')[0] in ('activewindow', 'activewindowv2', 'openwindow', 'closewindow') for line in lines):
                            continue
                    emit()
        except (OSError, KeyError):
            pass
        time.sleep(2)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('listen', 'recent', 'launch', 'pin', 'media', 'calendar'))
    parser.add_argument('identifier', nargs='?')
    parser.add_argument('--root', type=Path, default=ROOT)
    args = parser.parse_args()
    if args.action == 'listen':
        listen()
        return
    apps = applications()
    if args.action == 'recent':
        print(json.dumps(recent(apps)))
    elif args.action == 'launch':
        if not args.identifier or args.identifier not in apps:
            raise RuntimeError('This application is no longer installed.')
        launch(apps[args.identifier])
    elif args.action == 'pin':
        if not args.identifier or args.identifier not in apps:
            raise RuntimeError('This application is no longer installed.')
        toggle_pin(args.identifier)
    elif args.action == 'media':
        open_player(apps)
    else:
        open_calendar(apps, args.root)


if __name__ == '__main__':
    try:
        main()
    except (BrokenPipeError, KeyboardInterrupt):
        pass
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as error:
        notify(str(error))
        raise SystemExit(1)
