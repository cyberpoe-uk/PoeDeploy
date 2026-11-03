"""Bounded collectors and a single configurable background scheduler."""
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
import importlib.util
import json
import os
from pathlib import Path
import queue
import signal
import subprocess
import sys
import threading
import time
from urllib.parse import urlencode, urlparse
from urllib.request import Request, urlopen
import xml.etree.ElementTree as ET

from dashboard_model import REFRESH, SOURCES, read_json
from battery import reading as battery_reading
from service_health import failed_units

COMMANDS = {'cpu': ['cpu.sh'], 'ram': ['arch-status.sh', 'ram'],
            'cpu_temperature': ['cpu-temperature.py'], 'gpu': ['gpu.py', '--passive'],
            'network': ['network.sh'], 'vpn': ['vpn.sh'], 'power': ['power.py'],
            'processes': ['processes.py'], 'shares': ['shares.py'], 'arch': ['arch-status.sh'],
            'media': ['media.py'], 'system_info': ['system-info.py'],
            'packages': ['arch-status.sh', 'packages'], 'updates': ['arch-status.sh', 'updates'],
            'calendar': ['thunderbird-calendar.py'], 'session': ['idle-control.py', 'status']}


def fetch(url, token='', raw=False):
    parsed = urlparse(url)
    if parsed.scheme not in ('http', 'https') or not parsed.netloc:
        raise ValueError('Configure a valid HTTP or HTTPS URL')
    headers = {'User-Agent': 'PoeDash/2', 'Accept': 'application/json, application/xml, text/xml, */*'}
    if token: headers['Authorization'] = 'Bearer ' + token
    with urlopen(Request(url, headers=headers), timeout=5) as response:
        payload = response.read(2_000_001)
    if len(payload) > 2_000_000: raise ValueError('Response exceeds 2 MB')
    if raw: return payload
    return json.loads(payload)


def feed_items(payload):
    if b'<!DOCTYPE' in payload.upper() or b'<!ENTITY' in payload.upper():
        raise ValueError('Feed contains unsupported XML declarations')
    tree = ET.fromstring(payload)
    items = []
    for item in list(tree.findall('.//item')) + list(tree.findall('{http://www.w3.org/2005/Atom}entry')):
        def text(name):
            node = item.find(name)
            if node is None: node = item.find('{http://www.w3.org/2005/Atom}' + name)
            return ''.join(node.itertext()).strip() if node is not None else ''
        link = text('link')
        node = item.find('{http://www.w3.org/2005/Atom}link')
        if node is not None: link = node.get('href', link)
        if urlparse(link).scheme not in ('http', 'https'): link = ''
        title = text('title')[:400]
        if title: items.append({'title': title, 'url': link})
        if len(items) >= 15: break
    return items


def mounted_shares(payload):
    rows = []
    def visit(items):
        for item in items:
            rows.append({'target': item.get('target', '--'), 'source': item.get('source', '--'),
                         'type': item.get('fstype', '--').upper()})
            visit(item.get('children', []))
    visit(payload.get('filesystems', []))
    return rows


def health_issues(values, expected=(), expected_vpns=()):
    issues = []
    health = values.get('health', {})
    for disk in health.get('disks', []):
        if disk.get('percent', 0) >= 90:
            issues.append({'card': 'system', 'text': f"{disk['path']} disk {disk['percent']}% full"})
    for unit in failed_units(health.get('failed', [])):
        issues.append({'card': 'system', 'text': f"Failed {unit['scope']} unit: {unit['unit']}", **unit})
    targets = {s.get('target') for s in values.get('shares', []) if isinstance(s, dict)}
    if 'shares' in values:
        for target in expected:
            if target not in targets: issues.append({'card': 'shares', 'text': 'Share disconnected: ' + target})
    network = values.get('network', {})
    if network and network.get('state') == 'Offline':
        issues.append({'card': 'connectivity', 'text': 'Network disconnected'})
    vpn = values.get('vpn', {})
    if vpn:
        for name in expected_vpns:
            if not vpn.get(name):
                issues.append({'card': 'connectivity', 'text': ('Tailscale' if name == 'tailscale' else 'Proton VPN') + ' is disconnected'})
    power = values.get('power', {})
    if power.get('on_battery'):
        try:
            if float(str(power.get('battery', '')).rstrip('%')) < 15:
                issues.append({'card': 'power', 'text': 'Battery below 15%'})
        except ValueError: pass
    return issues


