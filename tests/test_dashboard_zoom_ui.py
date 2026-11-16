"""GTK zoom/profile checks. Run with POEDASH_GUI_TEST=1 GDK_BACKEND=x11 xvfb-run -a."""
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
class ProfileZoom(unittest.TestCase):
    def setUp(self):
        import dashboard_native as native
        self.native=native
        self.temporary=tempfile.TemporaryDirectory(prefix='poedash-zoom-')
        self.addCleanup(self.temporary.cleanup)
        with patch.object(native.Engine,'start'), patch.object(native.Dashboard,'spawn_listener'), \
                patch.object(native.Dashboard,'start_ipc'), patch.object(native.Dashboard,'smoke_test',return_value=False):
            self.app=native.Dashboard(Path(self.temporary.name),preview=True,smoke=True,size=(1920,1080))
        self.pump()

    def pump(self):
        context=self.native.GLib.MainContext.default()
        deadline=time.monotonic()+.15
        while time.monotonic()<deadline:
            while context.pending():context.iteration(False)
            time.sleep(.003)

    def test_zoom_persists_without_replacing_the_saved_layout(self):
        app=self.app
        app.store_layout(); saved=deepcopy(app.profile['layouts'])
        for zoom in (.5,1,1.25,1.5,2,1):
            with self.subTest(zoom=zoom):
                app.change_zoom(zoom-app.profile['appearance']['scale']);self.pump()
                self.assertEqual(self.native.Settings(app.root).profile['appearance']['scale'],zoom)
                self.assertEqual(app.profile['layouts'],saved)
                self.assertLessEqual(app.canvas_size[1],app.board_view.get_allocated_height())

    def test_editing_zoom_supports_undo_redo_and_cancel(self):
        app=self.app;app.settings.save()
        before=deepcopy(app.settings.data)
        app.edit_layout();app.change_zoom(.25);self.pump()
        self.assertEqual(app.profile['appearance']['scale'],1.25)
        self.assertEqual(self.native.Settings(app.root).profile['appearance']['scale'],1)
        app.undo();self.pump();self.assertEqual(app.profile['appearance']['scale'],1)
        app.redo();self.pump();self.assertEqual(app.profile['appearance']['scale'],1.25)
        app.cancel();self.pump();self.assertEqual(app.settings.data,before)

    def test_display_changes_keep_profiles_and_saved_arrangements(self):
        app=self.app;app.store_layout()
        saved=deepcopy(app.profile['layouts'])
        for width,height in ((1440,960),(2560,1440),(1920,1080)):
            display=f'test:{width}x{height}@1'
            with patch.object(app,'choose_monitor',side_effect=lambda:setattr(app,'display_key',display)):
                app.monitor_changed()
            app.window.set_size_request(width,height);app.window.resize(width,height);self.pump()
            self.assertEqual(app.profile['layouts'],saved)
            self.assertLessEqual(app.canvas_size[1],app.board_view.get_allocated_height())

    def test_card_heading_and_appearance_drafts(self):
        app=self.app
        card=next(iter(app.cards.values()))
        key=card.key
        title=card.title.get_allocation()
        heading=card.title.get_parent().get_allocation()
        self.assertAlmostEqual(title.x+title.width/2,heading.x+heading.width/2,delta=2)
        app.card_menu(card)
        app.set_card_color(key,'#28456a')
        app.save();self.pump()
        self.assertEqual(self.native.Settings(app.root).profile['card_colors'][key],'#28456a')
        app.card_menu(app.cards[key]);app.set_card_color(key,'#bb2244');app.cancel();self.pump()
        self.assertEqual(app.profile['card_colors'][key],'#28456a')
        app.card_menu(app.cards[key]);app.set_card_color(key,None);app.save();self.pump()
        self.assertNotIn(key,self.native.Settings(app.root).profile['card_colors'])
        app.open_settings('Appearance')
        def descendants(widget):
            yield widget
            if isinstance(widget,self.native.Gtk.Container):
                for child in widget.get_children():yield from descendants(child)
        controls={widget.get_accessible().get_name():widget for widget in descendants(app.drawer)
                  if isinstance(widget,self.native.Gtk.SpinButton)}
        controls['Dashboard width (%)'].set_value(80)
        controls['Dashboard height (%)'].set_value(90)
        controls['Content size (%)'].set_value(110)
        self.assertEqual(app.profile['appearance']['dashboard_width'],80)
        self.assertEqual(app.profile['appearance']['scale'],1.1)
        app.cancel();self.pump()
        self.assertEqual(app.profile['appearance'].get('dashboard_width',100),100)
        self.assertEqual(app.profile['appearance']['scale'],1)

    def tearDown(self):
        with patch.object(self.native.Gtk,'main_quit'):
            self.app.quit();self.app.window.destroy()
        self.pump()
