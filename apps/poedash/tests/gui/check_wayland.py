"""Opt-in real-pointer regression checks for a temporary Wayland surface.

Run: python apps/poedash/tests/gui/check_wayland.py --run
The test briefly overlays the selected desktop, then restores the pointer.
It never loads or writes the installed dashboard's settings.
"""
import argparse
from copy import deepcopy
import json
import os
from pathlib import Path
import shutil
import signal
import subprocess
import sys
import tempfile

parser=argparse.ArgumentParser(description=__doc__)
parser.add_argument('--run',action='store_true',help='Allow a temporary test surface and real pointer events')
args=parser.parse_args()
if not args.run: parser.error('Pass --run to execute the desktop interaction test')
source=Path(__file__).resolve().parents[2]
fixture=tempfile.TemporaryDirectory(prefix='poedash-wayland-')
root=Path(fixture.name)/'dashboard'
shutil.copytree(source/'assets',root,ignore=shutil.ignore_patterns('__pycache__'))
for filename,dest in [('workspace-state.py','workspace.py'),('desktop-actions.py','desktop.py'),('thunderbird-calendar.py','thunderbird-calendar.py')]:
 shutil.copy2(source.parent/'shared'/filename,root/'scripts'/dest)
shutil.copytree(source.parent/'shared/calendar-vendor',root/'scripts/calendar-vendor',ignore=shutil.ignore_patterns('__pycache__'))
shutil.copy2(root/'settings.example.json',root/'settings.json')
(root/'dashboard-id').write_text('poedash\n')
os.environ['XDG_STATE_HOME']=str(Path(fixture.name)/'state')
os.environ['XDG_CACHE_HOME']=str(Path(fixture.name)/'cache')
assets=Path(__file__).resolve().parent
build=Path(fixture.name)
subprocess.run(['wayland-scanner','client-header',str(assets/'virtual-pointer.xml'),str(build/'virtual-pointer.h')],check=True)
subprocess.run(['wayland-scanner','private-code',str(assets/'virtual-pointer.xml'),str(build/'virtual-pointer.c')],check=True)
subprocess.run(['cc',str(assets/'pointer.c'),str(build/'virtual-pointer.c'),'-I'+str(build),'-o',str(build/'pointer'),'-lwayland-client'],check=True)
sys.path.insert(0,str(root/'scripts'))
from dashboard_native import Dashboard, Gtk, GtkLayerShell, GLib, Gdk
try:
 cursor=json.loads(subprocess.run(['hyprctl','cursorpos','-j'],capture_output=True,text=True,check=True).stdout)
except (ValueError,OSError,subprocess.SubprocessError): cursor=None
app=Dashboard(root)
app.preview_window=True
for child in app.children:
 if any(str(arg).endswith('workspace.py') for arg in child.args): os.killpg(child.pid,signal.SIGTERM)
app.engine.visibility_override=True
GtkLayerShell.set_layer(app.window,GtkLayerShell.Layer.OVERLAY)
app.window.show()
pointer=subprocess.Popen([str(build/'pointer')],stdin=subprocess.PIPE,stdout=subprocess.PIPE,text=True)
checks=[]
state={}
def send(command):
 pointer.stdin.write(command+'\n');pointer.stdin.flush()
 if pointer.stdout.readline().strip()!='ok': raise RuntimeError('Virtual pointer unavailable')
display=Gdk.Display.get_default()
bounds=[display.get_monitor(i).get_geometry() for i in range(display.get_n_monitors())]
extent_width=max(r.x+r.width for r in bounds);extent_height=max(r.y+r.height for r in bounds)
def move(x,y):send(f'm {round(x)} {round(y)} {extent_width} {extent_height}')
def center(widget,fx=.5,fy=.5):
 bounds=widget.get_allocation(); pos=widget.translate_coordinates(app.window,round(bounds.width*fx),round(bounds.height*fy))
 if pos is None:raise RuntimeError('Widget not positioned')
 geometry=app.monitor.get_geometry()
 return (pos[0]+geometry.x,pos[1]+geometry.y)
def down(widget,fx=.5,fy=.5):
 x,y=center(widget,fx,fy);move(x,y);send('d')
def click(widget):
 if not widget.get_mapped():raise RuntimeError('Control is not mapped: '+str(getattr(widget,'get_label',lambda:'widget')()))
 down(widget);GLib.timeout_add(50,lambda:(send('u'),False)[1])
def descendants(widget):
 yield widget
 if isinstance(widget,Gtk.Container):
  for child in widget.get_children():yield from descendants(child)
def find_button(parent,title):
 return next(w for w in descendants(parent) if isinstance(w,Gtk.Button) and w.get_label()==title)
def expect(condition,message):
 if not condition:raise RuntimeError(message)
 checks.append(message)
