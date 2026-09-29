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
        self.args = argparse.Namespace(skip_deps=True, dry_run=False, no_integrate=False, hyprland_config=None)

    def tearDown(self):
        self.monitor.stop()
        self.env.stop()
        self.temp.cleanup()

    def install(self):
        poedash.install(self.args, self.root)

    def test_install_upgrade_uninstall_preserves_user_data(self):
        self.install()
        cfg = json.loads((self.root / 'settings.json').read_text())
        cfg['launchers']['terminal']['workspace'] = 9
        (self.root / 'settings.json').write_text(json.dumps(cfg))
        (self.root / 'colors.scss').write_text('// custom palette')
        (self.root / 'obsolete-interface-file').write_text('remove me')
        (self.root / 'disabled').touch()
        self.hypr.write_text(self.hypr.read_text() + '-- later user edit\n')
        self.install()
        self.assertEqual(self.hypr.read_text().count(poedash.BEGIN), 1)
        self.assertEqual(poedash.settings(self.root)['launchers']['terminal']['workspace'], 9)
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

    def test_reject_legacy_before_modifying_files(self):
        (self.hypr.parent / 'custom.lua').write_text('hl.exec_cmd("~/.config/eww/scripts/start.sh")')
        with self.assertRaisesRegex(RuntimeError, 'Legacy'):
            self.install()
        self.assertFalse(self.root.exists())

    def test_bad_settings_do_not_modify_installation(self):
        self.install()
        original = (self.root / 'eww.yuck').read_bytes()
        cfg = poedash.settings(self.root)
        cfg['launchers']['terminal']['workspace'] = 1
        (self.root / 'settings.json').write_text(json.dumps(cfg))
        with self.assertRaisesRegex(ValueError, 'reserved'):
            self.install()
        self.assertEqual(original, (self.root / 'eww.yuck').read_bytes())

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
        self.assertIn('font-size: 32px', (self.root / 'eww.scss').read_text())
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

    def test_target_and_launcher_isolation(self):
        self.install()
        sys.path.insert(0, str(self.root / 'scripts'))
        sys.modules.pop('config', None)
        spec = importlib.util.spec_from_file_location('ctf_test', self.root / 'scripts/ctf-control.py')
        ctf = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(ctf)
        sys.path.pop(0)
        for value in ['10.10.10.123', '2001:db8::1', 'lab.example', 'https://lab.example/path?q=a&x=b', '']:
            ctf.save_target(value)
            self.assertEqual(ctf.read_target(), value)
        self.assertEqual((ctf.STATE / 'target').stat().st_mode & 0o777, 0o600)
        for value in ['x;touch /tmp/bad', '$(id)', 'two\nlines', 'https://user:password@lab.example', 'http://lab.example:abc']:
            with self.assertRaises(ValueError):
                ctf.save_target(value)
        normal = {'class': 'firefox', 'pid': -1, 'workspace': {'id': 2}, 'address': 'normal'}
        dedicated = {'class': 'firefox-ctf', 'pid': -2, 'workspace': {'id': 2}, 'address': 'dedicated'}
        self.assertIsNone(ctf.find_window('firefox', [normal]))
        self.assertEqual(ctf.find_window('firefox', [normal, dedicated])['address'], 'dedicated')
        self.assertFalse(ctf.profile().exists())  # readiness queries create no browser state
        ctf.CACHE.mkdir(parents=True)
        window = {'class': 'kitty', 'address': '0x123', 'workspace': {'id': 3}}
        with patch.object(ctf, 'clients', return_value=[window]), patch.object(ctf, 'dispatch') as dispatch:
            ctf.ensure('terminal')
            self.assertFalse(any('exec_cmd' in str(c) for c in dispatch.call_args_list))
        # Timeout plus a second click must not launch a second process.
        with patch.object(ctf, 'clients', return_value=[]), patch.object(ctf, 'command', return_value=['kitty']), patch.object(ctf, 'running_without_window', return_value=False), patch.object(ctf.time, 'sleep'), patch.object(ctf, 'dispatch') as dispatch:
            for _ in range(2):
                with self.assertRaises(RuntimeError):
                    ctf.ensure('terminal')
            self.assertEqual(sum('exec_cmd' in str(c) for c in dispatch.call_args_list), 1)

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
