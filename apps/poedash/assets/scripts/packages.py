#!/usr/bin/env python3
"""Rofi package browser. Browsing is unprivileged; transactions run in a terminal."""
import argparse
import configparser
import ctypes
import ctypes.util
import fcntl
import gzip
import io
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
import urllib.parse
import urllib.request

CACHE = Path(os.environ.get('XDG_CACHE_HOME', Path.home() / '.cache')) / 'poedash/packages'
NAME = re.compile(r'[A-Za-z0-9@_+][A-Za-z0-9@._+\-]*\Z')
AUR = 'https://aur.archlinux.org'


def run(argv, timeout=15, codes=(0,)):
    result = subprocess.run(argv, capture_output=True, text=True, timeout=timeout,
                            env=dict(os.environ, LC_ALL='C'))
    if result.returncode not in codes:
        raise RuntimeError(result.stderr.strip() or f'{argv[0]} exited {result.returncode}')
    return result.stdout


def notify(message):
    if shutil.which('notify-send'):
        subprocess.run(['notify-send', 'PoeDash packages', message], check=False, timeout=5)


def atomic_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(dir=path.parent, prefix='.packages-')
    try:
        with os.fdopen(fd, 'w') as stream:
            json.dump(value, stream)
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)


def json_cache(path, ttl):
    try:
        if time.time() - path.stat().st_mtime < ttl:
            return json.loads(path.read_text())
    except (OSError, ValueError):
        pass
    return None


def fetch(url, limit=20 * 1024 * 1024):
    request = urllib.request.Request(url, headers={'User-Agent': 'PoeDash package browser'})
    with urllib.request.urlopen(request, timeout=15) as response:
        data = response.read(limit + 1)
    if len(data) > limit:
        raise RuntimeError('AUR response exceeds size limit')
    return data


def aur_names(cache=CACHE):
    path = cache / 'aur-names.json'
    names = json_cache(path, 24 * 3600)
    if isinstance(names, list) and names and all(isinstance(n, str) and NAME.fullmatch(n) for n in names):
        return names, ''
    try:
        # One cached index enables alphabetic suggestions even for a single letter.
        compressed = fetch(AUR + '/packages.gz')
        with gzip.GzipFile(fileobj=io.BytesIO(compressed)) as archive:
            raw = archive.read(16 * 1024 * 1024 + 1)
        if len(raw) > 16 * 1024 * 1024:
            raise RuntimeError('AUR package index exceeds size limit')
        names = sorted({line for line in raw.decode().splitlines() if NAME.fullmatch(line)}, key=str.casefold)
        if not names:
            raise RuntimeError('AUR returned no package names')
        atomic_json(path, names)
        return names, ''
    except (OSError, ValueError, RuntimeError, EOFError) as exc:
        # Stale data remains useful offline, but is explicitly labeled.
        try:
            stale = json.loads(path.read_text())
            if isinstance(stale, list) and stale and all(isinstance(n, str) and NAME.fullmatch(n) for n in stale):
                return stale, 'AUR offline: cached names'
        except (OSError, ValueError):
            pass
        return [], f'AUR unavailable: {exc}'


def aur_info(names):
    results = {}
    for offset in range(0, len(names), 100):
        query = urllib.parse.urlencode([('arg[]', n) for n in names[offset:offset + 100]])
        data = json.loads(fetch(AUR + '/rpc/v5/info?' + query).decode())
        if not isinstance(data, dict) or data.get('type') == 'error' or not isinstance(data.get('results'), list):
            raise RuntimeError('AUR metadata lookup failed')
        for item in data['results']:
            if not isinstance(item, dict):
                continue
            name, version = item.get('Name'), item.get('Version')
            if isinstance(name, str) and NAME.fullmatch(name) and isinstance(version, str):
                results[name] = version
    return results


_LIB = None


def compare(available, installed):
    global _LIB
    if _LIB is None:
        library = ctypes.util.find_library('alpm')
        if not library:
            raise RuntimeError('libalpm is unavailable; version comparison cannot be performed')
        _LIB = ctypes.CDLL(library)
        _LIB.alpm_pkg_vercmp.argtypes = [ctypes.c_char_p, ctypes.c_char_p]
        _LIB.alpm_pkg_vercmp.restype = ctypes.c_int
    return _LIB.alpm_pkg_vercmp(available.encode(), installed.encode())


def installed_packages():
    return dict(line.split(None, 1) for line in run(['pacman', '-Q']).splitlines() if len(line.split(None, 1)) == 2)


