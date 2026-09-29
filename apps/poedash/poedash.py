#!/usr/bin/env python3
"""PoeDash installer and management CLI; Python standard library only."""
import argparse
import datetime
import importlib.util
import json
import os
from pathlib import Path
import re
import shlex
import shutil
import subprocess
import sys
import tempfile

SOURCE = Path(__file__).resolve().parent
DEFAULT_ROOT = Path(os.environ.get('XDG_CONFIG_HOME', Path.home() / '.config')) / 'poedash'
BEGIN, END = '-- BEGIN POEDASH', '-- END POEDASH'
THEME_BEGIN, THEME_END = '# BEGIN POEDASH', '# END POEDASH'
PACKAGES = ['hyprland', 'jq', 'python', 'iproute2', 'util-linux', 'procps-ng',
            'coreutils', 'gawk', 'sed', 'grep', 'bash', 'pacman-contrib', 'kitty',
            'btop', 'nvtop', 'rofi', 'libnotify', 'ttf-jetbrains-mono-nerd',
            'matugen', 'playerctl']
REQUIRED = ['hyprctl', 'eww', 'jq', 'python3', 'ip', 'cal', 'flock', 'free',
            'timeout', 'checkupdates', 'kitty', 'btop', 'nvtop', 'rofi', 'notify-send', 'matugen', 'playerctl']


def run(argv, **kw):
    return subprocess.run([str(x) for x in argv], check=True, **kw)


def refresh(root):
    subprocess.Popen([str(root / 'scripts/start.sh')], start_new_session=True)


def atomic(path, text, mode=None):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix='.' + path.name)
    try:
        with os.fdopen(fd, 'w') as stream:
            stream.write(text)
        if mode is not None:
            os.chmod(tmp, mode)
        os.replace(tmp, path)
    finally:
        Path(tmp).unlink(missing_ok=True)


def settings(root, code_root=None):
    script = (code_root or root) / 'scripts/config.py'
    spec = importlib.util.spec_from_file_location('poedash_config', script)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.load(root)


def monitor_info(monitor):
    try:
        result = run(['hyprctl', 'monitors', '-j'], capture_output=True, text=True, timeout=3)
        monitors = json.loads(result.stdout)
        for index, item in enumerate(monitors):
            item['_index'] = index
        if isinstance(monitor, int):
            # Eww uses monitor index, not Hyprland's potentially sparse output ID.
            return monitors[monitor]
        return next(m for m in monitors if m['name'] == monitor)
    except (OSError, subprocess.SubprocessError, ValueError, IndexError, StopIteration):
        return None


def render(root):
    cfg = settings(root)
    scale = cfg['layout']['scale']
    monitor = monitor_info(cfg['monitor'])
    if scale == 'auto':
        scale = 1.0
        if monitor:
            width, height = monitor['width'], monitor['height']
            if monitor.get('transform', 0) % 2:
                width, height = height, width
            scale = min(1.0, width / monitor.get('scale', 1) / 1920,
                        height / monitor.get('scale', 1) / 1080)
            scale = max(.5, scale)
    yuck = (root / 'templates/eww.yuck').read_text()
    yuck = yuck.replace(':width 620', ':width ' + str(cfg['layout']['system_width']))
    yuck = yuck.replace(':width 520', ':width ' + str(cfg['layout']['network_width']))
    yuck = yuck.replace(':height 250', ':height ' + str(cfg['layout']['lower_height']))
    yuck = re.sub(r':(width|height|spacing) (\d+)', lambda m: ':' + m[1] + ' ' + str(max(1, round(int(m[2]) * scale))), yuck)
    dashboard_name = json.dumps(cfg['name'], ensure_ascii=False).replace('${', r'\${')
    yuck = yuck.replace('"@@DASHBOARD_NAME@@"', dashboard_name)
    selector = cfg['monitor']
    if isinstance(selector, str) and monitor:
        # GTK/Eww 0.6 may expose the EDID model rather than the connector name.
        matchers = list(dict.fromkeys([selector, monitor.get('model') or selector]))
        matchers.append(monitor.get('_index', 0))
        selector = json.dumps(matchers)
    yuck = yuck.replace(':monitor 0', ':monitor ' + json.dumps(selector))
    css = (root / 'templates/eww.scss').read_text()
    css = re.sub(r'(\d+(?:\.\d+)?)px', lambda m: f'{max(1, float(m[1]) * scale):g}px', css)
    start = shlex.join([str(root / 'scripts/start.sh')])
    lua = (root / 'templates/hyprland.lua').read_text().replace('@@START@@', json.dumps(start, ensure_ascii=False))
    # Validate everything before replacing any generated file.
    for name, content in [('eww.yuck', yuck), ('eww.scss', css), ('hyprland.lua', lua)]:
        atomic(root / name, content)
    print(f'Rendered {root} (scale {scale:g})')


