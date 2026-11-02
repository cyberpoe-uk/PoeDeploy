#!/usr/bin/env python3
"""One battery-aware scheduler with independent media and bounded collectors."""
import asyncio
import fcntl
import json
import os
from pathlib import Path
import signal
import sys
import time
from battery import reading as battery_state

ROOT = Path(__file__).resolve().parent.parent
CADENCE = {'cpu': 2, 'ram': 3, 'gpu': 5, 'network': 5, 'vpn': 5,
           'power': 1, 'processes': 3, 'shares': 15, 'arch': 60, 'media': 5}
COMMANDS = {'cpu': ['cpu.sh'], 'ram': ['arch-status.sh', 'ram'], 'gpu': ['gpu.py'],
            'network': ['network.sh'], 'vpn': ['vpn.sh'], 'power': ['power.py'],
            'processes': ['processes.py'], 'shares': ['shares.py'],
            'arch': ['arch-status.sh'], 'media': ['media.py']}


def interval(key, on_battery, media=None):
    if key == 'power':
        return 5 if on_battery else 1
    if key == 'media':
        return 1 if (media or {}).get('status') == 'Playing' else 5
    return 2 if on_battery else CADENCE[key]


async def command(argv, timeout=5):
    process = await asyncio.create_subprocess_exec(*argv, stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.DEVNULL, start_new_session=True)
    try:
        output, _ = await asyncio.wait_for(process.communicate(), timeout)
        if process.returncode:
            raise RuntimeError('Collector failed')
        return output.decode().strip()
    finally:
        if process.returncode is None:
            try:
                os.killpg(process.pid, signal.SIGTERM)
                await asyncio.wait_for(process.wait(), 0.5)
            except (ProcessLookupError, asyncio.TimeoutError):
                if process.returncode is None:
                    os.killpg(process.pid, signal.SIGKILL)
                    await process.wait()


class Scheduler:
    def __init__(self, root, collect=None, publish=None):
        self.root = root
        self.collect = collect or self.read
        self.publish = publish or self.send
        self.general_slots = asyncio.Semaphore(3)
        self.running, self.due, self.values, self.sent = {}, {}, {}, {}
        self.publisher = None
        self.batch = {}
        self.mode = None
        self.visible = False
        self.active = False
        self.media_state = None
        self.spotify_uri = None
        self.last_timeline = None

    async def read(self, key):
        args = COMMANDS[key]
        argv = [str(self.root / 'scripts' / args[0]), *args[1:]]
        if args[0].endswith('.py'):
            argv.insert(0, sys.executable)
        if key == 'gpu':
            try:
                preference = json.loads((self.root / 'layout.json').read_text()).get('gpu_monitoring', 'auto')
            except (OSError, ValueError, AttributeError):
                preference = 'auto'
            if preference == 'passive' or preference == 'auto' and battery_state(with_estimate=False)['present']:
                argv.append('--passive')
        output = await command(argv)
        return json.loads(output)

    async def send(self, values):
        args = ['eww', '--config', str(self.root), 'update']
        args += [key + '=' + (json.dumps(value) if not isinstance(value, str) else value)
                 for key, value in values.items()]
        try:
            await command(args, timeout=2)
            return True
        except (OSError, RuntimeError, asyncio.TimeoutError):
            return False

    async def guarded(self, key):
        # Media never queues behind network/GPU commands.
        if key == 'media':
            return await self.collect(key)
        async with self.general_slots:
            return await self.collect(key)

    async def step(self, now, on_battery, visible):
        for key, task in list(self.running.items()):
            if task.done():
                del self.running[key]
                try:
                    self.values[key] = task.result()
                    if key == 'media':
                        next_media = now + interval(key, on_battery, self.values[key])
                        self.due[key] = min(self.due.get(key, next_media), next_media)
                except (OSError, ValueError, RuntimeError, asyncio.TimeoutError, asyncio.CancelledError):
                    pass  # Retain the last successful sample.
        if self.publisher is not None and self.publisher.done():
            if self.publisher.result():
                self.sent.update(self.batch)
            self.publisher = None
        active = visible or not on_battery
        if self.mode != on_battery or active and not self.active:
            self.due.clear()
        self.mode, self.visible, self.active = on_battery, visible, active
        if not active:
            tasks = list(self.running.values()) + ([self.publisher] if self.publisher is not None else [])
            for task in tasks:
                task.cancel()
            if tasks:
                await asyncio.gather(*tasks, return_exceptions=True)
            self.running.clear()
            self.publisher = None
            self.batch = {}
            return
        for key in ('media', *[key for key in CADENCE if key != 'media']):
            if key not in self.running and now >= self.due.get(key, 0):
                self.running[key] = asyncio.create_task(self.guarded(key))
                self.due[key] = now + interval(key, on_battery, self.values.get('media'))
        media = self.values.get('media', {})
        if isinstance(media, dict):
            playing = media.get('status') == 'Playing'
            if playing != self.media_state:
                state = self.root / 'state'
                state.mkdir(parents=True, exist_ok=True)
                (state / 'media-playing').write_text('true' if playing else 'false')
                self.media_state = playing
            timeline = dict(progress=media.get('progress', 0), position=media.get('position_seconds', 0),
                            length=media.get('length_seconds', 0), playing=playing,
                            sampled=media.get('sampled_at', now))
            if timeline != self.last_timeline:
                path = self.root / 'state/media-timeline.json'
                temporary = path.with_suffix('.tmp')
                temporary.write_text(json.dumps(timeline))
                temporary.replace(path)
                self.last_timeline = timeline
            uri = media.get('uri', '')
            if playing and 'spotify' in media.get('player', '').lower() and uri and uri != self.spotify_uri:
                path = self.root / 'state/spotify-last.json'
                path.write_text(json.dumps({'uri': uri}))
                path.chmod(0o600)
                self.spotify_uri = uri
        changed = {key: value for key, value in self.values.items() if self.sent.get(key) != value}
        if changed and self.publisher is None:
            self.batch = changed
            self.publisher = asyncio.create_task(self.publish(changed))

    async def close(self):
        tasks = [*self.running.values(), *([self.publisher] if self.publisher is not None else [])]
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)