def repository_packages():
    packages = {}
    for line in run(['pacman', '-Sl']).splitlines():
        fields = line.split()
        if len(fields) >= 3 and all(NAME.fullmatch(x) for x in fields[:2]):
            repository, name, version = fields[:3]
            # pacman configuration order determines repository priority.
            packages.setdefault(name, dict(name=name, source=repository, version=version, aur=False))
    return packages


def icons():
    # Desktop-entry aliases provide real icons when installed/theme metadata exists.
    result = {}
    roots = [Path(os.environ.get('XDG_DATA_HOME', Path.home() / '.local/share'))]
    roots += [Path(p) for p in os.environ.get('XDG_DATA_DIRS', '/usr/local/share:/usr/share').split(':') if p]
    for root in reversed(roots):
        for path in (root / 'applications').glob('*.desktop'):
            parser = configparser.ConfigParser(interpolation=None, strict=False)
            try:
                parser.read(path)
                item = parser['Desktop Entry']
                icon = item.get('Icon')
                if not icon or item.getboolean('Hidden', False):
                    continue
                aliases = [path.stem, path.stem.rsplit('.', 1)[-1].lower(), item.get('StartupWMClass', '').lower()]
                argv = shlex.split(item.get('Exec', ''))
                if argv and Path(argv[0]).name not in ('env', 'flatpak', 'sh', 'bash'):
                    aliases.append(Path(argv[0]).name)
                for alias in aliases:
                    if NAME.fullmatch(alias):
                        result[alias.casefold()] = icon
            except (OSError, ValueError, KeyError, configparser.Error):
                continue
    return result


def status(package, installed):
    old = installed.get(package['name'])
    if old is None:
        return 'Not installed'
    version = package.get('version')
    if not version:
        return f'Installed {old} · update status unknown'
    difference = compare(version, old)
    if difference > 0:
        return f'Update available {old} → {version}'
    return f'Installed {old} · ' + ('newer local version' if difference < 0 else 'up to date')


def clean(value):
    return ''.join(c if c >= ' ' else ' ' for c in str(value))


def row(package, installed, icon_map):
    return (clean(f"{package['name']}  [{package['source']}]  {status(package, installed)}")
            + '\0icon\x1f' + clean(icon_map.get(package['name'].casefold(), 'package-x-generic')))


def choose(rows, prompt, message=''):
    argv = ['rofi', '-dmenu', '-i', '-no-custom', '-no-sort', '-matching', 'normal',
            '-show-icons', '-format', 'i', '-p', prompt, '-mesg', clean(message)]
    # Inherit the same theme, dimensions, font, wallpaper and colors as drun.
    config = Path(os.environ.get('XDG_CONFIG_HOME', Path.home() / '.config')) / 'rofi/config.rasi'
    if config.is_file():
        argv += ['-config', str(config)]
    result = subprocess.run(argv, input='\n'.join(rows) + '\n', capture_output=True, text=True)
    if result.returncode != 0:
        return None
    try:
        index = int(result.stdout.strip())
        return index if 0 <= index < len(rows) else None
    except ValueError:
        return None



def repository_updates(cache=CACHE):
    path = cache / 'repo-updates.json'
    saved = json_cache(path, 300)
    if isinstance(saved, dict) and all(NAME.fullmatch(k) and isinstance(v, str) for k, v in saved.items()):
        return saved, 'Repository update status checked within five minutes.'
    if shutil.which('checkupdates'):
        try:
            updates = {}
            # checkupdates uses a separate temporary database, never pacman -Sy.
            for line in run(['checkupdates'], timeout=30, codes=(0, 2)).splitlines():
                fields = line.split()
                if len(fields) == 4 and NAME.fullmatch(fields[0]) and fields[2] == '->':
                    updates[fields[0]] = fields[3]
            atomic_json(path, updates)
            return updates, 'Repository update status freshly checked.'
        except (OSError, RuntimeError, subprocess.SubprocessError):
            pass
    return {}, 'Fresh repository check unavailable. Versions use local pacman databases.'


def catalog(source, cache=CACHE):
    installed = installed_packages()
    packages = repository_packages() if source != 'aur' else {}
    notes = []
    if source != 'aur':
        updates, update_note = repository_updates(cache)
        notes.append(update_note)
        for name, version in updates.items():
            if name in packages:
                packages[name]['version'] = version
    if source != 'repo':
        names, note = aur_names(cache)
        if note:
            notes.append(note)
        wanted = sorted((set(installed) & set(names)) - set(packages))
        versions = {}
        if wanted:
            try:
                versions = aur_info(wanted)
            except (OSError, ValueError, RuntimeError):
                notes.append('AUR update status unavailable. Checked again on selection.')
        for name in names:
            packages.setdefault(name, dict(name=name, source='AUR', version=versions.get(name), aur=True))
    return sorted(packages.values(), key=lambda item: (item['name'].casefold(), item['source'])), installed, ' '.join(notes)


