#!/usr/bin/env python3
"""Manage only the PenDash Burp CA in Chromium's per-user shared NSS database."""
import argparse
import hashlib
import os
from pathlib import Path
import re
import socket
import subprocess
import sys
import tempfile

NICKNAME = 'PenDash Burp CA'


def proxy_available():
    try:
        with socket.create_connection(('127.0.0.1', 8080), timeout=1):
            return True
    except OSError:
        return False


def execute(args, **kwargs):
    return subprocess.run(args, capture_output=True, check=True, **kwargs)


def database():
    home = Path.home()
    legacy = home / '.pki/nssdb'
    # Chromium M146+ keeps using legacy if that directory exists.
    if legacy.is_dir():
        return legacy
    version = execute(['chromium', '--version'], text=True).stdout
    match = re.search(r'\b(\d+)\.', version)
    if not match:
        raise RuntimeError('Cannot detect Chromium version; refusing to guess NSS location.')
    return home / ('.local/share/pki/nssdb' if int(match[1]) >= 146 else '.pki/nssdb')


def certificate(data):
    with tempfile.TemporaryDirectory(prefix='pendash-ca-') as tmp:
        path = Path(tmp) / 'certificate'
        path.write_bytes(data)
        fmt = 'PEM' if b'-----BEGIN CERTIFICATE-----' in data else 'DER'
        der = execute(['openssl', 'x509', '-inform', fmt, '-in', str(path), '-outform', 'DER']).stdout
        info = execute(['openssl', 'x509', '-inform', fmt, '-in', str(path), '-noout',
                        '-subject', '-issuer', '-fingerprint', '-sha256', '-text'], text=True).stdout
        if not re.search(r'CA\s*:\s*TRUE\b', info):
            raise RuntimeError('Certificate is not a CA (Basic Constraints CA:TRUE required).')
        execute(['openssl', 'x509', '-inform', fmt, '-in', str(path), '-noout', '-checkend', '0'])
        return der, hashlib.sha256(der).hexdigest(), '\n'.join(info.splitlines()[:3])


def current(db):
    # List must succeed: a corrupt/locked DB must not masquerade as missing CA.
    listing = execute(['certutil', '-d', 'sql:' + str(db), '-L'], text=True).stdout
    match = re.search(r'^' + re.escape(NICKNAME) + r'\s+(\S+)\s*$', listing, re.M)
    if not match:
        return None
    data = execute(['certutil', '-d', 'sql:' + str(db), '-L', '-n', NICKNAME, '-a']).stdout
    der, fingerprint, info = certificate(data)
    return der, fingerprint, info, match[1]


def confirm(prompt):
    return sys.stdin.isatty() and input(prompt + ' [y/N] ').strip().lower() in ('y', 'yes')


def main(action='import', path=None):
    db = database()
    print('[PASS] NSS database detected: ' + str(db))
    initialized = (db / 'cert9.db').is_file()
    old = current(db) if initialized else None
    if old:
        print(old[2])
        print('[PASS] Burp CA trusted' if old[3] == 'C,,' else '[INFO] Burp CA trust flags: ' + old[3])
    else:
        print('[INFO] Burp CA setup pending.\n[INFO] Run: pendash setup-burp-ca')
    if action == 'status':
        return 0
    if action == 'remove':
        if old and confirm('Remove only the PenDash Burp CA shown above?'):
            execute(['certutil', '-d', 'sql:' + str(db), '-D', '-n', NICKNAME])
            if current(db):
                raise RuntimeError('Certificate removal verification failed.')
            print('[PASS] PenDash Burp CA removed')
        return 0
    path = Path(path).expanduser() if path else Path.home() / 'Downloads/cacert.der'
    if not path.is_file():
        print('Export the CA from your Burp instance at http://burpsuite (through its proxy).')
        if not sys.stdin.isatty():
            return 0
        value = input('Certificate path (empty to skip): ').strip()
        if not value:
            return 0
        path = Path(value).expanduser()
    der, fingerprint, info = certificate(path.read_bytes())
    print('Supplied certificate:\n' + info)
    if old and old[1] == fingerprint and old[3] == 'C,,':
        print('[PASS] Correct Burp CA already trusted; import skipped')
        return 0
    if old and old[1] != fingerprint:
        print('Fingerprint mismatch: Burp may have regenerated its CA. Only the PenDash entry will be replaced.')
    print('This NSS trust database is shared by Chromium profiles and possibly other applications. '
          'Trusting this CA allows it to authenticate HTTPS sites for those applications. '
          'Confirm the fingerprint against your own Burp instance. No system CA store is modified.')
    if not confirm('Trust this CA' + (' and replace the PenDash entry?' if old else '?')):
        print('[INFO] Burp CA setup pending.')
        return 0
    db.mkdir(parents=True, exist_ok=True, mode=0o700)
    if not initialized:
        execute(['certutil', '-d', 'sql:' + str(db), '-N', '--empty-password'])
    # Replace only our nickname; restore its previous certificate if import fails.
    with tempfile.TemporaryDirectory(prefix='pendash-ca-') as tmp:
        source = Path(tmp) / 'ca.der'
        source.write_bytes(der)
        if old:
            execute(['certutil', '-d', 'sql:' + str(db), '-D', '-n', NICKNAME])
        try:
            execute(['certutil', '-d', 'sql:' + str(db), '-A', '-t', 'C,,', '-n', NICKNAME, '-i', str(source)])
        except subprocess.SubprocessError:
            if old:
                source.write_bytes(old[0])
                execute(['certutil', '-d', 'sql:' + str(db), '-A', '-t', old[3], '-n', NICKNAME, '-i', str(source)])
            raise
    installed = current(db)
    if not installed or installed[1] != fingerprint or installed[3] != 'C,,':
        raise RuntimeError('Burp CA fingerprint/trust verification failed.')
    print('[PASS] Burp CA trusted. Restart Chromium before testing HTTPS interception.')
    return 0


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--action', choices=['import', 'status', 'remove'], default='import')
    parser.add_argument('--certificate', type=Path)
    args = parser.parse_args()
    try:
        sys.exit(main(args.action, args.certificate))
    except (OSError, RuntimeError, subprocess.SubprocessError) as exc:
        print('PenDash CA: ' + str(exc), file=sys.stderr)
        sys.exit(1)
