#!/usr/bin/env python3
"""Rofi package browser. Browsing is unprivileged; transactions run in a terminal."""
import argparse
import configparser
from concurrent.futures import ThreadPoolExecutor
import ctypes
import ctypes.util
import fcntl
import gzip
import html
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
import textwrap
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET

CACHE = Path(os.environ.get('XDG_CACHE_HOME', Path.home() / '.cache')) / 'poedash/packages'
NAME = re.compile(r'[A-Za-z0-9@_+][A-Za-z0-9@._+\-]*\Z')
AUR = 'https://aur.archlinux.org'


def run(argv, timeout=15, codes=(0,), extra_env=None):
    result = subprocess.run(argv, capture_output=True, text=True, timeout=timeout,
                            env=dict(os.environ, LC_ALL='C', **(extra_env or {})))
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


def aur_names(cache=CACHE, refresh=False):
    path = cache / 'aur-names.json'
    names = None if refresh else json_cache(path, 24 * 3600)
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


def aur_details(names):
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
                results[name] = dict(version=version, description=item.get('Description') or '')
    return results


def aur_info(names):
    return {name: data['version'] for name, data in aur_details(names).items()}


def metadata_records(compressed):
    """Read the official JSON array incrementally instead of retaining every field."""
    with io.TextIOWrapper(gzip.GzipFile(fileobj=io.BytesIO(compressed)), encoding='utf-8') as stream:
        decoder, buffer, total = json.JSONDecoder(), '', 0
        started = False
        while True:
            chunk = stream.read(65536)
            total += len(chunk)
            if total > 128 * 1024 * 1024:
                raise ValueError('AUR metadata exceeds size limit')
            buffer += chunk
            if not started:
                buffer = buffer.lstrip()
                if not buffer:
                    if not chunk: raise ValueError('Empty AUR metadata')
                    continue
                if not buffer.startswith('['): raise ValueError('AUR metadata is not an array')
                buffer, started = buffer[1:], True
            while True:
                buffer = buffer.lstrip(' \t\r\n,')
                if buffer.startswith(']'):
                    return
                try:
                    item, end = decoder.raw_decode(buffer)
                except json.JSONDecodeError:
                    break
                buffer = buffer[end:]
                if isinstance(item, dict):
                    yield item
            if not chunk:
                raise ValueError('Incomplete AUR metadata')


def aur_descriptions(cache=CACHE):
    path = cache / 'aur-descriptions.json'
    saved = json_cache(path, 3600)
    if isinstance(saved, dict):
        return saved
    try:
        values = {item['Name']: item.get('Description') or ''
                  for item in metadata_records(fetch(AUR + '/packages-meta-v1.json.gz'))
                  if isinstance(item.get('Name'), str) and NAME.fullmatch(item['Name'])
                  and isinstance(item.get('Description', ''), (str, type(None)))}
        atomic_json(path, values)
        return values
    except (OSError, ValueError, RuntimeError, EOFError):
        try:
            saved = json.loads(path.read_text())
            return saved if isinstance(saved, dict) else {}
        except (OSError, ValueError):
            return {}


def repository_descriptions(database):
    """Read only cached pacman archive members, never extract files."""
    import tarfile
    root = database or Path('/var/lib/pacman')
    result = {}
    for archive in (root / 'sync').glob('*.db'):
        try:
            with tarfile.open(archive, 'r:*') as tar:
                for member in tar:
                    if not member.isfile() or not member.name.endswith('/desc') or member.size > 1024 * 1024:
                        continue
                    stream = tar.extractfile(member)
                    if stream is None: continue
                    with stream:
                        text = stream.read().decode(errors='replace')
                    fields = dict(re.findall(r'^%([^%]+)%\n([^\n]*)', text, re.M))
                    if fields.get('NAME'):
                        result[(archive.stem, fields['NAME'])] = fields.get('DESC', '')
        except (OSError, tarfile.TarError):
            continue
    return result


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


