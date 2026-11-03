"""Read systemd diagnostics for an exact system or user unit."""
import os
import re
import subprocess


def failed_units(items):
    """Retain manager scope, accepting older collector samples during upgrades."""
    result = []
    for item in items:
        unit = {'unit': item, 'scope': 'system'} if isinstance(item, str) else item
        if not isinstance(unit, dict):
            continue
        name, scope = unit.get('unit'), unit.get('scope')
        if (isinstance(name, str) and len(name) <= 255 and not name.startswith('-') and
                re.fullmatch(r'[A-Za-z0-9_.:@\\-]+\.[A-Za-z0-9_-]+', name) and
                scope in ('system', 'user')):
            entry = {'unit': name, 'scope': scope}
            if entry not in result:
                result.append(entry)
    return result


def service_details(unit, scope):
    if not failed_units([{'unit': unit, 'scope': scope}]):
        raise ValueError('Choose an exact system or user unit')
    commands = {
        'status': ['systemctl', *(['--user'] if scope == 'user' else []),
                   'status', '--no-pager', '--full', '--lines=12', '--', unit],
        'journal': ['journalctl', *(['--user'] if scope == 'user' else []),
                    '--user-unit' if scope == 'user' else '--unit', unit,
                    '--boot', '--lines=50', '--no-pager', '--output=short-iso'],
    }
    result = {'unit': unit, 'scope': scope}
    for key, argv in commands.items():
        try:
            # A failed/inactive service normally makes systemctl status exit 3.
            command = subprocess.run(argv, capture_output=True, text=True, errors='replace',
                                     timeout=5, check=False,
                                     env=os.environ | {'SYSTEMD_COLORS': '0', 'SYSTEMD_URLIFY': '0'})
            output = '\n'.join(part.strip() for part in (command.stdout, command.stderr) if part.strip())
            result[key] = output[-64000:] or (
                'No accessible journal entries for this unit in the current boot.' if key == 'journal'
                else f'No status output (exit {command.returncode}). The unit may have been removed.')
        except subprocess.TimeoutExpired:
            result[key] = 'Reading these details timed out. Use Refresh details to try again.'
        except OSError as exc:
            result[key] = f'Could not read these details: {exc}'
    return result
