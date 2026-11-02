#!/usr/bin/env python3
"""Persistent dashboard controls for QuickShell, Waybar and the installer."""
import argparse
import fcntl
import json
import os
from pathlib import Path
import re
import shlex
import shutil
import subprocess
import sys
import time


DASHBOARD_ID = 'poedash'
DASHBOARD_NAME = 'PoeDash'


def validate_update_target(root):
    selection = Path(os.environ.get('XDG_CONFIG_HOME', Path.home() / '.config')) / 'poedeploy/dashboard'
    if selection.is_file() and selection.read_text().strip() != DASHBOARD_ID:
        raise RuntimeError('This is an outdated dashboard control. Use the selected dashboard updater or reinstall its bar integration.')
    identity = root / 'dashboard-id'
    if identity.is_file() and identity.read_text().strip() != DASHBOARD_ID:
        raise RuntimeError('The update control points to another dashboard. Reinstall the intended dashboard to repair the bar integration.')


def prepare(root):
    start = root / 'scripts/start.sh'
    if not start.is_file():
        raise RuntimeError('Dashboard is not installed.')
    guard = '[ -f "$(dirname "$(dirname "$(realpath "$0")")")/disabled" ] && exit 0'
    text = start.read_text()
    if guard not in text:
        first, rest = text.split('\n', 1)
        text = first + '\n' + guard + '\n' + rest
    # A disable click must also cancel a startup that is still waiting.
    text = re.sub(r'(?m)^(\s*)(if ! timeout 3 eww|if timeout 3 eww)', lambda m: m[1] + guard + '\n' + m[0], text) if '# Dashboard toggle checkpoints' not in text else text
    if '# Dashboard toggle checkpoints' not in text:
        text += '\n# Dashboard toggle checkpoints\n'
    if text != start.read_text():
        backup = start.with_name('start.sh.before-dashboard-toggle')
        if not backup.exists():
            shutil.copy2(start, backup)
        start.write_text(text)
    # Upgrade old integration without touching unrelated Hyprland settings.
    lua = root / 'hyprland.lua'
    if lua.is_file():
        text = lua.read_text()
        if 'local function protect_home' in text and 'dashboard_disabled' not in text:
            block = text
            function = ('local function dashboard_disabled()\n'
                        '    local f = io.open(' + json.dumps(str(root / 'disabled')) + ', "r")\n'
                        '    if f then f:close() return true end\n'
                        '    return false\nend\n')
            body = re.sub(r'(local function protect_home[^\n]*\n)', r'\1    if dashboard_disabled() then return end\n', block)
            body = body.replace('if current and current.workspace', 'if not dashboard_disabled() and current and current.workspace')
            wrapped = 'do\n' + function + 'if not dashboard_disabled() then\n' + body + '\nend\nend\n'
            backup = lua.with_name(lua.name + '.before-dashboard-toggle')
            if not backup.exists():
                shutil.copy2(lua, backup)
            lua.write_text(text.replace(block, wrapped, 1))


