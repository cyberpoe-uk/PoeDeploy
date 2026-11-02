#!/usr/bin/python3
"""Event-driven, hardware-gated HKF-WXX routing. Never opens a PCM device."""
import argparse
import ctypes as C
import errno
import logging
import os
from pathlib import Path
import re
import select
import signal
import socket
import struct
import subprocess
import time

LOG = logging.getLogger('matebook-audio')
PRODUCT = Path('/sys/class/dmi/id/product_name')
PROC = Path('/proc/asound')
DEV = Path('/dev/snd')
SPEAKERS = ((0x16, 0x701, 1), (0x17, 0x70c, 2), (0x01, 0x715, 2))
HEADPHONES = ((0x16, 0x701, 0), (0x17, 0x70c, 0), (0x01, 0x717, 2),
              (0x01, 0x716, 2), (0x01, 0x715, 0))


def discover(product=PRODUCT, proc=PROC, dev=DEV):
    """Both identities must match; codec Address, not filename, selects hwdep."""
    try:
        if product.read_text().strip() != 'HKF-WXX':
            return None
    except OSError:
        return None
    matches = []
    for path in proc.glob('card[0-9]*/codec#*'):
        try:
            text = path.read_text()
        except OSError:
            continue
        subsystem = re.search(r'^Subsystem Id:\s*(0x[0-9a-fA-F]+)\s*$', text, re.M)
        address = re.search(r'^Address:\s*(\d+)\s*$', text, re.M)
        card = re.fullmatch(r'card(\d+)', path.parent.name)
        if not (subsystem and address and card):
            continue
        if int(subsystem[1], 16) != 0x19e53285:
            continue
        number, addr = int(card[1]), int(address[1])
        if not 0 <= addr <= 15:
            continue
        matches.append((number, dev / f'hwC{number}D{addr}'))
    if len(matches) > 1:
        raise RuntimeError('Multiple matching codecs; refusing ambiguous routing')
    return matches[0] if matches else None


def response_value(output):
    match = re.search(r'\bvalue\s*=\s*(0x[0-9a-fA-F]+)\b', output)
    if not match or int(match[1], 16) > 0xffffffff:
        raise RuntimeError('hda-verb returned no valid 32-bit hexadecimal value')
    return int(match[1], 16)


def verb(codec, node, command, value):
    result = subprocess.run(['/usr/bin/hda-verb', str(codec), hex(node), hex(command), str(value)],
                            capture_output=True, text=True, timeout=3, check=True)
    return response_value(result.stdout)


def apply_route(match, previous=None, force=False):
    # Revalidate *before* every batch; never retain a stale card number across reset.
    if discover() != match or not match[1].exists():
        raise RuntimeError('Matching codec disappeared; waiting for sound-device events')
    connected = bool(verb(match[1], 0x16, 0xf09, 0) & 0x80000000)
    state = (str(match[1]), connected)
    if force or state != previous:
        for node, command, value in HEADPHONES if connected else SPEAKERS:
            verb(match[1], node, command, value)
        if state != previous:
            LOG.info('Routing %s on %s', 'headphones' if connected else 'speakers', match[1])
    return state


def route_event(name):
    """Ignore volume/mic/meter events. Observe policy writes affecting output routing."""
    name = name.lower()
    return (('jack' in name and ('headphone' in name or 'headset' in name))
            or name in ('auto-mute mode', 'headphone playback switch', 'speaker playback switch')
            or ('playback' in name and any(part in name for part in ('mux', 'route', 'source'))))


class PollFD(C.Structure):
    _fields_ = [('fd', C.c_int), ('events', C.c_short), ('revents', C.c_short)]


