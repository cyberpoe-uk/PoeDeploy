"""Exercise media selection, controls, connectivity, and missing utilities."""
import contextlib
import importlib.util
import io
import json
import os
from pathlib import Path
import runpy
import subprocess
import tempfile
import unittest
from unittest.mock import patch

SCRIPTS = Path(__file__).resolve().parents[1] / 'dashboard/scripts'
spec = importlib.util.spec_from_file_location('pendash_media', SCRIPTS / 'media.py')
media = importlib.util.module_from_spec(spec)
spec.loader.exec_module(media)


class MediaTests(unittest.TestCase):
    def test_no_playerctl_or_players_returns_empty_state(self):
        with patch.object(media.shutil, 'which', return_value=None):
            self.assertEqual(media.reading(), media.EMPTY)
        with patch.object(media.shutil, 'which', return_value='/bin/playerctl'), \
                patch.object(media, 'call', return_value=''):
            self.assertEqual(media.reading(), media.EMPTY)

    def test_playing_player_wins_and_metadata_is_preserved(self):
        def call(*args):
            if args == ('-l',):
                return 'firefox.instance1\nspotify'
            if args[-1] == 'status':
                return 'Playing' if args[1] == 'spotify' else 'Paused'
            self.assertEqual(args[1], 'spotify')
            if args[-1] == 'position':
                return '60'
            return 'Song "one"\x1fArtist & guest\x1f120000000\x1ffile:///cover.png'
        with patch.object(media.shutil, 'which', return_value='/bin/playerctl'), \
                patch.object(media, 'call', side_effect=call), \
                patch.object(media, 'artwork', return_value='/cover.png'):
            data = media.reading()
        self.assertTrue(data['available'])
        self.assertEqual(data['title'], 'Song "one"')
        self.assertEqual(data['artist'], 'Artist & guest')
        self.assertEqual(data['player'], 'Spotify')
        self.assertEqual((data['position'], data['length'], data['progress']), ('1:00', '2:00', 50))
        self.assertEqual(data['art'], '/cover.png')

    def test_disappearing_player_and_live_stream_without_position(self):
        def call(*args):
            if args == ('-l',):
                return 'closed-player\nradio'
            if args[1] == 'closed-player' or args[-1] == 'position':
                raise subprocess.CalledProcessError(1, ['playerctl'])
            if args[-1] == 'status':
                return 'Paused'
            return 'Live radio\x1fStation\x1f\x1f'
        with patch.object(media.shutil, 'which', return_value='/bin/playerctl'), \
                patch.object(media, 'call', side_effect=call):
            data = media.reading()
        self.assertTrue(data['available'])
        self.assertEqual(data['title'], 'Live radio')
        self.assertEqual((data['position'], data['length'], data['progress']), ('0:00', '0:00', 0))

    def test_local_artwork_and_remote_cache(self):
        with tempfile.TemporaryDirectory() as tmp:
            cover = Path(tmp) / 'my cover.png'
            cover.write_bytes(b'cached artwork')
            self.assertEqual(media.artwork(cover.as_uri()), str(cover))
            self.assertEqual(media.artwork('file:///missing/cover.png'), '')
            self.assertEqual(media.artwork('javascript:invalid'), '')
            with patch.dict(os.environ, {'XDG_CACHE_HOME': tmp}), \
                    patch.object(media, 'urlopen') as download:
                download.return_value.__enter__.return_value.read.return_value = b'artwork'
                first = media.artwork('https://example.invalid/cover.png')
                self.assertEqual(Path(first).read_bytes(), b'artwork')
                self.assertEqual(media.artwork('https://example.invalid/cover.png'), first)
                download.assert_called_once()

    def test_controls_target_the_playing_player_and_handle_no_players(self):
        body = r'''
playerctl() {
    if [[ "$1" == -l ]]; then
        [[ "$no_players" == true ]] || printf 'firefox\nspotify\n'
    elif [[ "$3" == status ]]; then
        if [[ "$2" == spotify ]]; then echo Playing; else echo Paused; fi
    fi
}
export -f playerctl
source "$controller" "$action"
'''
        # The final exec must be a real command; use a fixture on PATH for it.
        with tempfile.TemporaryDirectory() as tmp:
            playerctl = Path(tmp) / 'playerctl'
            playerctl.write_text('#!/bin/sh\nprintf "%s\\n" "$@"\n')
            playerctl.chmod(0o755)
            for no_players in (False, True):
                for action in ('previous', 'play-pause', 'next'):
                    with self.subTest(no_players=no_players, action=action):
                        result = subprocess.run(['bash', '-c', body], capture_output=True, text=True,
                            check=True, timeout=5, env=os.environ | {
                                'PATH': tmp + os.pathsep + os.environ['PATH'],
                                'controller': str(SCRIPTS / 'media-control.sh'),
                                'action': action, 'no_players': str(no_players).lower()})
                        self.assertEqual(result.stdout.splitlines(), [] if no_players else ['-p', 'spotify', action])


