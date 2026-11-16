"""One authenticated Timeshift operation. Executed as isolated, in-memory code.

No privileged service or passwordless policy is installed. Keep this module
self-contained: it must never import code from the dashboard or its directory.
"""
import datetime
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import sys
import tempfile

CONFIG = Path('/etc/timeshift/timeshift.json')
LEVELS = ('monthly', 'weekly', 'daily', 'hourly', 'boot')
NAME = r'\d{4}-\d{2}-\d{2}_\d{2}-\d{2}-\d{2}'
ENV = {'PATH': '/usr/bin:/bin', 'HOME': '/root', 'LANG': 'C', 'LC_ALL': 'C'}


def read_config():
    raw = CONFIG.read_bytes()
    data = json.loads(raw)
    if not isinstance(data, dict) or not data.get('backup_device_uuid'):
        raise ValueError('Finish Timeshift setup first.')
    return raw, data


def repository(data):
    return [data.get('backup_device_uuid', ''), str(data.get('btrfs_mode', 'false')).lower()]


def parse_list(output):
    output = re.sub(r'\x1b\[[0-9;]*m', '', output)
    rows = []
    for line in output.splitlines():
        match = re.match(r'^\s*\d+\s+>\s+(' + NAME + r')\s{2,}(.*)$', line)
        if not match:
            continue
        name, rest = match.groups()
        # Timeshift pads its Tags column. Empty tags must not consume a description.
        rest = rest.rstrip()
        tags = re.match(r'^([OBHDWM](?: [OBHDWM])*)\s{2,}(.*)$', rest)
        if tags:
            tag, description = tags.groups()
        elif re.fullmatch(r'[OBHDWM](?: [OBHDWM])*', rest):
            tag, description = rest, ''
        else:
            tag, description = '', rest.strip()
        rows.append({'name': name, 'tags': tag, 'description': description[:1000]})
    if not rows and 'No snapshots found' not in output:
        raise RuntimeError('Timeshift did not return a readable snapshot list. Open Timeshift for details.')
    return sorted(rows, key=lambda row: row['name'], reverse=True)


def timeshift(arguments, allow_empty=False):
    result = subprocess.run(['/usr/bin/timeshift', *arguments, '--scripted'],
                            stdin=subprocess.DEVNULL, capture_output=True, text=True, env=ENV)
    output = result.stdout + '\n' + result.stderr
    empty = allow_empty and 'No snapshots found' in output and not re.search(
        r'(?im)(?:^|\n)\s*(?:E:|Error:|Failed)', output)
    if result.returncode and not empty:
        lines = [line.strip() for line in output.splitlines() if line.strip()]
        raise RuntimeError('\n'.join(lines[-8:])[-1800:] or 'Timeshift could not complete the operation.')
    return output


def list_snapshots():
    rows = parse_list(timeshift(['--list'], allow_empty=True))
    _, data = read_config()
    return {'items': rows, 'checked': datetime.datetime.now().timestamp(),
            'repository': repository(data)}


def validate_schedule(value):
    if not isinstance(value, dict) or set(value) != set(LEVELS):
        raise ValueError('Provide all five snapshot schedule levels.')
    for level, item in value.items():
        if not isinstance(item, dict) or set(item) != {'enabled', 'keep'}:
            raise ValueError('Invalid schedule settings.')
        if type(item['enabled']) is not bool or type(item['keep']) is not int or not 1 <= item['keep'] <= 100:
            raise ValueError('Keep between 1 and 100 snapshots per schedule level.')
    return value


def timeshift_running():
    for path in Path('/proc').glob('[0-9]*/exe'):
        try:
            if path.resolve().name in ('timeshift', 'timeshift-gtk'):
                return True
        except OSError:
            pass
    return False