def switch(root, action):
    prepare(root)
    with (root / '.toggle.lock').open('w') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        marker = root / 'disabled'
        enabled = marker.exists() if action == 'toggle' else action == 'enable'
        if enabled:
            marker.unlink(missing_ok=True)
            with (root / 'toggle.log').open('a') as log:
                subprocess.Popen([str(root / 'scripts/start.sh')], stdout=log, stderr=log,
                                 start_new_session=True)
        else:
            marker.write_text('Dashboard disabled\n')
            if shutil.which('eww'):
                subprocess.run(['eww', '--config', str(root), 'kill'], check=False,
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def module(root):
    command = shlex.join(['python3', str(root / 'scripts/dashboard-control.py'), '--root', str(root)])
    return {'exec-if': shlex.join(['test', '-f', str(root / 'scripts/start.sh')]), 'exec': command + ' status', 'return-type': 'json', 'interval': 2,
            'on-click': command + ' toggle', 'format': ' {text} ', 'escape': True}


def update_cache():
    return Path(os.environ.get('XDG_CACHE_HOME', Path.home() / '.cache')) / 'poedash'


def update_notice(message, failed=False):
    if shutil.which('notify-send'):
        try:
            subprocess.run(['notify-send', '-a', DASHBOARD_NAME, '-u', 'normal',
                            DASHBOARD_NAME + (' update failed' if failed else ' update'), message],
                           check=False, timeout=5, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except (OSError, subprocess.SubprocessError):
            pass


def update(root):
    validate_update_target(root)
    subprocess.Popen([sys.executable, str(root / 'scripts/dashboard-control.py'),
                      '--root', str(root), 'update-run'], start_new_session=True,
                     stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def run_update(root):
    validate_update_target(root)
    cache = update_cache()
    cache.mkdir(parents=True, exist_ok=True)
    # Outside the installation tree: replacing that tree must not release the lock.
    with (cache / 'update.lock').open('w') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            update_notice('An update is already running.')
            return
        log_path = cache / 'update.log'
        with log_path.open('w') as log:
            log_path.chmod(0o600)
            try:
                result = subprocess.run(['bash', str(root / 'scripts/update.sh'), str(root)],
                                        stdin=subprocess.DEVNULL, stdout=log, stderr=log, check=False)
                if result.returncode:
                    raise RuntimeError(f'Installer exited with status {result.returncode}')
                # Keep launch suppression active until the replacement surface is ready.
                if not (root / 'disabled').exists():
                    for _ in range(30):
                        ready = subprocess.run(['eww', '--config', str(root), 'active-windows'],
                                               capture_output=True, text=True, timeout=3, check=False)
                        if ready.returncode == 0 and 'dashboard: dashboard' in ready.stdout:
                            break
                        time.sleep(.5)
                    else:
                        raise RuntimeError('Installed, but the dashboard did not reopen. Try poedash start.')
            except (OSError, RuntimeError, subprocess.SubprocessError) as exc:
                print(str(exc), file=log, flush=True)
                update_notice(f'{exc}. Details: {log_path}', failed=True)
                return
        update_notice('Updated successfully.')


def install_waybar(root, config):
    text = config.read_text()
    slug = DASHBOARD_ID
    name = 'custom/' + slug
    command = shlex.join(['python3', str(root / 'scripts/dashboard-control.py'), '--root', str(root)])
    entries = {name: module(root), name + '-update': {
        'exec-if': shlex.join(['test', '-f', str(root / 'scripts/start.sh')]),
        'exec': "printf '↻'", 'interval': 60, 'format': ' {} ',
        'tooltip-format': 'Update ' + DASHBOARD_NAME,
        'on-click': command + ' update'}}
    missing = {key: value for key, value in entries.items() if json.dumps(key) not in text}
    if not missing:
        return
    # Preserve JSONC comments and formatting; support a single bar object.
    clean = re.sub(r'//[^\n]*|/\*.*?\*/', '', text, flags=re.S).lstrip()
    if not clean.startswith('{') or not re.search(r'"modules-right"\s*:\s*\[', text):
        raise RuntimeError('Expected a single Waybar object with modules-right.')
    backup = config.with_name(config.name + '.before-dashboard-update')
    if not backup.exists():
        shutil.copy2(config, backup)
    for key, value in reversed(list(missing.items())):
        # On upgrade place the update button immediately after the existing switch.
        if key.endswith('-update') and name not in missing:
            pattern = r'("modules-right"\s*:\s*\[[^\]]*?' + re.escape(json.dumps(name)) + ')'
            text, count = re.subn(pattern, lambda m: m[1] + ', ' + json.dumps(key), text, count=1)
            if not count:
                raise RuntimeError('Existing dashboard switch is not in modules-right.')
        else:
            text = re.sub(r'("modules-right"\s*:\s*\[)(\s*)(\]?)', lambda m: m[1] + '\n        ' + json.dumps(key) + (',' if not m[3] else '') + m[2] + m[3], text, count=1)
        pos = text.index('{') + 1
        text = text[:pos] + '\n    ' + json.dumps(key) + ': ' + json.dumps(value) + ',\n' + text[pos:]
    config.write_text(text)


def _add_quickshell_module(text):
    if 'id: cDashboard' not in text:
        anchor = '    Component { id: cTerminal;   TerminalModule {} }'
        if anchor not in text:
            raise RuntimeError('Unsupported QuickShell StatusbarWindow.qml layout.')
        text = text.replace(anchor, anchor + '\n    Component { id: cDashboard;  DashboardModule {} }', 1)
    if '"dashboard":' not in text:
        anchor = '        "terminal":'
        if anchor not in text:
            raise RuntimeError('Unsupported QuickShell module map.')
        text = text.replace(anchor, '        "dashboard":  cDashboard,\n' + anchor, 1)
    return _place_dashboard_before_launcher(text)


def _place_dashboard_before_launcher(text):
    pattern = re.compile(r'("(left|center|right)"\s*:\s*\[)([^\]]*)(\])')
    groups = list(pattern.finditer(text))
    if not groups:
        raise RuntimeError('QuickShell status bar has no module placement lists.')
    modules = {match.group(2): re.findall(r'"([^"\\]+)"', match.group(3)) for match in groups}
    for names in modules.values():
        names[:] = [name for name in names if name != 'dashboard']
    if 'launcher' in modules.get('center', []):
        modules['center'].insert(modules['center'].index('launcher'), 'dashboard')
    else:
        modules.setdefault('right', []).insert(0, 'dashboard')
    return pattern.sub(lambda match: match.group(1) + ', '.join(json.dumps(name) for name in modules[match.group(2)]) + match.group(4), text)


def install_quickshell(root, statusbar=None):
    statusbar = statusbar or Path.home() / '.config/quickshell/StatusbarApp'
    window = statusbar / 'StatusbarWindow.qml'
    if not window.is_file():
        return False
    source = root / 'scripts/DashboardModule.qml'
    if not source.is_file():
        raise RuntimeError('Bundled QuickShell dashboard module is missing.')
    original = window.read_text()
    updated = _add_quickshell_module(original)
    integration_changed = updated != original
    backup = window.with_name(window.name + '.before-dashboard-controls')
    if updated != original:
        if not backup.exists():
            shutil.copy2(window, backup)
        window.write_text(updated)
    rendered = source.read_text().replace('"@@DASHBOARD_ROOT@@"', json.dumps(str(root))).replace('"@@DASHBOARD_NAME@@"', json.dumps(DASHBOARD_NAME))
    module_path = statusbar / 'DashboardModule.qml'
    if not module_path.is_file() or module_path.read_text() != rendered:
        module_path.write_text(rendered)
        integration_changed = True
    for config in (Path.home() / '.config/ml4w-statusbar/config.json',
                   Path.home() / '.config/ml4w-statusbar/statusbar.json',
                   Path.home() / '.config/ml4w/settings/statusbar.json'):
        if not config.is_file():
            continue
        text = config.read_text()
        try:
            changed = _add_quickshell_module(text)
        except RuntimeError:
            # Settings files only contain the module list, not QML components.
            try:
                changed = _place_dashboard_before_launcher(text)
            except RuntimeError:
                continue
        if changed != text:
            integration_changed = True
            config_backup = config.with_name(config.name + '.before-dashboard-controls')
            if not config_backup.exists():
                shutil.copy2(config, config_backup)
            config.write_text(changed)
    reload_script = Path.home() / '.config/ml4w/scripts/ml4w-reload-statusbar'
    if integration_changed and reload_script.is_file():
        subprocess.run([str(reload_script)], check=False, stdout=subprocess.DEVNULL,
                       stderr=subprocess.DEVNULL)
    return True


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument('action', choices=['status', 'toggle', 'enable', 'disable', 'prepare', 'waybar', 'quickshell', 'update', 'update-run'])
    parser.add_argument('--config', type=Path)
    args = parser.parse_args()
    root = args.root.expanduser().resolve()
    if args.action == 'status':
        if not (root / 'scripts/start.sh').is_file():
            print(json.dumps({'text': '', 'tooltip': 'Dashboard not installed'}))
            return
        name = DASHBOARD_NAME
        enabled = not (root / 'disabled').exists()
        state = 'on' if enabled else 'off'
        print(json.dumps({'text': name + ' ' + ('●' if enabled else '○'), 'class': state,
                          'tooltip': name + ' ' + state + ' — click to toggle (saved across logins)'}))
    elif args.action == 'waybar':
        if not args.config:
            parser.error('waybar requires --config')
        install_waybar(root, args.config.expanduser())
    elif args.action == 'update':
        update(root)
    elif args.action == 'update-run':
        run_update(root)
    elif args.action == 'quickshell':
        install_quickshell(root, args.config.expanduser() if args.config else None)
    elif args.action == 'prepare':
        prepare(root)
    else:
        switch(root, args.action)


if __name__ == '__main__':
    main()
