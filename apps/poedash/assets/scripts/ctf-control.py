#!/usr/bin/env python3
"""Local CTF launch controls. Target data is never executed or connected to."""
import fcntl
import ipaddress
import json
import os
from pathlib import Path
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
import time
from urllib.parse import urlsplit

from config import ROOT, load
HOME = Path.home()
SETTINGS = load()
STATE = Path(os.environ.get('XDG_STATE_HOME', HOME / '.local/state')) / 'poedash'
CACHE = Path(os.environ.get('XDG_CACHE_HOME', HOME / '.cache')) / 'poedash'
BURP = HOME / 'Applications/BurpSuite/BurpSuite'
APPS = {name: (app['workspace'], app['classes']) for name, app in SETTINGS['launchers'].items()}


def run(argv, timeout=5):
    return subprocess.run(argv, text=True, capture_output=True, timeout=timeout)


def profile():
    # Isolated profile: no copied cookies, credentials, or machine-specific ID.
    return STATE / 'firefox-ctf'


def command(app):
    custom = SETTINGS['launchers'][app]['command']
    if custom:
        argv = [os.path.expanduser(x) for x in custom]
        exe = shutil.which(argv[0])
        return [exe, *argv[1:]] if exe else None
    if app == 'burp':
        exe = shutil.which('burpsuite') or (str(BURP) if os.access(BURP, os.X_OK) else None)
        return [exe] if exe else None
    if app == 'firefox':
        exe = shutil.which('firefox')
        return [exe, '--no-remote', '--profile', str(profile())] if exe else None
    if app == 'code':
        exe = shutil.which('code') or shutil.which('codium')
        return [exe] if exe else None
    return None


def clients():
    result = run(['hyprctl', 'clients', '-j'])
    if result.returncode:
        raise RuntimeError('Cannot reach Hyprland')
    return json.loads(result.stdout)


def dispatch(expression):
    result = run(['hyprctl', 'dispatch', expression])
    if result.returncode or result.stdout.startswith('error:'):
        raise RuntimeError(result.stdout.strip() or result.stderr.strip())


def process_args(pid):
    try:
        return [x.decode(errors='replace') for x in Path(f'/proc/{pid}/cmdline').read_bytes().split(b'\0') if x]
    except OSError:
        return []


def is_ctf_process(pid):
    args = process_args(pid)
    if not args or 'firefox' not in Path(args[0]).name:
        return False
    p = profile()
    for i, arg in enumerate(args[:-1]):
        if arg in ('-P', '-p') and args[i+1] == 'CTF':
            return True
        if p and arg in ('--profile', '-profile') and Path(args[i+1]).resolve() == p:
            return True
    try:
        return b'MOZ_APP_REMOTINGNAME=firefox-ctf' in Path(f'/proc/{pid}/environ').read_bytes().split(b'\0')
    except OSError:
        return False


def find_window(app, windows):
    matches = [w for w in windows if w.get('class') in APPS[app][1]]
    if app == 'firefox':
        matches += [w for w in windows if w.get('class') == 'firefox' and is_ctf_process(w['pid'])]
    # Prefer a window already on the intended workspace, then the dedicated class.
    matches.sort(key=lambda w: (w['workspace']['id'] != APPS[app][0], w['class'] != APPS[app][1][0]))
    return matches[0] if matches else None


def running_without_window(app):
    # Do not start another copy while a slow startup is still in progress.
    for p in Path('/proc').glob('[0-9]*'):
        args = process_args(p.name)
        if not args:
            continue
        if app == 'firefox' and is_ctf_process(p.name):
            return True
        if app == 'burp' and (args[0] == str(BURP) or any(str(BURP.parent / 'burpsuite.jar') in a for a in args)):
            return True
        if app == 'terminal' and 'dashboard-ctf-terminal' in args and Path(args[0]).name == 'kitty':
            return True
        if app == 'wireshark' and Path(args[0]).name == 'wireshark':
            return True
    return False


def ensure(app, focus=True):
    workspace = APPS[app][0]
    window = find_window(app, clients())
    if not window:
        argv = command(app)
        if not argv:
            raise RuntimeError(f'{app}: executable or CTF profile is missing')
        stamp = CACHE / (app + '.pending')
        pending = stamp.exists() and time.time() - stamp.stat().st_mtime < 90
        if not pending and not running_without_window(app):
            # Hyprland applies this workspace rule only to the spawned application.
            # shlex.join quotes argv for the compositor's exec command; no target is used.
            if app == 'firefox':
                profile().mkdir(mode=0o700, parents=True, exist_ok=True)
                argv = ['env', 'MOZ_APP_REMOTINGNAME=firefox-ctf', *argv]
            cmd = shlex.join(argv)
            dispatch('hl.dsp.exec_cmd(' + json.dumps(cmd, ensure_ascii=False) + ', { workspace = ' + json.dumps(f'{workspace} silent') + ' })')
            stamp.touch()
        for _ in range(100):
            time.sleep(.25)
            window = find_window(app, clients())
            if window:
                break
        if not window:
            raise RuntimeError(f'{app}: started but no window yet; click again to focus it')
    (CACHE / (app + '.pending')).unlink(missing_ok=True)
    selector = json.dumps('address:' + window['address'], ensure_ascii=False)
    if window['workspace']['id'] != workspace:
        dispatch(f'hl.dsp.window.move({{ window = {selector}, workspace = "{workspace}", silent = true }})')
    if focus:
        dispatch(f'hl.dsp.focus({{ workspace = "{workspace}" }})')
        dispatch(f'hl.dsp.focus({{ window = {selector} }})')
    return window


