#!/usr/bin/env python3
"""One blocking Hyprland event listener; no periodic workspace subprocesses."""
import json
import os
import socket
import subprocess
import time


def visible(monitors):
    return any(m.get('id') == 0 and m.get('focused', True)
               and m.get('activeWorkspace', {}).get('id') == 1
               and m.get('specialWorkspace', {}).get('id', 0) == 0
               and m.get('dpmsStatus', True) for m in monitors)


def main():
    previous = None
    def emit(value):
        nonlocal previous
        if value != previous:
            print('true' if value else 'false', flush=True)
            previous = value
    def query():
        try:
            p = subprocess.run(['hyprctl', 'monitors', '-j'], capture_output=True, text=True, timeout=2, check=True)
            emit(visible(json.loads(p.stdout)))
        except (OSError, ValueError, subprocess.SubprocessError):
            emit(False)
    events = {'workspace', 'workspacev2', 'focusedmon', 'focusedmonv2', 'activespecial',
              'activespecialv2', 'monitoradded', 'monitoraddedv2', 'monitorremoved', 'dpms', 'configreloaded'}
    delay = 2
    while True:
        try:
            path = f"{os.environ['XDG_RUNTIME_DIR']}/hypr/{os.environ['HYPRLAND_INSTANCE_SIGNATURE']}/.socket2.sock"
            with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as s:
                s.connect(path)
                query()
                delay = 2
                with s.makefile() as stream:
                    for line in stream:
                        if line.partition('>>')[0] in events:
                            query()
        except (OSError, KeyError):
            pass
        emit(False)
        time.sleep(delay)
        delay = min(delay * 2, 30)


if __name__ == '__main__':
    try:
        main()
    except (BrokenPipeError, KeyboardInterrupt):
        pass
