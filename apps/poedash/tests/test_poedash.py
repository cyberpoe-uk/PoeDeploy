import argparse
import importlib.util
import json
import os
from pathlib import Path
import shutil
import socket
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
        cfg.pop('calendar')  # Earlier installations stored this in layout.json.
        (self.root / 'settings.json').write_text(json.dumps(cfg))
        (self.root / 'colors.scss').write_text('// custom palette')
        (self.root / 'obsolete-interface-file').write_text('remove me')
        (self.root / 'disabled').touch()
        (self.root / 'layout.json').write_text('{"density":"comfortable","calendar":"google"}')
        dashboard = '{"version":1,"notes":"keep my private note"}'
        (self.root / 'dashboard.json').write_text(dashboard)
        (self.root / 'state').mkdir(exist_ok=True)
        (self.root / 'state/history.fixture').write_text('saved history')
        self.hypr.write_text(self.hypr.read_text() + '-- later user edit\n')
        self.install()
        self.assertEqual(self.hypr.read_text().count(poedash.BEGIN), 1)
        self.assertEqual(poedash.settings(self.root)['name'], 'My Workstation')
        self.assertEqual((self.root / 'colors.scss').read_text(), '// custom palette')
        self.assertFalse((self.root / 'obsolete-interface-file').exists())
        self.assertTrue((self.root / 'disabled').exists())
        self.assertFalse((self.root / 'layout.json').exists())
        self.assertEqual(poedash.settings(self.root)['calendar'], 'google')
        self.assertEqual((self.root / 'dashboard.json').read_text(), dashboard)
        self.assertEqual((self.root / 'dashboard.json').stat().st_mode & 0o777, 0o600)
        self.assertEqual((self.root / 'state/history.fixture').read_text(), 'saved history')
        self.assertTrue((self.root / 'scripts/dashboard_native.py').is_file())
        self.assertTrue((self.root / 'scripts/workspace.py').stat().st_mode & 0o111)
        self.assertEqual((self.root / 'dashboard-id').read_text(), 'poedash\n')
        self.assertEqual((self.home / '.config/poedeploy/dashboard').read_text(), 'poedash\n')
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

    def test_dependency_installation_uses_only_native_runtime_packages(self):
        with patch.object(poedash.shutil, 'which', return_value='/usr/bin/pacman'), \
                patch.object(poedash.subprocess, 'run', return_value=subprocess.CompletedProcess([], 1)), \
                patch.object(poedash, 'run') as install:
            poedash.dependencies()
        packages=install.call_args.args[0]
        self.assertEqual(packages[:4],['sudo','pacman','-S','--needed'])
        for needed in ('python-gobject','python-cairo','gtk-layer-shell','gtk3'):
            self.assertIn(needed,packages)
        self.assertTrue(set(packages).isdisjoint({'eww','gcc','pkgconf','socat'}))

    def test_doctor_succeeds_without_eww_or_a_host_compiler(self):
        self.install()
        def available(command):
            return None if command in ('eww','cc','pkg-config') else '/usr/bin/'+command
        def execute(argv,**kwargs):
            payload=json.dumps({'version':'0.57.1'}) if argv[0]=='hyprctl' else ''
            return subprocess.CompletedProcess(argv,0,payload,'')
        with patch.object(poedash.shutil,'which',side_effect=available), patch.object(poedash,'run',side_effect=execute):
            self.assertEqual(poedash.doctor(self.root),0)

    def test_theme_update_does_not_start_another_renderer_when_dashboard_is_closed(self):
        self.install()
        wallpaper=self.home/'wallpaper.png'; wallpaper.touch()
        with patch.object(poedash,'run') as generate, patch.object(poedash,'native_control',return_value=False):
            poedash.theme(self.root,wallpaper)
        generate.assert_called_once()
        self.assertEqual(generate.call_args.args[0][0],'matugen')

    def test_upgrade_excludes_running_native_socket_from_backup(self):
        self.install()
        (self.root / 'state').mkdir(exist_ok=True)
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as server:
            server.bind(str(self.root / 'state/native.sock'))
            with patch.object(poedash, 'native_control'):
                self.install()
        for backup in (self.home / '.local/state/poedash/backups').iterdir():
            self.assertFalse((backup / 'config/state/native.sock').exists())

    def test_interactive_desktop_install_refreshes_running_dashboard(self):
        self.args.no_start = False
        with patch.dict(os.environ, {'HYPRLAND_INSTANCE_SIGNATURE': 'test', 'WAYLAND_DISPLAY': 'wayland-1'}), \
                patch.object(poedash, 'refresh') as launch:
            self.install()
        launch.assert_called_once_with(self.root)

    def test_upgrade_removes_obsolete_renderer_without_losing_user_state(self):
        self.install()
        (self.root/'surface-backend').write_text('eww\n')
        (self.root/'eww.yuck').write_text('old renderer')
        (self.root/'scripts/refresh.py').write_text('old scheduler')
        (self.root/'state').mkdir(exist_ok=True)
        (self.root/'state/surface-backend').write_text('eww')
        (self.root/'state/eww-host').mkdir()
        (self.root/'state/eww-host/module.so').write_bytes(b'old module')
        (self.root/'state/user-data.json').write_text('{"keep":true}')
        with patch.object(poedash, 'retire_legacy_surface'):
            self.install()
        for filename in ('surface-backend','eww.yuck','eww.scss','scripts/refresh.py',
                         'scripts/eww-host.py','scripts/eww_embed.py','scripts/layout.py',
                         'state/surface-backend','state/eww-host'):
            self.assertFalse((self.root/filename).exists(), filename)
        self.assertEqual((self.root/'state/user-data.json').read_text(),'{"keep":true}')

    def test_startup_uses_installed_directory(self):
        self.install()
        self.assertIn('cd "$root"', (self.root / 'scripts/start.sh').read_text())

    def test_recognised_legacy_dashboard_is_backed_up_and_retired(self):
        legacy = self.home / '.config/eww'
        legacy.mkdir(parents=True)
        (legacy / 'eww.yuck').write_text('(label :text "MY DASHBOARD")')
        (legacy / 'old-interface').write_text('legacy')
        custom = self.hypr.parent / 'custom.lua'
        custom.write_text('-- BEGIN OLDHOME\nhl.exec_cmd("~/.config/eww/scripts/start.sh")\n-- END OLDHOME\n-- BEGIN OTHER\n-- keep me\n-- END OTHER\n')
        self.install()
        self.assertFalse(legacy.exists())
        backups = list((self.home / '.local/state/poedash/backups').iterdir())
        self.assertEqual((backups[0] / 'retired-legacy-eww/old-interface').read_text(), 'legacy')
        self.assertNotIn('.config/eww/scripts/start.sh', custom.read_text())
        self.assertIn('-- keep me', custom.read_text())
        self.assertNotIn('OLDHOME', custom.read_text())
        self.assertIn('-- BEGIN OTHER', custom.read_text())

    def test_legacy_eww_preferences_and_state_survive_upgrades(self):
        legacy = self.home / '.config/eww'
        legacy.mkdir(parents=True)
        (legacy / 'eww.yuck').write_text('(label :text "MY DASHBOARD")')
        (legacy / 'colors.scss').write_text('// laptop palette')
        (legacy / 'layout.json').write_text('{"density":"compact","calendar":"auto"}')
        (legacy / 'disabled').touch()
        (legacy / 'state').mkdir()
        (legacy / 'state/custom.json').write_text('{"keep":true}')
        self.install()
        self.assertEqual((self.root / 'colors.scss').read_text(), '// laptop palette')
        self.assertFalse((self.root / 'layout.json').exists())
        self.assertEqual(poedash.settings(self.root)['calendar'], 'auto')
        self.assertTrue((self.root / 'disabled').exists())
        self.assertTrue((self.root / 'state/custom.json').exists())
        self.install()
        self.assertTrue((self.root / 'state/custom.json').exists())

    def test_install_removes_retired_theme_and_launcher_without_readding_them(self):
        legacy = self.home / '.config/eww'
        legacy.mkdir(parents=True)
        (legacy / 'eww.yuck').write_text('PenDash')
        old_command = self.home / '.local/bin/pendash'
        old_command.parent.mkdir(parents=True)
        old_command.write_text('old launcher')
        theme = self.home / '.config/matugen/config.toml'
        theme.parent.mkdir(parents=True)
        theme.write_text('[config]\n[templates.eww]\noutput_path="~/.config/eww/colors.scss"\n[templates.keep]\noutput_path="keep.scss"\n')
        self.install()
        self.assertFalse(legacy.exists())
        self.assertFalse(old_command.exists())
        self.assertNotIn('templates.eww', theme.read_text())
        self.assertIn('templates.keep', theme.read_text())
        self.assertIn('templates.poedash', theme.read_text())

    def test_old_launcher_settings_are_migrated_to_general_dashboard(self):
        self.install()
        old = {'monitor': 0, 'layout': {'scale': 'auto', 'system_width': 540,
               'network_width': 450, 'lower_height': 210}, 'launchers': {}, 'web_ctf': {}}
        (self.root / 'settings.json').write_text(json.dumps(old))
        self.install()
        cfg = poedash.settings(self.root)
        self.assertEqual(cfg['name'], 'PoeDash')
        self.assertEqual(set(cfg), {'name', 'monitor', 'calendar'})

    def test_render_preserves_named_monitor_and_user_settings(self):
        self.install()
        cfg = poedash.settings(self.root)
        cfg['monitor'] = 'eDP-1'
        (self.root / 'settings.json').write_text(json.dumps(cfg))
        before = (self.root / 'settings.json').read_text()
        poedash.render(self.root)
        self.assertEqual((self.root / 'settings.json').read_text(), before)
        self.assertIn(str(self.root / 'disabled'), (self.root / 'hyprland.lua').read_text())
        self.assertNotIn('eww', (self.root / 'hyprland.lua').read_text().lower())

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
        self.assertIn('desktop.py', (self.root / 'scripts/media-control.sh').read_text())
        self.assertTrue((self.root / 'scripts/desktop.py').stat().st_mode & 0o111)
        for script in ('system-info.py', 'processes.py', 'power.py', 'media.py', 'thunderbird-calendar.py'):
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
