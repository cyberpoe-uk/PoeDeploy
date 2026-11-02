import importlib.util
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1] / 'apps/poedash'
SCRIPT = next(REPO.glob('**/scripts/dashboard-control.py'))
spec = importlib.util.spec_from_file_location('control', SCRIPT)
c = importlib.util.module_from_spec(spec)
spec.loader.exec_module(c)

class DashboardControl(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        environment = patch.dict(os.environ, {'XDG_CONFIG_HOME': temporary.name})
        environment.start()
        self.addCleanup(environment.stop)
        home = patch.object(c.Path, 'home', return_value=Path(temporary.name))
        home.start()
        self.addCleanup(home.stop)

    def test_disable_enable_preserves_settings_and_scopes_eww(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / 'poedash'
            (root / 'scripts').mkdir(parents=True)
            (root / 'scripts/start.sh').write_text('#!/bin/sh\nexit 0\n')
            (root / 'settings.json').write_text('{"keep": true}')
            with patch.object(c.shutil, 'which', return_value='/bin/eww'), patch.object(c.subprocess, 'run') as run, patch.object(c.subprocess, 'Popen') as start:
                c.switch(root, 'disable')
                self.assertTrue((root / 'disabled').exists())
                run.assert_called_once_with(['eww', '--config', str(root), 'kill'], check=False,
                                            stdout=c.subprocess.DEVNULL,
                                            stderr=c.subprocess.DEVNULL)
                c.switch(root, 'toggle')
                self.assertFalse((root / 'disabled').exists())
                start.assert_called_once()
            self.assertEqual((root / 'settings.json').read_text(), '{"keep": true}')
            self.assertEqual((root / 'scripts/start.sh').read_text().count('&& exit 0'), 1)

    def test_disabled_startup_does_not_launch_commands(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / 'poedash'
            (root / 'scripts').mkdir(parents=True)
            start = root / 'scripts/start.sh'
            start.write_text('#!/bin/bash\nprintf should-not-run\n')
            (root / 'disabled').touch()
            c.prepare(root)
            result = c.subprocess.run(['bash', str(start)], capture_output=True, text=True)
            self.assertEqual(result.returncode, 0)
            self.assertEqual(result.stdout, '')

    def test_waybar_preserves_modules_and_is_idempotent(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = Path(tmp) / 'config'
            config.write_text('{"modules-right": ["clock"], "clock": {"format": "{:%H:%M}"}}')
            root = Path(tmp) / 'poedash'
            c.install_waybar(root, config)
            first = config.read_text()
            c.install_waybar(root, config)
            self.assertEqual(config.read_text(), first)
            data = json.loads(first)
            self.assertEqual(data['modules-right'], ['custom/poedash', 'custom/poedash-update', 'clock'])
            self.assertIn(' toggle', data['custom/poedash']['on-click'])

    def test_waybar_empty_array(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = Path(tmp) / 'config'
            config.write_text('{"modules-right": []}')
            c.install_waybar(Path(tmp) / 'eww', config)
            self.assertEqual(json.loads(config.read_text())['modules-right'], ['custom/poedash', 'custom/poedash-update'])

    def test_legacy_workspace_guard_is_upgraded_once(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / 'poedash'
            (root / 'scripts').mkdir(parents=True)
            (root / 'scripts/start.sh').write_text('#!/bin/bash\nexit 0\n')
            lua = root / 'hyprland.lua'
            lua.write_text('local function protect_home(window, follow)\nend\n')
            c.prepare(root)
            first = lua.read_text()
            c.prepare(root)
            self.assertEqual(lua.read_text(), first)
            self.assertIn('if dashboard_disabled() then return end', first)

    def test_existing_switch_gets_one_adjacent_update_button(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = Path(tmp) / 'config'
            config.write_text('{"modules-right": ["clock", "custom/poedash"], "custom/poedash": {"on-click": "keep"}}')
            c.install_waybar(Path(tmp) / 'poedash', config)
            c.install_waybar(Path(tmp) / 'poedash', config)
            data = json.loads(config.read_text())
            self.assertEqual(data['modules-right'], ['clock', 'custom/poedash', 'custom/poedash-update'])
            self.assertEqual(data['custom/poedash']['on-click'], 'keep')
            self.assertIn(' update', data['custom/poedash-update']['on-click'])

    def test_update_detaches_background_worker_without_terminal(self):
        root = Path('/tmp/path with spaces/poedash')
        with patch.object(c.subprocess, 'Popen') as launch:
            c.update(root)
        launch.assert_called_once_with([c.sys.executable, str(root / 'scripts/dashboard-control.py'),
                                       '--root', str(root), 'update-run'], start_new_session=True,
                                      stdin=c.subprocess.DEVNULL, stdout=c.subprocess.DEVNULL,
                                      stderr=c.subprocess.DEVNULL)

    def test_background_update_notifies_after_surface_reopens(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            result = c.subprocess.CompletedProcess([], 0, stdout='dashboard: dashboard\n')
            with patch.object(c, 'update_cache', return_value=root / 'cache'), \
                 patch.object(c.subprocess, 'run', return_value=result) as run, \
                 patch.object(c, 'update_notice') as notice:
                c.run_update(root)
            self.assertEqual(run.call_args_list[0].args[0], ['bash', str(root / 'scripts/update.sh'), str(root)])
            self.assertEqual(run.call_args_list[0].kwargs['stdin'], c.subprocess.DEVNULL)
            notice.assert_called_once_with('Updated successfully.')

    def test_failed_background_update_retains_error_log_and_notifies(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with patch.object(c, 'update_cache', return_value=root / 'cache'), \
                 patch.object(c.subprocess, 'run', return_value=c.subprocess.CompletedProcess([], 42)), \
                 patch.object(c, 'update_notice') as notice:
                c.run_update(root)
            self.assertTrue(notice.call_args.kwargs['failed'])
            self.assertIn('status 42', (root / 'cache/update.log').read_text())

    def test_duplicate_background_updates_do_not_run_installer(self):
        with tempfile.TemporaryDirectory() as tmp:
            cache = Path(tmp)
            with (cache / 'update.lock').open('w') as lock:
                c.fcntl.flock(lock, c.fcntl.LOCK_EX)
                with patch.object(c, 'update_cache', return_value=cache), \
                     patch.object(c.subprocess, 'run') as run, patch.object(c, 'update_notice') as notice:
                    c.run_update(cache)
                run.assert_not_called()
                notice.assert_called_once_with('An update is already running.')

    def test_quickshell_integration_adds_two_button_module_once(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            root = home / '.config/poedash'
            scripts = root / 'scripts'
            scripts.mkdir(parents=True)
            (scripts / 'start.sh').write_text('#!/bin/sh\n')
            (scripts / 'DashboardModule.qml').write_text(
                'root: "@@DASHBOARD_ROOT@@"\ntoggleButton\nupdateButton\n')
            statusbar = home / '.config/quickshell/StatusbarApp'
            statusbar.mkdir(parents=True)
            window = statusbar / 'StatusbarWindow.qml'
            window.write_text('''PanelWindow {
    Component { id: cTerminal;   TerminalModule {} }
    readonly property var moduleComponents: ({
        "terminal":   cTerminal
    })
    property var settings: ({"modules": {"left": ["terminal"], "center": ["launcher", "clock"], "right": ["updates"]}})
}
''')
            reloader = home / '.config/ml4w/scripts/ml4w-reload-statusbar'
            reloader.parent.mkdir(parents=True)
            reloader.write_text('#!/bin/sh\n')
            with patch.object(c.Path, 'home', return_value=home), patch.object(c.subprocess, 'run') as reload_bar:
                self.assertTrue(c.install_quickshell(root, statusbar))
                first = window.read_text()
                self.assertTrue(c.install_quickshell(root, statusbar))
                reload_bar.assert_called_once()
            self.assertEqual(window.read_text(), first)
            self.assertEqual(first.count('id: cDashboard'), 1)
            self.assertEqual(first.count('"dashboard":'), 1)
            self.assertIn('"dashboard"', first)
            self.assertIn('"center": ["dashboard", "launcher", "clock"]', first)
            self.assertIn('"right": ["updates"]', first)
            module = (statusbar / 'DashboardModule.qml').read_text()
            self.assertIn(str(root), module)
            self.assertIn('toggleButton', module)
            self.assertIn('updateButton', module)
            self.assertIn('󰍹', (REPO / 'assets/scripts/DashboardModule.qml').read_text())
