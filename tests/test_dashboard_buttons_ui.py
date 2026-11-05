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
            self.app = native.Dashboard(Path(self.temporary.name), preview=True, size=(2560, 1440))
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

    def test_header_buttons_dispatch_their_actions(self):
        self.click(self.button(self.app.header_controls, 'Packages'))
        self.app.run.assert_called_once_with('packages.py', 'launch')
        self.click(self.app.edit_button)
        self.assertTrue(self.app.drawer.get_mapped())
        self.click(self.button(self.app.drawer, 'Close'))
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

    def tearDown(self):
        self.release()
        with patch.object(self.native.Gtk, 'main_quit'):
            self.app.quit(); self.app.window.destroy()
        self.pump()


if __name__ == '__main__':
    unittest.main()
