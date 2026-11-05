"""Weather-code artwork and forecast colours without GTK or network access."""
import importlib.util
from pathlib import Path
import unittest
import xml.etree.ElementTree as ET
p=Path(__file__).resolve().parents[1]/'apps/poedash/assets/scripts/weather_visual.py'
spec=importlib.util.spec_from_file_location('weather_visual',p)
visual=importlib.util.module_from_spec(spec);spec.loader.exec_module(visual)

class WeatherVisual(unittest.TestCase):
    def test_supported_codes_have_valid_svg_and_readable_condition(self):
        for code in (0,1,2,3,45,48,51,53,55,56,57,61,63,65,66,67,71,73,75,77,80,81,82,85,86,95,96,99,None,1000):
            for day in (True,False):
                with self.subTest(code=code,day=day):
                    document=visual.icon_svg(code,day)
                    self.assertEqual(ET.fromstring(document).tag,'{http://www.w3.org/2000/svg}svg')
                    self.assertTrue(visual.condition(code,day)[1])
                    self.assertNotIn('<animate',document)
                    self.assertNotIn('href=',document)

    def test_rain_snow_storm_and_day_night_are_distinct(self):
        self.assertEqual(visual.condition(61)[0],'rain')
        self.assertEqual(visual.condition(75)[0],'snow')
        self.assertEqual(visual.condition(95)[0],'storm')
        self.assertNotEqual(visual.icon_svg(0,True),visual.icon_svg(0,False))
        self.assertNotEqual(visual.icon_svg(61),visual.icon_svg(75))
