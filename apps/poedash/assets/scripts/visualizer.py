#!/usr/bin/env python3
"""Output-monitor audio wave for Eww. No microphone capture or saved audio."""
import array
import asyncio
import json
import math
import os
from pathlib import Path
import re
import shutil
import signal
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parent.parent
BARS = 32


def flag(path, default=False):
    try:
        return path.read_text().strip() == 'true'
    except OSError:
        return default


def pcm_levels(data):
    samples = array.array('h')
    samples.frombytes(data[:len(data) // 2 * 2])
    if sys.byteorder != 'little': samples.byteswap()
    width = max(1, len(samples) // BARS)
    return [min(100, math.sqrt(sum(float(x) ** 2 for x in samples[i * width:(i + 1) * width])
                               / max(1, len(samples[i * width:(i + 1) * width]))) / 32768 * 300)
            for i in range(BARS)]


def smooth(values, previous):
    return [max(0, min(100, .45 * new + .55 * old)) for new, old in zip(values, previous)]


def svg(values, color='#89b4fa', width=320, height=32, progress=100):
    # Every ridge closes against the same fixed floor. Offset audio samples
    # give overlapping peaks without inventing motion when the output is silent.
    def ridge(offset, gain):
        levels = values or [0, 0]
        points = [(0, 30)] + [
            (i * 320 / max(1, len(levels) - 1),
             30 - max(0, min(100, levels[(i + offset) % len(levels)])) * gain)
            for i in range(len(levels))] + [(320, 30)]
        path = f'M {points[0][0]:.2f},{points[0][1]:.2f}'
        for i in range(1, len(points) - 1):
            x, y = points[i]
            after = points[i + 1]
            path += f' Q {x:.2f},{y:.2f} {(x + after[0]) / 2:.2f},{(y + after[1]) / 2:.2f}'
        return path + ' T 320,30 L 0,30 Z'

    played = min(320, max(0, float(progress) * 3.2))
    palette = ['#ef4444', '#a855f7', '#facc15', '#3b82f6', '#ffffff', '#000000', '#fb923c']
    definitions, layers = [], []
    for layer, (offset, gain, opacity) in enumerate(((0, .28, .65), (7, .22, .7), (15, .15, .85))):
        stops = ''.join(f'<stop offset="{i / (len(palette) - 1):.3f}" stop-color="{palette[(i + layer * 2) % len(palette)]}"/>'
                        for i in range(len(palette)))
        definitions.append(f'<linearGradient id="ridge{layer}" gradientUnits="userSpaceOnUse" x1="0" x2="{max(1, played):.2f}">{stops}</linearGradient>')
        layers.append(f'<path d="{ridge(offset, gain)}" fill="url(#ridge{layer})" fill-opacity="{opacity}" '
                      f'stroke="url(#ridge{layer})" stroke-width=".7" vector-effect="non-scaling-stroke"/>')
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 320 32" width="{int(width)}" height="{int(height)}" preserveAspectRatio="none">'
            '<defs>' + ''.join(definitions) +
            f'<clipPath id="played"><rect width="{played:.2f}" height="32"/></clipPath></defs>'
            f'<path d="M0 30 H320" stroke="{color}" stroke-opacity=".18"/>'
            '<g clip-path="url(#played)">' + ''.join(layers) + '</g></svg>')


def song_progress(timeline, now):
    length = timeline.get('length', 0)
    if length > 0:
        elapsed = min(3, max(0, now - timeline.get('sampled', now))) if timeline.get('playing') else 0
        return min(100, max(0, (timeline.get('position', 0) + elapsed) / length * 100))
    return min(100, max(0, timeline.get('progress', 0)))


def audio_command(directory, fps, prefer_cava=True):
    if prefer_cava and shutil.which('cava'):
        config = directory / 'cava.conf'
        config.write_text(f'[general]\nframerate={fps}\nbars={BARS}\nsleep_timer=1\n'
                          '[input]\nmethod=pulse\nsource=auto\n[output]\nmethod=raw\n'
                          'raw_target=/dev/stdout\ndata_format=ascii\nascii_max_range=100\n'
                          'bar_delimiter=59\nframe_delimiter=10\nchannels=mono\n[smoothing]\nnoise_reduction=75\n')
        return ['cava', '-p', str(config)], 'Cava output monitor'
    if shutil.which('parec'):
        return ['parec', '--device=@DEFAULT_MONITOR@', '--raw', '--format=s16le',
                '--rate=16000', '--channels=1', '--latency-msec=50'], 'PulseAudio output monitor'
    return None, 'Install libpulse or cava for audio visualization'


async def main(root=ROOT, native=False):
    runtime = os.environ.get('XDG_RUNTIME_DIR')
    directory = Path(runtime) / 'poedash-wave' if runtime else Path(tempfile.mkdtemp(prefix='poedash-wave-'))
    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT): loop.add_signal_handler(sig, stop.set)
    previous, frame, emitted = [0.0] * BARS, 0, None
    process, mode, backend = None, None, ''
    prefer_cava = True
    next_state = 0
    allowed, playing, battery = False, False, False
    command, backend_name, backend_fps = None, '', None
    next_backend, next_theme, restart_after = 0, 0, 0
    accent = '#89b4fa'
    dimensions = {'width': 320, 'height': 32}
    peak_reference = 1.0
    timeline = {}
    try:
        while not stop.is_set():
            now = time.monotonic()
            if now >= next_state:
                allowed = not flag(root / 'state/refresh-paused') and (not native or flag(root / 'state/home-visible', True))
                playing = flag(root / 'state/media-playing')
                battery = flag(root / 'state/on-battery')
                try:
                    timeline = json.loads((root / 'state/media-timeline.json').read_text())
                except (OSError, ValueError):
                    pass
                next_state = now + .5
            fps = (10 if battery else 15) if native else (12 if battery else 24)
            desired = fps if allowed and playing else None
            if process and (desired != mode or process.returncode is not None):
                if process.returncode is None:
                    process.terminate()
                    try: await asyncio.wait_for(process.wait(), 1)
                    except asyncio.TimeoutError:
                        process.kill(); await process.wait()
                elif backend.startswith('Cava'):
                    next_backend = 0
                    prefer_cava = False  # Fall back when Cava lacks PulseAudio support.
                if process.returncode and not backend.startswith('Cava'):
                    restart_after = now + 5
                process = None
            if now >= next_backend or fps != backend_fps:
                command, backend_name = audio_command(directory, fps, prefer_cava)
                next_backend, backend_fps = now + 30, fps
            if desired and process is None and command and now >= restart_after:
                process = await asyncio.create_subprocess_exec(*command, stdout=asyncio.subprocess.PIPE,
                                                               stderr=asyncio.subprocess.DEVNULL)
                mode, backend = desired, backend_name
            if not allowed:
                await asyncio.sleep(.5)
                continue  # Freeze the UI and release the audio monitor on battery.
            values = [0.0] * BARS
            if desired and process:
                try:
                    if backend.startswith('Cava'):
                        raw = await asyncio.wait_for(process.stdout.readline(), .3)
                        if not raw: raise asyncio.IncompleteReadError(raw, 1)
                        values = [float(x) for x in raw.decode().strip(';\n').split(';')][:BARS]
                        values += [0.0] * (BARS - len(values))
                    else:
                        raw = await asyncio.wait_for(process.stdout.readexactly(2 * (16000 // fps)), .3)
                        values = pcm_levels(raw)
                        peak_reference = max(max(values), peak_reference * .995, .05)
                        values = [min(100, value / peak_reference * 80) if value > .02 else 0 for value in values]
                except asyncio.TimeoutError:
                    continue
                except (ValueError, asyncio.IncompleteReadError):
                    await asyncio.sleep(.5)
                    continue
            previous = smooth(values, previous) if desired else values
            if now >= next_theme:
                try:
                    theme = (root / 'colors.scss').read_text()
                except OSError:
                    theme = ''
                color = re.search(r'\$accent:\s*(#[0-9a-fA-F]{6})', theme)
                accent = color[1] if color else '#89b4fa'
                try:
                    dimensions = json.loads((root / 'state/wave-size.json').read_text())
                except (OSError, ValueError):
                    pass
                next_theme = now + 2
            active = bool(desired and process)
            if native:
                payload = dict(values=previous, progress=song_progress(timeline, now),
                               active=bool(desired and process), available=bool(command), backend=backend_name)
                document = json.dumps(payload)
                if document != emitted:
                    print(document, flush=True)
                    emitted = document
            else:
                document = svg(previous, accent, dimensions.get('width', 320), dimensions.get('height', 32), song_progress(timeline, now))
                frame_path = directory / f'wave-{frame % 4}.svg'
                active = bool(desired and process)
                payload = dict(path=str(frame_path), active=active, available=bool(command), backend=backend_name)
                if active or document != emitted:
                    temporary = frame_path.with_suffix('.tmp')
                    temporary.write_text(document)
                    temporary.replace(frame_path)
                    print(json.dumps(payload), flush=True)
                    emitted = document
                    frame += 1
            await asyncio.sleep(0 if active and not backend.startswith('Cava') else 1 / fps if active else .5)
    finally:
        if process and process.returncode is None:
            process.terminate()
            try: await asyncio.wait_for(process.wait(), 1)
            except asyncio.TimeoutError:
                process.kill(); await process.wait()
        for path in directory.glob('wave-*.svg'): path.unlink(missing_ok=True)


if __name__ == '__main__':
    try:
        asyncio.run(main(native='--native' in sys.argv))
    except (OSError, BrokenPipeError, KeyboardInterrupt):
        pass
