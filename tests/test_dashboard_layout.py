"""Responsive geometry, hostname identity and persistent live density changes."""
import importlib.util
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('dashboard_layout', ROOT / 'apps/shared/dashboard-layout.py')
layout = importlib.util.module_from_spec(spec)
spec.loader.exec_module(layout)


class GeometryTests(unittest.TestCase):
    def test_card_widths_fit_wide_laptop_and_narrow_displays(self):
        for width, height in ((1920, 1080), (1366, 768), (1280, 720), (2560, 1440), (1000, 800), (720, 900), (320, 480)):
            for mode in ('compact', 'comfortable'):
                with self.subTest(width=width, height=height, mode=mode):
                    data = layout.geometry(width, height, mode)
                    padding = data['card_padding']
                    total = (data['columns'] * (data['card_width'] + 2 * padding + 4)
                             + (data['columns'] - 1) * data['gap'] + 2 * data['padding']
                             + data['rail_width'] + data['gap'])
                    self.assertLessEqual(total, width)
                    self.assertIn(data['columns'], (1, 2, 3))
                    self.assertIs(type(data['session_width']), int)
                    self.assertLessEqual(3 * data['session_width'] + 16 + 2 * data['row_gap'], data['card_width'])
                    for key in ('list_height', 'share_height', 'power_height'):
                        self.assertGreater(data[key], 0)
        self.assertEqual(layout.geometry(1920, 1080)['columns'], 3)
        self.assertEqual(layout.geometry(1100, 800)['columns'], 3)
        self.assertEqual(layout.geometry(720, 900)['columns'], 2)

    def test_enlarged_modes_use_readable_fonts_and_compact_fits_1080p(self):
        compact = layout.geometry(1920, 1080, 'compact')
        comfortable = layout.geometry(1920, 1080, 'comfortable')
        self.assertLess(compact['row_gap'], comfortable['row_gap'])
        self.assertLess(compact['padding'], comfortable['padding'])
        self.assertGreaterEqual(compact['font_size'], 10)
        self.assertGreater(comfortable['font_size'], compact['font_size'])
        self.assertLessEqual(comfortable['font_size'], 20)
        self.assertLessEqual(compact['font_size'], 17)
        total = sum(compact[key] for key in ('calendar_height', 'connectivity_height', 'management_height'))
        self.assertLessEqual(total + 2 * compact['padding'] + compact['header_height'] + 3 * compact['gap'], 1080)
        for data in (compact, comfortable):
            self.assertGreater(data['album_size'], 54)
            self.assertLessEqual(data['album_size'] + data['media_text_width'] + 16, data['card_width'])

    def test_new_typography_preserves_card_geometry_and_old_compact_sizes(self):
        sizes = ('font_size', 'small_size', 'heading_size', 'title_size',
                 'media_title_size', 'app_name_size', 'calendar_size')
        bounds = ('card_width', 'card_padding', 'gap', 'row_gap', 'rail_width', 'header_height',
                  'arch_height', 'system_height', 'calendar_height', 'performance_height',
                  'processes_height', 'connectivity_height', 'player_height', 'shares_height', 'management_height')
        for width, height in ((1280, 720), (1920, 1080), (3840, 2160)):
            baseline = layout._geometry(width, height, 'compact')
            for mode in ('compact', 'comfortable'):
                old = layout._geometry(width, height, mode)
                new = layout.geometry(width, height, mode)
                for key in bounds:
                    self.assertEqual(new[key], old[key], (width, mode, key))
                for key in sizes:
                    floor = 8 if key in ('small_size', 'app_name_size') else 9
                    expected = baseline[key] if mode == 'comfortable' else max(floor, baseline[key] - (2 if key == 'app_name_size' else 6))
                    self.assertEqual(new[key], expected, (width, mode, key))

    def test_each_column_fits_without_dashboard_scrolling(self):
        for width, height in ((1920,1080),(1366,768),(1280,720),(2560,1440),(1000,800)):
            for mode in ('compact','comfortable'):
                data = layout.geometry(width,height,mode)
                for column in [('arch','performance','player'),('system','processes','shares'),('calendar','connectivity','management')]:
                    total = sum(data[name+'_height'] for name in column)
                    self.assertLessEqual(total + 2*data['padding'] + data['header_height'] + 3*data['gap'], height)
                self.assertLess(data['arch_height'], data['player_height'])
                self.assertGreater(data['calendar_height'], 100)

    def test_resolution_matrix_up_to_4k_and_fractional_scaling(self):
        physical = [(3840,2160,1),(3840,2160,1.25),(3840,2160,1.5),(3840,2160,2),(3840,2160,3),(2560,1440,1),(1920,1080,1),(1366,768,1),(1280,720,1),(1024,768,1),(720,900,1),(320,480,1)]
        for width,height,scale in physical:
            width,height=round(width/scale),round(height/scale)
            for mode in ('compact','comfortable'):
                with self.subTest(width=width,height=height,mode=mode):
                    d=layout.geometry(width,height,mode)
                    if d['columns']==3:
                        columns=[('arch','performance','player'),('system','processes','shares'),('calendar','connectivity','management')]
                    else:
                        ordered=['arch','system','calendar','performance','processes','connectivity','player','shares','management']
                        columns=[ordered[i::d['columns']] for i in range(d['columns'])]
                    for cards in columns:
                        used=sum(d[name+'_height'] for name in cards)+(len(cards)-1)*d['gap']+d['header_height']+d['gap']+2*d['padding']
                        self.assertLessEqual(used,height)
                    self.assertLessEqual(d['columns']*(d['card_width']+2*d['card_padding']+4)+(d['columns']-1)*d['gap']+d['rail_width']+d['gap']+2*d['padding'],width)

    def test_app_captions_are_secondary_and_fit_the_rail(self):
        for mode, size in [('compact', 8), ('comfortable', 10)]:
            data = layout.geometry(1920, 1080, mode)
            self.assertEqual(data['app_name_size'], size)
            self.assertLessEqual(size, data['small_size'])
            self.assertLess((data['rail_name_chars'] + 3) * size * .62, data['rail_content_width'] + 1)

    def test_monitor_uses_logical_pixels_and_reserved_bars(self):
        monitors = [dict(name='eDP-1', width=2560, height=1440, scale=2, reserved=[0, 30, 0, 0]),
                    dict(name='DP-1', width=1920, height=1080, scale=1, transform=1, reserved=[0, 0, 0, 0])]
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with patch.object(layout.subprocess, 'run', return_value=subprocess.CompletedProcess([], 0, json.dumps(monitors))):
                self.assertEqual(layout.monitor_size(root), (1280, 690))
                (root / 'settings.json').write_text('{"monitor":"DP-1"}')
                self.assertEqual(layout.monitor_size(root), (1080, 1920))
                (root / 'settings.json').write_text('{"monitor":"disconnected-output"}')
                self.assertEqual(layout.monitor_size(root), (1280, 690))

    def test_missing_compositor_falls_back_without_failure(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(layout.subprocess, 'run', side_effect=FileNotFoundError):
            self.assertEqual(layout.monitor_size(Path(tmp)), (1920, 1080))


class PreferenceTests(unittest.TestCase):
    def test_hostname_comes_from_the_current_machine(self):
        with tempfile.TemporaryDirectory() as tmp, \
                patch.object(layout, 'monitor_size', return_value=(1920, 1080)), \
                patch.object(layout.socket, 'gethostname', return_value='my-other-laptop'):
            self.assertEqual(layout.snapshot(Path(tmp))['hostname'], 'my-other-laptop')

    def test_missing_corrupt_or_unknown_preferences_default_to_comfortable(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.assertEqual(layout.density(root), 'comfortable')
            for content in ('broken json', '[]', '{"density":"unknown"}'):
                (root / 'layout.json').write_text(content)
                self.assertEqual(layout.density(root), 'comfortable')

    def test_toggle_updates_only_its_running_dashboard_and_persists(self):
        with tempfile.TemporaryDirectory(prefix='layout preference ') as tmp:
            root = Path(tmp)
            (root / 'layout.json').write_text('{"custom":"keep","density":"compact"}')
            with patch.object(layout, 'monitor_size', return_value=(1366, 768)), \
                    patch.object(layout.subprocess, 'run') as command:
                first = layout.toggle(root)
                self.assertEqual(first['density'], 'comfortable')
                argv = command.call_args.args[0]
                self.assertEqual(argv[:4], ['eww', '--config', str(root), 'update'])
                self.assertEqual(json.loads(argv[4].removeprefix('layout=')), first)
                self.assertNotIn('reload', argv)
                self.assertEqual(layout.snapshot(root)['density'], 'comfortable')
                self.assertEqual(layout.toggle(root)['density'], 'compact')
            saved = json.loads((root / 'layout.json').read_text())
            self.assertEqual(saved, {'custom': 'keep', 'density': 'compact'})
            self.assertEqual(list(root.glob('.layout-*')), [])

    def test_disconnected_dashboard_keeps_preference_for_next_start(self):
        with tempfile.TemporaryDirectory() as tmp, \
                patch.object(layout, 'monitor_size', return_value=(1920, 1080)), \
                patch.object(layout.subprocess, 'run', side_effect=subprocess.CalledProcessError(1, ['eww'])):
            with self.assertRaises(subprocess.CalledProcessError):
                layout.toggle(Path(tmp))
            self.assertEqual(layout.density(Path(tmp)), 'compact')


class DashboardStructureTests(unittest.TestCase):
    def test_dashboard_has_the_same_three_rows_and_live_control(self):
        cards = (('arch', 'system', 'calendar'), ('performance', 'processes', 'connectivity'), ('player', 'shares', 'power'))
        for path in (ROOT / 'apps/poedash/assets/templates/eww.yuck',):
            with self.subTest(path=path):
                text = path.read_text()
                wide = layout.geometry(1920,1080)['grid']
                self.assertIn('(literal :content dashboard_grid)', text)
                for row in cards:
                    for card in row:
                        self.assertIn(f'({card}-card :height', wide)
                self.assertIn(':text {layout.hostname}', text)
                self.assertIn('layout.py toggle', text)
                self.assertIn('layout.py listen', text)
                self.assertIn('layout.list_height', text)
                self.assertIn('layout.share_height', text)
                self.assertIn('(recent-apps-card)', text)
                sidebar = text.split('(defwidget recent-apps-card []')[1].split('(defwidget dashboard-content []')[0]
                self.assertIn(':class "card recent-rail"', sidebar)
                self.assertNotIn('layout.hostname', sidebar)
                content = text.split('(defwidget dashboard-content []')[1]
                self.assertLess(content.index(':text {layout.hostname}'), content.index('(recent-apps-card)'))
                self.assertIn('app_lists.pinned', sidebar)
                self.assertIn('rail-divider', sidebar)
                self.assertIn(':onrightclick', text)
                self.assertIn('calendar_events.events', text)
                self.assertIn('desktop.py launch ${app.id}', text)
                self.assertIn('desktop.py calendar', text)
                self.assertIn(':image-width {layout.album_size}', text)
                self.assertIn('/media-control.sh open', text)
                self.assertIn(':width 0 :height {layout.list_height}', text)
                self.assertIn(':width 0 :height {layout.share_height}', text)
                self.assertNotIn(':text "BLACKARCH"', text)


if __name__ == '__main__':
    unittest.main()
