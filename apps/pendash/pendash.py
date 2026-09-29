#!/usr/bin/env python3
"""Install the laptop-specific pentest dashboard and power/offload setup."""
import argparse
import datetime
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.request
from urllib.parse import urlsplit

SOURCE = Path(__file__).resolve().parent
HOME = Path.home()
STATE = Path(os.environ.get('XDG_STATE_HOME', HOME / '.local/state')) / 'pendash'
STAMP = datetime.datetime.now().strftime('%Y%m%d-%H%M%S-%f')
BACKUP = STATE / 'backups' / STAMP
REPORTS = STATE / 'reports'
CURATED = ['ffuf', 'gobuster', 'nmap', 'sqlmap', 'tailscale', 'wfuzz',
           'wireshark-qt', 'jwt-tool']
DESKTOP = ['hyprland', 'hypridle', 'hyprlock', 'jq', 'python', 'kitty', 'btop',
           'nvtop', 'rofi', 'powertop', 'power-profiles-daemon', 'brightnessctl',
           'libnotify', 'mesa-utils', 'nvidia-prime']
DASHBOARD = ['hyprland', 'jq', 'python', 'kitty', 'btop', 'nvtop', 'rofi',
             'powertop', 'brightnessctl', 'libnotify']
BEGIN, END = '-- BEGIN PENDASH', '-- END PENDASH'
KNOWN_BURP_SHA256 = {
    'burpsuite_linux_v2026_8.sh': 'a9b71d5903e4aac00b790a7c5a0c0630fdcbfe1250aafd7bd540a3ad44b89983',
}
# PortSwigger switched to one Professional/Community desktop installer in 2026.4.
BURP_DOWNLOAD_URL = 'https://portswigger.net/burp/releases/download?product=desktop&type=Linux'


def run(argv, check=True, **kwargs):
    print('+ ' + ' '.join(map(str, argv)), flush=True)
    return subprocess.run([str(x) for x in argv], check=check, **kwargs)


def yes(prompt, default=False):
    suffix = ' [Y/n] ' if default else ' [y/N] '
    answer = input(prompt + suffix).strip().lower()
    return default if not answer else answer in ('y', 'yes')


def choose(prompt, values, default):
    while True:
        value = input(f'{prompt} [{default}]: ').strip().lower() or default
        if value in values:
            return value
        print('Choose: ' + ', '.join(values))


def size_text(value):
    for unit in ('B', 'KiB', 'MiB', 'GiB', 'TiB'):
        if value < 1024 or unit == 'TiB':
            return f'{value:.1f} {unit}'
        value /= 1024


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


def install_system(source, target, mode='0644'):
    source, target = Path(source), Path(target)
    same = target.exists() and source.read_bytes() == target.read_bytes()
    if same:
        return
    backup(target)
    run(['sudo', 'install', '-D', '-m', mode, source, target])


def replace_block(old, block):
    clean = re.sub(r'(?ms)^' + re.escape(BEGIN) + r'$.*?^' + re.escape(END) + r'$\n?', '', old)
    return clean.rstrip() + '\n\n' + block.strip() + '\n'


def ensure_blackarch(dry_run):
    if Path('/etc/pacman.d/blackarch-mirrorlist').exists() and '[blackarch]' in Path('/etc/pacman.conf').read_text():
        return
    if dry_run:
        print('Would download the official BlackArch strap.sh, verify its published SHA1, and run it with sudo.')
        return
    page = urllib.request.urlopen('https://blackarch.org/downloads.html', timeout=30).read().decode(errors='replace')
    match = re.search(r'echo\s+([0-9a-f]{40})\s+strap\.sh', page)
    if not match:
        raise RuntimeError('Could not find the current strap.sh checksum on the official BlackArch download page.')
    script = urllib.request.urlopen('https://blackarch.org/strap.sh', timeout=30).read()
    actual = hashlib.sha1(script).hexdigest()
    if actual != match.group(1):
        raise RuntimeError(f'BlackArch strap.sh checksum mismatch: {actual} != {match.group(1)}')
    with tempfile.NamedTemporaryFile(prefix='blackarch-strap-', delete=False) as stream:
        stream.write(script)
        path = Path(stream.name)
    try:
        run(['sudo', 'bash', path])
        run(['sudo', 'pacman', '-Syy'])
    finally:
        path.unlink(missing_ok=True)


_SYNC_RECORDS = None


