"""Run with POEDASH_GUI_TEST=1 GDK_BACKEND=x11 xvfb-run -a python -m unittest
discover -s tests -p test_dashboard_service_ui.py.
"""
import os
from pathlib import Path
import sys
import threading
import time
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'apps/poedash/assets/scripts'))


@unittest.skipUnless(os.environ.get('POEDASH_GUI_TEST') == '1', 'Requires an isolated GTK display')
class ServiceNavigation(unittest.TestCase):
    def setUp(self):
        import dashboard_native as native
        self.native = native
        self.app = native.Dashboard.__new__(native.Dashboard)
        self.app.drawer = native.Gtk.Box(orientation=native.Gtk.Orientation.VERTICAL)
        self.app.closing = False
        self.app.transaction = None
        self.app.samples = {'health': {'value': {'failed': []}}}
        self.app.engine = Mock()
        self.app.focus_card = Mock()
        self.app.issues = [{'card': 'system', 'text': 'Failed ' + scope + ' unit: example.service',
                            'unit': 'example.service', 'scope': scope} for scope in ('system', 'user')]

    def descendants(self, widget):
        yield widget
        if isinstance(widget, self.native.Gtk.Container):
            for child in widget.get_children(): yield from self.descendants(child)

    def button(self, title):
        return next(w for w in self.descendants(self.app.drawer)
                    if isinstance(w, self.native.Gtk.Button) and w.get_label() == title)

    def pump(self, condition):
        context = self.native.GLib.MainContext.default()
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline:
            while context.pending(): context.iteration(False)
            if condition(): return
            time.sleep(.01)
        self.fail('Diagnostics did not finish loading')

    def test_click_opens_exact_user_unit_and_back_returns_to_issues(self):
        result = {'status': 'Active: failed', 'journal': 'Concrete failure reason'}
        with patch.object(self.native, 'service_details', return_value=result) as read:
            self.app.show_health()
            self.button('Failed user unit: example.service').clicked()
            self.pump(lambda: self.button('Refresh details').get_sensitive())
        read.assert_called_once_with('example.service', 'user')
        views = [w for w in self.descendants(self.app.drawer) if isinstance(w, self.native.Gtk.TextView)]
        self.assertEqual([v.get_buffer().get_text(v.get_buffer().get_start_iter(), v.get_buffer().get_end_iter(), True)
                          for v in views], ['Active: failed', 'Concrete failure reason'])
        self.app.focus_card.assert_not_called()
        self.button('Back to system health').clicked()
        self.assertIsNotNone(self.button('Failed system unit: example.service'))

    def test_late_response_cannot_replace_another_drawer_page(self):
        release, delivered = threading.Event(), threading.Event()
        def read(*args):
            release.wait(2)
            return {'status': 'OLD RESULT', 'journal': 'OLD LOGS'}
        idle_add = self.native.GLib.idle_add
        def schedule(callback, result):
            def invoke():
                try: return callback(result)
                finally: delivered.set()
            return idle_add(invoke)
        with patch.object(self.native, 'service_details', side_effect=read), \
             patch.object(self.native.GLib, 'idle_add', side_effect=schedule):
            self.app.show_service_details('example.service', 'system')
            self.assertFalse(self.button('Refresh details').get_sensitive())
            self.app.show_health()
            generation = self.app.drawer_generation
            release.set()
            self.pump(delivered.is_set)
        self.assertEqual(self.app.drawer_generation, generation)
        self.assertIsNotNone(self.button('Failed user unit: example.service'))
        self.app.engine.request.assert_not_called()

    def test_refresh_shows_recovered_service_state(self):
        with patch.object(self.native, 'service_details', side_effect=[
                {'status': 'Active: failed', 'journal': 'Earlier failure'},
                {'status': 'Active: active (running)', 'journal': 'Service recovered'}]) as read:
            self.app.show_service_details('example.service', 'user')
            self.pump(lambda: self.button('Refresh details').get_sensitive())
            self.button('Refresh details').clicked()
            self.pump(lambda: self.button('Refresh details').get_sensitive())
        self.assertEqual(read.call_count, 2)
        status = next(w for w in self.descendants(self.app.drawer) if isinstance(w, self.native.Gtk.TextView)).get_buffer()
        self.assertEqual(status.get_text(status.get_start_iter(), status.get_end_iter(), True), 'Active: active (running)')

    def test_single_failure_summary_opens_its_diagnostics(self):
        self.app.issues = self.app.issues[1:]
        with patch.object(self.app, 'show_service_details') as show:
            self.app.open_health_summary()
        show.assert_called_once_with('example.service', 'user')


if __name__ == '__main__':
    unittest.main()
