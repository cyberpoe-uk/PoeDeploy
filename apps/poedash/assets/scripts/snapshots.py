"""Unprivileged snapshot status, a dated list cache, and explicit authentication."""
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess
import time

from dashboard_model import atomic_json, read_json
from snapshots_admin import LEVELS, NAME, repository, validate_schedule

CONFIG = Path('/etc/timeshift/timeshift.json')


def schedule_from_config(data):
    values = {}
    defaults = {'monthly': 2, 'weekly': 3, 'daily': 5, 'hourly': 6, 'boot': 5}
    for level in LEVELS:
        try: keep = int(data.get('count_' + level, defaults[level]))
        except (TypeError, ValueError): keep = defaults[level]
        values[level] = {'enabled': str(data.get('schedule_' + level, 'false')).lower() == 'true',
                         'keep': keep}
    return values


def status(root):
    value = {'available': bool(shutil.which('timeshift')), 'configured': False,
             'items': [], 'checked': 0, 'list_loaded': False}
    try:
        raw = CONFIG.read_bytes()
        data = json.loads(raw)
        if not isinstance(data, dict): raise ValueError('Invalid Timeshift settings')
        value.update(configured=bool(data.get('backup_device_uuid')) and str(data.get('do_first_run', 'false')).lower() != 'true',
                     mode='Btrfs' if str(data.get('btrfs_mode', 'false')).lower() == 'true' else 'Rsync',
                     repository=repository(data), schedule=schedule_from_config(data),
                     fingerprint=hashlib.sha256(raw).hexdigest(),
                     home_backup=str(data.get('include_btrfs_home_for_backup', 'false')).lower() == 'true',
                     home_restore=str(data.get('include_btrfs_home_for_restore', 'false')).lower() == 'true')
    except FileNotFoundError:
        value['error'] = 'Open Timeshift to finish setup.'
        return value
    except (OSError, ValueError) as exc:
        value['error'] = 'Cannot read Timeshift settings: ' + str(exc)
        return value
    cache = read_json(Path(root) / 'state/snapshots.json', {})
    items = cache.get('items') if isinstance(cache, dict) else None
    valid_items = isinstance(items, list) and len(items) <= 10000 and all(
        isinstance(item, dict) and isinstance(item.get('name'), str) and re.fullmatch(NAME, item['name'])
        and all(isinstance(item.get(key, ''), str) for key in ('tags', 'description')) for item in items)
    if valid_items and cache.get('repository') == value['repository']:
        checked = cache.get('checked', 0)
        if type(checked) in (int, float) and 0 < checked <= time.time() + 60:
            value.update(items=cache['items'], checked=checked, list_loaded=True,
                         stale=time.time() - checked > 300 or bool(cache.get('stale')))
    try:
        result = subprocess.run(['systemctl', 'is-active', 'cronie.service', 'cron.service'],
                                capture_output=True, text=True, timeout=2)
        value['scheduler'] = 'active' if 'active' in result.stdout.splitlines() else 'inactive'
    except (OSError, subprocess.SubprocessError): value['scheduler'] = 'unknown'
    # Resolve the configured snapshot device instead of assuming it is root.
    try:
        result = subprocess.run(['findmnt', '--json', '--output', 'TARGET,UUID'],
                                capture_output=True, text=True, timeout=3)
        def visit(nodes):
            for node in nodes:
                yield node
                yield from visit(node.get('children', []))
        mounts = visit(json.loads(result.stdout).get('filesystems', []))
        target = next((node['target'] for node in mounts if node.get('uuid') == value['repository'][0]), None)
        if target:
            usage = shutil.disk_usage(target)
            value.update(free_gib=round(usage.free / 2**30, 1), storage_path=target)
    except (OSError, ValueError, KeyError, subprocess.SubprocessError): pass
    return value


def perform(root, action, payload):
    """Run only on an explicit click; never called by background collectors."""
    if action not in ('list', 'create', 'delete', 'schedule'):
        raise ValueError('Unsupported snapshot operation.')
    if action == 'schedule': validate_schedule(payload.get('schedule'))
    if not shutil.which('pkexec'):
        raise RuntimeError('Administrator authentication is unavailable. Open Timeshift directly.')
    # Capture the code in this invocation. -I prevents privileged imports from
    # user-controlled paths; the bridge imports only the Python standard library.
    source = Path(__file__).with_name('snapshots_admin.py').read_text()
    result = subprocess.run(['/usr/bin/pkexec', '/usr/bin/python3', '-I', '-c', source,
                             action, json.dumps(payload)], stdin=subprocess.DEVNULL,
                            capture_output=True, text=True)
    if result.returncode in (126, 127):
        raise RuntimeError('Authentication was cancelled or denied. Nothing was changed by this request.')
    if result.returncode:
        raise RuntimeError(result.stderr.strip()[-1200:] or 'The snapshot operation could not complete.')
    try:
        response = json.loads(result.stdout)
        if not isinstance(response, dict): raise ValueError()
    except ValueError:
        raise RuntimeError('The snapshot operation returned an unreadable result. Check Timeshift before trying again.') from None
    if response.get('error'): raise RuntimeError(response['error'])
    cache = Path(root) / 'state/snapshots.json'
    try:
        if 'cache' in response:
            atomic_json(cache, response['cache'])
        elif response.get('changed'):
            previous = read_json(cache, {})
            if not isinstance(previous, dict): previous = {}
            previous['stale'] = True
            atomic_json(cache, previous)
    except OSError:
        response['message'] = response.get('message', 'Operation completed.') + ' The local list could not be saved; refresh it before another operation.'
    return response
