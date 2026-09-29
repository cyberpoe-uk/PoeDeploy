#!/usr/bin/env python3
"""Return the most relevant MPRIS player's state for the PoeDash media card."""
import json
import hashlib
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
from urllib.parse import unquote, urlparse
from urllib.request import Request, urlopen


EMPTY = {'available': False, 'player': 'No media', 'title': 'Nothing playing',
         'artist': '', 'status': 'Stopped', 'position': '0:00', 'length': '0:00',
         'progress': 0, 'icon': '♪', 'art': ''}


def call(*args):
    return subprocess.run(['playerctl', *args], capture_output=True, text=True,
                          timeout=2, check=True).stdout.strip()


def clock(microseconds):
    seconds = max(0, int(float(microseconds or 0) / 1_000_000))
    return f'{seconds // 60}:{seconds % 60:02d}'


def artwork(url):
    """Return a local artwork path, caching remote covers by their MPRIS URL."""
    if not url:
        return ''
    parsed = urlparse(url)
    if parsed.scheme == 'file':
        path = Path(unquote(parsed.path))
        return str(path) if path.is_file() else ''
    if parsed.scheme not in ('http', 'https'):
        return ''
    cache = Path(os.environ.get('XDG_CACHE_HOME', Path.home() / '.cache')) / 'poedash/artwork'
    cache.mkdir(parents=True, exist_ok=True)
    target = cache / ('cover-' + hashlib.sha256(url.encode()).hexdigest()[:20])
    if target.is_file() and target.stat().st_size:
        return str(target)
    temporary = None
    try:
        request = Request(url, headers={'User-Agent': 'PoeDash/1'})
        with urlopen(request, timeout=3) as response:
            content = response.read(5 * 1024 * 1024 + 1)
        if not content or len(content) > 5 * 1024 * 1024:
            return ''
        fd, temporary = tempfile.mkstemp(dir=cache, prefix='.cover-')
        with os.fdopen(fd, 'wb') as stream:
            stream.write(content)
        os.replace(temporary, target)
        for old in cache.glob('cover-*'):
            if old != target:
                old.unlink(missing_ok=True)
        return str(target)
    except (OSError, ValueError):
        if temporary:
            Path(temporary).unlink(missing_ok=True)
        return ''


data = dict(EMPTY)
if shutil.which('playerctl'):
    try:
        players = [name for name in call('-l').splitlines() if name]
        statuses = {name: call('-p', name, 'status') for name in players}
        player = next((name for name in players if statuses[name] == 'Playing'), players[0])
        fields = call('-p', player, 'metadata', '--format',
                      '{{title}}\u001f{{artist}}\u001f{{mpris:length}}\u001f{{mpris:artUrl}}').split('\x1f')
        title, artist, length, art_url = (fields + ['', '', '0', ''])[:4]
        position = float(call('-p', player, 'position') or 0)
        length_us = float(length or 0)
        data = {'available': True, 'player': player.split('.')[0].title(),
                'title': title or 'Unknown title', 'artist': artist,
                'status': statuses[player], 'position': clock(position * 1_000_000),
                'length': clock(length_us),
                'progress': min(100, round(position * 100_000_000 / length_us)) if length_us else 0,
                'icon': '' if 'spotify' in player.lower() else '♪',
                'art': artwork(art_url)}
    except (IndexError, OSError, ValueError, subprocess.SubprocessError):
        pass
print(json.dumps(data))