steps=[]
steps.append(lambda:click(app.cards['arch'].menu_button))
steps.append(lambda:expect(app.drawer.get_mapped(),'Card actions panel opens from an actual click'))
steps.append(lambda:click(find_button(app.drawer,'Close')))
steps.append(lambda:click(app.health_button))
steps.append(lambda:expect(app.drawer.get_mapped(),'Health details panel is mapped'))
steps.append(lambda:click(find_button(app.drawer,'Close')))
steps.append(lambda:click(app.edit_button))
steps.append(lambda:click(app.edit_actions['Move & resize cards']))
def editing_check():
 expect(app.toolbar.get_mapped(),'Editing toolbar is visible')
 expect(find_button(app.toolbar,'Save').get_mapped(),'Save button is mapped')
 expect(find_button(app.toolbar,'Cancel').get_mapped(),'Cancel button is mapped')
 expect(app.cards['arch'].cover.get_mapped(),'Drag overlay receives pointer input')
 state['before']=deepcopy(app.layout)
 down(app.cards['arch'])
steps.append(editing_check)
def drag():
 target=app.cards['system'];x,y=center(target);move(x,y)
steps.append(drag)
steps.append(lambda:send('u'))
steps.append(lambda:expect(app.layout['arch']==state['before']['system'],'Actual pointer drag swaps cards'))
def resize_start():
 state['resize_before']=deepcopy(app.layout['performance']);down(app.cards['performance'],.995,.99)
steps.append(resize_start)
def resize_move():
 x,y=center(app.cards['performance'],.995,.99);move(x-30,y-30)
steps.append(resize_move)
steps.append(lambda:send('u'))
steps.append(lambda:expect(app.layout['performance'][2]<state['resize_before'][2] and app.layout['performance'][3]<state['resize_before'][3],'Actual corner drag resizes both dimensions'))
steps.append(lambda:click(find_button(app.toolbar,'Cancel')))
steps.append(lambda:expect(not app.editing and app.transaction is None and not app.toolbar.get_mapped(),'Cancel exits editing mode'))
steps.append(lambda:click(app.edit_button))
steps.append(lambda:click(app.edit_actions['Refresh intervals']))
def refresh_check():
 expect(app.drawer.get_mapped(),'Refresh intervals panel is mapped')
 spin=next(w for w in descendants(app.drawer) if isinstance(w,Gtk.SpinButton) and w.get_mapped())
 state['interval_before']=spin.get_value_as_int()
 # Gtk SpinButton's native + control is on the right edge.
 down(spin,.90,.5);GLib.timeout_add(50,lambda:(send('u'),False)[1]);state['spin']=spin
steps.append(refresh_check)
steps.append(lambda:expect(state['spin'].get_value_as_int()!=state['interval_before'],'Refresh interval increment changes seconds'))
steps.append(lambda:click(find_button(app.drawer,'Save')))
steps.append(lambda:expect(app.transaction is None and not app.drawer.get_visible(),'Settings Save applies and closes panel'))
steps.append(lambda:click(app.edit_button))
steps.append(lambda:click(app.edit_actions['Appearance']))
def appearance_check():
 expect(app.drawer.get_mapped(),'Appearance panel is mapped')
 state['opacity_before']=app.profile['appearance']['opacity']
 spin=next(w for w in descendants(app.drawer) if isinstance(w,Gtk.SpinButton) and w.get_mapped())
 down(spin,.90,.5);GLib.timeout_add(50,lambda:(send('u'),False)[1])
steps.append(appearance_check)
steps.append(lambda:expect(app.profile['appearance']['opacity']!=state['opacity_before'],'Appearance increment applies a preview'))
steps.append(lambda:click(find_button(app.drawer,'Cancel')))
steps.append(lambda:expect(app.profile['appearance']['opacity']==state['opacity_before'],'Appearance Cancel restores saved opacity'))
steps.append(lambda:click(app.edit_button))
steps.append(lambda:click(app.edit_actions['Move & resize cards']))
steps.append(lambda:click(find_button(app.toolbar,'Save')))
steps.append(lambda:expect(not app.editing and app.display_key in app.settings.profile['layouts'],'Layout Save persists and exits editing'))
def execute():
 try:
  if not steps:
   print(json.dumps({'ok':True,'checks':checks}),flush=True);finish();return False
  steps.pop(0)()
  return True
 except Exception as exc:
  print(json.dumps({'ok':False,'error':str(exc),'checks':checks}),flush=True)
  subprocess.run(['grim','/tmp/poedash-wayland-failure.png'],check=False)
  state['failed']=True;finish();return False
def finish():
 try:send('u')
 except Exception:pass
 if cursor and cursor.get('x',-1)>=0 and cursor.get('y',-1)>=0:
  try:move(cursor['x'],cursor['y'])
  except Exception:pass
 try:pointer.stdin.write('q\n');pointer.stdin.flush();pointer.wait(timeout=2)
 except Exception:pointer.kill()
 app.quit()
GLib.timeout_add_seconds(3,lambda:(GLib.timeout_add(200,execute),False)[1])
GLib.timeout_add_seconds(35,lambda:(state.update(failed=True),finish(),False)[2])
Gtk.main()
raise SystemExit(1 if state.get('failed') else 0)
