"""Prevent invisible dashboards and stale workspace state during IPC recovery."""
import contextlib
import importlib.util
import io
import os
import fcntl
import signal
from pathlib import Path
import json
import subprocess
import tempfile
import unittest
from unittest.mock import MagicMock, patch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('workspace_state', ROOT / 'apps/shared/workspace-state.py')
workspace = importlib.util.module_from_spec(spec)
spec.loader.exec_module(workspace)


def monitor(identifier=7, name='eDP-1', active=1, focused=False, special=0, dpms=True):
    return {'id': identifier, 'name': name, 'focused': focused,
            'activeWorkspace': {'id': active, 'name': str(active)},
            'specialWorkspace': {'id': special, 'name': '' if special == 0 else 'scratchpad'},
            'dpmsStatus': dpms}


class MonitorVisibility(unittest.TestCase):
    def test_nonzero_monitor_ids_and_unfocused_home_are_visible(self):
        self.assertTrue(workspace.visible([monitor(identifier=42, focused=False)]))

    def test_monitor_selection_uses_array_index_or_connector_name(self):
        monitors = [monitor(identifier=8, name='DP-1', active=2), monitor(identifier=3)]
        self.assertFalse(workspace.visible(monitors, 0))
        self.assertTrue(workspace.visible(monitors, 1))
        self.assertTrue(workspace.visible(monitors, 'eDP-1'))
        self.assertFalse(workspace.visible(monitors, 'disconnected-monitor'))

    def test_other_workspaces_special_workspaces_and_dpms_are_hidden(self):
        self.assertFalse(workspace.visible([monitor(active=2)]))
        self.assertFalse(workspace.visible([monitor(special=-99)]))
        self.assertFalse(workspace.visible([monitor(dpms=False)]))

    def test_missing_special_workspace_is_not_treated_as_active(self):
        item = monitor()
        del item['specialWorkspace']
        self.assertTrue(workspace.visible([item]))

    def test_incomplete_monitor_data_is_unknown(self):
        for monitors in ([], None, [{}], [{'activeWorkspace': None}]):
            with self.subTest(monitors=monitors):
                self.assertIsNone(workspace.visible(monitors))


class ReturnHome(unittest.TestCase):
    def test_last_window_returns_to_home_without_requiring_focus_of_a_new_app(self):
        with patch.object(workspace.subprocess, 'run', side_effect=[
                subprocess.CompletedProcess([], 0, '[]'),
                subprocess.CompletedProcess([], 0, '{"id":2}'),
                subprocess.CompletedProcess([], 0, 'ok')]) as run:
            self.assertTrue(workspace.return_home_if_empty(Path('/unused')))
            self.assertIn('workspace="1"', run.call_args.args[0][-1])

    def test_other_workspace_windows_and_ipc_failure_do_not_move_the_user(self):
        with patch.object(workspace.subprocess, 'run', return_value=subprocess.CompletedProcess([], 0, '[{"mapped":true}]')) as run:
            self.assertFalse(workspace.return_home_if_empty(Path('/unused')))
            self.assertEqual(run.call_count, 1)
        with patch.object(workspace.subprocess, 'run', side_effect=OSError):
            self.assertFalse(workspace.return_home_if_empty(Path('/unused')))

    def test_already_on_workspace_one_does_not_dispatch_again(self):
        with patch.object(workspace.subprocess, 'run', side_effect=[
                subprocess.CompletedProcess([], 0, '[]'),
                subprocess.CompletedProcess([], 0, '{"id":1}')]) as run:
            self.assertFalse(workspace.return_home_if_empty(Path('/unused')))
            self.assertEqual(run.call_count, 2)


class ObserverRecovery(unittest.TestCase):
    def test_unknown_readings_keep_last_confirmed_state(self):
        output = io.StringIO()
        with patch.object(workspace, 'query', side_effect=[None, False, None, True, None]), contextlib.redirect_stdout(output):
            observer = workspace.Observer(Path('/unused'))
            for _ in range(5):
                observer.refresh()
        self.assertEqual(output.getvalue().splitlines(), ['true', 'false', 'true'])

    def test_socket_failure_does_not_hide_a_visible_dashboard(self):
        connection = MagicMock()
        connection.connect.side_effect = OSError('event socket not ready')
        manager = MagicMock()
        manager.__enter__.return_value = connection
        output = io.StringIO()
        with patch.dict(os.environ, {'XDG_RUNTIME_DIR': '/unused', 'HYPRLAND_INSTANCE_SIGNATURE': 'fixture'}), \
                patch.object(workspace, 'query', return_value=True), \
                patch.object(workspace.socket, 'socket', return_value=manager), \
                patch.object(workspace.time, 'sleep', side_effect=KeyboardInterrupt), contextlib.redirect_stdout(output):
            with self.assertRaises(KeyboardInterrupt):
                workspace.listen(Path('/unused'))
        self.assertEqual(output.getvalue(), 'true\n')

    def test_idle_event_socket_rechecks_state_to_recover_missed_events(self):
        manager = MagicMock()
        output = io.StringIO()
        with patch.dict(os.environ, {'XDG_RUNTIME_DIR': '/unused', 'HYPRLAND_INSTANCE_SIGNATURE': 'fixture'}), \
                patch.object(workspace, 'query', side_effect=[False, False, True, KeyboardInterrupt]), \
                patch.object(workspace.socket, 'socket', return_value=manager), \
                patch.object(workspace.select, 'select', return_value=([], [], [])), contextlib.redirect_stdout(output):
            with self.assertRaises(KeyboardInterrupt):
                workspace.listen(Path('/unused'))
        self.assertEqual(output.getvalue().splitlines(), ['false', 'true'])


