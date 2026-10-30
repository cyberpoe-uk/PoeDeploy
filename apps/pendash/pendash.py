#!/usr/bin/env python3
"""Install and manage the PenDash dashboard and Chromium integration."""
import burp_ca
import argparse
import datetime
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile

SOURCE = Path(__file__).resolve().parent
HOME = Path.home()
STATE = Path(os.environ.get('XDG_STATE_HOME', HOME / '.local/state')) / 'pendash'
STAMP = datetime.datetime.now().strftime('%Y%m%d-%H%M%S-%f')
BACKUP = STATE / 'backups' / STAMP
DASHBOARD = ['hyprland', 'jq', 'python', 'kitty', 'btop', 'nvtop', 'rofi',
             'powertop', 'brightnessctl', 'libnotify']
BEGIN, END = '-- BEGIN PENDASH', '-- END PENDASH'


def run(argv, check=True, **kwargs):
    print('+ ' + ' '.join(map(str, argv)), flush=True)
    return subprocess.run([str(x) for x in argv], check=check, **kwargs)


def yes(prompt, default=False):
    suffix = ' [Y/n] ' if default else ' [y/N] '
    answer = input(prompt + suffix).strip().lower()
    return default if not answer else answer in ('y', 'yes')


def backup(path):
    path = Path(path)
    if not path.exists() and not path.is_symlink():
        return
    BACKUP.mkdir(parents=True, exist_ok=True)
    target = BACKUP / path.as_posix().lstrip('/')
    target.parent.mkdir(parents=True, exist_ok=True)
    if os.access(path, os.R_OK):
        if path.is_dir():
            shutil.copytree(path, target, symlinks=True, dirs_exist_ok=True)
        else:
            shutil.copy2(path, target, follow_symlinks=False)
    else:
        run(['sudo', 'cp', '-a', path, target])
        run(['sudo', 'chown', '-R', f'{os.getuid()}:{os.getgid()}', target])