def sync_records():
    global _SYNC_RECORDS
    if _SYNC_RECORDS is not None:
        return _SYNC_RECORDS
    records = {}
    for database in Path('/var/lib/pacman/sync').glob('*.db'):
        try:
            raw = subprocess.check_output(['bsdtar', '-xOf', database], timeout=20).decode(errors='replace')
            for description in re.split(r'(?=^%FILENAME%$)', raw, flags=re.M):
                fields = {}
                for block in description.strip().split('\n\n'):
                    lines = block.splitlines()
                    if lines and lines[0].startswith('%'):
                        fields[lines[0].strip('%')] = lines[1:]
                if fields.get('NAME'):
                    records[fields['NAME'][0]] = fields
        except (OSError, subprocess.SubprocessError, ValueError):
            pass
    _SYNC_RECORDS = records
    return records


def group_packages(groups):
    groups = set(groups)
    return sorted(name for name, fields in sync_records().items()
                  if groups.intersection(fields.get('GROUPS', [])))


def package_sizes(packages):
    wanted = set(packages)
    compressed = installed = 0
    found = set()
    for name, fields in sync_records().items():
        if name in wanted:
            found.add(name)
            compressed += int(fields.get('CSIZE', ['0'])[0])
            installed += int(fields.get('ISIZE', ['0'])[0])
    return len(found), compressed, installed


def package_plan(args, browser):
    mode = args.tool_mode
    if not mode and not args.non_interactive:
        print('\nTool choices: curated = current daily tools; categories = selected BlackArch groups; all = every tool.')
        mode = choose('Tool installation', ('curated', 'categories', 'all'), 'curated')
    mode = mode or 'curated'
    ensure_blackarch(args.dry_run)
    if args.dry_run and not Path('/etc/pacman.d/blackarch-mirrorlist').exists():
        print('Would resolve and preview packages after repository setup.')
        return []
    if mode == 'curated':
        packages = sorted(set(DESKTOP + CURATED + [browser]))
    elif mode == 'categories':
        groups = sorted({group for fields in sync_records().values() for group in fields.get('GROUPS', [])
                         if group.startswith('blackarch-')})
        if args.categories:
            selected = [x.strip() for x in args.categories.split(',') if x.strip()]
        else:
            print('\nAvailable BlackArch categories:\n  ' + '\n  '.join(groups))
            selected = [x.strip() for x in input('Category names, comma separated: ').split(',') if x.strip()]
        invalid = [x for x in selected if x not in groups]
        if invalid:
            raise ValueError('Unknown BlackArch categories: ' + ', '.join(invalid))
        packages = sorted(set(DESKTOP + [browser] + group_packages(selected)))
    else:
        packages = sorted(set(DESKTOP + [browser] + group_packages(['blackarch'])))
    # Burp is always supplied by PortSwigger's native installer, even when a
    # selected BlackArch group also contains a package named burpsuite.
    packages = [package for package in packages if package != 'burpsuite']
    count, download, disk = package_sizes(packages)
    print(f'Package plan: {len(packages)} packages; repository metadata found for {count}.')
    print(f'Estimated download: {size_text(download)}; installed files: {size_text(disk)}.')
    if mode == 'all':
        print('WARNING: This installs the complete BlackArch collection. It can introduce conflicts and require substantial maintenance.')
        allowed = args.yes_all_tools or (not args.non_interactive and yes('Install every BlackArch tool?', False))
        if not allowed:
            raise RuntimeError('Complete BlackArch installation was not confirmed.')
    return packages


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


def find_burp_installer(explicit=None):
    if explicit:
        path = Path(explicit).expanduser().resolve()
        if not path.is_file():
            raise RuntimeError(f'Burp installer does not exist: {path}')
        return path
    patterns = ('burpsuite_linux_v*.sh', 'burpsuite_community_linux_v*.sh')
    matches = [path for pattern in patterns for path in (HOME / 'Downloads').glob(pattern)]
    return max(matches, key=lambda path: path.stat().st_mtime) if matches else None