class Collectors:
    def __init__(self, root):
        self.root = Path(root)
        self.processes = set()
        self.lock = threading.Lock()
        self.last_network = None
        self.stopped = False
        self.paused = False

    def run(self, argv, timeout=6, allow_empty=False):
        if self.stopped or self.paused: raise RuntimeError('Paused')
        process = subprocess.Popen([str(a) for a in argv], stdout=subprocess.PIPE,
                                   stderr=subprocess.PIPE, start_new_session=True)
        with self.lock: self.processes.add(process)
        try:
            out, err = process.communicate(timeout=timeout)
            if process.returncode and not allow_empty:
                # Commands may emit sensitive remote details; keep errors concise.
                raise RuntimeError(Path(str(argv[0])).name + ' is unavailable or returned an error')
            return out.decode(errors='replace').strip()
        except subprocess.TimeoutExpired:
            self.kill(process)
            process.communicate()
            raise RuntimeError('Collector timed out') from None
        finally:
            with self.lock: self.processes.discard(process)

    @staticmethod
    def kill(process):
        if process.poll() is None:
            try: os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError: pass

    def cancel(self):
        with self.lock:
            for process in list(self.processes): self.kill(process)

    def collect(self, source, settings):
        if self.stopped or self.paused: raise RuntimeError('Paused')
        if source == 'shares':
            output = self.run(['findmnt', '--json', '--types', 'cifs,nfs,nfs4,smb3', '--output', 'SOURCE,TARGET,FSTYPE'], allow_empty=True)
            return mounted_shares(json.loads(output)) if output else []
        if source == 'health':
            import shutil
            disks = []
            for path in dict.fromkeys(['/', str(Path.home())]):
                usage = shutil.disk_usage(path)
                disks.append({'path': path, 'percent': round(usage.used/usage.total*100),
                              'free_gib': round(usage.free/2**30, 1)})
            failed = []
            for scope in ([], ['--user']):
                try:
                    out = self.run(['systemctl', *scope, '--failed', '--no-legend', '--plain', '--no-pager', '--full'], timeout=3)
                    failed += [{'unit': line.split()[0], 'scope': 'user' if scope else 'system'}
                               for line in out.splitlines() if line.strip()][:15]
                except (OSError, RuntimeError): pass
            return {'disks': disks, 'failed': failed}
        if source == 'containers':
            output = self.run(['docker', 'ps', '-a', '--format', '{{json .}}'])
            return [json.loads(line) for line in output.splitlines() if line][:50]
        cfg = settings.get('integrations', {}).get(source, {})
        if source == 'weather':
            if cfg.get('latitude', '') == '' or cfg.get('longitude', '') == '':
                return {'configured': False}
            params = urlencode({'latitude': float(cfg['latitude']), 'longitude': float(cfg['longitude']),
                                'current': 'temperature_2m,apparent_temperature,relative_humidity_2m,weather_code,wind_speed_10m',
                                'daily': 'temperature_2m_max,temperature_2m_min,precipitation_probability_max',
                                'timezone': 'auto', 'forecast_days': 3})
            return {'configured': True, **fetch('https://api.open-meteo.com/v1/forecast?' + params)}
        if source == 'feeds':
            urls = [u.strip() for u in cfg.get('urls', '').splitlines() if u.strip()]
            rows, errors = [], 0
            for url in urls[:20]:
                if self.stopped or self.paused: break
                try:
                    rows += feed_items(fetch(url, raw=True))
                except (OSError, ValueError, ET.ParseError): errors += 1
            if urls and errors == len(urls): raise RuntimeError('Feeds could not be read')
            return {'configured': bool(urls), 'items': rows[:50], 'errors': errors}
        if source in ('nas', 'remote'):
            if not cfg.get('url'): return {'configured': False}
            payload = fetch(cfg['url'], cfg.get('token', ''))
            if not isinstance(payload, dict): raise ValueError('Endpoint must return a JSON object')
            return {'configured': True, 'data': payload}
        if source == 'session':
            draft = read_json(self.root / 'state/idle-edit.json', {})
            if draft.get('dirty'): return draft
        args = COMMANDS[source]
        argv = [self.root / 'scripts' / args[0], *args[1:]]
        if args[0].endswith('.py'): argv.insert(0, sys.executable)
        output = self.run(argv, timeout=95 if source == 'updates' else 8)
        if source in ('packages', 'updates'): return output
        value = json.loads(output)
        if source == 'network' and isinstance(value, dict):
            device = value.get('interface', '')
            try:
                path = Path('/sys/class/net') / device / 'statistics'
                now = time.monotonic()
                received, sent = int((path/'rx_bytes').read_text()), int((path/'tx_bytes').read_text())
                if self.last_network and self.last_network[0] == device:
                    _, stamp, rx, tx = self.last_network
                    elapsed = max(.1, now-stamp)
                    value.update(rx_bps=max(0,received-rx)/elapsed, tx_bps=max(0,sent-tx)/elapsed)
                self.last_network = (device, now, received, sent)
            except (OSError, ValueError): pass
        return value