def write(path, content, mode=0o644):
    path = Path(path)
    if path.exists() and path.read_text(errors='replace') == content and (path.stat().st_mode & 0o777) == mode:
        return
    backup(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name('.' + path.name + '.pendash')
    temporary.write_text(content)
    temporary.chmod(mode)
    temporary.replace(path)


def replace_block(old, block):
    clean = re.sub(r'(?ms)^' + re.escape(BEGIN) + r'$.*?^' + re.escape(END) + r'$\n?', '', old)
    return clean.rstrip() + '\n\n' + block.strip() + '\n'


def install_packages(packages, dry_run):
    installed = set(subprocess.check_output(['pacman', '-Qq'], text=True).splitlines())
    missing = [p for p in packages if p not in installed]
    if missing:
        argv = ['sudo', 'pacman', '-S', '--needed', *missing]
        if dry_run:
            if len(missing) > 30:
                print(f'Would install {len(missing)} missing packages with sudo pacman -S --needed.')
            else:
                print('Would run: ' + ' '.join(argv))
        else:
            run(argv)
    if shutil.which('eww') is None:
        helper = shutil.which('paru') or shutil.which('yay')
        if not helper:
            raise RuntimeError('Eww is unavailable; install paru/yay or Eww manually and rerun.')
        if dry_run:
            print(f'Would install eww with {helper}.')
        else:
            run([helper, '-S', '--needed', 'eww'])


def burp_executable():
    candidates = [
        HOME / 'Applications/BurpSuite/BurpSuite',
        HOME / 'BurpSuite/BurpSuite',
        Path('/opt/BurpSuite/BurpSuite'),
        Path('/usr/local/BurpSuite/BurpSuite'),
    ]
    command = shutil.which('BurpSuite') or shutil.which('burpsuite')
    if command:
        owner = subprocess.run(['pacman', '-Qo', command], text=True, capture_output=True)
        # Do not mistake a pre-existing BlackArch package for the native install.
        if owner.returncode or not re.search(r'\bis owned by burpsuite\b', owner.stdout):
            candidates.insert(0, Path(command))
    return next((path for path in candidates if path.is_file() and os.access(path, os.X_OK)), None)


def install_browser(dry_run):
    print('[BROWSER] Chromium selected (PenDash default)')
    if dry_run:
        print('Would install CTF Chromium launcher and certificate command.')
        return
    write(HOME / '.local/bin/ctf-chromium', (SOURCE / 'assets/ctf-chromium').read_text(), 0o755)
    write(HOME / '.local/lib/pendash/burp_ca.py', (SOURCE / 'burp_ca.py').read_text(), 0o755)
    write(HOME / '.local/bin/pendash', (SOURCE / 'assets/pendash').read_text(), 0o755)
    flags = HOME / '.config/chromium-flags.conf'
    old = flags.read_text() if flags.exists() else ''
    lines = [line for line in old.splitlines() if not line.strip().startswith(
        ('--proxy-server', '--proxy-bypass-list', '--no-proxy-server', '--proxy-pac-url', '--proxy-auto-detect'))]
    lines += ['--proxy-server=http://127.0.0.1:8080', '--proxy-bypass-list=<-loopback>']
    write(flags, '\n'.join(lines) + '\n')
    print('[PASS] Persistent Chromium HTTP/HTTPS Burp proxy configured')
    print('[PASS] CTF Chromium launcher installed')


def browser_checks():
    launcher = HOME / '.local/bin/ctf-chromium'
    values = [('Chromium installed', shutil.which('chromium')),
              ('NSS certificate utilities available', shutil.which('certutil')),
              ('Chromium launcher executable', os.access(launcher, os.X_OK)),
              ('Proxy configuration present', launcher.exists() and '--proxy-server="http://127.0.0.1:8080"' in launcher.read_text())]
    for label, value in values:
        print(('[PASS] ' if value else '[FAIL] ') + label)
    print('[PASS] Burp native executable detected' if burp_executable() else '[INFO] Burp native installation unavailable')
    if not burp_ca.proxy_available():
        print('[INFO] Burp proxy currently unavailable\n[INFO] Start Burp to configure or test HTTPS interception')
    try:
        burp_ca.main('status')
    except (OSError, RuntimeError, subprocess.SubprocessError) as exc:
        print('[INFO] Burp CA status unavailable: ' + str(exc))
    return all(value for _, value in values)


def offer_ca(args):
    if args.dry_run:
        return
    browser_checks()
    if not args.non_interactive and yes('Configure Burp CA now?'):
        burp_ca.main('import', args.certificate)
    else:
        print('[INFO] Burp CA setup pending.\n[INFO] Run: pendash setup-burp-ca')


def install_dashboard(browser, dry_run, preserve_colors=False):
    destination = HOME / '.config/eww'
    if dry_run:
        print(f'Would back up and install the PenDash dashboard into {destination}.')
        return
    preserved = {}
    for name in ('colors.scss', 'browser.json', 'disabled'):
        path = destination / name
        if path.is_file():
            preserved[name] = path.read_bytes()
    preserved_state = destination / 'state'
    state_copy = None
    if preserved_state.is_dir():
        state_copy = Path(tempfile.mkdtemp(prefix='pendash-state-')) / 'state'
        shutil.copytree(preserved_state, state_copy)
    backup(destination)
    if destination.exists():
        shutil.rmtree(destination)
    destination.mkdir(parents=True, exist_ok=True)
    for source in (SOURCE / 'dashboard').rglob('*'):
        if source.is_file():
            target = destination / source.relative_to(SOURCE / 'dashboard')
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)
            if target.parent.name == 'scripts' or target.name.endswith('.py'):
                target.chmod(0o755)
    if preserve_colors and 'colors.scss' in preserved:
        (destination / 'colors.scss').write_bytes(preserved['colors.scss'])
    if 'disabled' in preserved:
        (destination / 'disabled').write_bytes(preserved['disabled'])
    if state_copy:
        shutil.copytree(state_copy, destination / 'state', dirs_exist_ok=True)
        shutil.rmtree(state_copy.parent)
    write(destination / 'browser.json', json.dumps({'browser': browser}, indent=2) + '\n')
    install_browser(False)
    user_env = dict(os.environ, HOME=str(HOME))
    run([sys.executable, destination / 'scripts/dashboard-control.py', '--root', destination, 'prepare'], env=user_env)
    run([sys.executable, destination / 'scripts/dashboard-control.py', '--root', destination, 'quickshell'], env=user_env)
    custom = HOME / '.config/hypr/custom.lua'
    old = custom.read_text() if custom.exists() else ''
    if BEGIN not in old and '-- Home dashboard:' in old and 'local function protect_home' in old:
        old = ''  # Migrate the known pre-PenDash version of this managed dashboard file.
    write(custom, replace_block(old, (SOURCE / 'assets/custom.lua').read_text()))


