#!/usr/bin/env python3
"""Explicit optional security installations, independent of dashboard refreshes."""
import argparse
import datetime
import hashlib
from html.parser import HTMLParser
import os
from pathlib import Path
import platform
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
import urllib.request
import urllib.parse

HOME = Path.home()
STATE = Path(os.environ.get('XDG_STATE_HOME', HOME / '.local/state')) / 'poedeploy'
BACKUP = STATE / 'backups' / datetime.datetime.now().strftime('%Y%m%d-%H%M%S-%f')
CURATED = ['ffuf', 'gobuster', 'nmap', 'sqlmap', 'wfuzz', 'wireshark-qt', 'jwt-tool']
PACMAN_CONFIG = Path('/etc/pacman.conf')
BLACKARCH_MIRRORLIST = Path('/etc/pacman.d/blackarch-mirrorlist')
BURP_DOWNLOADS = 'https://portswigger.net/burp/downloads'


class BurpDownloads(HTMLParser):
    """Read platform build IDs and their SHA-256 checksums from PortSwigger."""
    def __init__(self):
        super().__init__()
        self.version = ''
        self.builds = {}
        self.hashes = {}
        self.panel = None
        self.capture = None

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        classes = attrs.get('class', '').split()
        if tag == 'input' and attrs.get('id') == 'CurrentVersion':
            self.version = attrs.get('value', '')
        if tag == 'a' and 'btn-download-small' in classes:
            self.builds[attrs.get('data-type')] = attrs.get('data-build-id')
        if tag == 'div' and 'checksum-panel' in classes:
            self.panel = attrs.get('data-build-id')
        if tag == 'code' and 'sha-256-checksum' in classes and self.panel:
            self.capture = self.panel
            self.hashes[self.capture] = ''

    def handle_data(self, data):
        if self.capture:
            self.hashes[self.capture] += data

    def handle_endtag(self, tag):
        if tag == 'code':
            self.capture = None


def burp_release(page, machine):
    kind = {'x86_64': 'Linux', 'aarch64': 'LinuxArm64', 'arm64': 'LinuxArm64'}.get(machine)
    if not kind:
        raise RuntimeError(f'PortSwigger does not provide a supported Linux installer for {machine}.')
    metadata = BurpDownloads()
    metadata.feed(page)
    checksum = metadata.hashes.get(metadata.builds.get(kind), '').strip().lower()
    if not re.fullmatch(r'\d{4}(?:\.\d+){1,3}', metadata.version) or not re.fullmatch(r'[0-9a-f]{64}', checksum):
        raise RuntimeError('Could not find the Burp Linux release and SHA-256 on the official download page.')
    url = 'https://portswigger.net/burp/releases/download?' + urllib.parse.urlencode(
        {'product': 'desktop', 'version': metadata.version, 'type': kind})
    return metadata.version, url, checksum


def official_burp():
    # Do not treat a pacman/AUR JAR launcher as the native PortSwigger install.
    launcher = HOME / '.local/bin/burpsuite'
    if launcher.is_file():
        try:
            for line in launcher.read_text().splitlines():
                if line.startswith('exec '):
                    binary = Path(shlex.split(line)[1])
                    if binary.name in ('BurpSuite', 'BurpSuiteCommunity', 'BurpSuitePro') and binary.is_file() and os.access(binary, os.X_OK):
                        return binary
        except (OSError, ValueError, IndexError):
            pass
    for directory, executable in (
            (HOME / '.local/share/poedeploy/burp', 'BurpSuite'),
            (HOME / 'BurpSuite', 'BurpSuite'),
            (HOME / 'BurpSuiteCommunity', 'BurpSuiteCommunity'),
            (HOME / 'BurpSuitePro', 'BurpSuitePro'),
            (Path('/opt/BurpSuite'), 'BurpSuite'),
            (Path('/opt/BurpSuiteCommunity'), 'BurpSuiteCommunity'),
            (Path('/opt/BurpSuitePro'), 'BurpSuitePro')):
        binary = directory / executable
        if binary.is_file() and os.access(binary, os.X_OK):
            return binary
    return None


def install_burp(dry_run):
    existing = official_burp()
    if existing:
        print(f'PortSwigger Burp is already installed: {existing}. Use its own updater for new releases.')
        return
    if dry_run:
        print('Would download the current native Burp Linux installer from PortSwigger, verify SHA-256, and install for this user.')
        return
    # Resolve an explicit version so the checksum and download cannot drift apart.
    with urllib.request.urlopen(BURP_DOWNLOADS, timeout=30) as response:
        page = response.read(2 * 1024 * 1024).decode()
    version, url, checksum = burp_release(page, platform.machine())
    print(f'Downloading PortSwigger Burp Suite {version} (native Linux installer)...', flush=True)
    destination = HOME / '.local/share/poedeploy/burp'
    with tempfile.TemporaryDirectory(prefix='poedeploy-burp-') as tmp:
        installer = Path(tmp) / 'burpsuite.sh'
        digest = hashlib.sha256()
        with urllib.request.urlopen(url, timeout=60) as response, installer.open('wb') as target:
            while chunk := response.read(1024 * 1024):
                digest.update(chunk)
                target.write(chunk)
        if digest.hexdigest() != checksum:
            raise RuntimeError('Burp installer SHA-256 mismatch. Installation was not run.')
        destination.parent.mkdir(parents=True, exist_ok=True)
        run(['sh', installer, '-q', '-dir', destination])
    binary = destination / 'BurpSuite'
    if not binary.is_file() or not os.access(binary, os.X_OK):
        raise RuntimeError(f'Burp installer did not create {binary}.')
    write(HOME / '.local/bin/burpsuite', '#!/bin/sh\nexec ' + shlex.quote(str(binary)) + ' "$@"\n', 0o755)
    print(f'Installed PortSwigger Burp Suite {version}. Use Community Edition, or activate an existing Professional license.')
    print('Existing repository packages were retained. Launch the PortSwigger installation from its desktop entry or ~/.local/bin/burpsuite.')


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
    temporary = path.with_name('.' + path.name + '.poedeploy')
    temporary.write_text(content)
    temporary.chmod(mode)
    temporary.replace(path)


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
    with tempfile.NamedTemporaryFile(prefix='poedeploy-blackarch-', delete=False) as stream:
        stream.write(script)
        path = Path(stream.name)
    try:
        run(['sudo', 'bash', path])
    finally:
        path.unlink(missing_ok=True)


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


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('choice', choices=['blackarch', 'security-tools', 'burp'])
    parser.add_argument('--dry-run', action='store_true')
    args = parser.parse_args()
    if args.choice == 'blackarch':
        ensure_blackarch(args.dry_run)
    elif args.choice == 'burp':
        install_burp(args.dry_run)
    else:
        if not args.dry_run and not (PACMAN_CONFIG.is_file() and
                re.search(r'(?m)^\s*\[blackarch\]\s*(?:#.*)?$', PACMAN_CONFIG.read_text())):
            raise RuntimeError('Select the optional BlackArch repository before installing this tool collection.')
        install_packages(CURATED, args.dry_run)
    return 0


if __name__ == '__main__':
    try:
        sys.exit(main())
    except Exception as exc:
        print('Security tools: ' + str(exc), file=sys.stderr)
        sys.exit(1)
