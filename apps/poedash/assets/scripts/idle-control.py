#!/usr/bin/env python3
"""Read, edit and transactionally activate the existing Hypridle configuration."""
import argparse
import fcntl
import glob
import json
import math
import os
from pathlib import Path
import re
import shlex
import shutil
import signal
import subprocess
import time

ROOT = Path(__file__).resolve().parents[1]
KINDS = ('screen', 'lock', 'suspend')
ACTIONS = {'screen': 'hyprctl dispatch \'hl.dsp.dpms({ action = "disable" })\'', 'lock': 'loginctl lock-session',
           'suspend': 'systemctl suspend'}
MAX_MINUTES = 1440


def run(argv, **kwargs):
    result = subprocess.run([str(a) for a in argv], capture_output=True, text=True,
                            timeout=5, **kwargs)
    if result.returncode:
        raise RuntimeError(result.stderr.strip() or result.stdout.strip() or f'{argv[0]} failed')
    return result.stdout.strip()


def processes():
    found = []
    for path in Path('/proc').glob('[0-9]*'):
        try:
            if path.stat().st_uid != os.getuid() or (path / 'comm').read_text().strip() != 'hypridle':
                continue
            if (path / 'stat').read_text().split(') ', 1)[1].startswith('Z'):
                continue
            args = (path / 'cmdline').read_bytes().decode().strip('\0').split('\0')
            env = dict(item.split('=', 1) for item in (path / 'environ').read_bytes().decode().split('\0') if '=' in item)
            ticks = int((path / 'stat').read_text().split(') ', 1)[1].split()[19])
            started = time.time() - float(Path('/proc/uptime').read_text().split()[0]) + ticks / os.sysconf('SC_CLK_TCK')
            service = None
            for line in (path / 'cgroup').read_text().splitlines():
                name = line.rsplit('/', 1)[-1]
                if name.endswith('.service'):
                    service = name
            found.append({'pid': int(path.name), 'args': args, 'env': env, 'started': started, 'service': service,
                          'cwd': (path / 'cwd').resolve()})
        except (OSError, ValueError, IndexError):
            continue
    return found


def discover():
    if not shutil.which('hypridle'):
        raise RuntimeError('Hypridle is not installed. Install hypridle and configure desktop autostart first.')
    instances = processes()
    if len(instances) > 1:
        raise RuntimeError('Multiple Hypridle instances are running. Resolve competing idle managers first.')
    proc = instances[0] if instances else None
    env = proc['env'] if proc else dict(os.environ)
    config_home = Path(env.get('XDG_CONFIG_HOME', str(Path.home() / '.config')))
    custom = None
    if proc:
        for i, arg in enumerate(proc['args']):
            if arg in ('-c', '--config') and i + 1 < len(proc['args']):
                custom = Path(proc['args'][i + 1]).expanduser()
            elif arg.startswith('--config='):
                custom = Path(arg.split('=', 1)[1]).expanduser()
        if custom and not custom.is_absolute():
            custom = proc['cwd'] / custom
    candidates = [custom] if custom else [config_home / 'hypr/hypridle.conf', config_home / 'hypridle.conf',
        *[Path(p) / 'hypr/hypridle.conf' for p in env.get('XDG_CONFIG_DIRS', '/etc/xdg').split(':')]]
    config = next((p for p in candidates if p and p.is_file()), None)
    if not config:
        raise RuntimeError('No existing Hypridle configuration found. Configure your idle manager first.')
    return config.resolve(), proc


def uncomment(text):
    # Hyprlang comments, respecting quoted strings in commands and source paths.
    output, quote, escape = [], None, False
    for line in text.splitlines(keepends=True):
        quote, escape = None, False
        for char in line:
            if char == '#' and not quote:
                break
            output.append(char)
            if escape:
                escape = False
            elif char == '\\':
                escape = True
            elif char in ('"', "'"):
                quote = None if quote == char else char if quote is None else quote
        if not output or output[-1] != '\n':
            output.append('\n')
    return ''.join(output)


