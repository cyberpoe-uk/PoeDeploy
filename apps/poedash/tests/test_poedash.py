import argparse
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
import poedash


class Installation(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='poedash test ')
        self.home = Path(self.temp.name)
        self.env = patch.dict(os.environ, {'HOME': str(self.home), 'XDG_CONFIG_HOME': str(self.home / '.config'),
            'XDG_STATE_HOME': str(self.home / '.local/state'), 'XDG_CACHE_HOME': str(self.home / '.cache')})
        self.env.start()
        self.root = self.home / '.config/poedash'
        self.hypr = self.home / '.config/hypr/hyprland.lua'
        self.hypr.parent.mkdir(parents=True)
        self.hypr.write_text('-- keep my compositor config\n')
        self.monitor = patch.object(poedash, 'monitor_info', return_value={'name': 'TEST-1', 'width': 1920, 'height': 1080, 'scale': 1})
        self.monitor.start()
        self.args = argparse.Namespace(skip_deps=True, dry_run=False, no_integrate=False,
                                       hyprland_config=None, name=None, non_interactive=True,
                                       no_start=True)

    def tearDown(self):
        self.monitor.stop()
        self.env.stop()
        self.temp.cleanup()

    def install(self):
        poedash.install(self.args, self.root)

    def test_install_upgrade_uninstall_preserves_user_data(self):
        self.install()
        cfg = json.loads((self.root / 'settings.json').read_text())
        cfg['name'] = 'My Workstation'
        (self.root / 'settings.json').write_text(json.dumps(cfg))
        (self.root / 'colors.scss').write_text('// custom palette')
        (self.root / 'obsolete-interface-file').write_text('remove me')
        (self.root / 'disabled').touch()
        self.hypr.write_text(self.hypr.read_text() + '-- later user edit\n')
        self.install()
        self.assertEqual(self.hypr.read_text().count(poedash.BEGIN), 1)
        self.assertEqual(poedash.settings(self.root)['name'], 'My Workstation')
        self.assertIn('My Workstation', (self.root / 'eww.yuck').read_text())
        self.assertEqual((self.root / 'colors.scss').read_text(), '// custom palette')
        self.assertFalse((self.root / 'obsolete-interface-file').exists())
        self.assertTrue((self.root / 'disabled').exists())
        import tomllib
        theme = self.home / '.config/matugen/config.toml'
        self.assertIn('poedash', tomllib.loads(theme.read_text())['templates'])
        self.assertIn('config', tomllib.loads(theme.read_text()))
        with patch.object(poedash.shutil, 'which', return_value=None):
            poedash.uninstall(self.root)
        self.assertIn('-- later user edit', self.hypr.read_text())
        self.assertNotIn(poedash.BEGIN, self.hypr.read_text())
        self.assertNotIn('poedash', theme.read_text())
        self.assertTrue((self.root / 'settings.json').exists())
        self.assertFalse((self.home / '.local/bin/poedash').exists())
        self.assertEqual(len(list((self.home / '.local/state/poedash/backups').iterdir())), 2)

    def test_dry_run_writes_nothing(self):
        before = sorted(str(p) for p in self.home.rglob('*'))
        self.args.dry_run = True
        self.install()
        self.assertEqual(before, sorted(str(p) for p in self.home.rglob('*')))

    def test_interactive_desktop_install_refreshes_running_dashboard(self):
        self.args.no_start = False
        with patch.dict(os.environ, {'HYPRLAND_INSTANCE_SIGNATURE': 'test', 'WAYLAND_DISPLAY': 'wayland-1'}), \
                patch.object(poedash, 'refresh') as launch:
            self.install()
        launch.assert_called_once_with(self.root)

    def test_startup_uses_installed_directory(self):
        self.install()
        self.assertIn('cd "$root"', (self.root / 'scripts/start.sh').read_text())

    def test_recognised_legacy_dashboard_is_backed_up_and_retired(self):
        legacy = self.home / '.config/eww'
        legacy.mkdir(parents=True)
        (legacy / 'eww.yuck').write_text('(label :text "MY DASHBOARD")')
        (legacy / 'old-interface').write_text('legacy')
        custom = self.hypr.parent / 'custom.lua'
        custom.write_text('hl.exec_cmd("~/.config/eww/scripts/start.sh")\n-- keep me\n')
        self.install()
        self.assertFalse(legacy.exists())
        backups = list((self.home / '.local/state/poedash/backups').iterdir())
        self.assertEqual((backups[0] / 'retired-legacy-eww/old-interface').read_text(), 'legacy')
        self.assertNotIn('.config/eww/scripts/start.sh', custom.read_text())
        self.assertIn('-- keep me', custom.read_text())

    def test_old_launcher_settings_are_migrated_to_general_dashboard(self):
        self.install()
        old = {'monitor': 0, 'layout': {'scale': 'auto', 'system_width': 540,
               'network_width': 450, 'lower_height': 210}, 'launchers': {}, 'web_ctf': {}}
        (self.root / 'settings.json').write_text(json.dumps(old))
        self.install()
        cfg = poedash.settings(self.root)
        self.assertEqual(cfg['name'], 'PoeDash')
        self.assertEqual(cfg['layout']['system_width'], 620)
        self.assertEqual(cfg['layout']['network_width'], 520)
        self.assertEqual(cfg['layout']['lower_height'], 250)
        yuck = (self.root / 'eww.yuck').read_text()
        for unwanted in ('QUICK LAUNCH', 'CTF FIREFOX', 'WIRESHARK', 'START WEB CTF'):
            self.assertNotIn(unwanted, yuck)

    def test_auto_scale_and_custom_dimensions(self):
        self.install()
        cfg = poedash.settings(self.root)
        cfg['layout']['system_width'] = 600
        (self.root / 'settings.json').write_text(json.dumps(cfg))
        with patch.object(poedash, 'monitor_info', return_value={'name': 'DP-2', 'width': 2560, 'height': 1440, 'scale': 2}):
            poedash.render(self.root)
        yuck = (self.root / 'eww.yuck').read_text()
        self.assertIn(':width 400', yuck)
        self.assertIn(':monitor 0', yuck)
        self.assertIn('font-size: 22.6667px', (self.root / 'eww.scss').read_text())
        self.assertNotIn('/home/', yuck)

    def test_named_monitor_supports_gtk_model_names(self):
        self.install()
        cfg = poedash.settings(self.root)
        cfg['monitor'] = 'eDP-1'
        (self.root / 'settings.json').write_text(json.dumps(cfg))
        with patch.object(poedash, 'monitor_info', return_value={'name': 'eDP-1', 'model': '0x084D', '_index': 0, 'width': 1920, 'height': 1080, 'scale': 1}):
            poedash.render(self.root)
        selector = json.dumps(json.dumps(['eDP-1', '0x084D', 0]))
        self.assertIn(':monitor ' + selector, (self.root / 'eww.yuck').read_text())

    def test_lua_syntax_and_cli_path_with_spaces(self):
        self.install()
        if shutil.which('luac'):
            subprocess.run(['luac', '-p', str(self.root / 'hyprland.lua')], check=True)
        result = subprocess.run([str(self.home / '.local/bin/poedash'), 'render'], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_custom_name_and_general_monitor_collectors(self):
        self.args.name = 'Studio PC'
        self.install()
        self.assertEqual(poedash.settings(self.root)['name'], 'Studio PC')
        yuck = (self.root / 'eww.yuck').read_text()
        for feature in ('TOP PROCESSES', 'Power draw', 'SMB / NFS SHARES',
                        '${system_info.host} SPECIFICATIONS', 'media-control.sh spotify',
                        'Tailscale IP', ':wrap true'):
            self.assertIn(feature, yuck)
        self.assertIn(':visible {power.available}', yuck)
        self.assertIn(':width 520', yuck)
        self.assertIn('updates > 50 ? "updates critical"', yuck)
        for script in ('system-info.py', 'processes.py', 'shares.py', 'power.py', 'media.py'):
            result = subprocess.run([str(self.root / 'scripts' / script)], capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            json.loads(result.stdout)
        rows = json.loads(subprocess.run([str(self.root / 'scripts/processes.py')],
                          capture_output=True, text=True, check=True).stdout)
        self.assertLessEqual(len(rows), 10)

    def test_amd_gpu_and_unavailable(self):
        spec = importlib.util.spec_from_file_location('gpu', REPO / 'assets/scripts/gpu.py')
        gpu = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(gpu)
        with patch.object(gpu.subprocess, 'run', side_effect=FileNotFoundError):
            self.assertEqual(gpu.reading(self.home)['label'], '--')
            device = self.home / 'card0/device'
            device.mkdir(parents=True)
            (device / 'gpu_busy_percent').write_text('23')
            hwmon = device / 'hwmon/hwmon0'
            hwmon.mkdir(parents=True)
            (hwmon / 'temp1_input').write_text('54000')
            self.assertEqual(gpu.reading(self.home), {'usage': 23, 'label': '23%', 'temperature': '54°C'})


if __name__ == '__main__':
    unittest.main()
