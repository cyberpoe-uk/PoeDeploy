import importlib.util
import os
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location('offload', Path(__file__).resolve().parents[1] / 'components/nvidia-offload-setup.py')
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)


class ConfigurationTests(unittest.TestCase):
    def test_environment_preserves_unrelated_settings_and_is_idempotent(self):
        old = 'export MY_CUSTOM_SETTING="keep me"\nexport AQ_DRM_DEVICES="/dev/dri/card0"\n'
        first = m.env_update(old)
        self.assertEqual(first, m.env_update(first))
        self.assertIn('export MY_CUSTOM_SETTING="keep me"', first)
        self.assertEqual(first.count('# BEGIN nvidia-offload-setup'), 1)
        self.assertTrue(first.index('/dev/dri/card0') < first.index('/dev/dri/intel-igpu'))

    def test_backup_preserves_symlink_and_second_apply_does_not_write(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            target = root / 'dotfile'
            target.write_text('original\n')
            target.chmod(0o644)
            link = root / 'linked-config'
            link.symlink_to(target)
            setup = m.Setup.__new__(m.Setup)
            setup.account = SimpleNamespace(pw_uid=os.getuid(), pw_gid=os.getgid())
            setup.backup = root / 'backups'
            setup.manifest, setup.changed, setup.lines = [], [], []
            self.assertTrue(setup.write(link, 'new\n', user=True))
            self.assertTrue(link.is_symlink())
            self.assertEqual(target.read_text(), 'new\n')
            self.assertEqual(Path(setup.manifest[0]['backup']).read_text(), 'original\n')
            self.assertFalse(setup.write(link, 'new\n', user=True))
            self.assertEqual(len(setup.manifest), 1)

    def test_idle_rejects_suspended_without_advancing_counter(self):
        setup = m.Setup.__new__(m.Setup)
        setup.power = Path('/fake/power')
        setup.nvidia_devices = [Path('/fake/0000:01:00.0')]
        setup.nvidia = '0000:01:00.0'
        setup.args = SimpleNamespace(wait=10)
        setup.lines = []
        setup.clients = lambda: []
        def fake_read(p):
            if str(p).endswith('runtime_status'):
                return 'suspended'
            if str(p).endswith('power/control'):
                return 'auto'
            return '100'
        with patch.object(m, 'read', side_effect=fake_read), patch.object(m.time, 'sleep'), \
             patch.object(m.time, 'monotonic', side_effect=[0, 0, 11]):
            self.assertFalse(setup.idle('test'))

    def test_idle_accepts_measured_sleep(self):
        setup = m.Setup.__new__(m.Setup)
        setup.power = Path('/fake/power')
        setup.nvidia_devices = [Path('/fake/0000:01:00.0')]
        setup.nvidia = '0000:01:00.0'
        setup.args = SimpleNamespace(wait=10)
        setup.lines = []
        counters = iter(['100', '5100'])
        def fake_read(p):
            if str(p).endswith('runtime_status'):
                return 'suspended'
            if str(p).endswith('power/control'):
                return 'auto'
            return next(counters)
        with patch.object(m, 'read', side_effect=fake_read), patch.object(m.time, 'sleep'):
            self.assertTrue(setup.idle('test'))

    def test_discovers_display_and_only_same_slot_nvidia_functions(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            devices = {
                '0000:03:00.0': ('0x10de', '0x030000'),
                '0000:03:00.1': ('0x10de', '0x040300'),
                '0000:03:00.2': ('0x10de', '0x0c0330'),
                '0000:07:00.0': ('0x10ec', '0x020000'),
            }
            for name, (vendor, device_class) in devices.items():
                path = root / name
                path.mkdir()
                (path / 'vendor').write_text(vendor)
                (path / 'class').write_text(device_class)
            gpu, siblings = m.discover_nvidia_devices(root)
            self.assertEqual(gpu.name, '0000:03:00.0')
            self.assertEqual([p.name for p in siblings], ['0000:03:00.0', '0000:03:00.1', '0000:03:00.2'])

    def test_dynamic_power_management_parsing(self):
        with tempfile.TemporaryDirectory() as tmp:
            params = Path(tmp) / 'params'
            params.write_text('DynamicPowerManagement: 2\nOther: 1\n')
            self.assertEqual(m.dynamic_power_management(params), 2)

    def test_stale_driver_is_reboot_required(self):
        setup = m.Setup.__new__(m.Setup)
        setup.lines = []
        with patch.object(m, 'dynamic_power_management', return_value=0):
            self.assertFalse(setup.driver_state())
        self.assertTrue(any(line.startswith('REBOOT REQUIRED:') for line in setup.lines))
        self.assertTrue(any('retries were skipped' in line for line in setup.lines))

if __name__ == '__main__':
    unittest.main()
