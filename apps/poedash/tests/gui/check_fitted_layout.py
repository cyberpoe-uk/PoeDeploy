#!/usr/bin/env python3
"""Deterministic offscreen GTK test; does not alter the installed dashboard."""
import argparse
from copy import deepcopy
import json
from pathlib import Path
import shutil
import sys
import tempfile
import traceback

REPO=Path(__file__).resolve().parents[4]
parser=argparse.ArgumentParser(description=__doc__)
parser.add_argument('--size',default='1440x960')
args=parser.parse_args()
size=tuple(map(int,args.size.split('x')))
with tempfile.TemporaryDirectory(prefix='poedash-fitted-gui-') as directory:
    root=Path(directory)
    shutil.copytree(REPO/'apps/poedash/assets/scripts',root/'scripts',ignore=shutil.ignore_patterns('__pycache__'))
    shutil.copy2(REPO/'apps/poedash/assets/colors.scss',root/'colors.scss')
    sys.path.insert(0,str(root/'scripts'))
    import dashboard_native as app
    class Engine:
        def __init__(self,*args):self.on_battery=False
        def start(self):pass
        def close(self):pass
        def configure(self,*args):pass
        def request(self,*args):pass
    app.Engine=Engine
    app.Dashboard.spawn_listener=lambda *args:None
    app.Dashboard.smoke_test=lambda *args:False
    dashboard=app.Dashboard(root,preview=True,smoke=True,size=size)
    errors=[]
    def check_bounds():
        height=dashboard.board_view.get_allocated_height()
        assert dashboard.canvas_size[1]<=height,'Canvas extends below viewport'
        adjustment=dashboard.board_view.get_vadjustment()
        assert adjustment.get_upper()-adjustment.get_page_size()<=1,'Dashboard can scroll vertically'
        for key,rect in dashboard.layout.items():assert app.valid_move(key,rect,dashboard.layout),(key,rect)
    def first():
        try:
            check_bounds()
            dashboard.open_settings('Cards')
            for key in ('weather','tasks','feeds'):
                before=deepcopy(dashboard.layout)
                if dashboard.toggle_card(key,True):
                    assert key in dashboard.layout
                    assert dashboard.canvas_size[1]<=dashboard.board_view.get_allocated_height()
                else:assert dashboard.layout==before,'Failed addition changed layout'
            app.GLib.timeout_add(500,second)
        except Exception:
            errors.append(traceback.format_exc());dashboard.quit()
        return False
    def second():
        try:
            check_bounds();dashboard.save()
            app.GLib.timeout_add(500,third)
        except Exception:
            errors.append(traceback.format_exc());dashboard.quit()
        return False
    def third():
        try:
            check_bounds()
            saved=app.Settings(root).profile
            assert saved.get('layout_sizes')
            print(json.dumps({'ok':True,'size':size,'canvas':dashboard.canvas_size,'cards':len(dashboard.cards)}),flush=True)
        except Exception:errors.append(traceback.format_exc())
        finally:dashboard.quit()
        return False
    app.GLib.timeout_add(500,first)
    app.Gtk.main()
    if errors:raise SystemExit('\n'.join(errors))
