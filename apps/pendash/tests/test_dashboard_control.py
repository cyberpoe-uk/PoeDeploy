import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]
SCRIPT = next(REPO.glob('**/scripts/dashboard-control.py'))
spec = importlib.util.spec_from_file_location('control', SCRIPT)
c = importlib.util.module_from_spec(spec)
spec.loader.exec_module(c)

class DashboardControl(unittest.TestCase):
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
            self.assertEqual(json.loads(config.read_text())['modules-right'], ['custom/pendash', 'custom/pendash-update'])

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

    def test_update_opens_terminal_without_running_installer_in_bar(self):
        root = Path('/tmp/path with spaces/poedash')
        with patch.object(c.subprocess, 'Popen') as launch:
            c.update(root)
        launch.assert_called_once_with(['kitty', '--hold', '--title', 'Update dashboard',
                                       'bash', str(root / 'scripts/update.sh'), str(root)],
                                      start_new_session=True)

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
    property var settings: ({"modules": {"right": ["clock"]}})
}
''')
            self.assertTrue(c.install_quickshell(root, statusbar))
            first = window.read_text()
            self.assertTrue(c.install_quickshell(root, statusbar))
            self.assertEqual(window.read_text(), first)
            self.assertEqual(first.count('id: cDashboard'), 1)
            self.assertEqual(first.count('"dashboard":'), 1)
            self.assertIn('"dashboard"', first)
            module = (statusbar / 'DashboardModule.qml').read_text()
            self.assertIn(str(root), module)
            self.assertIn('toggleButton', module)
            self.assertIn('updateButton', module)