def masked(text):
    # Preserve offsets while hiding comment/string braces from the block parser.
    chars = list(text)
    quote, comment, escape = None, False, False
    for i, char in enumerate(text):
        if comment:
            if char == '\n': comment = False
            else: chars[i] = ' '
        elif escape:
            chars[i] = ' '
            escape = False
        elif quote:
            chars[i] = ' '
            if char == '\\': escape = True
            elif char == quote: quote = None
        elif char == '#':
            comment = True
            chars[i] = ' '
        elif char in ('"', "'"):
            quote = char
            chars[i] = ' '
    return ''.join(chars)


def screen_off_action(command):
    if command == 'hyprctl dispatch dpms off': return True
    try: argv = shlex.split(command)
    except ValueError: return False
    if len(argv) != 3 or argv[0] not in ('hyprctl','/usr/bin/hyprctl'):
        return False
    expression = argv[2].strip().removesuffix(';').strip()
    if argv[1] == 'eval':
        outer = re.fullmatch(r'hl\.dispatch\s*\((.*)\)',expression,re.S)
        if not outer: return False
        expression = outer.group(1).strip()
    elif argv[1] != 'dispatch': return False
    call = re.fullmatch(r'hl\.dsp\.dpms\s*\(\s*\{(.*?)\}\s*\)',expression,re.S)
    if not call: return False
    # Only literal fields are recognised. Lua and shell text are never evaluated.
    table, fields, offset = call.group(1), {}, 0
    pattern = r"""(action|monitor)\s*=\s*(["'])([^"'\\\n]*)\2"""
    for match in re.finditer(pattern,table):
        gap = table[offset:match.start()].strip()
        if gap != (',' if fields else '') or match[1] in fields: return False
        fields[match[1]] = match[3]
        offset = match.end()
    return table[offset:].strip() in ('',',') and fields.get('action') in ('disable','off')


def same_values(left, right):
    return all(round(left[key]*60) == round(right[key]*60) for key in KINDS)


def display_values(data):
    for key in KINDS:
        if data.get('known'):
            seconds = round(data[key]*60)
            data[key+'_text'] = f'{seconds/60:.2f}'.rstrip('0').rstrip('.')
            data[key+'_detail'] = f'{seconds} seconds ({seconds//60} min {seconds%60} sec)'
        else:
            data[key+'_text'], data[key+'_detail'] = '—', data.get('message','')
    return data


def blocks(text):
    clean = masked(text)
    for match in re.finditer(r'(?m)^[ \t]*listener\s*\{', clean):
        start = match.start()
        depth, end = 1, match.end()
        while end < len(clean) and depth:
            depth += (clean[end] == '{') - (clean[end] == '}')
            end += 1
        if depth:
            raise RuntimeError('Unclosed Hypridle listener block.')
        raw = uncomment(text[match.end():end - 1])
        fields = dict(re.findall(r'(?m)^\s*([\w-]+)\s*=\s*(.*?)\s*$', raw))
        action = fields.get('on-timeout', '').strip()
        key = next((key for key, command in ACTIONS.items() if action == command), None)
        if screen_off_action(action): key = 'screen'
        if action in ('hyprlock', 'pidof hyprlock || hyprlock'):
            key = 'lock'
        if not key and re.search(r'dpms|lock|suspend|hibernate|screen.?off', action, re.I):
            raise RuntimeError(f'Custom idle action needs manual review: {action}')
        yield start, end, key, fields