class CollectorTests(unittest.TestCase):
    def collect(self, name, result=None, error=None):
        output = io.StringIO()
        with patch('subprocess.run', return_value=result, side_effect=error), contextlib.redirect_stdout(output):
            runpy.run_path(str(SCRIPTS / name), run_name='__main__')
        return json.loads(output.getvalue())

    def test_missing_utilities_have_readable_empty_states(self):
        self.assertEqual(self.collect('processes.py', error=FileNotFoundError()), [{'name': 'No process data available', 'pid': '', 'cpu': '', 'memory': ''}])
        self.assertEqual(self.collect('shares.py', error=FileNotFoundError()), ['No SMB or NFS shares mounted'])

    def test_processes_are_limited_and_exclude_the_collector(self):
        rows = ' 1 ps 0.0 0.0\n' + '\n'.join(f'{pid} app{pid} 5.0 1.2' for pid in range(2, 20))
        data = self.collect('processes.py', subprocess.CompletedProcess([], 0, rows))
        self.assertEqual(len(data), 10)
        self.assertEqual('app2', data[0]['name'])
        self.assertEqual('5.0%', data[0]['cpu'])
        self.assertEqual('1.2%', data[0]['memory'])

    def test_mounted_share_names_are_returned_as_text(self):
        mounts = {'filesystems': [{'fstype': 'cifs', 'source': '//nas/Team files', 'target': '/mnt/Team files'},
                                  {'fstype': 'nfs4', 'source': 'server:/export', 'target': '/mnt/nfs'}]}
        data = self.collect('shares.py', subprocess.CompletedProcess([], 0, json.dumps(mounts)))
        self.assertEqual(data, ['CIFS  /mnt/Team files  ←  //nas/Team files', 'NFS4  /mnt/nfs  ←  server:/export'])

    def test_network_route_and_tailscale_fallback(self):
        body = r'''
ip() {
    case "$*" in
        '-j -4 route get 1.1.1.1') printf '%s\n' "$route" ;;
        '-j -4 addr show dev eth0') echo '[{"addr_info":[{"scope":"global","local":"192.0.2.10"}]}]' ;;
        '-j -4 addr show dev tailscale0') echo '[{"addr_info":[{"scope":"global","local":"100.64.0.2"}]}]' ;;
    esac
}
timeout() { return 1; }
source "$collector"
'''
        for route in ('[{"dev":"eth0","prefsrc":"192.0.2.10"}]', '[{"dev":"eth0"}]', '[]'):
            with self.subTest(route=route):
                result = subprocess.run(['bash', '-c', body], capture_output=True, text=True,
                    check=True, timeout=5, env=os.environ | {'route': route, 'collector': str(SCRIPTS / 'network.sh')})
                data = json.loads(result.stdout)
                self.assertEqual(data['tailscale'], '100.64.0.2')
                self.assertEqual(data['state'], 'Offline' if route == '[]' else 'Connected')
                self.assertEqual(data['ip'], '--' if route == '[]' else '192.0.2.10')


if __name__ == '__main__':
    unittest.main()
