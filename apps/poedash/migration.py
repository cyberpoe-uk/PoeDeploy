#!/usr/bin/env python3
"""Install-time removal of a recognised retired dashboard, with full backups."""
import json
import hashlib
import os
from pathlib import Path
import re
import shlex
import signal
import time
import shutil
import subprocess

# These identifiers are migration signatures, not supported dashboard providers.
RETIRED = 'pendash'
SIGNATURES = ('MY DASHBOARD', 'START WEB CTF', 'BlackArch home screen', 'PenDash')


def stop_legacy_surface(root):
    """Stop an old PoeDash Eww surface only during an installation upgrade."""
    if not (root / 'eww.yuck').is_file(): return
    if shutil.which('eww'):
        subprocess.run(['eww', '--config', str(root), 'kill'], check=False,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=5)
    stop_workers([root], exclude={'dashboard-control.py', 'update.sh', 'poedash.py', 'retire-dashboard.py'})


def recognised(root):
    identity = root / 'dashboard-id'
    if identity.is_file() and identity.read_text().strip().lower() == RETIRED:
        return True
    definition = root / 'eww.yuck'
    return definition.is_file() and any(token in definition.read_text(errors='replace') for token in SIGNATURES)


def rewrite_waybar(text, root, old_roots):
    """Replace only retired control objects and their module IDs, preserving JSONC."""
    old_name = 'custom/' + RETIRED
    matches = list(re.finditer(r'"(' + re.escape(old_name) + r'(?:-update)?)"\s*:\s*\{', text))
    for match in reversed(matches):
        depth, end = 0, None
        for token in re.finditer(r'"(?:\\.|[^"\\])*"|//[^\n]*|/\*[\s\S]*?\*/|[{}]', text[match.end() - 1:]):
            value = token.group()
            if value == '{': depth += 1
            elif value == '}': depth -= 1
            if depth == 0:
                end = match.end() - 1 + token.end()
                break
        if end is None: raise RuntimeError('Unclosed retired Waybar control. No bar configuration was changed.')
        suffix = '-update' if match.group(1).endswith('-update') else ''
        new_name = 'custom/poedash' + suffix
        block = text[match.start():end]
        if re.search(r'"' + re.escape(new_name) + r'"\s*:', text):
            # Existing PoeDash controls win. Remove the old object and its comma.
            start = match.start()
            tail = re.match(r'\s*,', text[end:])
            if tail: end += tail.end()
            else:
                before = re.search(r',\s*$', text[:start])
                if before: start = before.start()
            text = text[:start] + text[end:]
            token_name = json.dumps(match.group(1))
            text = re.sub(r'(?P<open>"modules-(?:left|right|center)"\s*:\s*\[)(?P<body>[^\]]*)(?P<close>\])',
                lambda m: m['open'] + re.sub(r',\s*' + re.escape(token_name), '',
                    re.sub(re.escape(token_name) + r'\s*,\s*', '', m['body'])).replace(token_name, '') + m['close'], text)
        else:
            command = ' '.join(['python3', shlex.quote(str(root / 'scripts/dashboard-control.py')),
                                '--root', shlex.quote(str(root))])
            if suffix:
                entry = {'exec-if': 'test -f ' + shlex.quote(str(root / 'scripts/start.sh')),
                         'exec': "printf '↻'", 'interval': 60, 'format': ' {} ',
                         'tooltip-format': 'Update PoeDash', 'on-click': command + ' update'}
            else:
                entry = {'exec': command + ' status', 'return-type': 'json', 'interval': 2,
                         'on-click': command + ' toggle', 'format': ' {text} ', 'escape': True}
            text = text[:match.start()] + json.dumps(new_name) + ': ' + json.dumps(entry) + text[end:]
            text = text.replace(json.dumps(match.group(1)), json.dumps(new_name))
    return text