def load(config):
    documents, rules = {}, {}
    active = set()
    def visit(path):
        path = path.resolve()
        if path in active:
            raise RuntimeError(f'Circular Hypridle source: {path}')
        if path in documents:
            raise RuntimeError(f'Duplicate Hypridle source: {path}')
        active.add(path)
        text = path.read_text()
        documents[path] = text
        for start, end, key, fields in blocks(text):
            if not key:
                continue
            if key in rules:
                raise RuntimeError(f'Multiple {key} idle timers exist. Resolve the duplicate timers first.')
            seconds = fields.get('timeout', '')
            if not re.fullmatch(r'[0-9]+', seconds):
                raise RuntimeError(f'The {key} timeout is not a literal number of seconds. Review {path}.')
            if not 0 < int(seconds) <= MAX_MINUTES * 60:
                raise RuntimeError(f'The {key} timeout is outside the supported 1–{MAX_MINUTES} minute range.')
            rules[key] = (path, start, end, fields)
        for value in re.findall(r'(?m)^\s*source\s*=\s*(.+?)\s*$', uncomment(text)):
            try:
                parts = shlex.split(value)
            except ValueError as exc:
                raise RuntimeError(f'Invalid Hypridle source: {exc}') from exc
            if len(parts) != 1:
                raise RuntimeError('Hypridle source paths containing unquoted spaces need manual review.')
            expanded = os.path.expandvars(os.path.expanduser(parts[0]))
            if '$' in expanded:
                raise RuntimeError('Hypridle source uses an unsupported configuration variable.')
            source = Path(expanded)
            matches = sorted(glob.glob(str(source if source.is_absolute() else path.parent / source)))
            if not matches:
                raise RuntimeError(f'Hypridle source does not exist: {value}')
            for match in matches: visit(Path(match))
        active.remove(path)
    visit(config)
    values = {key: int(rules[key][3]['timeout']) / 60 if key in rules else 0 for key in KINDS}
    return documents, rules, values


def validate(values):
    if set(values) != set(KINDS):
        raise ValueError('Screen Off, Lock Screen and Auto Suspend must all be supplied.')
    for key, value in values.items():
        if type(value) not in (int,float) or not 0 <= value <= MAX_MINUTES or not math.isfinite(value) or abs(value*60-round(value*60)) > 1e-6:
            raise ValueError(f'{key}: enter minutes between 0 and {MAX_MINUTES}, with whole-second precision. Zero disables this timer.')


def plan(config, values):
    validate(values)
    documents, rules, _ = load(config)
    edits, additions = {}, []
    for key in KINDS:
        if key in rules:
            path, start, end, fields = rules[key]
            raw = documents[path][start:end]
            replacement = re.sub(r'(?m)^(\s*timeout\s*=\s*)[0-9]+', lambda m: m[1] + str(round(values[key] * 60)), raw) if values[key] else ''
            edits.setdefault(path, []).append((start, end, replacement))
        elif values[key]:
            if key == 'lock' and not any(re.search(r'(?m)^\s*lock_cmd\s*=\s*\S', uncomment(t)) for t in documents.values()):
                raise RuntimeError('No existing Hypridle lock_cmd is configured. Configure hyprlock before enabling idle locking.')
            additions.append(f'\nlistener {{\n    timeout = {round(values[key] * 60)}\n    on-timeout = {ACTIONS[key]}\n' + ('    on-resume = hyprctl dispatch \'hl.dsp.dpms({ action = "enable" })\'\n' if key == 'screen' else '') + '}\n')
    for path, changes in edits.items():
        for start, end, replacement in sorted(changes, reverse=True):
            documents[path] = documents[path][:start] + replacement + documents[path][end:]
    documents[config] += ''.join(additions)
    return documents