def transaction_command(source, target, upgrade=False):
    if source not in ('repo', 'aur'):
        raise ValueError('Invalid package source')
    parts = target.split('/')
    if (len(parts) != (2 if source == 'repo' else 1)
            or not all(NAME.fullmatch(part) for part in parts)):
        raise ValueError('Invalid package target')
    if source == 'aur':
        if not shutil.which('yay'):
            raise RuntimeError('yay is not installed. Install it through PoeDeploy first.')
        return ['yay', '-Syu' if upgrade else '-S', '--needed', '--', target]
    return ['sudo', 'pacman', '-Syu' if upgrade else '-S', '--needed', '--', target]


def transaction(source, target, upgrade=False):
    if os.geteuid() == 0:
        raise RuntimeError('Run PoeDash packages as your desktop user, never as root')
    argv = transaction_command(source, target, upgrade)
    # Revalidate availability, letting the real package manager resolve changes.
    print('This installs/updates the selected package together with a full system upgrade.' if upgrade
          else 'This installs/updates only the selected package and its required dependencies, using existing repository databases.')
    print('AUR builds, dependencies and package-manager confirmations remain interactive.')
    print('\nCommand: ' + shlex.join(argv))
    if input('\nContinue? [y/N]: ').strip().lower() != 'y':
        return
    result = subprocess.run(argv, check=False)
    print('\nCompleted.' if result.returncode == 0 else f'Package manager exited {result.returncode}.')
    input('Press Enter to close. ')


def open_browser():
    for binary in ('rofi', 'pacman', 'kitty'):
        if not shutil.which(binary):
            raise RuntimeError(f'{binary} is required. Run poedash doctor.')
    CACHE.mkdir(parents=True, exist_ok=True)
    with (CACHE / 'browser.lock').open('w') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return
        source = choose(['Both · repositories + AUR', 'Repositories · pacman', 'AUR · yay'],
                        'Package source', 'Search alphabetically. No changes until you confirm an action.')
        if source is None:
            return
        notify('Loading package names and installed versions…')
        packages, installed, note = catalog(('both', 'repo', 'aur')[source])
        if not packages:
            raise RuntimeError(note or 'No package databases are available')
        icon_map = icons()
        while True:
            index = choose([row(p, installed, icon_map) for p in packages], 'Packages', note)
            if index is None:
                return
            package = packages[index]
            if package['aur']:
                try:
                    package['version'] = aur_info([package['name']]).get(package['name'])
                except (OSError, ValueError, RuntimeError) as exc:
                    notify(f'AUR metadata unavailable: {exc}')
                    continue
                if not package['version']:
                    notify('This package is no longer available in the AUR.')
                    continue
            information = status(package, installed)
            old = installed.get(package['name'])
            if old is not None and compare(package['version'], old) <= 0:
                choose(['Back to package search'], package['name'], information)
                continue
            target = package['name'] if package['aur'] else package['source'] + '/' + package['name']
            kind = 'aur' if package['aur'] else 'repo'
            action = 'Update' if old else 'Install'
            confirmation = choose([action, action + ' and upgrade', 'Cancel'], package['name'],
                                  information + ' · First option: selected package only. Second option: full system upgrade.')
            if confirmation not in (0, 1):
                continue
            upgrade = confirmation == 1
            transaction_command(kind, target, upgrade)  # Check helper availability before opening a terminal.
            subprocess.Popen(['kitty', '--title', 'PoeDash package transaction', sys.executable,
                              str(Path(__file__).resolve()), 'transaction', kind, target] + (['--upgrade'] if upgrade else []),
                             start_new_session=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            return


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('launch', 'open', 'transaction'))
    parser.add_argument('source', nargs='?', choices=('repo', 'aur'))
    parser.add_argument('target', nargs='?')
    parser.add_argument('--upgrade', action='store_true', help='include a full system upgrade in a transaction')
    args = parser.parse_args()
    if os.geteuid() == 0:
        raise RuntimeError('Run PoeDash packages as your desktop user, never as root')
    if args.action == 'launch':
        subprocess.Popen([sys.executable, str(Path(__file__).resolve()), 'open'], start_new_session=True,
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    elif args.action == 'open':
        open_browser()
    elif not args.source or not args.target:
        parser.error('transaction requires source and target')
    else:
        transaction(args.source, args.target, args.upgrade)


if __name__ == '__main__':
    try:
        main()
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as exc:
        notify(str(exc))
        print('PoeDash packages: ' + str(exc), file=sys.stderr)
        raise SystemExit(1)
