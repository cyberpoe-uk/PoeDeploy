#!/usr/bin/env python3
"""Observe the dashboard monitor without hiding it on temporary IPC failures."""
import argparse
import json
import os
from pathlib import Path
import select
import socket
import subprocess
import time

ROOT = Path(__file__).resolve().parent.parent
EVENTS = {'workspace', 'workspacev2', 'focusedmon', 'focusedmonv2',
          'activespecial', 'activespecialv2', 'monitoradded', 'monitoraddedv2',
          'monitorremoved', 'monitorremovedv2', 'dpms', 'configreloaded'}


def visible(monitors, selector=0):
    """Eww selects monitors by array index or connector name, not numeric ID."""
    if not isinstance(monitors, list) or not monitors:
        return None
    if type(selector) is int:
        monitor = monitors[selector] if 0 <= selector < len(monitors) else monitors[0]
    else:
        monitor = next((item for item in monitors if item.get('name') == selector), monitors[0])
    active = monitor.get('activeWorkspace')
    if not isinstance(active, dict) or ('id' not in active and 'name' not in active):
        return None
    home = active.get('id') == 1 or (active.get('id') is None and active.get('name') == '1')
    special = monitor.get('specialWorkspace') or {}
    special_active = special.get('id', 0) != 0 or bool(special.get('name'))
    # A dashboard on another monitor stays visible even when that monitor loses focus.
    return home and not special_active and monitor.get('dpmsStatus', True)


def query(root):
    selector = 0
    try:
        settings = json.loads((root / 'settings.json').read_text())
        selector = settings.get('monitor', 0)
    except (OSError, ValueError, AttributeError):
        pass
    try:
        result = subprocess.run(['hyprctl', 'monitors', '-j'], capture_output=True,
                                text=True, timeout=2, check=True)
        return visible(json.loads(result.stdout), selector)
    except (OSError, ValueError, TypeError, AttributeError, subprocess.SubprocessError):
        return None


def return_home_if_empty(root):
    """Called only after closewindow, never just because a workspace is empty."""
    try:
        clients = json.loads(subprocess.run(['hyprctl', 'clients', '-j'], capture_output=True,
                                           text=True, timeout=2, check=True).stdout)
        if not isinstance(clients, list) or any(item.get('mapped', True) for item in clients):
            return False
        active = json.loads(subprocess.run(['hyprctl', 'activeworkspace', '-j'], capture_output=True,
                                          text=True, timeout=2, check=True).stdout)
        if active.get('id') == 1:
            return False
        result = subprocess.run(['hyprctl', 'eval', 'hl.dispatch(hl.dsp.focus({workspace="1"}))'],
                                capture_output=True, text=True, timeout=2, check=True)
        if 'error' in result.stdout.lower():
            subprocess.run(['hyprctl', 'dispatch', 'workspace', '1'], capture_output=True,
                           text=True, timeout=2, check=True)
        return True
    except (OSError, ValueError, TypeError, AttributeError, subprocess.SubprocessError):
        return False


class Observer:
    def __init__(self, root):
        self.root = root
        self.state = True
        self.emitted = None
        self.last_query = 0.0

    def refresh(self):
        reading = query(self.root)
        if reading is not None:
            self.state = bool(reading)
        self.last_query = time.monotonic()
        if self.state != self.emitted:
            try:
                path = self.root / 'state/home-visible'
                path.parent.mkdir(parents=True, exist_ok=True)
                temporary = path.with_suffix('.tmp')
                temporary.write_text('true' if self.state else 'false')
                temporary.replace(path)
            except OSError:
                pass
            print('true' if self.state else 'false', flush=True)
            self.emitted = self.state


def listen(root):
    observer = Observer(root)
    while True:
        # Always query first, even when the event socket is not ready during login.
        observer.refresh()
        try:
            path = f"{os.environ['XDG_RUNTIME_DIR']}/hypr/{os.environ['HYPRLAND_INSTANCE_SIGNATURE']}/.socket2.sock"
            with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as connection:
                connection.settimeout(2)
                connection.connect(path)
                observer.refresh()  # Covers a workspace change during subscription.
                buffer = ''
                while True:
                    ready, _, _ = select.select([connection], [], [], 10)
                    refresh = not ready
                    if ready:
                        chunk = connection.recv(65536)
                        if not chunk:
                            break
                        buffer += chunk.decode(errors='replace')
                        lines = buffer.split('\n')
                        buffer = lines.pop()
                        if any(line.startswith('closewindow>>') for line in lines):
                            time.sleep(.15)  # Coalesce close/open replacements before deciding.
                            return_home_if_empty(root)
                            refresh = True
                        else:
                            refresh = any(line.partition('>>')[0] in EVENTS for line in lines)
                    if refresh or time.monotonic() - observer.last_query >= 10:
                        observer.refresh()
        except (OSError, KeyError):
            pass
        # Keep the last confirmed state while reconnecting, rather than emitting false.
        time.sleep(2)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--listen', action='store_true')
    parser.add_argument('--root', type=Path, default=ROOT)
    args = parser.parse_args()
    if args.listen:
        listen(args.root)
    else:
        reading = query(args.root)
        print('false' if reading is False else 'true')


if __name__ == '__main__':
    try:
        main()
    except (BrokenPipeError, KeyboardInterrupt):
        pass