def stop_workers(roots, exclude=()):
    prefixes = [str(p).rstrip('/') + '/' for root in roots for p in (root, root.resolve())]
    def running():
        matches = []
        for proc in Path('/proc').glob('[0-9]*'):
            try:
                if proc.stat().st_uid != os.getuid(): continue
                if proc.joinpath('stat').read_text().split(') ',1)[1].startswith('Z'): continue
                argv = proc.joinpath('cmdline').read_bytes().decode().strip('\0').split('\0')
                executable = Path(argv[0]).name
                scripts = argv[:1] if any(argv[0].startswith(p) for p in prefixes) else argv[1:2]
                if any(Path(arg).name in exclude for arg in scripts): continue
                interpreter = executable in ('sh','bash','eww') or executable.startswith('python')
                owned_script = any(arg.startswith(prefix) and arg.endswith(('.py','.sh')) for arg in scripts for prefix in prefixes)
                owned_eww = executable == 'eww' and any(arg.rstrip('/')+'/' in prefixes for arg in argv[1:])
                if (interpreter and owned_script) or owned_eww: matches.append(int(proc.name))
            except (OSError, ValueError, IndexError): continue
        return matches
    for sig in (signal.SIGTERM, signal.SIGKILL):
        pids = running()
        if not pids: return
        for pid in pids:
            try: os.kill(pid, sig)
            except ProcessLookupError: pass
        deadline = time.monotonic() + 2
        while time.monotonic() < deadline:
            if not running(): return
            time.sleep(.05)
    raise RuntimeError('Retired dashboard processes did not stop. Configuration files were retained.')


