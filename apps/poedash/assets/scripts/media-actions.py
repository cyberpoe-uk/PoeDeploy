#!/usr/bin/env python3
"""Seek and resume Spotify without taking focus from the dashboard."""
import argparse
import configparser
import fcntl
import json
import math
import os
from pathlib import Path
import shlex
import shutil
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parent.parent


def call(*argv):
    return subprocess.run(argv, capture_output=True, text=True, check=True, timeout=3).stdout.strip()


def notify(message):
    if shutil.which('notify-send'):
        subprocess.run(['notify-send', 'PoeDash player', message], check=False, timeout=3)


def players():
    try:
        names = call('playerctl', '-l').splitlines()
    except (OSError, subprocess.SubprocessError):
        return []
    result = []
    for name in names:
        try:
            result.append((name, call('playerctl', '-p', name, 'status')))
        except (OSError, subprocess.SubprocessError):
            continue
    return result


def seek(percent):
    value = float(percent)
    if not math.isfinite(value):
        raise ValueError('Invalid seek position')
    items = players()
    if not items:
        return
    name = next((name for name, status in items if status == 'Playing'), items[0][0])
    length = float(call('playerctl', '-p', name, 'metadata', 'mpris:length')) / 1_000_000
    if not math.isfinite(length) or length <= 0:
        return  # Live streams and players without a known duration cannot seek.
    seconds = length * min(100, max(0, value)) / 100
    call('playerctl', '-p', name, 'position', f'{seconds:.3f}')


def spotify_entry():
    roots = [Path(os.environ.get('XDG_DATA_HOME', Path.home() / '.local/share'))]
    roots += [Path(p) for p in os.environ.get('XDG_DATA_DIRS', '/usr/local/share:/usr/share').split(':') if p]
    roots += [Path.home() / '.local/share/flatpak/exports/share', Path('/var/lib/flatpak/exports/share')]
    for root in roots:
        for name in ('spotify.desktop', 'spotify-launcher.desktop', 'com.spotify.Client.desktop'):
            path = root / 'applications' / name
            if path.is_file():
                parser = configparser.ConfigParser(interpolation=None, strict=False)
                try:
                    parser.read(path)
                    if not parser['Desktop Entry'].getboolean('Hidden', False):
                        return path
                except (OSError, configparser.Error, KeyError, ValueError):
                    pass
    return None


def launch_spotify():
    entry = spotify_entry()
    if entry:
        command = shlex.join(['gio', 'launch', str(entry)])
    elif shutil.which('spotify'):
        command = 'spotify'
    elif shutil.which('spotify-launcher'):
        command = 'spotify-launcher'
    else:
        if not shutil.which('rofi'):
            notify('Spotify is not installed. Open Packages and search for Spotify.')
            return False
        answer = subprocess.run(['rofi', '-dmenu', '-no-custom', '-format', 'i', '-p', 'Spotify',
                                 '-mesg', 'Spotify is not installed. Open package search to choose a version?'],
                                input='Cancel\nChoose Spotify package\n', capture_output=True, text=True)
        if answer.returncode == 0 and answer.stdout.strip() == '1':
            subprocess.Popen([sys.executable, str(ROOT / 'scripts/packages.py'), 'launch', '--query', 'spotify'],
                             start_new_session=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return False
    # Exec rules apply only to this launch, leaving existing window rules intact.
    expression = 'hl.dispatch(hl.dsp.exec_cmd(' + json.dumps(command, ensure_ascii=False) + ', {workspace="2 silent"}))'
    try:
        output = call('hyprctl', 'eval', expression)
        if 'error' in output.lower():
            raise RuntimeError(output)
    except (OSError, RuntimeError, subprocess.SubprocessError):
        try:
            call('hyprctl', 'dispatch', 'exec', '[workspace 2 silent] ' + command)
        except (OSError, subprocess.SubprocessError):
            notify('Spotify could not launch in the background. Open it once, then press Play.')
            return False
    return True


def resume_spotify():
    existing = any(name.lower().startswith('spotify') for name, _ in players())
    if not existing and not launch_spotify():
        return False
    try:
        saved = json.loads((ROOT / 'state/spotify-last.json').read_text())
        saved = saved.get('uri', '') if isinstance(saved, dict) else ''
    except (OSError, ValueError):
        saved = ''
    if not isinstance(saved, str) or not saved.startswith(('spotify:track:', 'spotify:playlist:', 'https://open.spotify.com/')):
        saved = ''
    opened = False
    seen = False
    for _ in range(60):
        for name, status in players():
            if not name.lower().startswith('spotify'):
                continue
            seen = True
            if status == 'Playing':
                return True
            # Spotify advertises MPRIS before playback is ready. A failed Play
            # must not abort startup or prevent restoring the saved context.
            try:
                call('playerctl', '-p', name, 'play')
            except (OSError, subprocess.SubprocessError):
                pass
            time.sleep(.5)
            try:
                if call('playerctl', '-p', name, 'status') == 'Playing':
                    return True
                if saved and not opened:
                    call('playerctl', '-p', name, 'open', saved)
                    opened = True
            except (OSError, subprocess.SubprocessError):
                continue
        time.sleep(.5)
    if seen and not saved:
        notify('Spotify opened. Sign in and play a track once so it has a saved playback context.')
    else:
        notify('Spotify is starting or needs sign-in. Press Play again when it is ready.')
    return False


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('seek', 'resume'))
    parser.add_argument('position', nargs='?')
    args = parser.parse_args()
    if args.action == 'seek':
        if args.position is None: parser.error('seek requires a percentage')
        seek(args.position)
    else:
        state = ROOT / 'state'
        state.mkdir(parents=True, exist_ok=True)
        with (state / '.spotify-launch.lock').open('w') as lock:
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                return
            resume_spotify()


if __name__ == '__main__':
    try:
        main()
    except (OSError, ValueError, subprocess.SubprocessError) as exc:
        notify(str(exc))