class Controls:
    """Subscribe to libasound control events, not audio playback/capture."""
    def __init__(self, card):
        self.lib = C.CDLL('libasound.so.2')
        self.handle = C.c_void_p()
        self.event = C.c_void_p()
        declarations = {
            'snd_ctl_open': ([C.POINTER(C.c_void_p), C.c_char_p, C.c_int], C.c_int),
            'snd_ctl_close': ([C.c_void_p], C.c_int),
            'snd_ctl_subscribe_events': ([C.c_void_p, C.c_int], C.c_int),
            'snd_ctl_poll_descriptors_count': ([C.c_void_p], C.c_int),
            'snd_ctl_poll_descriptors': ([C.c_void_p, C.POINTER(PollFD), C.c_uint], C.c_int),
            'snd_ctl_event_malloc': ([C.POINTER(C.c_void_p)], C.c_int),
            'snd_ctl_event_free': ([C.c_void_p], None),
            'snd_ctl_elem_list_malloc': ([C.POINTER(C.c_void_p)], C.c_int),
            'snd_ctl_elem_list_free': ([C.c_void_p], None),
            'snd_ctl_elem_list': ([C.c_void_p, C.c_void_p], C.c_int),
            'snd_ctl_elem_list_get_count': ([C.c_void_p], C.c_uint),
            'snd_ctl_elem_list_alloc_space': ([C.c_void_p, C.c_uint], C.c_int),
            'snd_ctl_elem_list_free_space': ([C.c_void_p], None),
            'snd_ctl_elem_list_get_used': ([C.c_void_p], C.c_uint),
            'snd_ctl_elem_list_get_name': ([C.c_void_p, C.c_uint], C.c_char_p),
            'snd_ctl_read': ([C.c_void_p, C.c_void_p], C.c_int),
            'snd_ctl_event_get_type': ([C.c_void_p], C.c_int),
            'snd_ctl_event_elem_get_name': ([C.c_void_p], C.c_char_p),
        }
        for name, (args, result) in declarations.items():
            func = getattr(self.lib, name)
            func.argtypes, func.restype = args, result
        try:
            self.check(self.lib.snd_ctl_open(C.byref(self.handle), f'hw:{card}'.encode(), 1 | 4))
            self.check(self.lib.snd_ctl_subscribe_events(self.handle, 1))
            self.check(self.lib.snd_ctl_event_malloc(C.byref(self.event)))
            count = self.lib.snd_ctl_poll_descriptors_count(self.handle)
            if count <= 0:
                raise RuntimeError('ALSA control has no event descriptors')
            descriptors = (PollFD * count)()
            self.check(self.lib.snd_ctl_poll_descriptors(self.handle, descriptors, count))
            self.fds = [p.fd for p in descriptors]
            self.has_jack = self.jack_available()
        except Exception:
            self.close()
            raise

    @staticmethod
    def check(result):
        if result < 0:
            raise OSError(-result, os.strerror(-result))

    def jack_available(self):
        elements = C.c_void_p()
        self.check(self.lib.snd_ctl_elem_list_malloc(C.byref(elements)))
        try:
            self.check(self.lib.snd_ctl_elem_list(self.handle, elements))
            count = self.lib.snd_ctl_elem_list_get_count(elements)
            self.check(self.lib.snd_ctl_elem_list_alloc_space(elements, count))
            self.check(self.lib.snd_ctl_elem_list(self.handle, elements))
            names = [self.lib.snd_ctl_elem_list_get_name(elements, i).decode(errors='replace').lower()
                     for i in range(self.lib.snd_ctl_elem_list_get_used(elements))]
            return any('jack' in name and ('headphone' in name or 'headset' in name) for name in names)
        finally:
            self.lib.snd_ctl_elem_list_free_space(elements)
            self.lib.snd_ctl_elem_list_free(elements)

    def drain(self):
        relevant = False
        while True:
            result = self.lib.snd_ctl_read(self.handle, self.event)
            if result == -errno.EAGAIN:
                return relevant
            self.check(result)
            if result == 0:
                raise OSError(errno.ENODEV, 'ALSA control closed')
            if self.lib.snd_ctl_event_get_type(self.event) == 0:
                name = self.lib.snd_ctl_event_elem_get_name(self.event).decode(errors='replace')
                relevant = route_event(name) or relevant

    def close(self):
        if self.event:
            self.lib.snd_ctl_event_free(self.event)
            self.event = C.c_void_p()
        if self.handle:
            self.lib.snd_ctl_close(self.handle)
            self.handle = C.c_void_p()


def sound_event(data, card=None):
    fields = dict(field.split('=', 1) for field in data.decode(errors='replace').split('\0') if '=' in field)
    if fields.get('SUBSYSTEM') != 'sound' or fields.get('ACTION') not in ('add', 'remove', 'change', 'bind'):
        return False
    # Once identified, USB/HDMI events on other cards should not wake this codec.
    if card is not None:
        return re.search(rf'/sound/card{card}(?:/|$)', fields.get('DEVPATH', '')) is not None
    return True


class Pending:
    """One debounce and one bounded follow-up per event burst, never periodic polling."""
    def __init__(self):
        self.deadline = None
        self.followup = False

    def trigger(self, now):
        # Cap delay under a burst so continuous control changes cannot starve routing.
        self.deadline = min(self.deadline, now + 0.4) if self.deadline is not None else now + 0.4
        self.followup = True

    def fired(self, now):
        self.deadline = now + 2 if self.followup else None
        self.followup = False