def download_burp_installer():
    cache = STATE / 'downloads'
    cache.mkdir(parents=True, exist_ok=True)
    request = urllib.request.Request(BURP_DOWNLOAD_URL, headers={'User-Agent': 'PenDash installer'})
    print('Downloading the latest native Linux installer from PortSwigger…', flush=True)
    with urllib.request.urlopen(request, timeout=60) as response:
        disposition = response.headers.get('Content-Disposition', '')
        match = re.search(r'filename\*?=(?:UTF-8\'\')?["\']?([^"\';]+)', disposition, re.I)
        name = Path(match.group(1)).name if match else Path(urlsplit(response.geturl()).path).name
        if not re.fullmatch(r'burpsuite_(?:community_)?linux_v\d{4}(?:_\d+)+\.sh', name):
            raise RuntimeError('PortSwigger returned an unexpected installer filename: ' + (name or '<empty>'))
        final = cache / name
        temporary = cache / ('.' + name + '.part')
        total = 0
        with temporary.open('wb') as output:
            while True:
                chunk = response.read(1024 * 1024)
                if not chunk:
                    break
                total += len(chunk)
                if total > 1024 * 1024 * 1024:
                    raise RuntimeError('Burp installer exceeded the 1 GiB download safety limit.')
                output.write(chunk)
        if total < 50 * 1024 * 1024:
            temporary.unlink(missing_ok=True)
            raise RuntimeError('PortSwigger download is unexpectedly small; refusing to execute it.')
        temporary.replace(final)
    return final


def burp_installer_checksum(path):
    """Verify known releases locally; discover future checksums on PortSwigger's release page."""
    expected = KNOWN_BURP_SHA256.get(path.name)
    if not expected:
        match = re.fullmatch(r'burpsuite_(?:community_)?linux_v(\d{4}(?:_\d+)+)\.sh', path.name)
        if not match:
            raise RuntimeError('Unexpected Burp installer filename; use PortSwigger\'s native Linux installer.')
        version = match.group(1).replace('_', '-')
        url = 'https://portswigger.net/burp/releases/professional-community-' + version
        page = urllib.request.urlopen(url, timeout=30).read().decode(errors='replace')
        position = page.find(path.name)
        nearby = page[position:position + 3000] if position >= 0 else ''
        found = re.search(r'(?i)(?:SHA-?256|sha256)[^0-9a-f]{0,200}([0-9a-f]{64})', nearby)
        if not found:
            raise RuntimeError('Could not obtain this installer\'s SHA-256 from PortSwigger\'s release page.')
        expected = found.group(1).lower()
    digest_hash = hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            digest_hash.update(chunk)
    digest = digest_hash.hexdigest()
    if digest != expected:
        raise RuntimeError(f'Burp installer checksum mismatch: {digest} != {expected}')
    return digest


def install_burp(args):
    current = burp_executable()
    if current and not args.reinstall_burp:
        print(f'Burp Suite already installed from a native installer: {current}')
        return
    installer = find_burp_installer(args.burp_installer)
    if not installer:
        if args.dry_run:
            print(f'Would download the latest native Linux installer from {BURP_DOWNLOAD_URL}')
            print('Would verify its SHA-256 against PortSwigger release data before execution.')
            return
        installer = download_burp_installer()
    if args.dry_run:
        print(f'Would verify and run PortSwigger installer interactively: {installer}')
        print('Select Community Edition when the unified installer asks for an edition.')
        return
    digest = burp_installer_checksum(installer)
    print(f'Verified PortSwigger installer SHA-256: {digest}')
    installer.chmod(installer.stat().st_mode | 0o100)
    print('Select Community Edition in the PortSwigger installer window.', flush=True)
    run([installer])
    if not burp_executable():
        raise RuntimeError('The PortSwigger installer closed without creating a recognized Burp executable.')


def install_dashboard(browser, dry_run, preserve_colors=False):
    destination = HOME / '.config/eww'
    if dry_run:
        print(f'Would back up and install the laptop-specific dashboard into {destination}.')
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
    (destination / 'state' / (browser + '-ctf')).mkdir(parents=True, exist_ok=True, mode=0o700)
    user_env = dict(os.environ, HOME=str(HOME))
    run([sys.executable, destination / 'scripts/dashboard-control.py', '--root', destination, 'prepare'], env=user_env)
    run([sys.executable, destination / 'scripts/dashboard-control.py', '--root', destination, 'quickshell'], env=user_env)
    custom = HOME / '.config/hypr/custom.lua'
    old = custom.read_text() if custom.exists() else ''
    if BEGIN not in old and '-- Home dashboard:' in old and 'local function protect_home' in old:
        old = ''  # Migrate the known pre-PenDash version of this managed dashboard file.
    write(custom, replace_block(old, (SOURCE / 'assets/custom.lua').read_text()))