class Engine:
    def __init__(self, root, settings, publish):
        self.root, self.settings, self.publish = Path(root), deepcopy(settings), publish
        self.collectors = Collectors(root)
        self.queue = queue.SimpleQueue()
        self.stop_event = threading.Event()
        self.thread = None
        self.visible = True
        self.on_battery = False
        self.due, self.running, self.samples = {}, {}, {}
        self.paused = False
        self.visibility_override = None

    def configure(self, settings):
        self.queue.put(('settings', deepcopy(settings)))

    def request(self, source):
        self.queue.put(('refresh', source))

    def start(self):
        self.thread = threading.Thread(target=self.loop, name='poedash-collectors', daemon=True)
        self.thread.start()

    def close(self):
        self.stop_event.set()
        self.collectors.stopped = True
        self.collectors.cancel()
        if self.thread: self.thread.join(timeout=10)

    def loop(self):
        pool = ThreadPoolExecutor(max_workers=4, thread_name_prefix='poedash-read')
        media_pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix='poedash-media')
        next_gate = 0
        try:
            while not self.stop_event.is_set():
                now = time.monotonic()
                while not self.queue.empty():
                    kind, value = self.queue.get()
                    if kind == 'settings':
                        self.settings = value
                        self.due.clear()
                    else: self.due[value] = 0
                if now >= next_gate:
                    try:
                        self.on_battery = battery_reading(with_estimate=False).get('on_battery', False)
                        spec = importlib.util.spec_from_file_location('poedash_workspace', self.root / 'scripts/workspace.py')
                        workspace = importlib.util.module_from_spec(spec)
                        spec.loader.exec_module(workspace)
                        reading = workspace.query(self.root)
                        if reading is not None: self.visible = reading
                    except (OSError, ValueError, AttributeError, ImportError): pass
                    if self.visibility_override is not None: self.visible = self.visibility_override
                    next_gate = now+2
                    self.publish({'_gate': {'visible': self.visible, 'on_battery': self.on_battery}})
                paused = self.on_battery and not self.visible
                if paused != self.paused:
                    self.paused = paused
                    self.collectors.paused = paused
                    if paused:
                        self.collectors.cancel()
                        for future in self.running.values(): future.cancel()
                    else: self.due.clear()
                state = self.root / 'state'
                state.mkdir(parents=True, exist_ok=True)
                for filename, content in [('home-visible', self.visible), ('refresh-paused', paused), ('on-battery', self.on_battery)]:
                    path = state / filename
                    text = str(bool(content)).lower()
                    try:
                        if not path.exists() or path.read_text() != text: path.write_text(text)
                    except OSError: pass
                completed = {}
                for source, future in list(self.running.items()):
                    if not future.done(): continue
                    del self.running[source]
                    try:
                        value = future.result()
                        self.samples[source] = {'value': value, 'updated': time.time(), 'error': ''}
                    except Exception as exc:
                        old = self.samples.get(source, {'value': None, 'updated': 0})
                        message = str(exc) if isinstance(exc, RuntimeError) else 'Unable to read this source'
                        self.samples[source] = {**old, 'error': message}
                    completed[source] = deepcopy(self.samples[source])
                if completed and not paused: self.publish(completed)
                if not paused:
                    profile = self.settings['profiles'][self.settings['active_profile']]
                    enabled = {'health'}
                    for card in profile['visible']: enabled.update(SOURCES.get(card, ()))
                    # Source/profile information is also needed for battery awareness.
                    enabled.add('power')
                    for source in enabled:
                        if source not in self.running and now >= self.due.get(source, 0):
                            seconds = profile['refresh'].get(source, REFRESH[source])
                            self.running[source] = (media_pool if source == 'media' else pool).submit(self.collectors.collect, source, deepcopy(self.settings))
                            self.due[source] = now+seconds
                self.stop_event.wait(.15)
        finally:
            self.collectors.cancel()
            pool.shutdown(wait=True, cancel_futures=True)
            media_pool.shutdown(wait=True, cancel_futures=True)
