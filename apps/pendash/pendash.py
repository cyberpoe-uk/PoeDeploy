#!/usr/bin/env python3
"""Install and manage PenDash with Chromium and curated BlackArch security tools."""
import argparse
import datetime
import hashlib
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import urllib.request

SOURCE = Path(__file__).resolve().parent
HOME = Path.home()
STATE = Path(os.environ.get('XDG_STATE_HOME', HOME / '.local/state')) / 'pendash'
STAMP = datetime.datetime.now().strftime('%Y%m%d-%H%M%S-%f')
BACKUP = STATE / 'backups' / STAMP
DASHBOARD = ['hyprland', 'jq', 'python', 'kitty', 'btop', 'nvtop',
             'powertop', 'brightnessctl', 'libnotify', 'playerctl', 'pciutils',
             'procps-ng', 'util-linux', 'iproute2', 'coreutils']
CURATED = ['burpsuite', 'ffuf', 'gobuster', 'nmap', 'sqlmap', 'wfuzz',
           'wireshark-qt', 'jwt-tool']
PACMAN_CONFIG = Path('/etc/pacman.conf')
BLACKARCH_MIRRORLIST = Path('/etc/pacman.d/blackarch-mirrorlist')
# Exact versions previously installed by PoeDeploy. Customised files are retained.
LEGACY_BROWSER_FILES = {
    '.local/bin/ctf-chromium': 'ccf8c5c1b359149f36ed7ed2a48a21346161f9ce0647cf62e4933a639df46969',
    '.local/bin/pendash': '7df42aa9fe0f9550e11de5487c70ed49f2f19da50d877b2aee021d85bbca3706',
    '.local/lib/pendash/burp_ca.py': 'ae34f12ca2c569731e2e545ee46ed08d38ef07a4a55ee7ff552709afbd13c1b5',
}
BEGIN, END = '-- BEGIN PENDASH', '-- END PENDASH'


def run(argv, check=True, **kwargs):
    print('+ ' + ' '.join(map(str, argv)), flush=True)
    return subprocess.run([str(x) for x in argv], check=check, **kwargs)


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


def ensure_blackarch(dry_run):
    if BLACKARCH_MIRRORLIST.is_file() and PACMAN_CONFIG.is_file() and re.search(
            r'(?m)^\s*\[blackarch\]\s*(?:#.*)?$', PACMAN_CONFIG.read_text()):
        return
    if dry_run:
        print('Would add the BlackArch repository using its official, checksum-verified strap.sh.')
        return
    with urllib.request.urlopen('https://blackarch.org/downloads.html', timeout=30) as response:
        page = response.read(2 * 1024 * 1024).decode(errors='replace')
    checksum = re.search(r'echo\s+([0-9a-f]{40})\s+strap\.sh', page)
    if not checksum:
        raise RuntimeError('Could not find the strap.sh checksum on the official BlackArch download page.')
    with urllib.request.urlopen('https://blackarch.org/strap.sh', timeout=30) as response:
        script = response.read(2 * 1024 * 1024)
    if hashlib.sha1(script).hexdigest() != checksum.group(1):
        raise RuntimeError('BlackArch strap.sh checksum mismatch. Repository setup was not run.')
    with tempfile.NamedTemporaryFile(prefix='pendash-blackarch-', delete=False) as stream:
        stream.write(script)
        path = Path(stream.name)
    try:
        run(['sudo', 'bash', path])
    finally:
        path.unlink(missing_ok=True)


def cleanup_legacy_browser_setup():
    owned = []
    for relative, digest in LEGACY_BROWSER_FILES.items():
        path = HOME / relative
        if not path.is_symlink() and path.is_file() and hashlib.sha256(path.read_bytes()).hexdigest() == digest:
            owned.append(path)
    # Only retire the old exact flags when the unmodified managed launcher
    # proves they came from our previous setup. Other browser settings stay put.
    if HOME / '.local/bin/ctf-chromium' in owned:
        flags = HOME / '.config/chromium-flags.conf'
        if flags.is_file() and not flags.is_symlink():
            original = flags.read_text()
            legacy = {'--proxy-server=http://127.0.0.1:8080', '--proxy-bypass-list=<-loopback>'}
            kept = [line for line in original.splitlines(keepends=True) if line.strip() not in legacy]
            cleaned = ''.join(kept)
            if cleaned != original:
                write(flags, cleaned, flags.stat().st_mode & 0o777)
    for path in owned:
        backup(path)
        path.unlink()


