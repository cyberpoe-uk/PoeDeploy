#!/usr/bin/env python3
"""Return the most relevant MPRIS player's state for the PoeDash media card."""
import json
import shutil
import subprocess


EMPTY = {'available': False, 'player': 'No media', 'title': 'Nothing playing',
         'artist': '', 'status': 'Stopped', 'position': '0:00', 'length': '0:00',
         'progress': 0, 'icon': '♪'}


def call(*args):
    return subprocess.run(['playerctl', *args], capture_output=True, text=True,
                          timeout=2, check=True).stdout.strip()


def clock(microseconds):
    seconds = max(0, int(float(microseconds or 0) / 1_000_000))
    return f'{seconds // 60}:{seconds % 60:02d}'


data = dict(EMPTY)
if shutil.which('playerctl'):
    try:
        players = [name for name in call('-l').splitlines() if name]
        statuses = {name: call('-p', name, 'status') for name in players}
        player = next((name for name in players if statuses[name] == 'Playing'), players[0])
        fields = call('-p', player, 'metadata', '--format',
                      '{{title}}\u001f{{artist}}\u001f{{mpris:length}}').split('\x1f')
        title, artist, length = (fields + ['', '', '0'])[:3]
        position = float(call('-p', player, 'position') or 0)
        length_us = float(length or 0)
        data = {'available': True, 'player': player.split('.')[0].title(),
                'title': title or 'Unknown title', 'artist': artist,
                'status': statuses[player], 'position': clock(position * 1_000_000),
                'length': clock(length_us),
                'progress': min(100, round(position * 100_000_000 / length_us)) if length_us else 0,
                'icon': '' if 'spotify' in player.lower() else '♪'}
    except (IndexError, OSError, ValueError, subprocess.SubprocessError):
        pass
print(json.dumps(data))
