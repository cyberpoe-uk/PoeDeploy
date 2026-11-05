"""Opt-in Hyprland header click check with an isolated reserved input strip.

Run: python3 apps/poedash/tests/gui/check_header_wayland.py --run
Uses a temporary dashboard, mocks application launches, briefly visits workspace
1, and restores the original workspace and pointer. A temporary transparent
panel reproduces the blocked header without depending on the current status bar.
Checks the default surface before reproducing the old placement and its fix.
"""
import argparse
import cairo
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import time
from unittest.mock import Mock, patch

source = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(source / 'assets/scripts'))
import dashboard_native as native

def query(command):
    return json.loads(subprocess.check_output(['hyprctl', command, '-j'], text=True))

def pump(seconds=.25):
    context = native.GLib.MainContext.default()
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        while context.pending(): context.iteration(False)
        time.sleep(.005)

def descendants(widget):
    yield widget
    if isinstance(widget, native.Gtk.Container):
        for child in widget.get_children(): yield from descendants(child)

def find(parent, title):
    return next(w for w in descendants(parent) if isinstance(w, native.Gtk.Button) and w.get_label() == title)

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--run', action='store_true', help='Allow a temporary dashboard and real pointer events')
if not parser.parse_args().run: parser.error('Pass --run to execute the desktop interaction test')

original_workspace = query('activeworkspace')['id']
original_cursor = query('cursorpos')
monitors = query('monitors')
left = min(m['x'] for m in monitors)
top = min(m['y'] for m in monitors)
width = max(m['x'] + m['width']/m['scale'] for m in monitors) - left
height = max(m['y'] + m['height']/m['scale'] for m in monitors) - top

with tempfile.TemporaryDirectory(prefix='poedash-header-wayland-') as temporary:
    root = Path(temporary)
    assets = Path(__file__).resolve().parent
    subprocess.run(['wayland-scanner', 'client-header', str(assets/'virtual-pointer.xml'), str(root/'virtual-pointer.h')], check=True)
    subprocess.run(['wayland-scanner', 'private-code', str(assets/'virtual-pointer.xml'), str(root/'virtual-pointer.c')], check=True)
    subprocess.run(['cc', str(assets/'pointer.c'), str(root/'virtual-pointer.c'), '-I'+str(root), '-o', str(root/'pointer'), '-lwayland-client'], check=True)
    pointer = subprocess.Popen([str(root/'pointer')], stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True)
    def send(command):
        pointer.stdin.write(command+'\n'); pointer.stdin.flush()
        assert pointer.stdout.readline().strip() == 'ok'
    def move(x,y):
        send(f'm {round(x-left)} {round(y-top)} {round(width)} {round(height)}')
    def layer(namespace='poedash-header-check'):
        return next(item for monitor in query('layers').values() for items in monitor['levels'].values() for item in items if item['namespace']==namespace)
    def click(widget):
        surface = layer()
        x,y = widget.translate_coordinates(app.window,widget.get_allocated_width()//2,widget.get_allocated_height()//2)
        position=(surface['x']+x,surface['y']+y)
        print('Click',getattr(widget,'get_label',lambda:'widget')(),position,flush=True)
        move(*position); pump(.1); send('d'); pump(.06); send('u'); pump()
    original_namespace = native.GtkLayerShell.set_namespace
    app = None
    panel = None
    try:
        subprocess.run(['hyprctl','eval','hl.dispatch(hl.dsp.focus({workspace="1"}))'],check=True,capture_output=True)
        panel=native.Gtk.Window()
        panel.set_app_paintable(True)
        visual=panel.get_screen().get_rgba_visual()
        if visual:panel.set_visual(visual)
        panel.set_size_request(-1,80)
        native.GtkLayerShell.init_for_window(panel)
        native.GtkLayerShell.set_namespace(panel,'poedash-header-blocker')
        native.GtkLayerShell.set_layer(panel,native.GtkLayerShell.Layer.OVERLAY)
        native.GtkLayerShell.set_monitor(panel,native.Gdk.Display.get_default().get_monitor(0))
        native.GtkLayerShell.set_exclusive_zone(panel,80)
        for edge in (native.GtkLayerShell.Edge.TOP,native.GtkLayerShell.Edge.LEFT,native.GtkLayerShell.Edge.RIGHT):
            native.GtkLayerShell.set_anchor(panel,edge,True)
        catcher=native.Gtk.EventBox()
        catcher.set_visible_window(False)
        catcher.add_events(native.Gdk.EventMask.BUTTON_PRESS_MASK | native.Gdk.EventMask.BUTTON_RELEASE_MASK)
        catcher.connect('button-press-event',lambda *_:True)
        catcher.connect('button-release-event',lambda *_:True)
        panel.add(catcher)
        def transparent(widget,cr):
            cr.set_operator(cairo.OPERATOR_SOURCE)
            cr.set_source_rgba(0,0,0,0);cr.paint()
            return False
        panel.connect('draw',transparent)
        panel.show_all();pump()
        print('Reserved test strip:',layer('poedash-header-blocker'),flush=True)
        with patch.object(native.Engine,'start'), patch.object(native.Dashboard,'spawn_listener'), patch.object(native.Dashboard,'start_ipc'), \
                patch.object(native.GtkLayerShell,'set_namespace', side_effect=lambda window,name:original_namespace(window,'poedash-header-check')):
            app = native.Dashboard(root)
        app.run=Mock()
        pump(.7)
        for zone in (None,-1,0):
            if zone is not None: native.GtkLayerShell.set_exclusive_zone(app.window,zone)
            pump(.5)
            print('Exclusive zone',zone,'surface',layer(),flush=True)
            click(app.edit_button)
            editing = app.drawer.get_mapped()
            print('Edit opened:',editing,flush=True)
            if editing: click(find(app.drawer,'Close'))
            before=app.profile['appearance']['scale']
            zoom = find(app.header_controls,'+')
            click(zoom)
            zoomed=app.profile['appearance']['scale']>before
            print('Zoom changed:',zoomed,flush=True)
            app.run.reset_mock()
            click(find(app.header_controls,'Packages'))
            packages = app.run.call_args == (('packages.py','launch'),)
            print('Packages dispatched:',packages,flush=True)
            if zone == -1:
                assert not editing and not zoomed and not packages, 'Original failure was not reproduced'
            else:
                assert editing and zoomed and packages, 'Header controls still blocked'
        print('PASS: actual Wayland clicks fail before the fix and pass after it',flush=True)
    finally:
        if app:
            with patch.object(native.Gtk,'main_quit'):
                app.quit(); app.window.destroy()
        if panel:panel.destroy();pump()
        subprocess.run(['hyprctl','eval','hl.dispatch(hl.dsp.focus({workspace='+json.dumps(str(original_workspace))+'}))'],capture_output=True)
        move(original_cursor['x'],original_cursor['y'])
        pointer.stdin.write('q\n');pointer.stdin.flush();pointer.wait(timeout=3)
