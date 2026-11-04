"""Media actions and visualization with no real playback or audio recording."""
import array
import asyncio
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import AsyncMock, Mock, patch

SCRIPTS = Path(__file__).resolve().parents[1] / 'apps/poedash/assets/scripts'
def module(name):
    spec = importlib.util.spec_from_file_location(name.replace('-', '_'), SCRIPTS / (name + '.py'))
    value = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(value)
    return value

actions = module('media-actions')
visual = module('visualizer')


class MediaActions(unittest.TestCase):
    def test_seek_targets_playing_player_and_clamps_percentage(self):
        with patch.object(actions, 'players', return_value=[('browser', 'Paused'), ('spotify', 'Playing')]), \
             patch.object(actions, 'call', return_value='200000000') as call:
            actions.seek('25')
            self.assertEqual(call.call_args.args, ('playerctl', '-p', 'spotify', 'position', '50.000'))
            actions.seek('150')
            self.assertEqual(call.call_args.args[-1], '200.000')
        with self.assertRaises(ValueError): actions.seek('nan')

    def test_live_stream_and_absent_player_do_not_seek(self):
        with patch.object(actions, 'players', return_value=[]), patch.object(actions, 'call') as call:
            actions.seek(50)
            call.assert_not_called()
        with patch.object(actions, 'players', return_value=[('radio', 'Playing')]), \
             patch.object(actions, 'call', return_value='0') as call:
            actions.seek(50)
            self.assertEqual(call.call_count, 1)

    def test_background_launch_has_silent_workspace_rule_and_safe_quoting(self):
        with patch.object(actions, 'spotify_entry', return_value=Path('/tmp/Spotify App.desktop')), \
             patch.object(actions, 'call', return_value='ok') as call:
            self.assertTrue(actions.launch_spotify())
            expression = call.call_args.args[-1]
            self.assertIn('workspace="2 silent"', expression)
            self.assertIn('gio launch', expression)
            self.assertIn("'/tmp/Spotify App.desktop'", expression)

    def test_missing_spotify_requires_approval_then_opens_prefilled_package_search(self):
        with patch.object(actions, 'spotify_entry', return_value=None), \
             patch.object(actions.shutil, 'which', side_effect=lambda name: '/bin/rofi' if name == 'rofi' else None), \
             patch.object(actions.subprocess, 'run', return_value=Mock(returncode=0, stdout='1')), \
             patch.object(actions.subprocess, 'Popen') as launch:
            self.assertFalse(actions.launch_spotify())
            self.assertEqual(launch.call_args.args[0][-3:], ['launch', '--query', 'spotify'])
        with patch.object(actions, 'spotify_entry', return_value=None), \
             patch.object(actions.shutil, 'which', side_effect=lambda name: '/bin/rofi' if name == 'rofi' else None), \
             patch.object(actions.subprocess, 'run', return_value=Mock(returncode=1, stdout='')), \
             patch.object(actions.subprocess, 'Popen') as launch:
            actions.launch_spotify()
            launch.assert_not_called()

    def test_existing_spotify_resumes_without_launch_or_focus(self):
        with patch.object(actions, 'players', return_value=[('spotify', 'Paused')]), \
             patch.object(actions, 'call', return_value='Playing') as call, \
             patch.object(actions, 'launch_spotify') as launch, patch.object(actions.time, 'sleep'):
            self.assertTrue(actions.resume_spotify())
            launch.assert_not_called()
            self.assertEqual(call.call_args_list[0].args[-1], 'play')

    def test_saved_track_is_used_when_spotify_does_not_restore_its_context(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / 'state').mkdir()
            (root / 'state/spotify-last.json').write_text(json.dumps({'uri': 'spotify:track:example'}))
            with patch.object(actions, 'ROOT', root), \
                 patch.object(actions, 'players', return_value=[('spotify', 'Stopped')]), \
                 patch.object(actions, 'call', return_value='Stopped') as call, patch.object(actions.time, 'sleep'):
                actions.resume_spotify()
                self.assertIn(('playerctl', '-p', 'spotify', 'open', 'spotify:track:example'), [c.args for c in call.call_args_list])