async def main(root=ROOT):
    root.mkdir(parents=True, exist_ok=True)
    with (root / '.refresh.lock').open('w') as lock:
        while True:
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                await asyncio.sleep(0.1)
        stop = asyncio.Event()
        loop = asyncio.get_running_loop()
        for signum in (signal.SIGINT, signal.SIGTERM):
            loop.add_signal_handler(signum, stop.set)
        scheduler = Scheduler(root)
        state, next_state, previous = {}, 0, None
        previous_gate = None
        previous_source = None
        try:
            while not stop.is_set():
                now = time.monotonic()
                if now >= next_state:
                    state = battery_state(with_estimate=False)
                    next_state = now + 1
                try:
                    visible = (root / 'state/home-visible').read_text().strip() != 'false'
                except OSError:
                    visible = True
                active = visible or not state.get('on_battery', False)
                if active != previous_gate or state.get('on_battery', False) != previous_source:
                    path = root / 'state/refresh-paused'
                    path.parent.mkdir(parents=True, exist_ok=True)
                    temporary = path.with_suffix('.tmp')
                    temporary.write_text('false' if active else 'true')
                    temporary.replace(path)
                    (path.parent / 'on-battery').write_text('true' if state.get('on_battery') else 'false')
                    if await scheduler.send({'refresh_allowed': active}):
                        previous_gate = active
                        previous_source = state.get('on_battery', False)
                await scheduler.step(now, state.get('on_battery', False), visible)
                status = 'active' if active else 'hidden'
                if status != previous:
                    print(status, flush=True)
                    previous = status
                deadlines = [value for key, value in scheduler.due.items() if key not in scheduler.running]
                delay = min(1, max(0.02, min(deadlines, default=now + 1) - now)) if active else 1
                pending = [task for task in scheduler.running.values() if not task.done()]
                if scheduler.publisher is not None and not scheduler.publisher.done():
                    pending.append(scheduler.publisher)
                waiter = asyncio.create_task(stop.wait())
                try:
                    await asyncio.wait([waiter, *pending], timeout=delay, return_when=asyncio.FIRST_COMPLETED)
                finally:
                    waiter.cancel()
                    await asyncio.gather(waiter, return_exceptions=True)
        finally:
            await scheduler.close()


if __name__ == '__main__':
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, BrokenPipeError):
        pass
