#!/usr/bin/env python3
"""Event-driven power policy, independent of dashboard visibility and refreshes."""
import argparse
import asyncio
import fcntl
import json
import os
from pathlib import Path
import re
import shutil
import signal
import subprocess
import sys
import time
from battery import POWER_SUPPLY, reading, read

ROOT = Path(__file__).resolve().parents[1]
STATE = Path(os.environ.get('XDG_STATE_HOME', Path.home() / '.local/state')) / 'poedash'
CONFIG = Path(os.environ.get('XDG_CONFIG_HOME', Path.home() / '.config'))
UNIT = CONFIG / 'systemd/user/poedash-power.service'
OWNER = '# Managed by PoeDash power policy'
PROFILES = ('performance', 'balanced', 'power-saver')


def run(argv):
    result = subprocess.run([str(v) for v in argv], text=True, capture_output=True, timeout=5)
    if result.returncode:
        raise RuntimeError(result.stderr.strip() or result.stdout.strip() or f'{argv[0]} failed')
    return result.stdout.strip()


def active(unit):
    try: return run(['systemctl', 'is-active', unit]) == 'active'
    except (OSError, RuntimeError, subprocess.SubprocessError): return False


def source(root=POWER_SUPPLY):
    try:
        supplies = list(root.iterdir())
    except OSError as exc:
        raise RuntimeError('System power supplies are unreadable; automatic switching is deferred.') from exc
    if any(not read(p / 'type') for p in supplies):
        raise RuntimeError('A power-supply sensor is unreadable; automatic switching is deferred.')
    data = reading(root, with_estimate=False)
    if not data['present']: return 'desktop'
    if data['status'] == 'Unknown':
        raise RuntimeError('AC/battery state is unknown; the current profile is retained.')
    return 'battery' if data['on_battery'] else 'ac'


class Backend:
    def __init__(self):
        native = active('power-profiles-daemon.service')
        tuned = active('tuned.service')
        tlp = active('tlp.service')
        if (native and (tuned or tlp)) or (tuned and tlp) or active('auto-cpufreq.service'):
            raise RuntimeError('Conflicting automatic power managers are active. Review their policies before enabling PoeDash automation.')
        self.kind, self.mapping = '', {}
        if shutil.which('powerprofilesctl'):
            try:
                output = run(['powerprofilesctl', 'list'])
                available = re.findall(r'(?m)^\s*\*?\s*(performance|balanced|power-saver):', output)
                if available:
                    self.kind, self.mapping = 'power-profiles API', {p: p for p in available}
            except (RuntimeError, OSError, subprocess.SubprocessError): pass
        if not self.mapping and tuned and shutil.which('tuned-adm'):
            output = run(['tuned-adm', 'list'])
            names = re.findall(r'(?m)^\s*-\s+([a-z0-9-]+)\s', output)
            self.kind = 'tuned'
            self.mapping = {display: name for display, name in
                [('performance', 'throughput-performance'), ('balanced', 'balanced'), ('power-saver', 'powersave')] if name in names}
        if not self.mapping:
            raise RuntimeError('No supported power-profile service is available. Start your existing power-profiles-daemon, tuned-ppd or tuned service. PoeDash will not install a competing manager.')

    def current(self):
        if self.kind == 'tuned':
            output = run(['tuned-adm', 'active'])
            match = re.search(r':\s*([a-z0-9-]+)\s*$', output)
            name = match.group(1) if match else output
            return next((key for key, value in self.mapping.items() if value == name), name)
        return run(['powerprofilesctl', 'get'])

    def set(self, profile):
        if profile not in self.mapping:
            raise RuntimeError(f'{profile} is not supported. Available: {", ".join(self.mapping)}')
        if self.current() != profile:
            run(['tuned-adm', 'profile', self.mapping[profile]] if self.kind == 'tuned' else ['powerprofilesctl', 'set', profile])
        actual = self.current()
        if actual != profile:
            raise RuntimeError(f'Power-profile readback mismatch: requested {profile}, active {actual}. A profile hold or another manager may be active.')
        return actual


