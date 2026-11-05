"""Shared PoeDash widgets attached to an Eww-owned GTK container."""
import fcntl
import os
from pathlib import Path

# Do not propagate our hosting module into launched desktop applications.
previous=os.environ.pop('POEDASH_PREVIOUS_GTK_MODULES','')
if previous:os.environ['GTK_MODULES']=previous
else:os.environ.pop('GTK_MODULES',None)

from dashboard_native import Dashboard

_instances={}

def attach(host):
    root=Path(os.environ['POEDASH_ROOT']).resolve()
    lock=(root/'.native.lock').open('w')
    try:fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
    except BlockingIOError:
        lock.close()
        raise RuntimeError('Another PoeDash surface is already running')
    try:
        dashboard=Dashboard(root,host=host)
    except BaseException:
        lock.close();raise
    dashboard.host_lock=lock
    _instances[id(host)]=dashboard
    host.connect('destroy',lambda *_:_instances.pop(id(host),None))
    return dashboard