def install_power(dry_run):
    expected = {
        '0000:07:00.0': ('0x10ec', '0x8168'),
        '0000:00:17.0': ('0x8086', '0xa353'),
    }
    for pci, (vendor, device) in expected.items():
        root = Path('/sys/bus/pci/devices') / pci
        if (root / 'vendor').read_text().strip() != vendor or (root / 'device').read_text().strip() != device:
            raise RuntimeError(f'Expected Legion device {pci} {vendor}:{device} not found; refusing hardware-specific PM rules.')
    if dry_run:
        print('Would install AC/battery idle policy, event-driven power profile switching, and Legion Ethernet/SATA runtime PM.')
        return
    install_system(SOURCE / 'assets/81-legion-idle-device-pm.rules', '/etc/udev/rules.d/81-legion-idle-device-pm.rules')
    write(HOME / '.config/hypr/hypridle.conf', (SOURCE / 'assets/hypridle.conf').read_text())
    write(HOME / '.local/bin/pendash-idle-action', (SOURCE / 'assets/pendash-idle-action').read_text(), 0o755)
    write(HOME / '.local/bin/pendash-power-watch.py', (SOURCE / 'assets/pendash-power-watch.py').read_text(), 0o755)
    write(HOME / '.config/systemd/user/pendash-power-watch.service',
          (SOURCE / 'assets/pendash-power-watch.service').read_text())
    run(['sudo', 'udevadm', 'control', '--reload-rules'])
    run(['sudo', 'udevadm', 'trigger', '--subsystem-match=pci', '--action=add'])
    run(['systemctl', '--user', 'daemon-reload'])
    # PenDash owns charger switching. Retire the older visual-profile watcher so
    # plugging/unplugging does not also change blur, shadows, or transparency.
    legacy_watcher = HOME / '.config/systemd/user/hyprmod-power-watch.service'
    if legacy_watcher.exists():
        run(['systemctl', '--user', 'disable', '--now', 'hyprmod-power-watch.service'], check=False)
    run(['systemctl', '--user', 'enable', '--now', 'pendash-power-watch.service'])


