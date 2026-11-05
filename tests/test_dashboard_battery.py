"""System battery detection, OS estimates and desktop layout visibility."""
import importlib.util
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('battery', ROOT / 'apps/poedash/assets/scripts/battery.py')
battery = importlib.util.module_from_spec(spec)
spec.loader.exec_module(battery)


class BatteryDetection(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def supply(self, name='BAT0', **values):
        path = self.root / name
        path.mkdir(exist_ok=True)
        for key, value in values.items():
            (path / key).write_text(str(value))
        return path

    def test_desktop_and_unreadable_detection_hide_the_power_card(self):
        self.assertFalse(battery.reading(self.root)['present'])
        self.assertFalse(battery.reading(self.root / 'missing')['present'])

    def test_peripheral_and_absent_batteries_are_excluded(self):
        self.supply('mouse', type='Battery', scope='Device', capacity=80)
        self.supply(type='Battery', present=0)
        self.assertFalse(battery.reading(self.root)['present'])

    def test_kernel_estimate_is_used_without_calculating_time_from_energy(self):
        self.supply(type='Battery', status='Discharging', capacity=50,
                    energy_now=10_000_000, energy_full=20_000_000, power_now=2_000_000,
                    time_to_empty_now=7200)
        data = battery.reading(self.root)
        self.assertTrue(data['present'])
        self.assertTrue(data['on_battery'])
        self.assertEqual(data['battery'], '50%')
        self.assertEqual(data['remaining'], '2h 00m remaining')

    def test_missing_or_invalid_estimates_stay_hidden(self):
        path = self.supply(type='Battery', status='Discharging', capacity=50,
                           energy_now=10_000_000, energy_full=20_000_000, power_now=2_000_000)
        with patch.object(battery.subprocess, 'run', side_effect=FileNotFoundError):
            for value in ('0', '-1', 'nan', 'invalid'):
                (path / 'time_to_empty_now').write_text(value)
                self.assertEqual(battery.reading(self.root)['remaining'], '')

    def test_upower_estimate_is_accepted_when_available(self):
        self.supply(type='Battery', status='Discharging', capacity=60)
        with patch.object(battery.subprocess, 'run', return_value=subprocess.CompletedProcess([], 0, 'x 5400\n')):
            self.assertEqual(battery.reading(self.root)['remaining'], '1h 30m remaining')

    def test_ac_transition_changes_mode_and_hides_discharge_estimate(self):
        self.supply(type='Battery', status='Discharging', capacity=60, time_to_empty_now=3600)
        ac = self.supply('AC', type='Mains', online=0)
        self.assertTrue(battery.reading(self.root)['on_battery'])
        (ac / 'online').write_text('1')
        data = battery.reading(self.root)
        self.assertFalse(data['on_battery'])
        self.assertEqual(data['remaining'], '')

    def test_multiple_batteries_use_weighted_percentage(self):
        self.supply(type='Battery', status='Full', energy_now=10, energy_full=20)
        self.supply('BAT1', type='Battery', status='Full', energy_now=30, energy_full=30)
        self.assertEqual(battery.reading(self.root)['battery'], '80%')


if __name__ == '__main__':
    unittest.main()
