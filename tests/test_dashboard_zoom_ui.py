"""Run with POEDASH_GUI_TEST=1 GDK_BACKEND=x11 xvfb-run -a python -m unittest
discover -s tests -p test_dashboard_zoom_ui.py.
"""
from copy import deepcopy
import os
from pathlib import Path
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'apps/poedash/assets/scripts'))


@unittest.skipUnless(os.environ.get('POEDASH_GUI_TEST') == '1', 'Requires an isolated GTK display')
class ResponsiveZoom(unittest.TestCase):
    def setUp(self):
        import dashboard_native as native
        self.native = native
        self.temporary = tempfile.TemporaryDirectory(prefix='poedash-zoom-test-')
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.apps = []

    def create(self, width=1280, height=800):
        native = self.native
        with patch.object(native.Engine, 'start'), patch.object(native.Dashboard, 'spawn_listener'), \
                patch.object(native.Dashboard, 'start_ipc'), \
                patch.object(native.Dashboard, 'power_profile', return_value={
                    'supported': True, 'available': ['performance', 'balanced', 'power-saver']}), \
                patch.object(native.Dashboard, 'smoke_test', return_value=False):
            app = native.Dashboard(self.root, preview=True, smoke=True, size=(width, height))
        self.apps.append(app)
        self.pump()
        return app

    def pump(self):
        context = self.native.GLib.MainContext.default()
        deadline = time.monotonic() + .15
        while time.monotonic() < deadline:
            while context.pending(): context.iteration(False)
            time.sleep(.005)

    def zoom(self, app, target):
        app.change_zoom(target - app.profile['appearance']['scale'])
        self.pump()

    def assert_fits(self, app, size):
        self.assertEqual(tuple(app.window.get_size()), size)
        horizontal = app.board_view.get_hadjustment()
        self.assertLessEqual(horizontal.get_upper() - horizontal.get_page_size(), 1)
        width, height = app.canvas_size
        for key, card in app.cards.items():
            bounds = card.get_allocation()
            self.assertGreaterEqual(bounds.x, 0, key)
            self.assertGreaterEqual(bounds.y, 0, key)
            self.assertLessEqual(bounds.x + bounds.width, width + 2, key)
            self.assertLessEqual(bounds.y + bounds.height, height + 2, key)
            for other_key, other in app.cards.items():
                if key >= other_key: continue
                target = other.get_allocation()
                overlap_x = min(bounds.x + bounds.width, target.x + target.width) - max(bounds.x, target.x)
                overlap_y = min(bounds.y + bounds.height, target.y + target.height) - max(bounds.y, target.y)
                self.assertFalse(overlap_x > 2 and overlap_y > 2, (key, other_key))

    def test_zoom_reflows_cards_and_keeps_every_card_reachable(self):
        app = self.create()
        for target in (.5, 1, 1.25, 1.5, 2, 1):
            with self.subTest(zoom=target):
                self.zoom(app, target)
                self.assert_fits(app, (1280, 800))
        self.zoom(app, 2)
        self.assertEqual(len({round(rect[0], 3) for rect in app.layout.values()}), 1)
        vertical = app.board_view.get_vadjustment()
        self.assertGreater(vertical.get_upper(), vertical.get_page_size())
        vertical.set_value(vertical.get_upper() - vertical.get_page_size())
        self.pump()
        self.assertGreater(vertical.get_value(), 0)

    def test_small_screen_and_maximum_zoom_keep_the_controls_on_screen(self):
        app = self.create(800, 600)
        self.zoom(app, 2)
        self.assert_fits(app, (800, 600))
        for control in (app.profile_combo, app.zoom_label, app.edit_button):
            x, y = control.translate_coordinates(app.window, 0, 0)
            self.assertGreaterEqual(x, 0)
            self.assertLessEqual(x + control.get_allocated_width(), 800)

    def test_zoom_preserves_and_restores_custom_arrangement(self):
        app = self.create()
        saved = deepcopy(app.layout)
        saved['arch'], saved['system'] = saved['system'], saved['arch']
        app.profile['layouts'][app.display_key] = deepcopy(saved)
        app.settings.save()
        app.reflow()
        self.pump()
        self.zoom(app, 2)
        self.assertNotEqual(app.layout, saved)
        self.assertEqual(app.profile['layouts'][app.display_key], saved)
        self.zoom(app, 1)
        self.assertEqual(app.layout, saved)
        self.assertEqual(app.profile['layouts'][app.display_key], saved)
        self.assert_fits(app, (1280, 800))

    def test_editing_zoom_undo_redo_and_cancel_restore_the_view(self):
        app = self.create()
        app.settings.save()
        original = deepcopy(app.settings.data)
        app.edit_layout()
        self.zoom(app, 2)
        self.assert_fits(app, (1280, 800))
        app.undo(); self.pump()
        self.assertEqual(app.profile['appearance']['scale'], 1)
        self.assert_fits(app, (1280, 800))
        app.redo(); self.pump()
        self.assertEqual(app.profile['appearance']['scale'], 2)
        self.assert_fits(app, (1280, 800))
        app.cancel(); self.pump()
        self.assertEqual(app.settings.data, original)
        self.assert_fits(app, (1280, 800))

    def test_live_resolution_changes_resize_without_restarting(self):
        app = self.create()
        self.zoom(app, 1.5)
        original_display = app.display_key
        saved = deepcopy(app.layout)
        app.profile['layouts'][original_display] = deepcopy(saved)
        for width, height in ((800, 600), (1920, 1080), (1280, 800)):
            with self.subTest(resolution=(width, height)):
                display = f'test:{width}x{height}@1'
                with patch.object(app, 'choose_monitor', side_effect=lambda: setattr(app, 'display_key', display)):
                    app.monitor_changed()
                app.window.set_size_request(width, height)
                app.window.set_default_size(width, height)
                app.window.resize(width, height)
                self.pump()
                self.assert_fits(app, (width, height))
                self.assertEqual(app.profile['appearance']['scale'], 1.5)
                self.assertEqual(app.profile['layouts'][original_display], saved)

    def test_desktop_custom_layout_stays_intact_at_maximum_zoom(self):
        app = self.create(2560, 1440)
        saved = deepcopy(app.layout)
        saved['arch'], saved['system'] = saved['system'], saved['arch']
        app.profile['layouts'][app.display_key] = deepcopy(saved)
        self.zoom(app, 2)
        self.assert_fits(app, (2560, 1440))
        self.assertEqual(app.layout, saved)
        self.zoom(app, 1)
        self.assertEqual(app.layout, saved)

    def tearDown(self):
        with patch.object(self.native.Gtk, 'main_quit'):
            for app in self.apps:
                app.quit()
                app.window.destroy()
        self.pump()


if __name__ == '__main__':
    unittest.main()