def notify(message):
    print(message, file=sys.stderr)
    if shutil.which('notify-send'):
        run(['notify-send', 'CTF control', message])


def launch(app):
    CACHE.mkdir(parents=True, exist_ok=True)
    with (CACHE / 'ctf-launch.lock').open('w') as lock:
        # Serialize clicks, so a second click sees the first window rather than
        # spawning another while it is loading. No scans or captures are started.
        fcntl.flock(lock, fcntl.LOCK_EX)
        if app == 'web-ctf':
            errors = []
            for name in SETTINGS['web_ctf']['apps']:
                try:
                    ensure(name, focus=False)
                except RuntimeError as exc:
                    errors.append(str(exc))
            dispatch('hl.dsp.focus({ workspace = ' + json.dumps(str(SETTINGS['web_ctf']['workspace'])) + ' })')
            if errors:
                notify('; '.join(errors))
                return 1
        else:
            ensure(app)
    return 0


def status():
    missing = []
    for app in SETTINGS['web_ctf']['apps']:
        if not command(app):
            missing.append(app if app != 'firefox' else 'Firefox / CTF profile')
    try:
        route = json.loads(run(['ip', '-j', '-4', 'route', 'get', '1.1.1.1']).stdout)
        if not route or not route[0].get('dev') or not (route[0].get('prefsrc') or route[0].get('src')):
            missing.append('IPv4 route')
    except (OSError, ValueError, subprocess.TimeoutExpired):
        missing.append('network')
    return {'ready': not missing, 'label': 'CHECK' if missing else 'READY',
            'detail': 'Missing: ' + ', '.join(missing) if missing else 'Configured Web CTF apps and an IPv4 route are available. No target connectivity test performed.'}


def read_target():
    try:
        return (STATE / 'target').read_text().strip()
    except FileNotFoundError:
        return ''


def validate_target(value):
    value = value.strip()
    if not value:
        return ''
    if len(value) > 512 or re.search(r'[\s\x00-\x1f\x7f]', value):
        raise ValueError('Enter one IP address, hostname, or HTTP(S) URL.')
    host = value
    if '://' in value:
        parsed = urlsplit(value)
        if parsed.scheme not in ('http', 'https') or parsed.username or parsed.password:
            raise ValueError('Use an IP address, hostname, or HTTP(S) URL without credentials.')
        host = parsed.hostname or ''
        _ = parsed.port  # Reject malformed port numbers.
    try:
        ipaddress.ip_address(host)
    except ValueError:
        if not re.fullmatch(r'(?=.{1,253}\.?$)(?:[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?\.)*[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?\.?', host):
            raise ValueError('Enter a valid IP address, hostname, or HTTP(S) URL.')
    return value


def save_target(value):
    value = validate_target(value)
    STATE.mkdir(mode=0o700, parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix='.target-', dir=STATE)
    try:
        with os.fdopen(fd, 'w') as stream:
            stream.write(value + '\n')
        os.replace(temporary, STATE / 'target')
    finally:
        Path(temporary).unlink(missing_ok=True)
    return value


def palette():
    colors = dict(re.findall(r'^\$(\w+):\s*(#[0-9a-fA-F]{6});', (ROOT / 'colors.scss').read_text(), re.M))
    return colors


def edit_target():
    # Existing Rofi receives text via stdin/filter and returns it on stdout.
    # It never passes the entered value to a shell, unlike Eww 0.5 input events.
    CACHE.mkdir(parents=True, exist_ok=True)
    with (CACHE / 'ctf-target.lock').open('w') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return
        c = palette()
        theme = f'''* {{ background-color: {c['background']}; text-color: {c['foreground']}; font: "JetBrains Mono 14"; }}
window {{ width: 640px; border: 1px; border-color: {c['accent']}; border-radius: 11px; }}
mainbox {{ padding: 22px; children: [inputbar, message]; spacing: 14px; }}
inputbar {{ children: [prompt, entry]; spacing: 16px; }}
prompt {{ text-color: {c['accent']}; }}
entry {{ placeholder: "IP address, hostname, or URL"; }}
message {{ padding: 0; }}
textbox {{ text-color: {c['secondary']}; }}'''
        value = read_target()
        message = 'Enter saves · Escape cancels · Empty value clears'
        while True:
            result = subprocess.run(['rofi', '-no-config', '-dmenu', '-p', 'TARGET', '-filter', value,
                                     '-mesg', message, '-theme-str', theme], input='', text=True, capture_output=True)
            if result.returncode:
                return
            value = result.stdout.rstrip('\n')
            try:
                value = save_target(value)
            except ValueError as exc:
                message = str(exc)
                continue
            run(['eww', '--config', str(ROOT), 'update', 'ctf_target=' + (value or 'NOT SET')])
            return


def main():
    action = sys.argv[1]
    if action == 'status':
        print(json.dumps(status()))
    elif action == 'target':
        print(read_target() or 'NOT SET')
    elif action == 'save-target':
        save_target(sys.argv[2])
    elif action == 'edit-target':
        edit_target()
    elif action == 'launch' and sys.argv[2] in (*APPS, 'web-ctf'):
        return launch(sys.argv[2])
    else:
        raise ValueError('Unknown CTF control action')
    return 0


if __name__ == '__main__':
    try:
        sys.exit(main())
    except (OSError, ValueError, RuntimeError, subprocess.TimeoutExpired) as exc:
        notify(str(exc))
        sys.exit(1)