def repository_packages(database=None, all_repositories=False):
    packages = {}
    argv = ['pacman'] + (['--dbpath', str(database)] if database else []) + ['-Sl']
    for line in run(argv).splitlines():
        fields = line.split()
        if len(fields) >= 3 and all(NAME.fullmatch(x) for x in fields[:2]):
            repository, name, version = fields[:3]
            # pacman configuration order determines repository priority.
            key = (repository, name) if all_repositories else name
            packages.setdefault(key, dict(name=name, source=repository, version=version, aur=False))
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
    # AppStream metadata can supply icons even without an installed desktop entry.
    cached_icons = {}
    icon_roots = [Path('/var/cache/swcatalog/icons')] + [root / 'swcatalog/icons' for root in roots]
    for directory in icon_roots:
        for path in directory.rglob('*'):
            if path.suffix in ('.png', '.svg', '.xpm') and path.is_file():
                cached_icons.setdefault(path.name, str(path))
    metadata = [Path('/var/cache/swcatalog/xml')]
    metadata += [root / suffix for root in roots for suffix in ('metainfo', 'appdata', 'swcatalog/xml')]
    for directory in metadata:
        for path in list(directory.glob('*.xml')) + list(directory.glob('*.xml.gz')):
            try:
                opener = gzip.open if path.suffix == '.gz' else open
                with opener(path, 'rb') as stream:
                    content = stream.read(32 * 1024 * 1024 + 1)
                if len(content) > 32 * 1024 * 1024:
                    continue
                tree = ET.fromstring(content)
                components = [tree] if tree.tag == 'component' else tree.findall('component')
                for component in components:
                    names = [element.text for element in component.findall('pkgname') if element.text]
                    icon = next((element.text for element in component.findall('icon')
                                 if element.text and element.get('type') in ('stock', 'local')), None)
                    if icon is None:
                        icon = next((cached_icons.get(Path(element.text).name)
                                     for element in component.findall('icon')
                                     if element.text and element.get('type') == 'cached'
                                     and Path(element.text).name in cached_icons), None)
                    if icon and (not icon.startswith('/') or Path(icon).is_file()):
                        for name in names:
                            if NAME.fullmatch(name):
                                result.setdefault(name.casefold(), icon)
            except (OSError, ValueError, EOFError, ET.ParseError):
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
    return (html.escape(clean(package['name'])) + '&#10;<span size="small">'
            + html.escape(clean(package['source'] + ' · ' + status(package, installed))) + '</span>'
            + ('&#10;<span size="small">' + html.escape(textwrap.shorten(clean(package['description']), width=100, placeholder='…')) + '</span>'
               if package.get('description') else '')
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



def repository_updates(cache=CACHE, refresh=False):
    path = cache / 'repo-updates.json'
    saved = None if refresh else json_cache(path, 300)
    if isinstance(saved, dict) and all(NAME.fullmatch(k) and isinstance(v, str) for k, v in saved.items()):
        return saved, 'Repository update status checked within five minutes.'
    if shutil.which('checkupdates'):
        try:
            updates = {}
            # checkupdates uses a separate temporary database, never pacman -Sy.
            for line in run(['checkupdates'], timeout=30, codes=(0, 2),
                            extra_env={'CHECKUPDATES_DB': str(cache / 'repo-db')}).splitlines():
                fields = line.split()
                if len(fields) == 4 and NAME.fullmatch(fields[0]) and fields[2] == '->':
                    updates[fields[0]] = fields[3]
            atomic_json(path, updates)
            return updates, 'Repository update status freshly checked.'
        except (OSError, RuntimeError, subprocess.SubprocessError):
            pass
    return {}, 'Fresh repository check unavailable. Versions use local pacman databases.'


def catalog(source='both', cache=CACHE, refresh=False):
    installed = installed_packages()
    notes = []
    # Independent refreshes run together, once per browser opening, never per key.
    with ThreadPoolExecutor(max_workers=3) as workers:
        repo_job = workers.submit(repository_updates, cache, refresh=refresh) if source != 'aur' else None
        aur_job = workers.submit(aur_names, cache, refresh=refresh) if source != 'repo' else None
        description_job = workers.submit(aur_descriptions, cache) if source != 'repo' else None
        updates, update_note = repo_job.result() if repo_job else ({}, '')
        names, aur_note = aur_job.result() if aur_job else ([], '')
        descriptions = description_job.result() if description_job else {}
    if update_note:
        notes.append(update_note)
    if aur_note:
        notes.append(aur_note)
    database = cache / 'repo-db'
    snapshot = database if (database / 'sync').is_dir() else None
    repo = {}
    if source != 'aur':
        try:
            repo = repository_packages(snapshot, all_repositories=True)
        except (OSError, RuntimeError, subprocess.SubprocessError):
            if snapshot is None:
                raise
            notes.append('Search snapshot unavailable. Using local pacman databases.')
            snapshot = None
            repo = repository_packages(None, all_repositories=True)
    packages = list(repo.values())
    repo_details = repository_descriptions(snapshot)
    for package in packages:
        package['description'] = repo_details.get((package['source'], package['name']), '')
    # Fresh snapshot versions are authoritative per repository. Do not apply the
    # priority repository's update version to the same name in another repository.
    if snapshot is None:
        for package in packages:
            if package['name'] in updates:
                package['version'] = updates[package['name']]
    if source != 'repo':
        wanted = sorted(set(installed) & set(names))
        versions = {}
        if wanted:
            try:
                versions = aur_info(wanted)
            except (OSError, ValueError, RuntimeError):
                notes.append('AUR update status unavailable. Checked again on selection.')
        packages.extend(dict(name=name, source='AUR', version=versions.get(name), description=descriptions.get(name, ''), aur=True) for name in names)
    return sorted(packages, key=lambda item: (item['name'].casefold(), item['source'])), installed, ' '.join(notes)


def ranked(packages, icon_map, repository=None):
    selected = [p for p in packages if repository is None or p['source'] == repository]
    return sorted(selected, key=lambda p: (p['name'].casefold() not in icon_map,
                                           p['name'].casefold(), p['source']))


def package_picker(loader, query='', repository=None):
    """Show the input immediately, then feed freshly loaded, fully sorted rows."""
    scope = repository or 'All repositories + AUR'
    argv = ['rofi', '-dmenu', '-i', '-no-sort', '-matching', 'normal',
            '-show-icons', '-markup-rows', '-eh', '3',
            '-format', 'i\x1ff', '-filter', query, '-kb-custom-1', 'Alt+r', '-kb-custom-2', 'Alt+d',
            '-p', 'Packages', '-mesg', html.escape(scope + ' · Alt+R: repository · Alt+D: full description')]
    config = Path(os.environ.get('XDG_CONFIG_HOME', Path.home() / '.config')) / 'rofi/config.rasi'
    if config.is_file():
        argv += ['-config', str(config)]
    process = subprocess.Popen(argv, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                               stderr=subprocess.PIPE, text=True)
    try:
        # This selectable control also exposes repository filtering without a
        # keyboard shortcut. It is not a package and can never start a transaction.
        process.stdin.write('Choose repository · ' + html.escape(scope) + '\0icon\x1fview-filter-symbolic\n')
        process.stdin.flush()
        rows = loader()
        try:
            process.stdin.write('\n'.join(rows) + ('\n' if rows else ''))
            process.stdin.close()
        except BrokenPipeError:
            pass  # The user may cancel while catalogs are refreshing.
        process.stdin = None
        output, error = process.communicate()
        index_text, _, current_query = output.rstrip('\n').partition('\x1f')
        if process.returncode == 10:
            return dict(filter=True, query=current_query)
        if process.returncode not in (0, 11):
            return None
        try:
            index = int(index_text)
        except ValueError:
            return None
        if index == 0:
            return dict(filter=True, query=current_query)
        if 1 <= index <= len(rows):
            return dict(index=index - 1, query=current_query, details=process.returncode == 11)
        return None
    except BrokenPipeError:
        process.stdin = None
        process.communicate()
        return None
    finally:
        if process.poll() is None:
            process.terminate()
            process.communicate()



def show_details(package, installed):
    description = clean(package.get('description') or 'Description unavailable. Try again when connected.')
    information = [package['name'], package['source'] + ' · ' + status(package, installed), '']
    information += textwrap.wrap(description, width=52)
    rows = ['Back to package search'] + [clean(line) + '\0nonselectable\x1ftrue' for line in information]
    choose(rows, 'Package details')

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


def open_browser(initial_query=''):
    for binary in ('rofi', 'pacman', 'kitty'):
        if not shutil.which(binary):
            raise RuntimeError(f'{binary} is required. Run poedash doctor.')
    CACHE.mkdir(parents=True, exist_ok=True)
    with (CACHE / 'browser.lock').open('w') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return
        # The first UI is always the all-repository search, never a source menu.
        data, installed, icon_map = None, {}, {}
        visible = []
        repository, query = None, initial_query

        def load_rows():
            nonlocal data, installed, icon_map, visible
            if data is None:
                data, installed, note = catalog('both', CACHE, refresh=True)
                icon_map = icons()
                if 'unavailable' in note.lower() or 'offline' in note.lower():
                    notify(note)
            visible = ranked(data, icon_map, repository)
            return [row(p, installed, icon_map) for p in visible]

        while True:
            selection = package_picker(load_rows, query, repository)
            if selection is None:
                return
            query = selection['query']
            if selection.get('filter'):
                sources = sorted({p['source'] for p in data})
                index = choose(['All repositories + AUR'] + sources, 'Repository',
                               'Choose a repository, then continue typing in the package search.')
                if index is not None:
                    repository = None if index == 0 else sources[index - 1]
                continue
            package = visible[selection['index']]
            if package['aur']:
                try:
                    detail = aur_details([package['name']]).get(package['name'], {})
                    package.update(detail)
                except (OSError, ValueError, RuntimeError) as exc:
                    notify(f'AUR metadata unavailable: {exc}')
                    continue
                if not package['version']:
                    notify('This package is no longer available in the AUR.')
                    continue
            if selection.get('details'):
                show_details(package, installed)
                continue
            information = status(package, installed)
            old = installed.get(package['name'])
            if old is not None and compare(package['version'], old) <= 0:
                show_details(package, installed)
                continue
            target = package['name'] if package['aur'] else package['source'] + '/' + package['name']
            kind = 'aur' if package['aur'] else 'repo'
            action = 'Update' if old else 'Install'
            confirmation = choose([action, action + ' and upgrade', 'Full description', 'Cancel'], package['name'],
                                  information + ' · First option: selected package only. Second option: full system upgrade.')
            if confirmation == 2:
                show_details(package, installed)
                continue
            if confirmation not in (0, 1):
                continue
            upgrade = confirmation == 1
            transaction_command(kind, target, upgrade)  # Check helper availability before opening a terminal.
            subprocess.Popen(['kitty', '--title', 'PoeDash package transaction', sys.executable,
                              str(Path(__file__).resolve()), 'transaction', kind, target] + (['--upgrade'] if upgrade else []),
                             start_new_session=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            return


def update_in_progress():
    path = CACHE.parent / 'update.lock'
    if not path.exists():
        return False
    with path.open('r') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return True
        return False


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('launch', 'open', 'transaction'))
    parser.add_argument('source', nargs='?', choices=('repo', 'aur'))
    parser.add_argument('target', nargs='?')
    parser.add_argument('--query', default='', help='prefill the package search')
    parser.add_argument('--upgrade', action='store_true', help='include a full system upgrade in a transaction')
    args = parser.parse_args()
    if os.geteuid() == 0:
        raise RuntimeError('Run PoeDash packages as your desktop user, never as root')
    if args.action in ('launch', 'open') and update_in_progress():
        return  # Replacing/reopening widgets must never summon the finder.
    if args.action == 'launch':
        subprocess.Popen([sys.executable, str(Path(__file__).resolve()), 'open', '--query', args.query], start_new_session=True,
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    elif args.action == 'open':
        open_browser(args.query)
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