class SurfaceVisibility(unittest.TestCase):
    def test_eww_autostart_does_not_keep_the_startup_lock(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            root = home / 'dashboard'
            (root / 'scripts').mkdir(parents=True)
            script = root / 'scripts/start.sh'
            script.write_text((ROOT / 'apps/poedash/assets/scripts/start.sh').read_text())
            (root / 'poedash.py').write_text('')
            binaries = home / 'bin'
            binaries.mkdir()
            fake_eww = binaries / 'eww'
            fake_eww.write_text('''#!/usr/bin/env python3
import os, subprocess, sys
if sys.argv[-2:] == ['open', 'dashboard']:
    child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(30)'],
                             close_fds=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    with open(os.environ['DAEMON_PID'], 'w') as stream:
        stream.write(str(child.pid))
''')
            fake_eww.chmod(0o755)
            (binaries / 'sleep').write_text('#!/bin/sh\nexit 0\n')
            (binaries / 'sleep').chmod(0o755)
            pid_path = home / 'daemon.pid'
            env = dict(os.environ, HOME=str(home), XDG_CACHE_HOME=str(home / '.cache'),
                       DAEMON_PID=str(pid_path), PATH=str(binaries) + os.pathsep + os.environ['PATH'])
            try:
                subprocess.run(['bash', str(script)], env=env, check=True, timeout=10)
                with (home / '.cache/poedash/start.lock').open() as lock:
                    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            finally:
                if pid_path.exists():
                    os.kill(int(pid_path.read_text()), signal.SIGTERM)

    def test_refresh_recreates_only_its_own_dashboard_surface(self):
        for relative in ('apps/poedash/assets',):
            with self.subTest(relative=relative), tempfile.TemporaryDirectory() as tmp:
                home = Path(tmp)
                root = home / 'config with spaces'
                (root / 'scripts').mkdir(parents=True)
                script = root / 'scripts/start.sh'
                script.write_text((ROOT / relative / 'scripts/start.sh').read_text())
                (root / 'poedash.py').write_text('')
                binaries = home / 'bin'
                binaries.mkdir()
                log = home / 'commands.jsonl'
                fake_eww = binaries / 'eww'
                fake_eww.write_text('#!/usr/bin/env python3\nimport json, os, sys\n'
                                    'with open(os.environ["COMMAND_LOG"], "a") as stream:\n'
                                    '    stream.write(json.dumps(sys.argv[1:]) + "\\n")\n')
                fake_eww.chmod(0o755)
                (binaries / 'sleep').write_text('#!/bin/sh\nexit 0\n')
                (binaries / 'sleep').chmod(0o755)
                env = dict(os.environ, HOME=str(home), XDG_CACHE_HOME=str(home / '.cache'),
                           XDG_RUNTIME_DIR=str(home), COMMAND_LOG=str(log),
                           PATH=str(binaries) + os.pathsep + os.environ['PATH'])
                subprocess.run(['bash', str(script)], env=env, check=True, timeout=10)
                commands = [json.loads(line) for line in log.read_text().splitlines()]
                self.assertTrue(all(command[:2] == ['--config', str(root)] for command in commands))
                self.assertEqual([command[2:] for command in commands],
                                 [['ping'], ['reload'], ['close', 'dashboard'],
                                  ['active-windows'], ['open', 'dashboard']])

    def test_both_dashboards_hide_widgets_instead_of_making_them_transparent(self):
        for relative in ('apps/poedash/assets/templates',):
            with self.subTest(relative=relative):
                root = ROOT / relative
                yuck = (root / 'eww.yuck').read_text()
                css = (root / 'eww.scss').read_text()
                self.assertIn(':visible home_visible', yuck)
                self.assertIn('workspace.py --listen', yuck)
                self.assertIn(':stacking "bottom"', yuck)
                self.assertNotIn('dashboard-away', yuck + css)
                self.assertNotRegex(css, r'\.dashboard-(?:surface|panel)[^{]*\{[^}]*opacity:\s*0;')


if __name__ == '__main__':
    unittest.main()
