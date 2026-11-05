"""CPU sensor fallbacks used by the GTK performance card."""
import importlib.util
from pathlib import Path
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('temps', ROOT / 'apps/poedash/assets/scripts/cpu-temperature.py')
temps = importlib.util.module_from_spec(spec)
spec.loader.exec_module(temps)

class CpuTemperature(unittest.TestCase):
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