def dependencies(dry_run=False):
    if not shutil.which('pacman'):
        raise RuntimeError('Automatic dependency installation supports Arch-based systems only.')
    missing = [p for p in PACKAGES if subprocess.run(['pacman', '-Q', p], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode]
    if missing:
        argv = ['sudo', 'pacman', '-S', '--needed', *missing]
        print('Dependencies:', shlex.join(argv), flush=True)
        if not dry_run:
            run(argv)
    for package, executable in [('eww', 'eww')]:
        if shutil.which(executable):
            continue
        repo = subprocess.run(['pacman', '-Si', package], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode == 0
        helper = shutil.which('paru') or shutil.which('yay')
        if repo:
            argv = ['sudo', 'pacman', '-S', '--needed', package]
        elif helper:
            argv = [helper, '-S', '--needed', package]
        else:
            print(f'{package}: needs an AUR helper (paru/yay) or manual installation.')
            if not dry_run:
                raise RuntimeError('Install the missing dependency and rerun. No AUR helper or third-party repository is installed automatically.')
            continue
        print('Dependency:', shlex.join(argv), flush=True)
        if not dry_run:
            run(argv)


def doctor(root):
    failures = []
    for command in REQUIRED:
        found = shutil.which(command)
        print(f'{"OK" if found else "MISSING"}: {command}')
        if not found:
            failures.append(command)
    if shutil.which('hyprctl'):
        try:
            version = run(['hyprctl', 'version', '-j'], capture_output=True, text=True, timeout=3)
            data = json.loads(version.stdout)
            match = re.search(r'(\d+)\.(\d+)', data.get('version', '') or data.get('tag', ''))
            if not match or tuple(map(int, match.groups())) < (0, 55):
                failures.append('Hyprland 0.55+ with Lua required')
        except (OSError, subprocess.SubprocessError, ValueError):
            failures.append('Run doctor inside a Hyprland session')
    if (root / 'settings.json').exists():
        cfg = settings(root)
        if not monitor_info(cfg['monitor']):
            failures.append('Configured monitor is not connected')
    if failures:
        print('Needs attention: ' + '; '.join(failures))
    return int(bool(failures))


def hook_text(root):
    return BEGIN + '\ndofile(' + json.dumps(str(root / 'hyprland.lua'), ensure_ascii=False) + ')\n' + END


def without_hook(text):
    return re.sub(r'(?m)^' + BEGIN + r'\n.*?^' + END + r'\n?', '', text, flags=re.S)


def chosen_name(args, root):
    current = 'PoeDash'
    path = root / 'settings.json'
    if path.is_file():
        try:
            value = json.loads(path.read_text()).get('name')
            if isinstance(value, str) and value.strip():
                current = value.strip()
        except (OSError, ValueError):
            pass
    if args.name is not None:
        value = args.name.strip()
    elif args.non_interactive or not sys.stdin.isatty():
        value = current
    else:
        value = input(f'Dashboard name [{current}]: ').strip() or current
    if not 1 <= len(value) <= 32 or any(ord(char) < 32 for char in value):
        raise ValueError('Dashboard name must contain 1–32 printable characters.')
    return value


def retire_legacy_dashboard(config_home, backup):
    legacy = config_home / 'eww'
    definition = legacy / 'eww.yuck'
    if not definition.is_file():
        return False
    text = definition.read_text(errors='replace')
    fingerprints = ('MY DASHBOARD', 'START WEB CTF', 'BlackArch home screen')
    if not any(marker in text for marker in fingerprints):
        return False
    if shutil.which('eww'):
        subprocess.run(['eww', '--config', str(legacy), 'kill'],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    shutil.copytree(legacy, backup / 'retired-legacy-eww', dirs_exist_ok=True)
    shutil.rmtree(legacy)
    custom = config_home / 'hypr/custom.lua'
    if custom.is_file():
        old = custom.read_text()
        cleaned = re.sub(r'(?ms)^-- BEGIN PENDASH\n.*?^-- END PENDASH\n?', '', old)
        cleaned = re.sub(r'(?m)^.*\.config/eww/scripts/start\.sh.*\n?', '', cleaned)
        if cleaned != old:
            shutil.copy2(custom, backup / 'retired-custom.lua')
            atomic(custom, cleaned, custom.stat().st_mode & 0o777)
    return True


def install(args, root):
    assets = SOURCE / 'assets'
    if not assets.is_dir():
        raise RuntimeError('Run install from a cloned PoeDash repository.')
    config_home = Path(os.environ.get('XDG_CONFIG_HOME', Path.home() / '.config'))
    hypr = Path(args.hyprland_config).expanduser().resolve() if args.hyprland_config else config_home / 'hypr/hyprland.lua'
    binpath = Path.home() / '.local/bin/poedash'
    matugen = config_home / 'matugen/config.toml'
    matugen_text = matugen.read_text() if matugen.exists() else ''
    name = chosen_name(args, root)
    if not args.no_integrate:
        import tomllib
        parsed = tomllib.loads(matugen_text)
        if 'poedash' in parsed.get('templates', {}) and THEME_BEGIN not in matugen_text:
            raise RuntimeError('Matugen already has an unmanaged templates.poedash entry.')
    if not args.no_integrate:
        if not hypr.is_file() or hypr.suffix != '.lua':
            raise RuntimeError('An existing Hyprland Lua configuration is required. Start Hyprland once or use --hyprland-config PATH / --no-integrate.')
    if args.dry_run:
        if not args.skip_deps:
            dependencies(True)
        print(f'Would back up and install into {root}; preserve settings, palette and state.')
        print(f'Would install CLI: {binpath}')
        print('No integration requested.' if args.no_integrate else f'Would append a managed block to {hypr}')
        return
    if not args.skip_deps:
        dependencies()
    # Versioned snapshots are never overwritten; uninstall does not delete user data.
    backup = Path(os.environ.get('XDG_STATE_HOME', Path.home() / '.local/state')) / 'poedash/backups' / datetime.datetime.now().strftime('%Y%m%d-%H%M%S-%f')
    backup.mkdir(parents=True, mode=0o700)
    if root.exists():
        shutil.copytree(root, backup / 'config')
    if binpath.exists():
        shutil.copy2(binpath, backup / 'poedash-command')
    if not args.no_integrate:
        shutil.copy2(hypr, backup / 'hyprland.lua')
        if matugen.exists():
            shutil.copy2(matugen, backup / 'matugen.toml')
        retire_legacy_dashboard(config_home, backup)
    preserved = {}
    for preserved_name in ('settings.json', 'colors.scss', 'disabled'):
        path = root / preserved_name
        if path.is_file():
            preserved[preserved_name] = path.read_bytes()
    if root.exists():
        if shutil.which('eww'):
            subprocess.run(['eww', '--config', str(root), 'kill'], check=False,
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        shutil.rmtree(root)
    root.mkdir(parents=True, exist_ok=True)
    for directory in ('scripts', 'templates'):
        shutil.copytree(assets / directory, root / directory, dirs_exist_ok=True)
    for filename in ('colors.scss', 'settings.example.json'):
        shutil.copy2(assets / filename, root / filename)
    if 'colors.scss' in preserved:
        (root / 'colors.scss').write_bytes(preserved['colors.scss'])
    if 'settings.json' in preserved:
        try:
            old_settings = json.loads(preserved['settings.json'])
        except ValueError:
            old_settings = {}
    else:
        old_settings = {}
    new_settings = json.loads((assets / 'settings.example.json').read_text())
    new_settings['name'] = name
    if 'monitor' in old_settings:
        new_settings['monitor'] = old_settings['monitor']
    new_schema = set(old_settings) == {'name', 'monitor', 'layout'}
    if new_schema and isinstance(old_settings.get('layout'), dict):
        for key in new_settings['layout']:
            if key in old_settings['layout']:
                new_settings['layout'][key] = old_settings['layout'][key]
    atomic(root / 'settings.json', json.dumps(new_settings, indent=2) + '\n')
    if 'disabled' in preserved:
        (root / 'disabled').write_bytes(preserved['disabled'])
    shutil.copy2(SOURCE / 'poedash.py', root / 'poedash.py')
    render(root)
    run([sys.executable, root / 'scripts/dashboard-control.py', '--root', root, 'prepare'])
    run([sys.executable, root / 'scripts/dashboard-control.py', '--root', root, 'quickshell'])
    cli = '#!/usr/bin/env bash\nexec python3 ' + shlex.quote(str(root / 'poedash.py')) + ' --root ' + shlex.quote(str(root)) + ' "$@"\n'
    atomic(binpath, cli, 0o755)
    manifest_path = root / 'install.json'
    manifest = json.loads(manifest_path.read_text()) if manifest_path.exists() else {}
    manifest.update({'bin': str(binpath), 'backup': str(backup)})
    if not args.no_integrate:
        previous = hypr.read_text()
        atomic(hypr, without_hook(previous).rstrip() + '\n\n' + hook_text(root) + '\n', hypr.stat().st_mode & 0o777)
        manifest['hyprland_config'] = str(hypr)
        if 'config' not in parsed:
            matugen_text = '[config]\n' + matugen_text
        clean_theme = re.sub(r'(?ms)^# BEGIN POEDASH\n.*?^# END POEDASH\n?', '', matugen_text)
        block = THEME_BEGIN + '\n[templates.poedash]\ninput_path = ' + json.dumps(str(root / 'templates/matugen.scss'))
        block += '\noutput_path = ' + json.dumps(str(root / 'colors.scss'))
        block += '\npost_hook = ' + json.dumps(shlex.join(['eww', '--config', str(root), 'reload'])) + '\n' + THEME_END + '\n'
        atomic(matugen, clean_theme.rstrip() + '\n\n' + block)
        manifest['matugen_config'] = str(matugen)
    atomic(manifest_path, json.dumps(manifest, indent=2) + '\n')
    if (not args.no_start and not (root / 'disabled').exists() and
            os.environ.get('HYPRLAND_INSTANCE_SIGNATURE') and os.environ.get('WAYLAND_DISPLAY')):
        try:
            refresh(root)
        except OSError as exc:
            print(f'WARNING: PoeDash was installed but could not be refreshed automatically: {exc}', file=sys.stderr)
    print(f'Installed. Backup: {backup}\nRun ~/.local/bin/poedash doctor, then ~/.local/bin/poedash start.')
    print('Log in again to activate workspace protection, or reload Hyprland after reviewing the appended block.')


def uninstall(root):
    manifest = json.loads((root / 'install.json').read_text())
    if manifest.get('hyprland_config'):
        hypr = Path(manifest['hyprland_config'])
        if hypr.exists():
            text = hypr.read_text()
            if hook_text(root) in text:
                atomic(hypr, without_hook(text), hypr.stat().st_mode & 0o777)
            elif BEGIN in text:
                raise RuntimeError('Managed block was edited; remove it manually before uninstalling.')
    if manifest.get('matugen_config'):
        matugen = Path(manifest['matugen_config'])
        if matugen.exists():
            text = re.sub(r'(?ms)^# BEGIN POEDASH\n.*?^# END POEDASH\n?', '', matugen.read_text())
            atomic(matugen, text)
    if shutil.which('eww'):
        subprocess.run(['eww', '--config', str(root), 'kill'], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    binary = Path(manifest['bin'])
    if binary.exists() and str(root / 'poedash.py') in binary.read_text():
        binary.unlink()
    print(f'Autostart and CLI removed. Settings remain at {root}; state and backups are retained. Log in again to reset workspace bindings.')


def theme(root, wallpaper):
    wallpaper = Path(wallpaper).expanduser().resolve(strict=True)
    # A separate Matugen config avoids modifying another desktop theme setup.
    cfg = '[config]\n[templates.poedash]\ninput_path = ' + json.dumps(str(root / 'templates/matugen.scss')) + '\noutput_path = ' + json.dumps(str(root / 'colors.scss')) + '\n'
    with tempfile.TemporaryDirectory(prefix='poedash-matugen-') as tmp:
        path = Path(tmp) / 'config.toml'
        path.write_text(cfg)
        run(['matugen', '--config', path, 'image', wallpaper])
    subprocess.run(['eww', '--config', str(root), 'reload'])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=DEFAULT_ROOT)
    sub = parser.add_subparsers(dest='action', required=True)
    ins = sub.add_parser('install', help='install from this repository')
    ins.add_argument('--skip-deps', action='store_true')
    ins.add_argument('--dry-run', action='store_true')
    ins.add_argument('--no-integrate', action='store_true')
    ins.add_argument('--hyprland-config')
    ins.add_argument('--name')
    ins.add_argument('--non-interactive', action='store_true')
    ins.add_argument('--no-start', action='store_true', help=argparse.SUPPRESS)
    for name in ('render', 'reload', 'doctor', 'uninstall', 'start', 'stop', 'enable', 'disable', 'update'):
        sub.add_parser(name)
    sub.add_parser('theme').add_argument('wallpaper')
    args = parser.parse_args()
    root = args.root.expanduser().resolve()
    if args.action == 'install':
        if os.geteuid() == 0:
            raise RuntimeError('Run as your desktop user, without sudo. Only package installation uses sudo.')
        install(args, root)
    elif args.action == 'doctor':
        return doctor(root)
    elif args.action in ('render', 'reload'):
        render(root)
        if args.action == 'reload':
            run(['eww', '--config', root, 'reload'])
    elif args.action == 'start':
        run([root / 'scripts/start.sh'])
    elif args.action == 'stop':
        run(['eww', '--config', root, 'kill'])
    elif args.action in ('enable', 'disable', 'update'):
        run([sys.executable, root / 'scripts/dashboard-control.py', '--root', root, args.action])
    elif args.action == 'uninstall':
        uninstall(root)
    elif args.action == 'theme':
        theme(root, args.wallpaper)
    return 0


if __name__ == '__main__':
    try:
        sys.exit(main())
    except (OSError, ValueError, KeyError, TypeError, RuntimeError, subprocess.SubprocessError) as exc:
        print('PoeDash: ' + str(exc), file=sys.stderr)
        sys.exit(1)
