"""Editor/save geometry regressions on an isolated GTK display."""
import os
from pathlib import Path
import sys
import tempfile
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'apps/poedash/assets/scripts'))


@unittest.skipUnless(os.environ.get('POEDASH_GUI_TEST') == '1', 'Requires an isolated GTK display')
class EditLayoutGeometry(unittest.TestCase):
    def setUp(self):
        import dashboard_native as native
        self.native=native
        self.temporary=tempfile.TemporaryDirectory(prefix='poedash-edit-layout-')
        self.addCleanup(self.temporary.cleanup)
        self.root=Path(self.temporary.name)
        settings=native.Settings(self.root)
        settings.profile['visible']=['arch','system','connectivity','performance','calendar','player']
        settings.profile['appearance'].update(spacing=6,graphs=False)
        settings.save()
        with patch.object(native.Engine,'start'), patch.object(native.Dashboard,'spawn_listener'), \
                patch.object(native.Dashboard,'start_ipc'), patch.object(native.Dashboard,'smoke_test',return_value=False):
            self.app=native.Dashboard(self.root,preview=True,smoke=True,size=(1920,1080))
        self.app.clock.set_text('12:00\nThu 05 Nov')
        self.pump()
        width,height=self.app.canvas_size
        self.app.profile['layouts'][self.app.display_key]=self.uniform_layout(width,height)
        self.app.profile.setdefault('layout_sizes',{})[self.app.display_key]=[width,height]
        self.app.settings.save();self.app.reflow();self.pump()

    def uniform_layout(self,width,height):
        half=(width-6)/2
        pixels={'arch':[0,0,half,150], 'system':[0,156,half,300],
                'connectivity':[0,462,half,height-462],
                'performance':[half+6,0,half,230], 'calendar':[half+6,236,half,170],
                'player':[half+6,412,half,height-412]}
        return {key:[x/width,y/height,w/width,h/height] for key,(x,y,w,h) in pixels.items()}

    def pump(self,seconds=.2):
        context=self.native.GLib.MainContext.default()
        deadline=time.monotonic()+seconds
        while time.monotonic()<deadline:
            while context.pending():context.iteration(False)
            time.sleep(.003)

    def geometry(self):
        return {key:(*card.translate_coordinates(self.app.window,0,0),
                     card.get_allocated_width(),card.get_allocated_height()) for key,card in self.app.cards.items()}

    def swap_cards(self):
        app=self.app;card=app.cards['arch']
        origin=app.layout['arch'];target=app.layout['performance']
        width,height=app.canvas_size
        card.press(card.cover,SimpleNamespace(button=1,x=card.get_allocated_width()/2,
                   y=card.get_allocated_height()/2,x_root=100,y_root=100))
        dx=((target[0]+target[2]/2)-(origin[0]+origin[2]/2))*width
        dy=((target[1]+target[3]/2)-(origin[1]+origin[3]/2))*height
        event=SimpleNamespace(x_root=100+dx,y_root=100+dy)
        card.motion(card.cover,event);card.release(card.cover,event);self.pump()
        self.assertNotEqual(app.layout['arch'],origin)

    def test_edit_controls_do_not_move_or_resize_cards(self):
        before=self.geometry();canvas=self.app.canvas_size
        self.app.edit_layout();self.pump()
        self.assertTrue(self.app.toolbar.get_mapped())
        self.assertEqual(self.app.canvas_size,canvas)
        self.assertEqual(self.geometry(),before)
        self.app.cancel();self.pump()
        self.assertEqual(self.geometry(),before)

    def test_drag_save_reload_and_repeated_editing_keep_the_preview_geometry(self):
        self.app.edit_layout();self.pump();self.swap_cards()
        card=self.app.cards['player']
        card.press(card.cover,SimpleNamespace(button=1,x=card.get_allocated_width()-1,
                   y=card.get_allocated_height()-1,x_root=100,y_root=100))
        event=SimpleNamespace(x_root=88,y_root=88)
        card.motion(card.cover,event);card.release(card.cover,event);self.pump()
        preview=self.geometry();canvas=self.app.canvas_size
        self.app.save();self.pump()
        self.assertEqual(self.app.canvas_size,canvas)
        self.assertEqual(self.geometry(),preview)
        self.app.reload();self.pump()
        self.assertEqual(self.geometry(),preview)
        for _ in range(3):
            self.app.edit_layout();self.pump();self.app.save();self.pump()
            self.assertEqual(self.geometry(),preview)

    def test_cancel_restores_the_arrangement_after_dragging(self):
        original=self.geometry()
        self.app.edit_layout();self.pump();self.swap_cards()
        self.app.cancel();self.pump()
        self.assertEqual(self.geometry(),original)

    def test_layout_saved_by_the_older_shorter_editor_keeps_six_pixel_gaps(self):
        width,height=self.app.canvas_size
        oldheight=height-40
        self.app.profile['layouts'][self.app.display_key]=self.uniform_layout(width,oldheight)
        self.app.profile['layout_sizes'][self.app.display_key]=[width,oldheight]
        self.app.settings.save();self.app.reflow();self.pump()
        geometry=self.geometry()
        for first,second in [('arch','system'),('system','connectivity'),
                             ('performance','calendar'),('calendar','player')]:
            self.assertEqual(geometry[second][1]-geometry[first][1]-geometry[first][3],6)
        self.app.edit_layout();self.pump();self.app.save();self.pump()
        self.assertEqual(self.geometry(),geometry)

    def test_status_messages_do_not_change_the_canvas(self):
        before=self.geometry();canvas=self.app.canvas_size
        self.app.message('A much longer message about the saved card arrangement')
        self.pump()
        self.assertEqual(self.app.canvas_size,canvas)
        self.assertEqual(self.geometry(),before)

    def tearDown(self):
        with patch.object(self.native.Gtk,'main_quit'):
            self.app.quit();self.app.window.destroy()
        self.pump()
