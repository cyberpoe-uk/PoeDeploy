"""Real clicks on an isolated display:
POEDASH_GUI_TEST=1 GDK_BACKEND=x11 xvfb-run -a -s '-screen 0 2560x1440x24' \
    python3 -m unittest discover -s tests -p test_dashboard_buttons_ui.py -v
"""
import ctypes
import os
from pathlib import Path
import sys
import tempfile
import time
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'apps/poedash/assets/scripts'))


@unittest.skipUnless(os.environ.get('POEDASH_GUI_TEST') == '1', 'Requires an isolated X11 display')
class ButtonRefresh(unittest.TestCase):
    def setUp(self):
        import dashboard_native as native
        self.native = native
        self.temporary = tempfile.TemporaryDirectory(prefix='poedash-buttons-')
        self.addCleanup(self.temporary.cleanup)
        self.x11 = ctypes.CDLL('libX11.so.6')
        self.xtst = ctypes.CDLL('libXtst.so.6')
        self.x11.XOpenDisplay.restype = ctypes.c_void_p
        self.x11.XOpenDisplay.argtypes = [ctypes.c_char_p]
        self.x11.XFlush.argtypes = [ctypes.c_void_p]
        self.x11.XCloseDisplay.argtypes = [ctypes.c_void_p]
        self.xtst.XTestFakeMotionEvent.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_ulong]
        self.xtst.XTestFakeButtonEvent.argtypes = [ctypes.c_void_p, ctypes.c_uint, ctypes.c_int, ctypes.c_ulong]
        self.display = self.x11.XOpenDisplay(None)
        self.assertTrue(self.display)
        self.addCleanup(self.x11.XCloseDisplay, self.display)
        with patch.object(native.Engine, 'start'), patch.object(native.Dashboard, 'spawn_listener'), \
                patch.object(native.Dashboard, 'start_ipc'):
            self.app = native.Dashboard(Path(self.temporary.name), preview=True, size=(1920, 1080))
        self.app.run = Mock()
        self.pump(.3)

    def pump(self, seconds=.12):
        context = self.native.GLib.MainContext.default()
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            while context.pending(): context.iteration(False)
            time.sleep(.003)

    def descendants(self, widget):
        yield widget
        if isinstance(widget, self.native.Gtk.Container):
            for child in widget.get_children(): yield from self.descendants(child)

    def button(self, parent, title):
        return next(w for w in self.descendants(parent)
                    if isinstance(w, self.native.Gtk.Button) and w.get_label() == title)

    def press(self, widget):
        x, y = widget.translate_coordinates(self.app.window, widget.get_allocated_width()//2, widget.get_allocated_height()//2)
        origin = self.app.window.get_window().get_origin()
        self.xtst.XTestFakeMotionEvent(self.display, -1, origin.x+x, origin.y+y, 0)
        self.x11.XFlush(self.display)
        self.pump()
        self.xtst.XTestFakeButtonEvent(self.display, 1, 1, 0)
        self.x11.XFlush(self.display)
        self.pump(.06)

    def release(self):
        self.xtst.XTestFakeButtonEvent(self.display, 1, 0, 0)
        self.x11.XFlush(self.display)
        self.pump(.2)

    def click(self, widget):
        self.press(widget); self.release()

    def test_header_packages_button_dispatches_its_action(self):
        self.click(self.button(self.app.header_controls, 'Packages'))
        self.app.run.assert_called_once_with('packages.py', 'launch')

    def test_header_edit_button_opens_the_drawer(self):
        self.click(self.app.edit_button)
        self.assertTrue(self.app.drawer.get_mapped())

    def test_header_zoom_button_changes_zoom(self):
        before = self.app.profile['appearance']['scale']
        self.click(self.button(self.app.header_controls, '+'))
        self.assertGreater(self.app.profile['appearance']['scale'], before)

    def test_media_click_survives_a_collector_refresh(self):
        card = self.app.cards['player']
        self.press(self.button(card.player_controls, '▶'))
        card.render(); self.pump()
        self.release()
        self.app.run.assert_called_once_with('media-control.sh', 'play-pause')

    def test_timer_click_survives_a_collector_refresh(self):
        self.app.samples['session'] = {'value': {'supported': True, 'screen': 60, 'lock': 60, 'suspend': 0}}
        card = self.app.cards['session']; card.render(); self.pump()
        self.press(self.button(card.body, '+'))
        card.render(); self.pump()
        self.release()
        self.app.run.assert_called_once_with('idle-control.py', 'adjust', 'screen', '1')

    def test_seek_drag_survives_a_collector_refresh(self):
        self.app.samples['media'] = {'value': {'available': True, 'length': '3:00', 'progress': 30}}
        card = self.app.cards['player']; card.render(); self.pump()
        seek = next(w for w in self.descendants(card.player_controls) if isinstance(w, self.native.Gtk.Scale))
        self.press(seek)
        card.render(); self.pump()
        self.release()
        self.assertEqual(self.app.run.call_count, 1)
        self.assertEqual(self.app.run.call_args.args[:2], ('media-actions.py', 'seek'))
        self.assertGreater(float(self.app.run.call_args.args[2]), 30)

    def test_details_stay_expanded_and_show_new_readings(self):
        for key in ('system', 'connectivity'):
            with self.subTest(card=key):
                card = self.app.cards[key]
                detail = next(w for w in self.descendants(card) if isinstance(w, self.native.Gtk.Expander))
                detail.set_expanded(True); self.pump()
                self.app.samples['health'] = {'value': {'disks': [{'path': '/new-mount', 'free_gib': 42, 'percent': 20}]}}
                self.app.samples['network'] = {'value': {'interface': 'new-interface'}}
                card.render(); self.pump()
                detail = next(w for w in self.descendants(card) if isinstance(w, self.native.Gtk.Expander))
                self.assertTrue(detail.get_expanded())
                labels = [w.get_text() for w in self.descendants(detail) if isinstance(w, self.native.Gtk.Label)]
                self.assertIn('/new-mount' if key == 'system' else 'new-interface', labels)

    def populate_recent_apps(self):
        self.app.receive_apps({'pinned': [], 'recent': [
            {'id': 'test.desktop', 'name': 'Test app', 'icon': 'application-x-executable'}]})
        self.pump()

    def appearance_control(self, title):
        return next(w for w in self.descendants(self.app.drawer)
                    if isinstance(w, self.native.Gtk.SpinButton) and w.get_accessible().get_name() == title)

    def assert_app_sizes(self, text_size, icon_size):
        self.pump()
        image = next(w for w in self.descendants(self.app.rail_body) if isinstance(w, self.native.Gtk.Image))
        text = next(w for w in self.descendants(self.app.rail_body)
                    if isinstance(w, self.native.Gtk.Label) and w.get_text() == 'Test app')
        self.assertEqual(image.get_pixel_size(), icon_size)
        font = text.get_style_context().get_font(self.native.Gtk.StateFlags.NORMAL)
        pixels = font.get_size() / self.native.Pango.SCALE
        if not font.get_size_is_absolute():
            dpi = text.get_screen().get_resolution()
            pixels *= (dpi if dpi > 0 else 96) / 72
        self.assertAlmostEqual(pixels, text_size)

    def test_recent_app_sizes_preview_save_and_remain_separate_from_zoom(self):
        self.populate_recent_apps()
        self.app.open_settings('Appearance')
        self.appearance_control('Recent Apps text size').set_value(20)
        self.appearance_control('Recent Apps icon size').set_value(64)
        self.assert_app_sizes(20, 64)
        self.assertEqual(self.app.profile['appearance']['font_size'], 14)
        self.assertEqual(self.app.profile['appearance']['scale'], 1)
        self.app.save()
        saved = self.native.Settings(self.app.root).profile['appearance']
        self.assertEqual((saved['recent_text_size'], saved['recent_icon_size']), (20, 64))
        self.assertGreaterEqual(self.app.rail.get_allocated_width(), 100)

    def test_recent_app_sizes_can_be_reduced_and_cancel_restores_them(self):
        self.populate_recent_apps()
        self.app.settings.save()
        self.app.open_settings('Appearance')
        self.appearance_control('Recent Apps text size').set_value(11)
        self.appearance_control('Recent Apps icon size').set_value(24)
        self.assert_app_sizes(11, 24)
        self.app.cancel()
        self.assert_app_sizes(14, 40)
        self.assertEqual(self.native.Settings(self.app.root).profile['appearance']['recent_icon_size'], 40)

    def test_recent_app_sizes_are_independent_between_profiles(self):
        self.populate_recent_apps()
        self.app.open_settings('Appearance')
        self.appearance_control('Recent Apps icon size').set_value(64)
        self.app.save()
        self.app.profile_combo.set_active(1)
        self.assert_app_sizes(14, 40)
        self.app.profile_combo.set_active(0)
        self.assert_app_sizes(14, 64)

    def tearDown(self):
        self.release()
        with patch.object(self.native.Gtk, 'main_quit'):
            self.app.quit(); self.app.window.destroy()
        self.pump()


if __name__ == '__main__':
    unittest.main()
