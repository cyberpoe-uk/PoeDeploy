"""No real codec access: identity fixtures, mocked verbs and event-loop sources."""
import importlib.util
from pathlib import Path
import select
import signal
import shlex
import socket
import subprocess
import tempfile
import unittest
from unittest.mock import Mock, patch

from test_workflows import ROOT, run_bash

BASE = ROOT / 'installer/matebook-audio'
spec = importlib.util.spec_from_file_location('matebook_audio', BASE / 'routing.py')
audio = importlib.util.module_from_spec(spec)
spec.loader.exec_module(audio)


class IdentityTests(unittest.TestCase):
    def fixture(self, root, product='HKF-WXX', subsystem='0x19e53285', address='2'):
        product_file = root / 'product'
        product_file.write_text(product + '\n')
        proc = root / 'asound'
        codec = proc / 'card3/codec#0'
        codec.parent.mkdir(parents=True, exist_ok=True)
        codec.write_text(f'Codec: Conexant SN6140\nAddress: {address}\nSubsystem Id: {subsystem}\n')
        return product_file, proc, root / 'snd'

    def test_card_and_address_discovered_independently(self):
        with tempfile.TemporaryDirectory() as tmp:
            args = self.fixture(Path(tmp))
            self.assertEqual(audio.discover(*args), (3, Path(tmp) / 'snd/hwC3D2'))

    def test_both_exact_identities_and_valid_address_required(self):
        for product, subsystem, address in [('HKF-WXX-PCB', '0x19e53285', '0'),
                                             ('OTHER', '0x19e53285', '0'),
                                             ('HKF-WXX', '0x19e53286', '0'),
                                             ('HKF-WXX', '0x19e53285', '16')]:
            with self.subTest(product=product, subsystem=subsystem, address=address):
                with tempfile.TemporaryDirectory() as tmp:
                    self.assertIsNone(audio.discover(*self.fixture(Path(tmp), product, subsystem, address)))

    def test_missing_metadata_and_ambiguous_codecs(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            args = self.fixture(root)
            codec = args[1] / 'card3/codec#0'
            codec.write_text('Subsystem Id: 0x19e53285\n')
            self.assertIsNone(audio.discover(*args))
            self.fixture(root)
            other = args[1] / 'card7/codec#1'
            other.parent.mkdir()
            other.write_text(codec.read_text())
            with self.assertRaisesRegex(RuntimeError, 'ambiguous'):
                audio.discover(*args)
        self.assertIsNone(audio.discover(Path('/nonexistent-product')))


class RoutingTests(unittest.TestCase):
    def setUp(self):
        self.match = (3, Path('/dev/snd/hwC3D2'))

    def apply(self, sense, previous=None, force=False):
        with patch.object(audio, 'discover', return_value=self.match), \
             patch.object(Path, 'exists', return_value=True), \
             patch.object(audio, 'verb', side_effect=[sense] + [0] * 5) as verb:
            state = audio.apply_route(self.match, previous, force)
            return state, [call.args[1:] for call in verb.call_args_list]

    def test_hex_value_and_high_presence_bit(self):
        self.assertEqual(audio.response_value('nid = 0x16\nvalue = 0x80000000\n'), 0x80000000)
        for text in ('', 'value = error', 'value = 0x100000000'):
            with self.subTest(text=text), self.assertRaises(RuntimeError):
                audio.response_value(text)
        state, calls = self.apply(0x80000000)
        self.assertTrue(state[1])
        self.assertEqual(calls, [(0x16, 0xf09, 0)] + list(audio.HEADPHONES))
        state, calls = self.apply(0x1234)
        self.assertFalse(state[1])
        self.assertEqual(calls, [(0x16, 0xf09, 0)] + list(audio.SPEAKERS))

    def test_read_failure_never_routes_speakers(self):
        with patch.object(audio, 'discover', return_value=self.match), \
             patch.object(Path, 'exists', return_value=True), \
             patch.object(audio, 'verb', side_effect=RuntimeError('read failed')) as verb:
            with self.assertRaisesRegex(RuntimeError, 'read failed'):
                audio.apply_route(self.match)
            self.assertEqual(verb.call_count, 1)

    def test_revalidation_prevents_stale_card_writes(self):
        with patch.object(audio, 'discover', return_value=None), patch.object(audio, 'verb') as verb:
            with self.assertRaises(RuntimeError):
                audio.apply_route(self.match)
            verb.assert_not_called()

    def test_unchanged_state_skipped_unless_policy_reset_event(self):
        previous = (str(self.match[1]), False)
        _, calls = self.apply(0, previous)
        self.assertEqual(len(calls), 1)
        _, calls = self.apply(0, previous, force=True)
        self.assertEqual(calls[1:], list(audio.SPEAKERS))

    def test_hda_execution_uses_fixed_binary_timeout_and_checks_exit(self):
        with patch.object(subprocess, 'run', return_value=Mock(stdout='value = 0x80000000')) as run:
            self.assertEqual(audio.verb(self.match[1], 0x16, 0xf09, 0), 0x80000000)
            self.assertEqual(run.call_args.args[0][0], '/usr/bin/hda-verb')
            self.assertTrue(run.call_args.kwargs['check'])
            self.assertEqual(run.call_args.kwargs['timeout'], 3)


class PlaybackEventTests(unittest.TestCase):
    def test_real_inotify_filters_card_capture_control_and_our_own_verbs(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            names = ['pcmC3D0p', 'pcmC3D2p', 'pcmC4D0p', 'pcmC3D0c',
                     'controlC3', 'hwC3D2']
            for name in names:
                (directory / name).touch()
            with patch.object(audio, 'DEV', directory):
                watcher = audio.PlaybackEvents()
            try:
                self.assertFalse(watcher.drain(3))
                for name in names:
                    with (directory / name).open('rb'):
                        pass
                    self.assertEqual(watcher.drain(3), name in names[:2], name)
                with (directory / 'pcmC4D0p').open('rb'):
                    pass
                self.assertTrue(watcher.drain(None))
            finally:
                watcher.close()

    def test_queue_overflow_requests_one_recheck(self):
        watcher = audio.PlaybackEvents.__new__(audio.PlaybackEvents)
        watcher.fd = 55
        data = watcher.HEADER.pack(-1, watcher.OVERFLOW, 0, 0)
        with patch.object(audio.os, 'read', side_effect=[data, BlockingIOError()]):
            self.assertTrue(watcher.drain(3))


class EventTests(unittest.TestCase):
    def setUp(self):
        watcher = patch.object(audio, 'PlaybackEvents', return_value=Mock(fd=55))
        self.playback = watcher.start().return_value
        self.addCleanup(watcher.stop)

    def test_alsa_route_filter_ignores_volume_microphone_and_meters(self):
        for name in ('Headphone Jack', 'Headset Jack', 'Speaker Playback Switch',
                     'Headphone Playback Switch', 'Auto-Mute Mode', 'Playback Route'):
            self.assertTrue(audio.route_event(name), name)
        for name in ('Mic Jack', 'Capture Volume', 'Headphone Playback Volume', 'PCM Playback Volume'):
            self.assertFalse(audio.route_event(name), name)

    def test_kernel_sound_events_only_for_enumeration(self):
        self.assertTrue(audio.sound_event(b'change@/devices/foo\0SUBSYSTEM=sound\0ACTION=change\0'))
        self.assertFalse(audio.sound_event(b'SUBSYSTEM=input\0ACTION=change\0'))
        self.assertFalse(audio.sound_event(b'SUBSYSTEM=sound\0ACTION=offline\0'))
        event = b'SUBSYSTEM=sound\0ACTION=change\0DEVPATH=/devices/pci/sound/card3/hwC3D2\0'
        self.assertTrue(audio.sound_event(event, 3))
        self.assertFalse(audio.sound_event(event, 0))
        self.assertFalse(audio.sound_event(event, 30))

    def test_debounce_is_bounded_and_stops_after_followup(self):
        pending = audio.Pending()
        self.assertIsNone(pending.deadline)
        pending.trigger(1)
        pending.trigger(1.2)
        self.assertAlmostEqual(pending.deadline, 1.4)
        pending.fired(1.4)
        self.assertAlmostEqual(pending.deadline, 3.4)
        pending.fired(3.4)
        self.assertIsNone(pending.deadline)

    def test_unsupported_product_opens_no_event_or_audio_devices(self):
        with patch.object(Path, 'read_text', return_value='OTHER'), \
             patch.object(socket, 'socket') as sock, patch.object(audio, 'Controls') as controls:
            audio.run()
            sock.assert_not_called()
            controls.assert_not_called()

    def test_late_device_jack_policy_and_resume_reconnect(self):
        now = [0.0]
        script = iter([
            (0.5, []), (2.6, []), (3.0, [(44, select.POLLIN)]),
            (3.5, []), (5.6, []), (6.0, [(33, select.POLLIN)]),
            (6.5, []), (8.6, []), (9.0, [(11, select.POLLIN)]),
            (9.5, []), (11.6, []), (12.0, [(11, select.POLLIN)]),
        ])
        timeouts = []
        def wait(timeout):
            timeouts.append(timeout)
            now[0], events = next(script)
            return events
        poller = Mock()
        poller.poll.side_effect = wait
        uevents = Mock()
        uevents.fileno.return_value = 44
        uevents.recvfrom.side_effect = [(b'SUBSYSTEM=sound\0ACTION=add\0', (0, 1)), BlockingIOError()]
        controls = Mock(fds=[33], has_jack=True)
        controls.drain.return_value = True
        match = (3, Path('/dev/snd/hwC3D2'))
        with patch.object(Path, 'read_text', return_value='HKF-WXX'), \
             patch.object(Path, 'exists', return_value=True), \
             patch.object(audio.time, 'monotonic', side_effect=lambda: now[0]), \
             patch.object(audio.select, 'poll', return_value=poller), \
             patch.object(audio.socket, 'socket', return_value=uevents), \
             patch.object(audio.os, 'pipe2', return_value=(11, 12)), \
             patch.object(audio.os, 'read', side_effect=[bytes([signal.SIGUSR1]), bytes([signal.SIGTERM])]), \
             patch.object(audio.os, 'close'), patch.object(signal, 'set_wakeup_fd'), \
             patch.object(signal, 'signal'), \
             patch.object(audio, 'discover', side_effect=[None, None] + [match] * 6), \
             patch.object(audio, 'Controls', return_value=controls) as factory, \
             patch.object(audio, 'apply_route', return_value=(str(match[1]), False)) as apply:
            audio.run()
            self.assertEqual(factory.call_count, 2)  # late arrival, then resume reopen
            self.assertEqual(controls.close.call_count, 2)  # resume and shutdown
            self.assertEqual(apply.call_count, 6)  # bounded pairs for arrival, jack, resume
            self.assertTrue(all(call.kwargs['force'] for call in apply.call_args_list))
        self.assertEqual(timeouts.count(-1), 4)

    def test_playback_open_reapplies_route_after_idle_without_alsa_event(self):
        now = [0.0]
        script = iter([(0.5, []), (2.6, []), (20, [(55, select.POLLIN)]),
                       (20.5, []), (22.6, []), (23, [(11, select.POLLIN)])])
        def wait(timeout):
            now[0], events = next(script)
            return events
        poller = Mock()
        poller.poll.side_effect = wait
        match = (3, Path('/dev/snd/hwC3D2'))
        with patch.object(Path, 'read_text', return_value='HKF-WXX'), \
             patch.object(Path, 'exists', return_value=True), \
             patch.object(audio.time, 'monotonic', side_effect=lambda: now[0]), \
             patch.object(audio.select, 'poll', return_value=poller), \
             patch.object(audio.socket, 'socket'), \
             patch.object(audio.os, 'pipe2', return_value=(11, 12)), \
             patch.object(audio.os, 'read', return_value=bytes([signal.SIGTERM])), \
             patch.object(audio.os, 'close'), patch.object(signal, 'set_wakeup_fd'), \
             patch.object(signal, 'signal'), \
             patch.object(audio, 'discover', return_value=match), \
             patch.object(audio, 'Controls', return_value=Mock(fds=[33], has_jack=True)), \
             patch.object(audio, 'apply_route') as apply:
            audio.run()
        self.assertEqual(apply.call_count, 4)
        self.playback.drain.assert_called_once_with(3)
        self.assertTrue(all(call.kwargs['force'] for call in apply.call_args_list))
        self.assertEqual([call.args[0] for call in poller.poll.call_args_list].count(-1), 2)

    def test_event_loop_waits_indefinitely_without_hardware_then_handles_resume(self):
        # startup+followup probes, then block forever; resume schedules another
        # bounded pair. SIGTERM exits. No codec writes when device is absent.
        clock = iter([0, 0, 1, 1, 4, 4, 5, 5, 6, 6, 9, 9, 10])
        poller = Mock()
        poller.poll.side_effect = [[], [], [(11, select.POLLIN)], [], [], [(11, select.POLLIN)]]
        with patch.object(Path, 'read_text', return_value='HKF-WXX'), \
             patch.object(audio.time, 'monotonic', side_effect=lambda: next(clock)), \
             patch.object(audio.select, 'poll', return_value=poller), \
             patch.object(audio.socket, 'socket'), \
             patch.object(audio.os, 'pipe2', return_value=(11, 12)), \
             patch.object(audio.os, 'read', side_effect=[bytes([signal.SIGUSR1]), bytes([signal.SIGTERM])]), \
             patch.object(audio.os, 'close'), patch.object(signal, 'set_wakeup_fd'), \
             patch.object(signal, 'signal'), patch.object(audio, 'discover', return_value=None) as discover, \
             patch.object(audio, 'verb') as verb:
            audio.run()
            self.assertEqual(discover.call_count, 4)
            verb.assert_not_called()
        self.assertEqual([c.args[0] for c in poller.poll.call_args_list].count(-1), 2)


class InstallationTests(unittest.TestCase):
    def test_shell_preflight_matches_unique_subsystem_without_dependencies(self):
        with tempfile.TemporaryDirectory() as tmp:
            codec = Path(tmp) / 'card3/codec#2'
            codec.parent.mkdir()
            codec.write_text('Subsystem Id: 0x19e53285\n')
            quoted = shlex.quote(tmp)
            result = run_bash(f'matebook_audio_subsystem_matches {quoted}')
            self.assertEqual(result.returncode, 0, result.stderr)
            second = codec.parent / 'codec#4'
            second.write_text(codec.read_text())
            result = run_bash(f'matebook_audio_subsystem_matches {quoted}')
            self.assertNotEqual(result.returncode, 0)
            second.unlink()
            codec.write_text('Subsystem Id: 0x19e53286\n')
            result = run_bash(f'matebook_audio_subsystem_matches {quoted}')
            self.assertNotEqual(result.returncode, 0)

    def test_registered_optional_terminal_section(self):
        result = run_bash('''
[[ "${SETUP_MODULE_LABELS[matebook_audio]}" == *MateBook* ]]
setup_module_needs_terminal matebook_audio
setup_matebook_audio() { echo DISPATCHED; }
run_setup_module matebook_audio
''')
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn('DISPATCHED', result.stdout)

    def test_chroot_or_other_hardware_has_no_installs(self):
        result = run_bash('''
POEDEPLOY_IN_CHROOT=true
setup_matebook_audio
''')
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertNotIn('UNEXPECTED PRIVILEGED', result.stderr)

    def test_hardware_gates_and_declining_never_install_files(self):
        for product, codec, answer in [(1, 0, 'y'), (0, 1, 'y'), (0, 0, 'n')]:
            result = run_bash(f"""
matebook_audio_product_matches() {{ return {product}; }}
matebook_audio_subsystem_matches() {{ return {codec}; }}
matebook_audio_codec_matches() {{ return {codec}; }}
ensure_command_dependencies() {{ :; }}
ui_heading() {{ :; }}
ui_prompt() {{ printf -v "$1" '%s' {answer}; }}
setup_matebook_audio
""")
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertNotIn('UNEXPECTED PRIVILEGED', result.stderr)

    def test_reinstall_replaces_files_and_restarts_single_service(self):
        result = run_bash(r"""
matebook_audio_product_matches() { return 0; }
matebook_audio_subsystem_matches() { return 0; }
matebook_audio_codec_matches() { return 0; }
ensure_command_dependencies() { echo "DEP:$*"; }
ui_heading() { :; }
ui_prompt() { printf -v "$1" '%s' y; }
sudo() { printf 'SUDO:%s\n' "$*"; }
setup_matebook_audio
setup_matebook_audio
""")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(result.stdout.count('DEP:python3:python hda-verb:alsa-tools'), 2)
        self.assertEqual(result.stdout.count('systemctl restart poedeploy-matebook-audio.service'), 2)
        self.assertEqual(result.stdout.count('systemctl enable poedeploy-matebook-audio.service'), 2)
        self.assertEqual(result.stdout.count('install -o root -g root -m 0755'), 4)
        self.assertNotIn('pacmd', result.stdout)

    def test_resume_signals_without_starting_disabled_service(self):
        text = (BASE / 'resume.sh').read_text()
        self.assertIn('== post', text)
        self.assertIn('kill --kill-whom=main --signal=SIGUSR1', text)
        self.assertNotIn('restart', text)
        self.assertNotIn('systemctl start ', text)


if __name__ == '__main__':
    unittest.main()