def retire(config_home, backup, new_root):
    home = Path.home()
    candidates = [config_home / 'eww', config_home / RETIRED]
    roots = [p for p in candidates if recognised(p)]
    selected = config_home / 'poedeploy/dashboard'
    selected_old = selected.is_file() and selected.read_text().strip().lower() == RETIRED
    launcher = home / '.local/bin' / RETIRED
    if not roots and not selected_old:
        return False
    references = [RETIRED, *[str(p) for p in roots], *[str(p.resolve()) for p in roots]]
    if config_home / 'eww' in roots:
        references += ['$XDG_CONFIG_HOME/eww', '${XDG_CONFIG_HOME}/eww']
        if config_home.resolve() == (home / '.config').resolve():
            references += ['~/.config/eww', '$HOME/.config/eww']
    def owned(text):
        text = text.replace('/' + RETIRED + '/burp', '/__independent_burp__')
        explicit = bool(re.search(r'\b' + RETIRED + r'\b', text, re.I)) or any(token in text for token in references[1:])
        default_eww = config_home / 'eww' in roots and any('--config' not in line and re.search(r'\beww\s+(?:(?:--?[\w-]+)\s+)*(?:daemon|open\s+dashboard)\b', line) for line in text.splitlines())
        return explicit or default_eww
    def save(path):
        path = Path(path)
        relative = path.relative_to(home) if path.is_relative_to(home) else Path('external') / path.as_posix().lstrip('/')
        target = backup / 'retired-files' / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        if path.is_dir(): shutil.copytree(path, target, symlinks=True, dirs_exist_ok=True)
        else: shutil.copy2(path, target)
    def write(path, text):
        # Update a dotfiles symlink's target, preserving the symlink itself.
        save(path)
        destination = path.resolve()
        temporary = destination.with_name('.' + destination.name + '.dashboard-migration')
        try:
            temporary.write_text(text)
            temporary.chmod(destination.stat().st_mode & 0o777)
            temporary.replace(destination)
        finally: temporary.unlink(missing_ok=True)
    def delete(path):
        if not path.exists() and not path.is_symlink(): return
        save(path)
        if path.is_symlink() or path.is_file(): path.unlink()
        else: shutil.rmtree(path)
    # Stop only the retired config's daemon and user units, never a generic Eww daemon.
    for root in roots:
        if shutil.which('eww'):
            result = subprocess.run(['eww', '--config', str(root), 'kill'], capture_output=True, text=True)
            if result.returncode and 'No such file' not in result.stderr:
                # An already stopped daemon is normal. Active PID checks below are
                # not guessed from names, so other widgets stay untouched.
                pass
    changed_units = False
    for unit in (RETIRED + '.service', RETIRED + '-dashboard.service'):
        path = config_home / 'systemd/user' / unit
        if path.is_file() and owned(path.read_text()):
            result = subprocess.run(['systemctl', '--user', 'disable', '--now', unit], capture_output=True, text=True)
            if result.returncode:
                raise RuntimeError(f'Could not stop retired {unit}: {result.stderr.strip()}. Run installation in the desktop user session.')
            delete(path)
            delete(path.with_name(unit + '.d'))
            changed_units = True
            for relation in ('*.wants/', '*.requires/'):
                for link in (config_home / 'systemd/user').glob(relation + unit):
                    if link.is_symlink(): link.unlink()
    if changed_units:
        result = subprocess.run(['systemctl','--user','daemon-reload'],capture_output=True,text=True)
        if result.returncode: raise RuntimeError('Retired user units were removed, but systemd reload failed: '+result.stderr.strip())
    stop_workers([*roots, home / '.local/lib' / RETIRED])
    # Remove managed old hooks as complete blocks, preserving unrelated settings.
    for folder in (config_home / 'hypr', config_home / 'autostart'):
        if not folder.is_dir(): continue
        for path in folder.rglob('*'):
            if not path.is_file() or path.suffix not in ('.lua', '.conf', '.desktop'): continue
            text = path.read_text(errors='replace')
            if not owned(text): continue
            if path.suffix == '.desktop':
                command = re.search(r'(?m)^Exec=(.*)$',text)
                try: parts = shlex.split(command.group(1)) if command else []
                except ValueError: parts = []
                executable = parts[0] if parts else ''
                if path.name == RETIRED+'.desktop' or owned(executable) or command and owned(command.group(1)):
                    delete(path)
                continue
            pattern = r'(?ms)^(--|#) BEGIN [A-Z_]+\n.*?^\1 END [A-Z_]+\n?'
            text = re.sub(pattern, lambda m: '' if owned(m.group()) and (re.search(r'BEGIN (?:PENDASH|[A-Z_]*HOME[A-Z_]*|[A-Z_]*DASHBOARD[A-Z_]*)',m.group()) or 'local function protect_home' in m.group()) else m.group(), text)
            text = ''.join(line for line in text.splitlines(keepends=True) if not owned(line))
            if text != path.read_text(errors='replace'): write(path, text)
    matugen = config_home / 'matugen/config.toml'
    if matugen.is_file():
        original = matugen.read_text()
        text = re.sub(r'(?ms)^# BEGIN [A-Z_]+\n.*?^# END [A-Z_]+\n?',
                      lambda m: '' if owned(m.group()) else m.group(), original)
        text = re.sub(r'(?ms)^\[templates\.[^\]]+\][^\n]*\n.*?(?=^\[|\Z)',
                      lambda m: '' if owned(m.group()) else m.group(), text)
        if text != original: write(matugen, text)
    waybar = config_home / 'waybar'
    if waybar.is_dir():
        for path in waybar.rglob('*'):
            if not path.is_file() or not (path.suffix in ('.css','.json','.jsonc') or path.name == 'config'): continue
            original = path.read_text()
            if path.suffix == '.css':
                text = original.replace('#custom-' + RETIRED, '#custom-poedash')
            elif path.name in ('config','config.json','config.jsonc') or path.suffix in ('.json','.jsonc'):
                text = rewrite_waybar(original, new_root, roots)
            else: continue
            if text != original: write(path, text)
    module = config_home / 'quickshell/StatusbarApp/DashboardModule.qml'
    if module.is_file() and owned(module.read_text()):
        source = (Path(__file__).parent / 'assets/scripts/DashboardModule.qml').read_text()
        text = source.replace('"@@DASHBOARD_ROOT@@"', json.dumps(str(new_root)))
        text = text.replace('"@@DASHBOARD_NAME@@"', json.dumps('PoeDash'))
        if text != module.read_text(): write(module, text)
    for root in roots:
        destination = backup / ('retired-legacy-eww' if root == roots[0] else 'retired-legacy-extra')
        shutil.copytree(root, destination, symlinks=True, dirs_exist_ok=True)
        for name in ('settings.json','colors.scss','disabled','layout.json'):
            original = root / name
            target = destination / name
            if original.is_file() and target.is_symlink():
                target.unlink()
                shutil.copy2(original,target)
        if root.is_symlink(): root.unlink()  # Keep the user's inactive dotfiles source.
        else: shutil.rmtree(root)
    for path in (launcher, home / '.local/lib' / RETIRED,
                 home / '.local/share/applications' / (RETIRED + '.desktop')):
        delete(path)
    browser_launcher = home / '.local/bin/ctf-chromium'
    if browser_launcher.is_file() and not browser_launcher.is_symlink():
        content = browser_launcher.read_bytes()
        managed_hash = 'ccf8c5c1b359149f36ed7ed2a48a21346161f9ce0647cf62e4933a639df46969'
        if hashlib.sha256(content).hexdigest() == managed_hash or owned(content.decode(errors='replace')):
            delete(browser_launcher)
    cache_home = Path(os.environ.get('XDG_CACHE_HOME', home / '.cache'))
    delete(cache_home / RETIRED)
    shared = home / '.local/share' / RETIRED
    for name in ('dashboard','assets','scripts',RETIRED+'.py','install.sh','bootstrap.sh'):
        delete(shared / name)
    if shared.is_dir() and not any(shared.iterdir()): shared.rmdir()
    # Security applications and browser profiles are independent and remain installed.
    return True
