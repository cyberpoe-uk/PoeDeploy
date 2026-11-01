"""Application history, safe desktop activation and the playing application's UI."""
import importlib.util
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('dashboard_desktop', ROOT / 'apps/shared/desktop-actions.py')
desktop = importlib.util.module_from_spec(spec)
spec.loader.exec_module(desktop)


def app(name):
    return {'id': name + '.desktop', 'name': name.title(), 'icon': name,
            'path': '/applications/' + name + '.desktop', 'aliases': {name}, 'calendar': False}


def window(name, order=0, address='0x123'):
    return {'class': name, 'initialClass': name, 'address': address, 'focusHistoryID': order,
            'title': 'Private document title that must never be stored'}


class DesktopEntries(unittest.TestCase):
    def test_user_entries_override_system_and_hidden_entries_mask_them(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            user, system = root / 'user', root / 'system'
            for base in (user, system):
                (base / 'applications').mkdir(parents=True)
            def entry(base, name, extra=''):
                (base / 'applications' / (name + '.desktop')).write_text(
                    '[Desktop Entry]\nType=Application\nName=' + base.name + '\nExec=/bin/true %U\n' + extra)
            entry(system, 'example')
            entry(user, 'example', 'StartupWMClass=ExampleWindow\n')
            entry(system, 'masked')
            entry(user, 'masked', 'Hidden=true\n')
            entry(user, 'hidden', 'NoDisplay=true\n')
            entry(user, 'bad;id')
            with patch.dict(os.environ, {'XDG_DATA_HOME': str(user), 'XDG_DATA_DIRS': str(system)}):
                apps = desktop.applications()
            self.assertEqual(apps['example.desktop']['name'], 'user')
            self.assertEqual(desktop.match_app(apps, 'EXAMPLEWINDOW')['id'], 'example.desktop')
            self.assertNotIn('masked.desktop', apps)
            self.assertNotIn('hidden.desktop', apps)
            self.assertNotIn('bad;id.desktop', apps)


class RecentApplications(unittest.TestCase):
    def test_pins_persist_above_recents_and_right_click_unpins_them(self):
        apps = {name + '.desktop': app(name) for name in ('firefox', 'code')}
        with tempfile.TemporaryDirectory() as tmp, patch.object(desktop, 'STATE', Path(tmp) / 'recent.json'), \
                patch.object(desktop, 'clients', return_value=[window('code'), window('firefox', 1)]):
            desktop.toggle_pin('firefox.desktop')
            data = desktop.app_lists(apps)
            self.assertEqual([item['id'] for item in data['pinned']], ['firefox.desktop'])
            self.assertEqual([item['id'] for item in data['recent']], ['code.desktop'])
            self.assertEqual(desktop.STATE.with_name('pinned-apps.json').stat().st_mode & 0o777, 0o600)
            desktop.toggle_pin('firefox.desktop')
            data = desktop.app_lists(apps)
            self.assertEqual(data['pinned'], [])
            self.assertEqual([item['id'] for item in data['recent']], ['code.desktop', 'firefox.desktop'])

    def test_history_remembers_closed_apps_deduplicates_and_stores_only_ids(self):
        apps = {name + '.desktop': app(name) for name in ('firefox', 'code', 'spotify')}
        with tempfile.TemporaryDirectory() as tmp, patch.object(desktop, 'STATE', Path(tmp) / 'recent.json'):
            with patch.object(desktop, 'clients', return_value=[window('firefox'), window('code', 1)]):
                self.assertEqual([item['id'] for item in desktop.recent(apps)], ['firefox.desktop', 'code.desktop'])
            with patch.object(desktop, 'clients', return_value=[window('spotify'), window('code', 1)]):
                self.assertEqual([item['id'] for item in desktop.recent(apps)],
                                 ['spotify.desktop', 'firefox.desktop', 'code.desktop'])
            content = desktop.STATE.read_text()
            self.assertNotIn('Private', content)
            self.assertEqual(json.loads(content), ['spotify.desktop', 'firefox.desktop', 'code.desktop'])
            self.assertEqual(desktop.STATE.stat().st_mode & 0o777, 0o600)
            with patch.object(desktop, 'clients', return_value=[]):
                self.assertEqual(desktop.recent(apps)[0]['id'], 'spotify.desktop')
                del apps['spotify.desktop']
                self.assertNotIn('spotify.desktop', [item['id'] for item in desktop.recent(apps)])

    def test_broken_history_and_unavailable_compositor_are_tolerated(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(desktop, 'STATE', Path(tmp) / 'recent.json'):
            desktop.STATE.write_text('{broken')
            with patch.object(desktop, 'call', side_effect=OSError('no IPC')):
                self.assertEqual(desktop.recent({}), [])
            desktop.STATE.write_text('["example.desktop", "; command", 123]')
            self.assertEqual(desktop.history(), ['example.desktop'])


class Activation(unittest.TestCase):
    def test_existing_window_is_focused_without_launching_a_duplicate(self):
        with patch.object(desktop, 'clients', return_value=[window('firefox')]), \
                patch.object(desktop, 'call', return_value='ok') as command, \
                patch.object(desktop, 'remember') as remember:
            desktop.launch(app('firefox'))
        self.assertEqual(command.call_args.args, ('hyprctl', 'eval', 'hl.dispatch(hl.dsp.focus({window = "address:0x123"}))'))
        remember.assert_called_once_with(['firefox.desktop'])

    def test_closed_app_launches_via_gio_on_a_free_non_home_workspace(self):
        commands = []
        def call(*argv):
            commands.append(argv)
            if argv[1:3] == ('activeworkspace', '-j'):
                return '{"id":1}'
            if argv[1:3] == ('workspaces', '-j'):
                return '[{"id":1},{"id":2},{"id":4}]'
            return 'ok'
        with patch.object(desktop, 'clients', return_value=[]), \
                patch.object(desktop, 'call', side_effect=call), \
                patch.object(desktop, 'start', side_effect=call), patch.object(desktop, 'remember'):
            desktop.launch(app('firefox'))
        self.assertIn(('hyprctl', 'eval', 'hl.dispatch(hl.dsp.focus({workspace = "3"}))'), commands)
        self.assertEqual(commands[-1], ('gio', 'launch', '/applications/firefox.desktop'))

    def test_gui_child_does_not_keep_the_launch_action_waiting_on_output_pipes(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            launcher = root / 'gio'
            pidfile = root / 'child.pid'
            launcher.write_text('#!' + sys.executable + '\nimport subprocess, sys\n'
                                'from pathlib import Path\n'
                                'child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(15)"])\n'
                                'Path(' + repr(str(pidfile)) + ').write_text(str(child.pid))\n')
            launcher.chmod(0o755)
            try:
                with patch.dict(os.environ, {'PATH': str(root) + os.pathsep + os.environ['PATH']}), \
                        patch.object(desktop, 'focus', return_value=False), \
                        patch.object(desktop, 'leave_home'), patch.object(desktop, 'remember'):
                    desktop.launch(app('firefox'))
                self.assertTrue(pidfile.exists())
            finally:
                if pidfile.exists():
                    try:
                        os.kill(int(pidfile.read_text()), signal.SIGTERM)
                    except ProcessLookupError:
                        pass

    def test_playing_player_wins_and_its_window_is_opened(self):
        def call(*argv):
            if argv == ('playerctl', '-l'):
                return 'spotify\nfirefox.instance123'
            if argv[0] == 'playerctl':
                return 'Playing' if argv[2].startswith('firefox') else 'Paused'
            return 's "firefox"'
        apps = {'firefox.desktop': app('firefox'), 'spotify.desktop': app('spotify')}
        with patch.object(desktop, 'call', side_effect=call), \
                patch.object(desktop, 'focus', return_value=True) as focus, patch.object(desktop, 'remember'):
            desktop.open_player(apps)
            focus.assert_called_once_with(apps['firefox.desktop'])

    def test_mpris_raise_handles_players_without_matching_desktop_entries(self):
        def call(*argv):
            if argv[-1] == 'CanRaise':
                return 'b true'
            if argv[-1] == 'DesktopEntry':
                return 's "unknown"'
            return ''
        with patch.object(desktop, 'selected_player', return_value='custom.instance'), \
                patch.object(desktop, 'call', side_effect=call) as command:
            desktop.open_player({})
        self.assertEqual(command.call_args.args[-1], 'Raise')
        self.assertIn('org.mpris.MediaPlayer2.custom.instance', command.call_args.args)

    def test_calendar_opens_thunderbird_and_targets_only_its_calendar_tab(self):
        with tempfile.TemporaryDirectory() as tmp, \
                patch.object(desktop, 'launch') as launch, \
                patch.object(desktop, 'clients', return_value=[window('firefox', address='0x999'), window('thunderbird')]), \
                patch.object(desktop, 'hypr_eval', return_value=True) as evaluate:
            thunderbird = app('thunderbird')
            desktop.open_calendar({'thunderbird.desktop': thunderbird}, Path(tmp))
            launch.assert_called_once_with(thunderbird)
            self.assertEqual(evaluate.call_args.args[0],
                             'hl.dispatch(hl.dsp.send_shortcut({window = "address:0x123", mods = "CTRL", key = "3"}))')

    def test_missing_player_and_calendar_give_useful_feedback(self):
        with tempfile.TemporaryDirectory() as tmp, \
                patch.object(desktop, 'selected_player', return_value=None), patch.object(desktop, 'notify') as notify:
            desktop.open_player({})
            self.assertIn('No player', notify.call_args.args[0])
            desktop.open_calendar({}, Path(tmp))
            self.assertIn('Thunderbird is not installed', notify.call_args.args[0])


if __name__ == '__main__':
    unittest.main()