class PlaybackEvents:
    """Watch device opens without opening a PCM or waking an idle codec."""
    HEADER = struct.Struct('iIII')
    OPEN = 0x20
    OVERFLOW = 0x4000

    def __init__(self):
        lib = C.CDLL(None, use_errno=True)
        lib.inotify_init1.argtypes = [C.c_int]
        lib.inotify_init1.restype = C.c_int
        lib.inotify_add_watch.argtypes = [C.c_int, C.c_char_p, C.c_uint32]
        lib.inotify_add_watch.restype = C.c_int
        self.fd = lib.inotify_init1(os.O_NONBLOCK | os.O_CLOEXEC)
        if self.fd < 0:
            raise OSError(C.get_errno(), 'Cannot create playback event listener')
        if lib.inotify_add_watch(self.fd, os.fsencode(DEV), self.OPEN) < 0:
            error = C.get_errno()
            self.close()
            raise OSError(error, 'Cannot watch sound device opens')

    def drain(self, card):
        relevant = False
        while True:
            try:
                data = os.read(self.fd, 65536)
            except BlockingIOError:
                return relevant
            offset = 0
            while offset + self.HEADER.size <= len(data):
                _, mask, _, length = self.HEADER.unpack_from(data, offset)
                offset += self.HEADER.size
                name = data[offset:offset + length].split(b'\0', 1)[0].decode(errors='replace')
                offset += length
                # Capture, control and hwdep accesses (including our own verbs)
                # cannot retrigger routing. Other cards are ignored once known.
                playback = re.fullmatch(r'pcmC(\d+)D\d+p', name)
                relevant |= bool(mask & self.OVERFLOW or
                                 (mask & self.OPEN and playback and
                                  (card is None or int(playback[1]) == card)))

    def close(self):
        os.close(self.fd)


def run():
    # Do not even open a control device on another model.
    if PRODUCT.read_text().strip() != 'HKF-WXX':
        LOG.info('Unsupported product; no audio changes made')
        return
    # Kernel uevents are for enumeration/reset only. Jack changes come from ALSA.
    uevents = socket.socket(socket.AF_NETLINK, socket.SOCK_DGRAM | socket.SOCK_NONBLOCK, 15)
    uevents.bind((os.getpid(), 1))
    playback = PlaybackEvents()
    wake_read, wake_write = os.pipe2(os.O_NONBLOCK | os.O_CLOEXEC)
    signal.set_wakeup_fd(wake_write)
    for sig in (signal.SIGUSR1, signal.SIGTERM, signal.SIGINT):
        signal.signal(sig, lambda *_: None)
    poller = select.poll()
    poller.register(uevents, select.POLLIN)
    poller.register(wake_read, select.POLLIN)
    poller.register(playback.fd, select.POLLIN)
    control, match, previous = None, None, None
    pending = Pending()
    pending.trigger(time.monotonic())
    last_error = None
    warned_no_jack = False

    def disconnect():
        nonlocal control, match
        if control:
            for fd in control.fds:
                poller.unregister(fd)
            control.close()
        control, match = None, None

    try:
        LOG.info('Listening for ALSA route/jack events, sound devices and resume')
        while True:
            now = time.monotonic()
            timeout = -1 if pending.deadline is None else max(0, int((pending.deadline - now) * 1000) + 1)
            for fd, flags in poller.poll(timeout):
                if fd == wake_read:
                    signals = os.read(wake_read, 4096)
                    if signal.SIGTERM in signals or signal.SIGINT in signals:
                        return
                    if signal.SIGUSR1 in signals:
                        disconnect()
                        pending.trigger(time.monotonic())
                elif fd == playback.fd:
                    if flags & (select.POLLERR | select.POLLHUP | select.POLLNVAL):
                        raise RuntimeError('Playback event listener disconnected')
                    if playback.drain(match[0] if match else None):
                        pending.trigger(time.monotonic())
                elif fd == uevents.fileno():
                    while True:
                        try:
                            data, sender = uevents.recvfrom(65536)
                        except BlockingIOError:
                            break
                        if sender[0] == 0 and sound_event(data, match[0] if match else None):
                            disconnect()
                            pending.trigger(time.monotonic())
                elif control and fd in control.fds:
                    try:
                        if flags & (select.POLLERR | select.POLLHUP | select.POLLNVAL):
                            raise OSError(errno.ENODEV, 'ALSA control disconnected')
                        if control.drain():
                            pending.trigger(time.monotonic())
                    except OSError:
                        disconnect()
                        pending.trigger(time.monotonic())
            now = time.monotonic()
            if pending.deadline is None or now < pending.deadline:
                continue
            pending.fired(now)
            try:
                found = discover()
                if found != match:
                    disconnect()
                if not found or not found[1].exists():
                    continue  # Wait for a sound-device event, no periodic hardware probes.
                if control is None:
                    control = Controls(found[0])
                    match = found
                    if not control.has_jack and not warned_no_jack:
                        LOG.warning('No Headphone/Headset Jack ALSA control exported; automatic jack switching '
                                    'cannot be guaranteed. Check kernel/driver support; no polling fallback enabled.')
                        warned_no_jack = True
                    for fd in control.fds:
                        poller.register(fd, select.POLLIN | select.POLLERR | select.POLLHUP)
                previous = apply_route(match, previous, force=True)
                last_error = None
            except (OSError, RuntimeError, subprocess.SubprocessError) as exc:
                message = str(exc)
                if message != last_error:
                    LOG.warning('Routing not applied: %s; retry on next event or restart service', message)
                    last_error = message
    finally:
        disconnect()
        signal.set_wakeup_fd(-1)
        os.close(wake_read)
        os.close(wake_write)
        uevents.close()
        playback.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--check', action='store_true', help='check identities only; no device access or writes')
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')
    if args.check:
        match = discover()
        if match:
            print(match[1])
        return 0 if match else 1
    run()
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