def atomic(path, text):
    mode = path.stat().st_mode & 0o777
    temporary = path.with_name(f'.{path.name}.poedash-{os.getpid()}')
    try:
        temporary.write_text(text)
        temporary.chmod(mode)
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def activate(config, proc, root):
    managed = False
    service = (proc or {}).get('service') or 'hypridle.service'
    try:
        managed = run(['systemctl', '--user', 'show', service, '-p', 'MainPID', '--value']) == str(proc['pid'] if proc else -1)
    except (OSError, RuntimeError, subprocess.SubprocessError):
        pass
    expected = sum(len(list(blocks(text))) for text in load(config)[0].values())
    since = str(time.time())
    logpath = root / 'state/idle-activation.log'
    if managed:
        run(['systemctl', '--user', 'restart', service])
        pid = int(run(['systemctl', '--user', 'show', service, '-p', 'MainPID', '--value']))
        def logs():
            return run(['journalctl', '--user', f'_PID={pid}', '--since', '@' + since, '--no-pager', '-o', 'cat'])
    else:
        if not proc:
            raise RuntimeError('Hypridle is not running. Start it through your existing desktop autostart, then retry.')
        run(['hyprctl', 'version'])  # Check the launcher before stopping the existing manager.
        try:
            os.kill(proc['pid'], signal.SIGTERM)
        except ProcessLookupError:
            pass  # Rollback can relaunch after a rejected daemon has already exited.
        deadline = time.monotonic() + 3
        while any(p['pid'] == proc['pid'] for p in processes()):
            if time.monotonic() > deadline: raise RuntimeError('The existing Hypridle process did not stop.')
            time.sleep(.05)
        args = list(proc['args'])
        if '-v' not in args and '--verbose' not in args: args.append('-v')
        if not any(arg in ('-c', '--config') or arg.startswith('--config=') for arg in args):
            args += ['-c', str(config)]
        logpath.write_text('')
        logpath.chmod(0o600)
        # Launch through the compositor, as ML4W does, so the idle manager is not
        # owned by a dashboard/terminal cgroup that may disappear when it closes.
        command = 'cd ' + shlex.quote(str(proc['cwd'])) + ' && exec ' + shlex.join(args)
        command += ' >' + shlex.quote(str(logpath)) + ' 2>&1'
        run(['hyprctl', 'eval', 'hl.exec_cmd(' + json.dumps(command) + ')'])
        pid = None
        def logs(): return logpath.read_text(errors='replace')
    deadline = time.monotonic() + 4
    while time.monotonic() < deadline:
        text = logs()
        current = processes()
        if pid is None and len(current) == 1:
            pid = current[0]['pid']
        checked = re.sub(r'[^\n]*Config has errors[^\n]*\n[^\n]*No rules configured[^\n]*', '', text) if expected == 0 else text
        if re.search(r'Config has errors|\b(CRIT|ERR)\b|[Cc]ouldn.t|[Ff]ailed', checked):
            raise RuntimeError('Hypridle rejected activation: ' + text[-1200:])
        if any(p['pid'] == pid for p in current) and 'wayland done' in text.lower() and (text.lower().count('registered timeout rule') == expected):
            return pid
        time.sleep(.1)
    raise RuntimeError('Hypridle did not acknowledge its timers. Check ' + str(logpath))


def apply(values, root=ROOT):
    validate(values)
    config, proc = discover()
    if not proc:
        raise RuntimeError('Hypridle is not running. Start the existing idle manager before applying changes.')
    documents, rules, current = load(config)
    updated = plan(config, values)
    for path in updated:
        if path.stat().st_uid != os.getuid() or not os.access(path, os.W_OK) or not os.access(path.parent, os.W_OK):
            raise RuntimeError(f'Configuration is not writable by this user: {path}. No settings were changed.')
    lock_action = rules.get('lock', (None, None, None, {}))[3].get('on-timeout', ACTIONS['lock'])
    lock_binary = 'hyprlock' if lock_action in ('hyprlock', 'pidof hyprlock || hyprlock') else 'loginctl'
    for key, binary in [('screen', 'hyprctl'), ('lock', lock_binary), ('suspend', 'systemctl')]:
        if values[key] and not shutil.which(binary):
            raise RuntimeError(f'{binary} is unavailable. Cannot enable {key}.')
    if values['suspend']:
        answer = run(['busctl', '--system', 'call', 'org.freedesktop.login1', '/org/freedesktop/login1',
                      'org.freedesktop.login1.Manager', 'CanSuspend'])
        if answer not in ('s "yes"', 's "challenge"'):
            raise RuntimeError('logind does not support suspend: ' + answer)
    backup = root / 'state/idle-backups' / str(time.time_ns())
    backup.mkdir(parents=True, mode=0o700)
    for i, (path, text) in enumerate(documents.items()):
        (backup / f'{i}.conf').write_text(text)
    (backup / 'paths.json').write_text(json.dumps([str(p) for p in documents]))
    try:
        for path, text in updated.items():
            if text != documents[path]: atomic(path, text)
        activate(config, proc, root)
        if not same_values(load(config)[2], values):
            raise RuntimeError('Hypridle configuration readback did not match the requested settings.')
    except Exception as exc:
        for path, text in documents.items(): atomic(path, text)
        try:
            active = processes()
            activate(config, active[0] if len(active) == 1 else proc, root)
        except Exception as rollback:
            raise RuntimeError(f'{exc}. Configuration restored, but restart failed: {rollback}') from exc
        raise RuntimeError(f'{exc}. Previous configuration restored and reactivated.') from exc
    return values


