"""PoeDash column budgets, growing shares and CPU sensor fallbacks."""
import importlib.util
from pathlib import Path
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]

def module(name, path):
    spec = importlib.util.spec_from_file_location(name, ROOT / path)
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result

layout = module('layout', 'apps/shared/dashboard-layout.py')
temps = module('temps', 'apps/poedash/assets/scripts/cpu-temperature.py')


class PoeDashLayout(unittest.TestCase):
    def test_columns_fit_and_shares_grow_without_displacing_performance(self):
        for width, height in ((320,480),(720,900),(1280,720),(1366,768),(1920,1080),(3840,2160)):
            for mode in ('comfortable', 'compact'):
                for count in (0, 1, 5, 30):
                    d = layout.poedash_geometry(width, height, mode, count)
                    columns = [('arch','system','connectivity','session','power'),
                               ('performance','processes','shares'),('calendar','player')]
                    if d['columns'] < 3:
                        ordered = ['arch','system','connectivity','session','power',
                                   'performance','processes','shares','calendar','player']
                        columns = [ordered[i::d['columns']] for i in range(d['columns'])]
                    for cards in columns:
                        used = sum(d[c+'_height'] for c in cards) + len(cards)*d['gap'] + d['header_height'] + 2*d['padding']
                        self.assertLessEqual(used, height)
        small = layout.poedash_geometry(1920,1080,share_count=1)
        large = layout.poedash_geometry(1920,1080,share_count=8)
        self.assertGreater(large['shares_height'], small['shares_height'])
        self.assertEqual(large['performance_height'], small['performance_height'])
        self.assertGreater(large['processes_height'], 100)

    def test_power_fills_remaining_left_column_height(self):
        for width, height in ((1280, 720), (1920, 1080), (2160, 1440), (3840, 2160)):
            for mode in ('comfortable', 'compact'):
                d = layout.poedash_geometry(width, height, mode)
                left = sum(d[c + '_height'] for c in ('arch', 'system', 'connectivity', 'session', 'power')) + 4*d['gap']
                middle = sum(d[c + '_height'] for c in ('performance', 'processes', 'shares')) + 2*d['gap']
                right = d['calendar_height'] + d['player_height'] + d['gap']
                self.assertEqual(left, middle)
                self.assertEqual(left, right)
                self.assertIn(':vexpand true :width 0 :height {layout.power_height}', d['grid'])

    def test_middle_width_is_taken_equally_from_both_sides(self):
        original = layout.geometry(1920, 1080)
        data = layout.poedash_geometry(1920, 1080)
        donation = original['card_width'] - data['card_width']
        self.assertGreater(donation, 0)
        self.assertEqual(data['middle_width'] - original['card_width'], 2 * donation)
        self.assertEqual(2 * data['card_width'] + data['middle_width'], 3 * original['card_width'])
        short = layout.poedash_geometry(1920, 1080, share_count=1, share_rows=['NFS /mnt/media'])
        long = layout.poedash_geometry(1920, 1080, share_count=1, share_rows=['long directory name ' * 30])
        self.assertGreater(long['shares_height'], short['shares_height'])
        self.assertLess(long['processes_height'], short['processes_height'])
        self.assertEqual(long['performance_height'], short['performance_height'])

    def test_temperature_uses_cpu_sensors_and_handles_missing_values(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.assertEqual(temps.reading(root), '--')
            cpu = root / 'class/hwmon/hwmon0'
            cpu.mkdir(parents=True)
            (cpu / 'name').write_text('coretemp')
            (cpu / 'temp1_input').write_text('52000')
            (cpu / 'temp2_input').write_text('57000')
            (cpu / 'temp3_input').write_text('invalid')
            self.assertEqual(temps.reading(root), '57°C')
            (cpu / 'name').write_text('amdgpu')
            self.assertEqual(temps.reading(root), '--')
            zone = root / 'class/thermal/thermal_zone0'
            zone.mkdir(parents=True)
            (zone / 'type').write_text('x86_pkg_temp')
            (zone / 'temp').write_text('48000')
            self.assertEqual(temps.reading(root), '48°C')
