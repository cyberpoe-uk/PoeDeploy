import importlib.util
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('ctf', ROOT / 'dashboard/scripts/ctf-control.py')
control = importlib.util.module_from_spec(spec)
spec.loader.exec_module(control)


class LaunchTests(unittest.TestCase):
    def test_normal_chromium_and_blackarch_burp_executables(self):
        executables = {'chromium': '/usr/bin/chromium', 'burpsuite': '/usr/bin/burpsuite'}
        with patch.object(control.shutil, 'which', side_effect=executables.get):
            self.assertEqual(control.command('chromium'), ['/usr/bin/chromium', '--new-window'])
            self.assertEqual(control.command('burp'), ['/usr/bin/burpsuite'])

    def test_chromium_launch_does_not_require_a_proxy_listener(self):
        window = {'address': '0x123', 'class': 'chromium', 'workspace': {'id': 2}}
        with patch.object(control, 'clients', side_effect=[[], [window]]), \
             patch.object(control.shutil, 'which', return_value='/usr/bin/chromium'), \
             patch.object(control, 'running_without_window', return_value=False), \
             patch.object(control, 'dispatch') as dispatch, patch.object(control.time, 'sleep'), \
             patch('socket.create_connection', side_effect=OSError('No Burp listener')) as listener:
            self.assertEqual(control.ensure('chromium'), window)
            listener.assert_not_called()
            launch = dispatch.call_args_list[0].args[0]
            self.assertIn('/usr/bin/chromium --new-window', launch)
            self.assertNotIn('proxy', launch)
            self.assertNotIn('ctf-chromium', launch)

    def test_saved_target_opens_without_browser_proxy_configuration(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            with patch.object(control, 'STATE', home / 'state'), patch.object(control, 'CACHE', home / 'cache'), \
                 patch.object(control, 'ensure') as ensure, patch.object(control, 'dispatch'), \
                 patch('socket.create_connection', side_effect=OSError('No Burp listener')) as listener:
                with self.assertRaises(ValueError):
                    control.save_target('https://example.test/path?x=1&y=$(touch bad)')
                target = 'https://example.test/path?x=1&y=2'
                control.save_target(target)
                self.assertEqual(control.read_target(), target)
                self.assertEqual(control.launch('web-ctf'), 0)
                self.assertEqual(ensure.call_args_list[0].args, ('burp',))
                self.assertEqual(ensure.call_args_list[1].kwargs['target'], target)
                listener.assert_not_called()

    def test_chromium_is_recognised_without_proxy_flags(self):
        with patch.object(control, 'process_args', return_value=['/usr/lib/chromium/chromium']):
            self.assertTrue(control.is_browser_process(123))
        with patch.object(control, 'process_args', return_value=['/usr/lib/chromium/chromium', '--type=renderer']):
            self.assertFalse(control.is_browser_process(124))

    def test_blackarch_burp_startup_is_detected_before_its_window_exists(self):
        with patch.object(control.Path, 'glob', return_value=[Path('/proc/123')]), \
             patch.object(control, 'process_args', return_value=['/usr/bin/java', '-jar', '/usr/share/burpsuite/burpsuite.jar']):
            self.assertTrue(control.running_without_window('burp'))