def installation_checks():
    installed = set(subprocess.check_output(['pacman', '-Qq'], text=True).splitlines())
    missing = sorted(set(CURATED + ['chromium']) - installed)
    for package in missing:
        print('[MISSING] ' + package)
    dashboard_ready = (HOME / '.config/eww/eww.yuck').is_file()
    print('[PASS] Dashboard installed' if dashboard_ready else '[MISSING] PenDash dashboard')
    return dashboard_ready and not missing


def install_packages(packages, dry_run):
    installed = set(subprocess.check_output(['pacman', '-Qq'], text=True).splitlines())
    missing = [p for p in packages if p not in installed]
    if missing:
        argv = ['sudo', 'pacman', '-Syu', '--needed', *missing]
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


def install_dashboard(dry_run, preserve_colors=False):
    destination = HOME / '.config/eww'
    if dry_run:
        print(f'Would back up and install the PenDash dashboard into {destination}.')
        return
    preserved = {}
    for name in ('colors.scss', 'disabled', 'layout.json'):
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
    for name in ('disabled', 'layout.json'):
        if name in preserved:
            (destination / name).write_bytes(preserved[name])
    shutil.copy2(SOURCE.parent / 'shared/dashboard-layout.py', destination / 'scripts/layout.py')
    (destination / 'scripts/layout.py').chmod(0o755)
    if state_copy:
        shutil.copytree(state_copy, destination / 'state', dirs_exist_ok=True)
        shutil.rmtree(state_copy.parent)
    cleanup_legacy_browser_setup()
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
    action.add_argument('--update-dashboard', action='store_true', help='refresh the dashboard and install missing security tools')
    action.add_argument('--disable-dashboard', action='store_true', help='stop dashboard and disable autostart')
    action.add_argument('--enable-dashboard', action='store_true', help='restore dashboard and autostart')
    action.add_argument('--check', action='store_true', help='check the dashboard, Chromium, and security tools')
    action.add_argument('--dry-run', action='store_true')
    parser.add_argument('--waybar-config', type=Path, help='add a toggle to this Waybar config')
    parser.add_argument('--non-interactive', action='store_true')
    parser.add_argument('--skip-packages', action='store_true')
    args = parser.parse_args()
    if os.geteuid() == 0:
        parser.error('Run as the desktop user; the installer requests sudo for repository and package installation.')
    if args.update_dashboard:
        root = HOME / '.config/eww'
        if not (root / 'eww.yuck').is_file():
            raise RuntimeError('Install PenDash before updating it.')
        if not args.skip_packages:
            ensure_blackarch(False)
            install_packages(sorted(set(DASHBOARD + CURATED + ['chromium'])), False)
        install_dashboard(False, preserve_colors=True)
        if args.waybar_config:
            run([sys.executable, root / 'scripts/dashboard-control.py', '--root', root, 'waybar', '--config', args.waybar_config])
        if not (root / 'disabled').exists():
            dashboard_enabled(root, True)
        print('PenDash dashboard updated. Configure Chromium and Burp manually.')
        return 0
    if args.disable_dashboard or args.enable_dashboard:
        dashboard_enabled(HOME / '.config/eww', args.enable_dashboard)
        return 0
    if args.check:
        return 0 if installation_checks() else 2
    if not args.skip_packages:
        ensure_blackarch(args.dry_run)
        install_packages(sorted(set(DASHBOARD + CURATED + ['chromium'])), args.dry_run)
    install_dashboard(args.dry_run)
    if args.waybar_config and not args.dry_run:
        root = HOME / '.config/eww'
        run([sys.executable, root / 'scripts/dashboard-control.py', '--root', root,
             'waybar', '--config', args.waybar_config])
    print('PenDash installation finished. Configure Chromium and Burp manually.')
    return 0


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as exc:
        print('PenDash: ' + str(exc), file=sys.stderr)
        raise SystemExit(4)