def save_schedule(value, expected):
    validate_schedule(value)
    if timeshift_running():
        raise RuntimeError('Timeshift is running. Close its window or wait for its operation to finish, then try again.')
    if CONFIG.is_symlink() or not stat.S_ISREG(CONFIG.stat().st_mode):
        raise ValueError('Timeshift settings must be a regular file.')
    raw, data = read_config()
    if not isinstance(expected, str) or hashlib.sha256(raw).hexdigest() != expected:
        raise RuntimeError('Timeshift settings changed. Reopen Schedule to load the latest settings.')
    for level, item in value.items():
        data['schedule_' + level] = str(item['enabled']).lower()
        data['count_' + level] = str(item['keep'])
    metadata = CONFIG.stat()
    temporary = None
    try:
        fd, temporary = tempfile.mkstemp(prefix='.poedash-', dir=CONFIG.parent)
        with os.fdopen(fd, 'w') as stream:
            os.fchmod(stream.fileno(), stat.S_IMODE(metadata.st_mode))
            os.fchown(stream.fileno(), metadata.st_uid, metadata.st_gid)
            json.dump(data, stream, indent=2)
            stream.write('\n'); stream.flush(); os.fsync(stream.fileno())
        if CONFIG.read_bytes() != raw or timeshift_running():
            raise RuntimeError('Timeshift settings changed or Timeshift started. Reopen Schedule and try again.')
        backup = CONFIG.with_name(CONFIG.name + '.poedash-' + datetime.datetime.now().strftime('%Y%m%d-%H%M%S-%f') + '.bak')
        with backup.open('xb') as stream:
            os.fchmod(stream.fileno(), 0o600)
            stream.write(raw); stream.flush(); os.fsync(stream.fileno())
        os.replace(temporary, CONFIG)
    finally:
        if temporary and os.path.exists(temporary):
            os.unlink(temporary)
    return {'message': 'Snapshot schedule saved.'}


def execute(action, payload):
    if action not in ('list', 'create', 'delete', 'schedule') or not isinstance(payload, dict):
        raise ValueError('Unsupported snapshot operation.')
    _, data = read_config()
    if payload.get('repository') != repository(data):
        raise RuntimeError('The snapshot device or mode changed. Refresh the card and try again.')
    if action == 'schedule':
        return save_schedule(payload.get('schedule'), payload.get('expected'))
    if action == 'list':
        return {'cache': list_snapshots(), 'message': 'Snapshot list refreshed.'}
    if action == 'create':
        description = payload.get('description', '')
        if not isinstance(description, str) or len(description) > 200 or any(ord(c) < 32 for c in description):
            raise ValueError('Use a description of up to 200 characters on one line.')
        timeshift(['--create', '--comments', description or 'Created from PoeDash', '--tags', 'O'])
        message = 'Snapshot created.'
    else:
        name = payload.get('name', '')
        if not isinstance(name, str) or not re.fullmatch(NAME, name):
            raise ValueError('Select a valid snapshot to delete.')
        current = list_snapshots()
        if name not in {item['name'] for item in current['items']}:
            raise RuntimeError('That snapshot no longer exists. Refresh the snapshot list.')
        timeshift(['--delete', '--snapshot', name, '--yes'])
        message = 'Snapshot deleted.'
    try:
        return {'message': message, 'cache': list_snapshots(), 'changed': True}
    except (OSError, ValueError, RuntimeError) as exc:
        # The mutation succeeded: do not encourage the user to repeat it.
        return {'message': message + ' Refresh the list to check its latest state.',
                'changed': True, 'refresh_error': str(exc)}


def main():
    try:
        if os.geteuid() != 0:
            raise RuntimeError('Administrator authentication is required.')
        if len(sys.argv) != 3 or len(sys.argv[2]) > 10000:
            raise ValueError('Invalid snapshot request.')
        result = execute(sys.argv[1], json.loads(sys.argv[2]))
    except (OSError, ValueError, RuntimeError) as exc:
        result = {'error': str(exc)}
    print(json.dumps(result))


if __name__ == '__main__':
    main()
