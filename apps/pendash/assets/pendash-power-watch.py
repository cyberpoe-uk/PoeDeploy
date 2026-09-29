#!/usr/bin/env python3
"""Switch power-profiles-daemon on charger events without polling."""
from pathlib import Path
import socket
import subprocess


def ac_online(root=Path('/sys/class/power_supply')):
    values = []
    for supply in root.iterdir():
        try:
            if (supply / 'type').read_text().strip() != 'Battery':
                values.append((supply / 'online').read_text().strip() == '1')
        except OSError:
            pass
    if not values:
        raise RuntimeError('No readable AC power supply')
    return any(values)


def apply(online):
    profile = 'balanced' if online else 'power-saver'
    subprocess.run(['/usr/bin/powerprofilesctl', 'set', profile], check=True, timeout=15)
    print(('AC' if online else 'Battery') + ': ' + profile, flush=True)


def main():
    previous = None
    with socket.socket(socket.AF_NETLINK, socket.SOCK_DGRAM, 15) as events:
        events.bind((0, 1))
        while True:
            online = ac_online()
            if online != previous:
                apply(online)
                previous = online
            payload, sender = events.recvfrom(65536)
            while sender[0] != 0 or b'SUBSYSTEM=power_supply' not in payload.split(b'\0'):
                payload, sender = events.recvfrom(65536)


if __name__ == '__main__':
    main()
