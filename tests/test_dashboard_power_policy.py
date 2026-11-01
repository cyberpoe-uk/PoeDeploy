"""Power-source transitions and persistent manual overrides, without hardware writes."""
import importlib.util
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

SCRIPTS = Path(__file__).resolve().parents[1] / 'apps/poedash/assets/scripts'
sys.path.insert(0, str(SCRIPTS))
spec = importlib.util.spec_from_file_location('power_control', SCRIPTS / 'power-control.py')
power = importlib.util.module_from_spec(spec)
spec.loader.exec_module(power)


class FakeBackend:
    kind = 'test backend'
    def __init__(self):
        self.mapping = {p: p for p in power.PROFILES}
        self.profile = 'balanced'
        self.calls = []
    def current(self): return self.profile
    def set(self, profile):
        if profile not in self.mapping: raise RuntimeError('unsupported profile')
        if self.profile != profile:
            self.calls.append(profile)
            self.profile = profile
        return self.profile


class PowerPolicy(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.state = Path(self.temp.name)
        self.backend = FakeBackend()
        self.source = 'ac'
        self.policy = power.Policy(self.state, lambda: self.backend, lambda: self.source, 'boot-one')

    def test_initial_ac_battery_and_desktop_profiles(self):
        for source, profile in [('ac', 'performance'), ('battery', 'power-saver'), ('desktop', 'performance')]:
            self.source = source
            self.assertEqual(self.policy.sync()['active'], profile)

    def test_manual_choices_on_either_source_survive_refresh_restart_and_reinstall(self):
        for source in ('ac', 'battery', 'desktop'):
            self.source = source
            self.policy.sync()
            self.policy.sync(manual='balanced')
            self.policy.sync()
            restart = power.Policy(self.state, lambda: self.backend, lambda: self.source, 'boot-one')
            data = restart.sync()
            self.assertEqual(data['active'], 'balanced')
            self.assertEqual(data['mode'], 'Manual')
            with patch.object(power, 'UNIT', self.state / 'unit.service'), patch.object(power, 'unit_text', return_value=power.OWNER), patch.object(power, 'run', return_value='active'):
                power.install(restart)
            self.assertEqual(self.backend.profile, 'balanced')

    def test_repeated_events_do_not_set_profiles_again(self):
        self.policy.sync()
        for _ in range(10): self.policy.sync()
        self.assertEqual(self.backend.calls, ['performance'])

    def test_actual_cable_transitions_release_manual_override(self):
        self.policy.sync()
        self.policy.sync(manual='power-saver')
        self.assertEqual(self.policy.sync()['active'], 'power-saver')
        self.source = 'battery'
        self.assertEqual(self.policy.sync()['mode'], 'Automatic')
        self.policy.sync(manual='performance')
        self.assertEqual(self.policy.sync()['active'], 'performance')
        self.source = 'ac'
        data = self.policy.sync()
        self.assertEqual((data['active'], data['mode']), ('performance', 'Automatic'))
        for source in ('battery', 'ac', 'battery', 'ac'):
            self.source = source
            self.assertEqual(self.policy.sync()['active'], 'power-saver' if source == 'battery' else 'performance')

    def test_new_boot_initialises_default_but_ui_restart_does_not(self):
        self.policy.sync()
        self.policy.sync(manual='balanced')
        self.policy.boot = 'boot-two'
        self.assertEqual(self.policy.sync()['active'], 'performance')

    def test_missing_profile_uses_documented_supported_fallback(self):
        self.backend.mapping.pop('performance')
        data = self.policy.sync()
        self.assertEqual(data['active'], 'balanced')
        self.assertIn('performance is unavailable', data['message'])
        self.assertIn('unsupported', self.policy.sync(manual='performance')['message'])

    def test_missing_backend_and_unreadable_sensors_preserve_last_confirmed_source(self):
        self.policy.sync()
        self.policy.get_source = lambda: (_ for _ in ()).throw(RuntimeError('sensor unavailable'))
        self.assertIn('sensor unavailable', self.policy.sync()['message'])
        self.assertEqual(self.policy.saved()['source'], 'ac')
        self.policy.backend = lambda: (_ for _ in ()).throw(RuntimeError('backend unavailable'))
        self.assertFalse(self.policy.sync()['supported'])
        self.assertEqual(self.backend.calls, ['performance'])

    def test_disabled_automation_stays_disabled_on_reinstall(self):
        self.policy.sync()
        self.policy.enable(False)
        self.backend.profile = 'balanced'
        self.source = 'battery'
        self.assertEqual(self.policy.sync()['active'], 'balanced')
        with patch.object(power, 'run') as run:
            self.assertIn('remains disabled', power.install(self.policy))
            run.assert_not_called()

    def test_external_manual_change_is_not_overwritten(self):
        self.policy.sync()
        self.backend.profile = 'balanced'
        data = self.policy.sync()
        self.assertEqual((data['active'], data['mode']), ('balanced', 'Manual / external'))

    def test_uninstall_removes_owned_service_and_enabled_link(self):
        unit = self.state / 'poedash-power.service'
        unit.write_text(power.OWNER)
        wants = self.state / 'default.target.wants'
        wants.mkdir()
        link = wants / unit.name
        link.symlink_to('../' + unit.name)
        with patch.object(power, 'UNIT', unit), patch.object(power, 'run', return_value=''):
            power.remove(self.policy, True)
        self.assertFalse(unit.exists())
        self.assertFalse(link.is_symlink())
        self.assertFalse(self.policy.saved()['enabled'])

    def test_battery_detection_uses_system_supply_state(self):
        supplies = self.state / 'supplies'
        supplies.mkdir()
        self.assertEqual(power.source(supplies), 'desktop')
        bat = supplies / 'BAT0'
        bat.mkdir()
        for key, value in [('type','Battery'), ('status','Discharging'), ('capacity','50')]:
            (bat / key).write_text(value)
        self.assertEqual(power.source(supplies), 'battery')
        ac = supplies / 'AC'
        ac.mkdir()
        (ac / 'type').write_text('Mains')
        (ac / 'online').write_text('1')
        self.assertEqual(power.source(supplies), 'ac')

    def test_desktop_profile_status_remains_visible_without_battery(self):
        text = (SCRIPTS.parent / 'templates/eww.yuck').read_text()
        card = text.split('(defwidget power-card')[1].split('(defwidget dashboard-grid')[0]
        self.assertIn(':heading "Profile"', card)
        self.assertIn(':heading "Selected by"', card)
        self.assertNotIn('power_tab', text)
        self.assertNotIn('power-control.py set', text)
        self.assertIn('(literal :content dashboard_grid)', text)

class BackendDetection(unittest.TestCase):
    def test_profile_api_uses_only_advertised_profiles(self):
        def command(argv):
            if argv == ['powerprofilesctl', 'list']: return '* balanced:\n  power-saver:\n'
            if argv == ['powerprofilesctl', 'get']: return 'balanced'
            raise AssertionError(argv)
        with patch.object(power, 'active', return_value=False), patch.object(power.shutil, 'which', return_value='/usr/bin/powerprofilesctl'), patch.object(power, 'run', side_effect=command):
            backend = power.Backend()
            self.assertEqual(set(backend.mapping), {'balanced', 'power-saver'})
            with self.assertRaisesRegex(RuntimeError, 'not supported'): backend.set('performance')

    def test_native_tuned_mapping_and_conflicts(self):
        def command(argv):
            if argv == ['powerprofilesctl', 'list']: raise RuntimeError('no API provider')
            if argv == ['tuned-adm', 'list']: return '- balanced - General\n- powersave - Save\n- throughput-performance - Fast\n'
            if argv == ['tuned-adm', 'active']: return 'Current active profile: powersave'
            raise AssertionError(argv)
        with patch.object(power, 'active', side_effect=lambda unit: unit == 'tuned.service'), patch.object(power.shutil, 'which', return_value='/bin/tool'), patch.object(power, 'run', side_effect=command):
            backend = power.Backend()
            self.assertEqual(backend.kind, 'tuned')
            self.assertEqual(backend.current(), 'power-saver')
        with patch.object(power, 'active', return_value=True):
            with self.assertRaisesRegex(RuntimeError, 'Conflicting'): power.Backend()