def snapshot(root=ROOT):
    result = dict(screen=0, lock=0, suspend=0, dirty=False, supported=False, known=False, message='', config='')
    try:
        config, proc = discover()
        documents, _, values = load(config)
        stale = bool(proc and any(p.stat().st_mtime > proc.get('started', float('inf')) + .5 for p in documents))
        result.update(values, known=True, supported=bool(proc), config=str(config),
                      dirty=stale, message='Configuration changed since Hypridle started. Apply to activate and verify these values.' if stale else 'Minutes · 0 disables a timer' if proc else 'Hypridle is configured but not running.')
    except (OSError, ValueError, RuntimeError) as exc:
        result['message'] = str(exc)
    return display_values(result)


def publish(data, root):
    run(['eww', '--config', root, 'update', 'idle=' + json.dumps(display_values(data))])



def ui_paused(root):
    try:
        return (root / 'state/refresh-paused').read_text().strip() == 'true'
    except OSError:
        return False

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['status', 'listen', 'adjust', 'apply'])
    parser.add_argument('field', nargs='?', choices=KINDS)
    parser.add_argument('delta', nargs='?', type=int, choices=[-10, -1, 1, 10])
    args = parser.parse_args()
    state = ROOT / 'state/idle-edit.json'
    state.parent.mkdir(parents=True, exist_ok=True)
    if args.action == 'status':
        print(json.dumps(snapshot()))
        return
    if args.action == 'listen':
        previous = None
        while True:
            try:
                if ui_paused(ROOT):
                    time.sleep(1)
                    continue
                # Drafts survive failures and refreshes. External changes are read
                # when no edit is pending, so polling never discards entered values.
                try:
                    data = json.loads(state.read_text()) if state.is_file() else snapshot()
                    if not isinstance(data, dict): raise ValueError('Editor state must be an object')
                except (OSError, ValueError):
                    data = snapshot()
                if data.get('dirty'):
                    try:
                        validate({key: data[key] for key in KINDS})
                        data['known'] = True
                    except (KeyError, ValueError):
                        data = snapshot()
                if not data.get('dirty'):
                    fresh = snapshot()
                    if not fresh.get('dirty') and fresh.get('supported') and all(data.get(k) == fresh[k] for k in KINDS) and str(data.get('message', '')).startswith('Applied and verified'):
                        fresh['message'] = data['message']
                    data = fresh
                encoded = json.dumps(display_values(data))
                if encoded != previous:
                    print(encoded, flush=True)
                    previous = encoded
            except (OSError, ValueError, RuntimeError) as exc:
                data = dict(screen=0, lock=0, suspend=0, dirty=False, supported=False, known=False, message=str(exc), config='')
                print(json.dumps(display_values(data)), flush=True)
            time.sleep(5)
    with (state.parent / '.idle-edit.lock').open('w') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        data = json.loads(state.read_text()) if state.is_file() else snapshot()
        if not data.get('dirty'):
            data = snapshot()
        if args.action == 'adjust':
            if not args.field or args.delta is None: parser.error('adjust requires field and delta')
            if not data['supported']: raise RuntimeError(data['message'])
            data[args.field] = max(0, min(MAX_MINUTES, data[args.field] + args.delta))
            actual = snapshot()
            data['dirty'] = not same_values(data, actual)
            data['message'] = 'Unsaved changes · minutes · 0 disables' if data['dirty'] else actual['message']
        else:
            try:
                apply({key: data[key] for key in KINDS})
                data.update(dirty=False, message='Applied and verified in Hypridle')
            except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as exc:
                data.update(dirty=True, message=str(exc))
        state.write_text(json.dumps(display_values(data)))
        publish(data, ROOT)


if __name__ == '__main__':
    try:
        main()
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as exc:
        raise SystemExit(str(exc))
