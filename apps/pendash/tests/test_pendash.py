import importlib.util
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
spec = importlib.util.spec_from_file_location('pendash', REPO / 'pendash.py')
p = importlib.util.module_from_spec(spec)
spec.loader.exec_module(p)


class InstallerTests(unittest.TestCase):
    def test_default_and_legacy_dashboard_installs_only_dashboard_dependencies(self):
        for options in ([], ['--dashboard-only']):
            with self.subTest(options=options), \
                 patch.object(p.sys, 'argv', ['pendash.py', '--non-interactive', *options]), \
                 patch.object(p.os, 'geteuid', return_value=1000), \
                 patch.object(p, 'install_packages') as packages, \
                 patch.object(p, 'install_dashboard') as dashboard, \
                 patch.object(p, 'offer_ca') as certificate, \
                 patch.object(p, 'run') as command:
                self.assertEqual(p.main(), 0)
                packages.assert_called_once()
                selected = packages.call_args.args[0]
                self.assertIn('chromium', selected)
                self.assertIn('nss', selected)
                self.assertFalse(set(selected).intersection({
                    'nvidia-prime', 'hypridle', 'hyprlock', 'power-profiles-daemon',
                    'ffuf', 'gobuster', 'burpsuite', 'tailscale',
                }))
                dashboard.assert_called_once_with('chromium', False)
                certificate.assert_called_once()
                self.assertTrue(certificate.call_args.args[0].non_interactive)
                command.assert_not_called()

    def test_retired_system_setup_flags_are_rejected_before_installation(self):
        for options in (['--tool-mode', 'all'], ['--skip-nvidia'], ['--burp-installer', '/tmp/installer.sh']):
            with self.subTest(options=options), \
                 patch.object(p.sys, 'argv', ['pendash.py', *options]), \
                 patch.object(p.sys, 'stderr', io.StringIO()), \
                 patch.object(p, 'install_packages') as packages, \
                 patch.object(p, 'install_dashboard') as dashboard:
                with self.assertRaises(SystemExit) as result:
                    p.main()
                self.assertEqual(result.exception.code, 2)
                packages.assert_not_called()
                dashboard.assert_not_called()

    def test_check_requires_only_dashboard_and_browser(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            dashboard = home / '.config/eww/eww.yuck'
            dashboard.parent.mkdir(parents=True)
            dashboard.touch()
            with patch.object(p, 'HOME', home), \
                 patch.object(p.os, 'geteuid', return_value=1000), \
                 patch.object(p.sys, 'argv', ['pendash.py', '--check']), \
                 patch.object(p, 'browser_checks', return_value=True), \
                 patch.object(p, 'run') as command:
                self.assertEqual(p.main(), 0)
                dashboard.unlink()
                self.assertEqual(p.main(), 2)
                command.assert_not_called()

    def test_dashboard_update_preserves_browser_palette_and_skips_system_setup(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            root = home / '.config/eww'
            root.mkdir(parents=True)
            (root / 'eww.yuck').write_text('old')
            (root / 'browser.json').write_text('{"browser": "chromium"}')
            (root / 'colors.scss').write_text('custom palette')
            (root / 'disabled').touch()
            (root / 'obsolete-interface-file').write_text('remove me')
            profile = root / 'state/chromium-ctf'
            profile.mkdir(parents=True)
            (profile / 'keep').write_text('profile data')
            with patch.object(p.shutil, 'which', return_value='/usr/bin/mock'), patch.object(p, 'HOME', home), patch.object(p, 'BACKUP', home / 'backup'), patch.object(p.sys, 'argv', ['pendash.py', '--update-dashboard']), patch.object(p, 'install_packages') as packages, patch.object(p, 'dashboard_enabled') as enable:
                self.assertEqual(p.main(), 0)
            for mock in (packages, enable):
                mock.assert_not_called()
            self.assertEqual((root / 'colors.scss').read_text(), 'custom palette')
            self.assertEqual(json.loads((root / 'browser.json').read_text())['browser'], 'chromium')
            self.assertEqual((profile / 'keep').read_text(), 'profile data')
            self.assertTrue((root / 'disabled').exists())
            self.assertFalse((root / 'obsolete-interface-file').exists())
            self.assertIn('defwindow', (root / 'eww.yuck').read_text())

    def test_managed_lua_block_is_idempotent_and_preserves_user_content(self):
        block = (REPO / 'assets/custom.lua').read_text()
        first = p.replace_block('-- user setting\n', block)
        second = p.replace_block(first, block)
        self.assertEqual(first, second)
        self.assertIn('-- user setting', first)
        self.assertEqual(first.count(p.BEGIN), 1)

    def test_browser_controller_uses_single_launcher(self):
        text = (REPO / 'dashboard/scripts/ctf-control.py').read_text()
        self.assertIn("HOME / '.local/bin/ctf-chromium'", text)
        self.assertNotIn('--user-data-dir', text)
        self.assertNotIn('firefox', text)

    def test_dashboard_keeps_adaptive_and_hidden_polling(self):
        yuck = (REPO / 'dashboard/eww.yuck').read_text()
        self.assertIn(':run-while home_visible', yuck)
        self.assertIn('adaptive-run.py cpu 2 15', yuck)
        self.assertIn('LAPTOP POWER', yuck)
        self.assertIn('START WEB CTF', yuck)


if __name__ == '__main__':
    unittest.main()