def local_checks(browser):
    checks = []
    def check(label, value):
        checks.append((label, bool(value)))
        print(('PASS ' if value else 'FAIL ') + label)
    check('system battery detected', any((p / 'type').read_text().strip() == 'Battery'
          for p in Path('/sys/class/power_supply').iterdir() if (p / 'type').is_file()))
    check('dashboard installed', (HOME / '.config/eww/eww.yuck').exists())
    check('PortSwigger Burp executable', burp_executable())
    check('isolated browser profile', (HOME / f'.config/eww/state/{browser}-ctf').is_dir())
    idle = HOME / '.config/hypr/hypridle.conf'
    idle_text = idle.read_text() if idle.exists() else ''
    check('idle timing: lock 5m, battery display 10m, final action 60m',
          all(x in idle_text for x in ('timeout = 300', 'timeout = 600', 'timeout = 3600')))
    check('Legion runtime PM rule', Path('/etc/udev/rules.d/81-legion-idle-device-pm.rules').exists())
    check('power profile watcher enabled', subprocess.run(['systemctl', '--user', 'is-enabled',
          'pendash-power-watch.service'], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode == 0)
    for pci in ('0000:07:00.0', '0000:00:17.0'):
        path = Path('/sys/bus/pci/devices') / pci / 'power/control'
        check(pci + ' runtime PM auto', path.is_file() and path.read_text().strip() == 'auto')
    return all(value for _, value in checks)


def nvidia(args, mode):
    command = [sys.executable, SOURCE / 'components/nvidia-offload-setup.py', mode,
               '--attempts', str(args.retry), '--wait', str(args.wait)]
    if mode == '--apply':
        command.append('--install-missing')
    return run(command, check=False).returncode


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
    action.add_argument('--update-dashboard', action='store_true', help='refresh dashboard without package, browser, power or NVIDIA setup')
    action.add_argument('--disable-dashboard', action='store_true', help='stop dashboard and disable autostart')
    action.add_argument('--enable-dashboard', action='store_true', help='restore dashboard and autostart')
    action.add_argument('--check', action='store_true')
    action.add_argument('--dry-run', action='store_true')
    parser.add_argument('--waybar-config', type=Path, help='add a toggle to this Waybar config')
    parser.add_argument('--retry', type=int, default=3, metavar='N')
    parser.add_argument('--wait', type=int, default=60)
    parser.add_argument('--browser', choices=('firefox', 'chromium'))
    parser.add_argument('--tool-mode', choices=('curated', 'categories', 'all'))
    parser.add_argument('--categories')
    parser.add_argument('--yes-all-tools', action='store_true')
    parser.add_argument('--non-interactive', action='store_true')
    parser.add_argument('--dashboard-only', action='store_true',
                        help='install only the dashboard and its packages, without BlackArch, Burp, NVIDIA or laptop power setup')
    parser.add_argument('--skip-packages', action='store_true')
    parser.add_argument('--skip-nvidia', action='store_true')
    parser.add_argument('--skip-burp', action='store_true')
    parser.add_argument('--reinstall-burp', action='store_true')
    parser.add_argument('--burp-installer', help='path to PortSwigger Linux installer (default: newest in ~/Downloads)')
    args = parser.parse_args()
    if os.geteuid() == 0:
        parser.error('Run as the desktop user; the installer requests sudo for system files.')
    if args.update_dashboard:
        root = HOME / '.config/eww'
        browser_config = root / 'browser.json'
        if not (root / 'eww.yuck').is_file():
            raise RuntimeError('Install PenDash before updating it.')
        browser = json.loads(browser_config.read_text())['browser'] if browser_config.exists() else 'firefox'
        if browser not in ('firefox', 'chromium'):
            raise ValueError('Invalid installed browser setting.')
        install_dashboard(browser, False, preserve_colors=True)
        if args.waybar_config:
            run([sys.executable, root / 'scripts/dashboard-control.py', '--root', root, 'waybar', '--config', args.waybar_config])
        if not (root / 'disabled').exists():
            dashboard_enabled(root, True)
        print('Dashboard updated; package, power and NVIDIA settings were retained.')
        return 0
    if args.disable_dashboard or args.enable_dashboard:
        dashboard_enabled(HOME / '.config/eww', args.enable_dashboard)
        return 0
    if not 1 <= args.retry <= 10 or not 10 <= args.wait <= 300:
        parser.error('--retry must be 1–10 and --wait must be 10–300')
    browser = args.browser
    if not browser and not args.non_interactive and not args.check:
        browser = choose('Isolated pentest browser', ('firefox', 'chromium'), 'firefox')
    browser = browser or 'firefox'
    if args.check:
        try:
            browser = json.loads((HOME / '.config/eww/browser.json').read_text())['browser']
        except (OSError, ValueError, KeyError):
            pass
        local_ok = local_checks(browser)
        gpu = 0 if args.skip_nvidia else nvidia(args, '--retry')
        return 0 if local_ok and gpu == 0 else 2
    if args.dashboard_only:
        if not args.skip_packages:
            install_packages(sorted(set(DASHBOARD + [browser])), args.dry_run)
        install_dashboard(browser, args.dry_run)
        if args.waybar_config and not args.dry_run:
            root = HOME / '.config/eww'
            run([sys.executable, root / 'scripts/dashboard-control.py', '--root', root,
                 'waybar', '--config', args.waybar_config])
        print('PenDash dashboard-only installation finished. BlackArch, Burp, NVIDIA and laptop power setup were skipped.')
        return 0
    if not args.skip_packages:
        packages = package_plan(args, browser)
        install_packages(packages, args.dry_run)
    if not args.skip_burp:
        install_burp(args)
    install_dashboard(browser, args.dry_run)
    if args.waybar_config and not args.dry_run:
        root = HOME / '.config/eww'
        run([sys.executable, root / 'scripts/dashboard-control.py', '--root', root, 'waybar', '--config', args.waybar_config])
    install_power(args.dry_run)
    if args.dry_run:
        print('Would apply NVIDIA offload/RTD3 setup, then verify only if the loaded driver already uses the configured parameters.')
        return 0
    gpu = 0 if args.skip_nvidia else nvidia(args, '--apply')
    local_ok = local_checks(browser)
    REPORTS.mkdir(parents=True, exist_ok=True)
    report = REPORTS / f'{STAMP}.json'
    report.write_text(json.dumps({'browser': browser, 'local_checks': local_ok,
                                  'nvidia_exit': gpu, 'backup': str(BACKUP)}, indent=2) + '\n')
    print(f'Report: {report}')
    if gpu == 3:
        print('NVIDIA settings are configured; reboot is required before post-boot verification. Rerun: ./install.sh --check --retry 3')
    return 0 if local_ok and gpu == 0 else gpu or 2


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as exc:
        print('PenDash: ' + str(exc), file=sys.stderr)
        raise SystemExit(4)