def dashboard_enabled(root, enabled):
    helper = root / 'scripts/dashboard-control.py'
    if not helper.exists():
        helper = SOURCE / 'dashboard/scripts/dashboard-control.py'
    run([sys.executable, helper, '--root', root, 'enable' if enabled else 'disable'])
    print('Dashboard ' + ('enabled.' if enabled else 'disabled; settings are retained.'))
    print('Log out and back in to refresh workspace bindings.')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    action = parser.add_mutually_exclusive_group()
    action.add_argument('--update-dashboard', action='store_true', help='refresh dashboard and Chromium integration')
    action.add_argument('--disable-dashboard', action='store_true', help='stop dashboard and disable autostart')
    action.add_argument('--enable-dashboard', action='store_true', help='restore dashboard and autostart')
    action.add_argument('--check', action='store_true', help='check the dashboard and Chromium integration')
    action.add_argument('--dry-run', action='store_true')
    parser.add_argument('--waybar-config', type=Path, help='add a toggle to this Waybar config')
    parser.add_argument('--non-interactive', action='store_true')
    # Accept existing dashboard launch commands. Dashboard installation is now
    # the only installation mode, including when no flag is supplied.
    parser.add_argument('--dashboard-only', action='store_true', help=argparse.SUPPRESS)
    parser.add_argument('--skip-packages', action='store_true')
    parser.add_argument('command', nargs='?', choices=['setup-burp-ca'])
    parser.add_argument('--certificate', type=Path)
    parser.add_argument('--ca-action', choices=['import', 'status', 'remove'], default='import')
    args = parser.parse_args()
    if args.command:
        return burp_ca.main(args.ca_action, args.certificate)
    if os.geteuid() == 0:
        parser.error('Run as the desktop user; the installer requests sudo for package installation.')
    browser = 'chromium'
    if args.update_dashboard:
        root = HOME / '.config/eww'
        if not (root / 'eww.yuck').is_file():
            raise RuntimeError('Install PenDash before updating it.')
        if any(not shutil.which(command) for command in ('chromium', 'certutil', 'openssl')):
            install_packages(['chromium', 'nss', 'openssl'], False)
        install_dashboard(browser, False, preserve_colors=True)
        if args.waybar_config:
            run([sys.executable, root / 'scripts/dashboard-control.py', '--root', root, 'waybar', '--config', args.waybar_config])
        if not (root / 'disabled').exists():
            dashboard_enabled(root, True)
        print('Dashboard and Chromium integration updated.')
        return 0
    if args.disable_dashboard or args.enable_dashboard:
        dashboard_enabled(HOME / '.config/eww', args.enable_dashboard)
        return 0
    if args.check:
        return 0 if browser_checks() and (HOME / '.config/eww/eww.yuck').is_file() else 2
    if not args.skip_packages:
        install_packages(sorted(set(DASHBOARD + ['chromium', 'nss', 'openssl'])), args.dry_run)
    install_dashboard(browser, args.dry_run)
    offer_ca(args)
    if args.waybar_config and not args.dry_run:
        root = HOME / '.config/eww'
        run([sys.executable, root / 'scripts/dashboard-control.py', '--root', root,
             'waybar', '--config', args.waybar_config])
    print('PenDash dashboard installation finished.')
    return 0


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as exc:
        print('PenDash: ' + str(exc), file=sys.stderr)
        raise SystemExit(4)