class Wave(unittest.TestCase):
    def test_pulse_fallback_monitors_output_never_default_microphone(self):
        with tempfile.TemporaryDirectory() as tmp, \
             patch.object(visual.shutil, 'which', side_effect=lambda name: '/bin/parec' if name == 'parec' else None):
            command, backend = visual.audio_command(Path(tmp), 12)
            self.assertIn('--device=@DEFAULT_MONITOR@', command)
            self.assertNotIn('--device=@DEFAULT_SOURCE@', command)
            self.assertIn('output monitor', backend)

    def test_pcm_silence_real_amplitude_smoothing_and_svg_are_bounded(self):
        silence = array.array('h', [0] * 1024).tobytes()
        sound = array.array('h', [16000] * 1024).tobytes()
        self.assertEqual(visual.pcm_levels(silence), [0] * visual.BARS)
        levels = visual.pcm_levels(sound)
        self.assertTrue(all(0 < n <= 100 for n in levels))
        filtered = visual.smooth(levels, [0] * visual.BARS)
        self.assertTrue(all(0 < n < 100 for n in filtered))
        self.assertIn('<svg', visual.svg(filtered))
        self.assertIn(' Q ', visual.svg(filtered))

    def test_wave_has_colored_progress_clip_full_card_width_and_no_cursor(self):
        image = visual.svg([50] * 32, width=1075, progress=25)
        self.assertIn('width="1075"', image)
        self.assertIn('<rect width="80.00"', image)
        self.assertEqual(image.count('<linearGradient '), 3)
        self.assertEqual(image.count('T 320,30 L 0,30 Z'), 3)
        for color in ('#ef4444', '#a855f7', '#facc15', '#3b82f6', '#ffffff', '#000000', '#fb923c'):
            self.assertIn(color, image)
        self.assertNotIn('#6ee7b7', image)
        self.assertNotEqual(image, visual.svg([0] * 32, width=1075, progress=25))
        self.assertNotIn('<circle', image)
        self.assertEqual(visual.song_progress(dict(length=100, position=25, playing=True, sampled=10), 11), 26)
        self.assertEqual(visual.song_progress(dict(length=100, position=25, playing=False, sampled=10), 11), 25)

    def test_cava_configuration_uses_monitor_source_and_bounded_frame_rate(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(visual.shutil, 'which', return_value='/bin/cava'):
            directory = Path(tmp)
            command, _ = visual.audio_command(directory, 12)
            self.assertEqual(command[0], 'cava')
            config = (directory / 'cava.conf').read_text()
            self.assertIn('framerate=12', config)
            self.assertIn('method=pulse\nsource=auto', config)


if __name__ == '__main__':
    unittest.main()


class NativeVisualizer(unittest.TestCase):
    class Finished(Exception):
        pass

    def test_native_stream_emits_multiple_frames_without_svg_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp); (root/'state').mkdir()
            for name in ('media-playing','home-visible'):
                (root/'state'/name).write_text('true')
            process=Mock(returncode=None)
            process.stdout.readexactly=AsyncMock(return_value=array.array('h',[16000]*1066).tobytes())
            process.wait=AsyncMock(return_value=0)
            frames=[]
            def receive(document, **kwargs):
                frames.append(json.loads(document))
                if len(frames)==3: raise self.Finished()
            with patch.dict(visual.os.environ,{'XDG_RUNTIME_DIR':tmp}), \
                 patch.object(visual,'audio_command',return_value=(['fake-monitor'],'PulseAudio output monitor')) as command, \
                 patch.object(visual.asyncio,'create_subprocess_exec',new=AsyncMock(return_value=process)), \
                 patch('builtins.print',side_effect=receive):
                with self.assertRaises(self.Finished): asyncio.run(visual.main(root,native=True))
            self.assertEqual(len(frames),3)
            self.assertTrue(all(frame['active'] and len(frame['values'])==32 for frame in frames))
            self.assertFalse(list((root/'poedash-wave').glob('wave-*.svg')))
            self.assertEqual(command.call_args.args[1],15)
            process.terminate.assert_called_once()

    def test_native_hidden_dashboard_does_not_start_audio_monitor(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp); (root/'state').mkdir()
            (root/'state/media-playing').write_text('true')
            (root/'state/home-visible').write_text('false')
            (root/'state/on-battery').write_text('true')
            with patch.dict(visual.os.environ,{'XDG_RUNTIME_DIR':tmp}), \
                 patch.object(visual,'audio_command',return_value=(['fake-monitor'],'PulseAudio output monitor')) as command, \
                 patch.object(visual.asyncio,'create_subprocess_exec',new=AsyncMock()) as spawn, \
                 patch.object(visual.asyncio,'sleep',new=AsyncMock(side_effect=self.Finished)):
                with self.assertRaises(self.Finished): asyncio.run(visual.main(root,native=True))
            spawn.assert_not_called()
            self.assertEqual(command.call_args.args[1],10)