def atomic(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    encoded = json.dumps(data)
    if path.is_file() and path.read_text() == encoded: return
    temporary = path.with_name('.' + path.name + f'-{os.getpid()}')
    temporary.write_text(encoded)
    temporary.chmod(0o600)
    temporary.replace(path)


class Policy:
    def __init__(self, state=STATE, backend=Backend, get_source=source, boot=None):
        self.state, self.backend, self.get_source = state, backend, get_source
        self.boot = boot or read(Path('/proc/sys/kernel/random/boot_id'))
        self.file = state / 'power-policy.json'

    def saved(self):
        try:
            data = json.loads(self.file.read_text())
            return data if isinstance(data, dict) else {}
        except (OSError, ValueError): return {}

    def sync(self, manual=None):
        self.state.mkdir(parents=True, exist_ok=True)
        with (self.state / '.power-policy.lock').open('w') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            old = self.saved()
            data = dict(old)
            data.update(supported=False, message='', available=[], active='Unavailable', mode=old.get('mode', 'Automatic'), enabled=old.get('enabled', True))
            try:
                backend = self.backend()
                data.update(supported=True, backend=backend.kind, available=list(backend.mapping), active=backend.current())
                current_source = self.get_source()
                data['source'] = current_source
                changed = old.get('boot') != self.boot or old.get('source') != current_source
                if manual is not None:
                    if manual not in PROFILES: raise RuntimeError('Invalid power profile.')
                    data['active'] = backend.set(manual)
                    data['mode'] = 'Manual'
                    data.pop('fallback', None)
                elif data['enabled'] and changed:
                    desired = 'power-saver' if current_source == 'battery' else 'performance'
                    selected = desired if desired in backend.mapping else 'balanced' if 'balanced' in backend.mapping else next(iter(backend.mapping))
                    data['active'] = backend.set(selected)
                    data['mode'] = 'Automatic'
                    data['fallback'] = f'{desired} is unavailable; using supported {selected}.' if selected != desired else ''
                    data['message'] = data['fallback']
                elif old.get('active') and data['active'] != old['active']:
                    data['mode'] = 'Manual / external'
                    data.pop('fallback', None)
                if not data['message'] and data.get('mode') == 'Automatic':
                    data['message'] = data.get('fallback', '')
                data.update(boot=self.boot, automatic=bool(data['enabled']))
            except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as exc:
                # Preserve the last confirmed source/boot on failure so an actual
                # transition is retried, never fabricated by a UI refresh.
                data.update(message=str(exc), source=old.get('source', 'unknown'), boot=old.get('boot', ''))
            atomic(self.file, data)
            return data

    def enable(self, enabled):
        self.state.mkdir(parents=True, exist_ok=True)
        with (self.state / '.power-policy.lock').open('w') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            data = self.saved()
            data['enabled'] = enabled
            if enabled:
                data.pop('boot', None)  # Explicit re-enable initialises the policy.
            atomic(self.file, data)


def publish(data):
    # Eww may be closed. Policy always persists; the UI listener reads it later.
    if not shutil.which('eww'): return
    try: run(['eww', '--config', ROOT, 'update', 'power_profile=' + json.dumps(data)])
    except (OSError, RuntimeError, subprocess.SubprocessError): pass


def unit_text():
    # systemd ExecStart quoting uses double quotes, not shell single quotes.
    command = ' '.join('"' + a.replace('\\', '\\\\').replace('"', '\\"').replace('%', '%%') + '"' for a in [sys.executable, str(ROOT / 'scripts/power-control.py'), 'watch'])
    return OWNER + '\n[Unit]\nDescription=PoeDash automatic power profiles\nAfter=dbus.service\n\n[Service]\nExecStart=' + command + '\nRestart=on-failure\nRestartSec=5\n\n[Install]\nWantedBy=default.target\n'


def install(policy, force=False):
    if not force and policy.saved().get('enabled') is False:
        return 'Automatic power management remains disabled by user preference.'
    if UNIT.exists() and not UNIT.read_text().startswith(OWNER):
        raise RuntimeError('A custom poedash-power.service exists. It was left unchanged.')
    data = policy.sync()
    if not data['supported']:
        return data['message']
    UNIT.parent.mkdir(parents=True, exist_ok=True)
    text = unit_text()
    if not UNIT.exists() or UNIT.read_text() != text:
        UNIT.write_text(text)
    try:
        run(['systemctl', '--user', 'daemon-reload'])
        run(['systemctl', '--user', 'enable', 'poedash-power.service'])
        run(['systemctl', '--user', 'restart', 'poedash-power.service'])
        if run(['systemctl', '--user', 'is-active', 'poedash-power.service']) != 'active':
            raise RuntimeError('Power policy service did not start.')
    except (RuntimeError, OSError, subprocess.SubprocessError) as exc:
        wants = UNIT.parent / 'default.target.wants'
        wants.mkdir(exist_ok=True)
        link = wants / UNIT.name
        if not link.exists() and not link.is_symlink(): link.symlink_to('../' + UNIT.name)
        return f'Power policy configured for next login. User-service startup unavailable: {exc}'
    return data['message'] or f'Automatic power policy active: {data["source"]} → {data["active"]}'


def stop_worker(state=STATE):
    pidfile = state / 'power-worker.json'
    if not pidfile.is_file(): return
    data = json.loads(pidfile.read_text())
    pid = int(data['pid'])
    proc = Path('/proc') / str(pid)
    if not proc.exists():
        pidfile.unlink(missing_ok=True)
        return
    args = proc.joinpath('cmdline').read_bytes().decode().strip('\0').split('\0')
    if proc.stat().st_uid != os.getuid() or str(ROOT / 'scripts/power-control.py') not in args or 'watch' not in args:
        raise RuntimeError('Power worker PID does not match the managed process. No other process was stopped.')
    os.kill(pid, signal.SIGTERM)
    deadline = time.monotonic() + 4
    while proc.exists():
        if ') Z ' in proc.joinpath('stat').read_text(): break
        if time.monotonic() > deadline: raise RuntimeError('Power worker did not stop. Dashboard files were retained.')
        time.sleep(.05)
    pidfile.unlink(missing_ok=True)


def remove(policy, uninstall=False):
    if UNIT.exists() and not UNIT.read_text().startswith(OWNER):
        raise RuntimeError('Custom power service retained. Disable it manually if required.')
    policy.enable(False)
    if UNIT.exists():
        try: run(['systemctl', '--user', 'disable', '--now', UNIT.name])
        except (RuntimeError, OSError, subprocess.SubprocessError):
            stop_worker(policy.state)
        link = UNIT.parent / 'default.target.wants' / UNIT.name
        if link.is_symlink(): link.unlink()
        UNIT.unlink()
        try: run(['systemctl', '--user', 'daemon-reload'])
        except (RuntimeError, OSError, subprocess.SubprocessError): pass
    stop_worker(policy.state)


async def watch(policy):
    policy.state.mkdir(parents=True, exist_ok=True)
    with (policy.state / '.power-worker.lock').open('w') as singleton:
        try: fcntl.flock(singleton, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError: return
        atomic(policy.state / 'power-worker.json', dict(pid=os.getpid()))
        queue = asyncio.Queue(maxsize=1)
        stop = asyncio.Event()
        loop = asyncio.get_running_loop()
        for signum in (signal.SIGTERM, signal.SIGINT): loop.add_signal_handler(signum, stop.set)
        async def monitor(argv, token):
            while not stop.is_set():
                proc = None
                try:
                    proc = await asyncio.create_subprocess_exec(*argv, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL)
                    while line := await proc.stdout.readline():
                        if token in line and queue.empty(): queue.put_nowait(True)
                except (OSError, ValueError): pass
                finally:
                    if proc and proc.returncode is None:
                        proc.terminate()
                        try: await asyncio.wait_for(proc.wait(), 2)
                        except asyncio.TimeoutError:
                            proc.kill()
                            await proc.wait()
                await asyncio.sleep(5)
                if queue.empty(): queue.put_nowait(True)
        tasks = [asyncio.create_task(monitor(['udevadm', 'monitor', '--udev', '--subsystem-match=power_supply', '--property'], b'SUBSYSTEM=power_supply'))]
        # gdbus subscribes normally as the user (no privileged BecomeMonitor).
        # Both historical/current API names are harmless; repeated signals dedupe.
        for name, path in [('org.freedesktop.UPower.PowerProfiles', '/org/freedesktop/UPower/PowerProfiles'),
                           ('net.hadess.PowerProfiles', '/net/hadess/PowerProfiles')]:
            tasks.append(asyncio.create_task(monitor(['gdbus', 'monitor', '--system', '--dest', name, '--object-path', path], b'PropertiesChanged')))
        try:
            publish(policy.sync())
            while not stop.is_set():
                event = asyncio.create_task(queue.get())
                halted = asyncio.create_task(stop.wait())
                try:
                    done, _ = await asyncio.wait([event, halted], timeout=60, return_when=asyncio.FIRST_COMPLETED)
                    if stop.is_set(): break
                    if event in done: await asyncio.sleep(.3)  # coalesce cable event bursts
                    while not queue.empty(): queue.get_nowait()
                    publish(policy.sync())  # also reconciles missed events after resume
                finally:
                    event.cancel(); halted.cancel()
                    await asyncio.gather(event, halted, return_exceptions=True)
        finally:
            for task in tasks: task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            (policy.state / 'power-worker.json').unlink(missing_ok=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['install', 'watch', 'status', 'listen', 'set', 'enable', 'disable', 'uninstall'])
    parser.add_argument('profile', nargs='?', choices=PROFILES)
    args = parser.parse_args()
    policy = Policy()
    if args.action == 'watch': asyncio.run(watch(policy))
    elif args.action == 'listen':
        previous = None
        while True:
            data = dict(supported=False, source='unknown', active='Unavailable', available=[], mode='Unavailable', enabled=False, message='Power profile service is not configured.')
            data.update(policy.saved())
            encoded = json.dumps(data)
            if encoded != previous:
                print(encoded, flush=True)
                previous = encoded
            time.sleep(1)
    elif args.action == 'set':
        if args.profile is None: parser.error('set requires a profile')
        publish(policy.sync(manual=args.profile))
    elif args.action == 'status': print(json.dumps(policy.saved()))
    elif args.action in ('disable', 'uninstall'): remove(policy, args.action == 'uninstall')
    else:
        if args.action == 'enable': policy.enable(True)
        print(install(policy, force=args.action == 'enable'))


if __name__ == '__main__':
    try: main()
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as exc:
        raise SystemExit(str(exc))
