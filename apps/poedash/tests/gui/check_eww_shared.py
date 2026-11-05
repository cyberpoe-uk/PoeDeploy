#!/usr/bin/env python3
"""Test shared widgets in a real, transparent, input-pass-through Eww window.

The temporary Eww configuration is separate from the installed dashboard.
No pointer events are injected and no installed settings are read or written.
"""
import argparse
import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import sys
import tempfile
import time

parser=argparse.ArgumentParser(description=__doc__)
parser.add_argument('--run',action='store_true')
parser.add_argument('--startup',action='store_true',help='also test backend selection and the installed startup script')
args=parser.parse_args()
if not args.run:parser.error('Pass --run to launch the isolated Eww test window')
repo=Path(__file__).resolve().parents[4]
with tempfile.TemporaryDirectory(prefix='poedash-eww-shared-') as temporary:
    root=Path(temporary)
    shutil.copytree(repo/'apps/poedash/assets',root,dirs_exist_ok=True,ignore=shutil.ignore_patterns('__pycache__','state'))
    shutil.copy2(repo/'apps/poedash/poedash.py',root/'poedash.py')
    (root/'settings.json').write_bytes((root/'settings.example.json').read_bytes())
    (root/'eww.yuck').write_text('''(defwindow dashboard :monitor 0 :geometry (geometry :width "1px" :height "1px" :anchor "bottom right") :stacking "bottom" :exclusive false :focusable false
(box :class "poedash-shared-host" :hexpand true :vexpand true :space-evenly false))''')
    (root/'eww.scss').write_text('window { background: transparent; opacity: 0; }')
    shutil.copy2(root/'eww.yuck',root/'templates/eww-shared.yuck')
    shutil.copy2(root/'eww.scss',root/'templates/eww-shared.scss')
    (root/'scripts/thunderbird-calendar.py').write_text('import json;print(json.dumps({"status":"Fixture day","events":[],"connected":True}))\n')
    entry=root/'scripts/eww_embed.py'
    text=entry.read_text().replace('from dashboard_native import Dashboard','''import dashboard_native as native
from dashboard_native import Dashboard, Gtk, GLib
class Engine:
    def __init__(self,*args):self.on_battery=False
    def start(self):pass
    def close(self):pass
    def configure(self,*args):pass
    def request(self,*args):pass
native.Engine=Engine
Dashboard.spawn_listener=lambda *args:None
''')
    text+='''
_original_attach=attach
def attach(host):
    import cairo
    import datetime
    import traceback
    window=host.get_toplevel()
    window.set_opacity(0)
    def pass_through(*_):
        if window.get_window():window.get_window().input_shape_combine_region(cairo.Region(),0,0)
    window.connect('realize',pass_through);pass_through()
    window.set_size_request(1440,960)
    dashboard=_original_attach(host)
    window.set_accept_focus(False)
    if native.GtkLayerShell.is_supported():native.GtkLayerShell.set_keyboard_mode(window,native.GtkLayerShell.KeyboardMode.NONE)
    destination=dashboard.root/'state/host-test.json'
    if destination.exists():return dashboard
    def walk(widget):
        yield widget
        if isinstance(widget,Gtk.Container):
            for child in widget.get_children():yield from walk(child)
    def finish(error=None):
        destination.write_text(__import__('json').dumps({'ok':error is None,'error':error,'pid':os.getpid(),'executable':os.readlink('/proc/self/exe'),'backend':'eww'}))
    def first():
        try:
            assert dashboard.host is host
            dashboard.card_menu(dashboard.cards['performance'])
            entries=[w for w in walk(dashboard.drawer) if isinstance(w,Gtk.Entry)]
            assert len(entries)==4
            cpu=next(w for w in entries if w.get_accessible().get_name()=='CPU usage refresh interval in seconds')
            original=dashboard.profile['refresh']['cpu']
            plus=next(w for w in walk(dashboard.drawer) if isinstance(w,Gtk.Button) and w.get_accessible().get_name()=='Increase CPU usage refresh interval')
            plus.clicked();assert dashboard.profile['refresh']['cpu']==original+1
            cpu.set_text('17')
            assert dashboard.profile['refresh']['cpu']==17
            dashboard.cancel();assert dashboard.profile['refresh']['cpu']==original
            dashboard.select_calendar_date(datetime.date.today()+datetime.timedelta(days=1))
            GLib.timeout_add(300,second)
        except Exception:finish(traceback.format_exc())
        return False
    def second():
        try:
            assert dashboard.calendar_day_data['status']=='Fixture day'
            dashboard.receive({'_gate':{'visible':False,'on_battery':False}})
            dashboard.receive({'_gate':{'visible':True,'on_battery':False}})
            assert dashboard.calendar_selection is None
            native.search_weather_locations=lambda query:[{'location':'Cambridge, England, United Kingdom','latitude':'52.2','longitude':'.12'}]
            dashboard.open_settings('Cards')
            dashboard.toggle_card('weather',True)
            entry=next(w for w in walk(dashboard.drawer) if isinstance(w,Gtk.Entry) and (w.get_placeholder_text() or '').startswith('Town or city'))
            entry.set_text('Cambridge')
            next(w for w in walk(dashboard.drawer) if isinstance(w,Gtk.Button) and w.get_label()=='Search').clicked()
            GLib.timeout_add(300,third)
        except Exception:finish(traceback.format_exc())
        return False
    def third():
        try:
            from types import SimpleNamespace
            from copy import deepcopy
            next(w for w in walk(dashboard.drawer) if isinstance(w,Gtk.Button) and w.get_label()=='Cambridge, England, United Kingdom').clicked()
            dashboard.save()
            assert native.Settings(dashboard.root).data['integrations']['weather']['location'].startswith('Cambridge')
            import time
            dashboard.receive({'weather':{'value':{'configured':True,'current':{'temperature_2m':12,'apparent_temperature':10,'weather_code':61,'is_day':1},'daily':{'time':[]}},'updated':time.time(),'error':''},'cpu':{'value':12,'updated':time.time(),'error':''}})
            dashboard.edit_layout()
            GLib.timeout_add(200,fourth)
        except Exception:finish(traceback.format_exc())
        return False
    def fourth():
        try:
            from types import SimpleNamespace
            from copy import deepcopy
            original=deepcopy(dashboard.layout)
            card=dashboard.cards['arch'];card.cover.grab_add();card.drag=(0,0,deepcopy(original['arch']),'')
            origin,target=original['arch'],original['system'];width,height=dashboard.canvas_size
            dx=((target[0]+target[2]/2)-(origin[0]+origin[2]/2))*width
            dy=((target[1]+target[3]/2)-(origin[1]+origin[3]/2))*height
            card.motion(card.cover,SimpleNamespace(x_root=dx,y_root=dy))
            assert dashboard.layout==original and dashboard.preview_layout is None
            card.release(card.cover,None)
            assert dashboard.layout['arch']==original['system']
            dashboard.undo();assert dashboard.layout==original
            dashboard.cancel()
            assert dashboard.canvas_size[1]<=dashboard.board_view.get_allocated_height()
            dashboard.receive({'_gate':{'visible':True,'on_battery':False}})
            finish()
        except Exception:finish(traceback.format_exc())
        return False
    GLib.timeout_add(500,first)
    return dashboard
'''
    entry.write_text(text)
    module=subprocess.check_output([sys.executable,str(root/'scripts/eww-host.py')],text=True).strip()
    env=dict(os.environ,POEDASH_ROOT=str(root),POEDASH_PREVIOUS_GTK_MODULES=os.environ.get('GTK_MODULES',''))
    env['GTK_MODULES']=':'.join(filter(None,[env.get('GTK_MODULES'),module]))
    command=['eww','--config',str(root)]
    log=(root/'eww-test.log').open('w')
    daemon=None
    def ipc(command):
        with socket.socket(socket.AF_UNIX) as client:
            client.settimeout(1);client.connect(str(root/'state/native.sock'));client.sendall(command.encode());return client.recv(65536).decode().strip()
    try:
        if args.startup:
            env['XDG_CACHE_HOME']=str(root/'cache')
            if os.environ.get('GTK_MODULES'):env['GTK_MODULES']=os.environ['GTK_MODULES']
            else:env.pop('GTK_MODULES',None)
            subprocess.run([sys.executable,str(root/'poedash.py'),'--root',str(root),'backend','eww'],env=env,stdout=log,stderr=log,check=True,timeout=30)
        else:daemon=subprocess.Popen([*command,'--force-wayland','--no-daemonize','daemon'],env=env,stdout=log,stderr=log)
        for _ in range(100):
            if subprocess.run([*command,'ping'],capture_output=True).returncode==0:break
            if daemon and daemon.poll() is not None:raise RuntimeError('Eww daemon exited')
            time.sleep(.05)
        if not args.startup:subprocess.run([*command,'open','dashboard'],check=True,capture_output=True)
        result=root/'state/host-test.json'
        for _ in range(200):
            if result.exists():break
            if daemon and daemon.poll() is not None:raise RuntimeError('Eww daemon exited while hosting')
            time.sleep(.05)
        data=json.loads(result.read_text())
        assert data['ok'],data['error']
        assert 'eww' in Path(data['executable']).name,data
        assert json.loads(ipc('diagnostics'))['backend']=='eww'
        subprocess.run([*command,'close','dashboard'],check=True,capture_output=True)
        for _ in range(100):
            if not (root/'state/native.sock').exists():break
            time.sleep(.05)
        assert not (root/'state/native.sock').exists(),'Host close did not clean up dashboard controller'
        assert subprocess.run([*command,'ping'],capture_output=True).returncode==0,'Closing dashboard killed Eww'
        subprocess.run([*command,'open','dashboard'],check=True,capture_output=True)
        for _ in range(100):
            try:
                if ipc('status')=='active':break
            except OSError:pass
            time.sleep(.05)
        else:raise RuntimeError('Eww reload did not restore shared surface')
        log.flush()
        captured=(root/'eww-test.log').read_text()
        startup_log=root/'cache/poedash/startup.log'
        if startup_log.exists():captured+=startup_log.read_text()
        assert 'Traceback (most recent call last)' not in captured,captured[-10000:]
        print(json.dumps({'ok':True,'backend':'eww','checks':['shared card editor','Save/Cancel','async calendar date','workspace reset','weather search and Save','release-only swap and Undo','fixed canvas','close/reopen lifecycle']}))
    except BaseException:
        log.flush();print((root/'eww-test.log').read_text()[-10000:],file=sys.stderr)
        startup_log=root/'cache/poedash/startup.log'
        if startup_log.exists():print(startup_log.read_text()[-10000:],file=sys.stderr)
        raise
    finally:
        subprocess.run([*command,'kill'],capture_output=True)
        if daemon:
            try:daemon.wait(timeout=10)
            except subprocess.TimeoutExpired:daemon.kill();daemon.wait()
        log.close()
