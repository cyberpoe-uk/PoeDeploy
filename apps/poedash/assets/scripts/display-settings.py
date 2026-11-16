#!/usr/bin/env python3
"""Open appearance controls on the dashboard workspace."""
from pathlib import Path
import socket
ROOT=Path(__file__).resolve().parent.parent

def open_dashboard_settings():
    import subprocess
    def send():
        with socket.socket(socket.AF_UNIX,socket.SOCK_STREAM) as client:
            client.settimeout(5)
            client.connect(str(ROOT/'state/native.sock'))
            client.sendall(b'open-appearance\n')
            if client.recv(100).strip()!=b'ok':raise OSError('Could not open dashboard settings')
    try:send()
    except (FileNotFoundError,ConnectionRefusedError):
        subprocess.run(['bash',str(ROOT/'scripts/start.sh')],check=True,timeout=15)
        send()
    # Focus the reserved dashboard workspace without creating an application window.
    result=subprocess.run(['hyprctl','eval','hl.dispatch(hl.dsp.focus({workspace="1"}))'],capture_output=True,text=True,timeout=3)
    if result.returncode or 'error' in result.stdout.lower():
        subprocess.run(['hyprctl','dispatch','workspace','1'],check=True,timeout=3)

if __name__=='__main__':open_dashboard_settings()
