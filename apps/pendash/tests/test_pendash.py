import importlib.util
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('pendash', REPO / 'pendash.py')
p = importlib.util.module_from_spec(spec)
spec.loader.exec_module(p)


class InstallerTests(unittest.TestCase):
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
            with patch.object(p.shutil, 'which', return_value='/usr/bin/mock'), patch.object(p, 'HOME', home), patch.object(p, 'BACKUP', home / 'backup'), patch.object(p.sys, 'argv', ['pendash.py', '--update-dashboard']), patch.object(p, 'install_packages') as packages, patch.object(p, 'install_power') as power, patch.object(p, 'install_burp') as burp, patch.object(p, 'nvidia') as nvidia, patch.object(p, 'dashboard_enabled') as enable:
                self.assertEqual(p.main(), 0)
            for mock in (packages, power, burp, nvidia, enable):
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

    def test_complete_group_size_preview_uses_repository_metadata(self):
        records = {
            'one': {'GROUPS': ['blackarch'], 'CSIZE': ['100'], 'ISIZE': ['250']},
            'two': {'GROUPS': ['blackarch', 'blackarch-webapp'], 'CSIZE': ['50'], 'ISIZE': ['75']},
            'desktop': {'GROUPS': [], 'CSIZE': ['20'], 'ISIZE': ['30']},
        }
        with patch.object(p, 'sync_records', return_value=records):
            self.assertEqual(p.group_packages(['blackarch']), ['one', 'two'])
            self.assertEqual(p.group_packages(['blackarch-webapp']), ['two'])
            self.assertEqual(p.package_sizes(['one', 'two']), (2, 150, 325))

    def test_blackarch_plan_always_excludes_burp(self):
        args = SimpleNamespace(tool_mode='all', non_interactive=True, dry_run=False,
            browser='chromium', categories=None, yes_all_tools=True)
        with patch.object(p, 'ensure_blackarch'), \
             patch.object(p, 'group_packages', return_value=['burpsuite', 'ffuf', 'tailscale', 'proton-vpn-gtk-app']), \
             patch.object(p, 'package_sizes', return_value=(1, 10, 20)):
            packages = p.package_plan(args, args.browser)
        self.assertNotIn('burpsuite', packages)
        self.assertNotIn('tailscale', packages)
        self.assertNotIn('proton-vpn-gtk-app', packages)
        self.assertIn('ffuf', packages)

    def test_interactive_browser_is_used_by_curated_package_plan(self):
        args = SimpleNamespace(tool_mode='curated', non_interactive=False,
            dry_run=False, browser=None, categories=None, yes_all_tools=False)
        with patch.object(p, 'ensure_blackarch'), \
             patch.object(p, 'package_sizes', return_value=(1, 10, 20)):
            packages = p.package_plan(args, 'chromium')
        self.assertIn('chromium', packages)
        self.assertNotIn(None, packages)
        self.assertNotIn('tailscale', packages)

    def test_dashboard_only_skips_full_laptop_setup(self):
        argv = ['pendash.py', '--dashboard-only', '--non-interactive']
        with patch.object(p.sys, 'argv', argv), \
             patch.object(p.os, 'geteuid', return_value=1000), \
             patch.object(p, 'install_packages') as packages, \
             patch.object(p, 'offer_ca'), \
             patch.object(p, 'install_dashboard') as dashboard, \
             patch.object(p, 'ensure_blackarch') as blackarch, \
             patch.object(p, 'install_burp') as burp, \
             patch.object(p, 'install_power') as power, \
             patch.object(p, 'nvidia') as nvidia:
            self.assertEqual(p.main(), 0)
        packages.assert_called_once()
        self.assertIn('chromium', packages.call_args.args[0])
        dashboard.assert_called_once_with('chromium', False)
        for skipped in (blackarch, burp, power, nvidia):
            skipped.assert_not_called()

    def test_known_portswigger_installer_checksum(self):
        self.assertIn('product=desktop', p.BURP_DOWNLOAD_URL)
        self.assertEqual(
            p.KNOWN_BURP_SHA256['burpsuite_linux_v2026_8.sh'],
            'a9b71d5903e4aac00b790a7c5a0c0630fdcbfe1250aafd7bd540a3ad44b89983')

    def test_browser_controller_uses_single_launcher(self):
        text = (REPO / 'dashboard/scripts/ctf-control.py').read_text()
        self.assertIn("HOME / '.local/bin/ctf-chromium'", text)
        self.assertNotIn('--user-data-dir', text)
        self.assertNotIn('firefox', text)

    def test_idle_policy_matches_requested_ac_and_battery_times(self):
        text = (REPO / 'assets/hypridle.conf').read_text()
        self.assertEqual(text.count('timeout = 60\n'), 1)
        self.assertEqual(text.count('timeout = 300\n'), 1)
        self.assertEqual(text.count('timeout = 600\n'), 1)
        self.assertEqual(text.count('timeout = 3600\n'), 1)
        action = (REPO / 'assets/pendash-idle-action').read_text()
        self.assertIn('$on_ac || hyprctl', action)
        self.assertIn('systemctl suspend', action)

    def test_pendash_retires_visual_profile_switching(self):
        source = (REPO / 'pendash.py').read_text()
        self.assertIn("disable', '--now', 'hyprmod-power-watch.service'", source)
        watcher = (REPO / 'assets/pendash-power-watch.py').read_text()
        self.assertIn("profile = 'balanced' if online else 'power-saver'", watcher)
        self.assertNotIn('hyprmod', watcher.lower())

    def test_laptop_dashboard_keeps_adaptive_and_hidden_polling(self):
        yuck = (REPO / 'dashboard/eww.yuck').read_text()
        self.assertIn(':run-while home_visible', yuck)
        self.assertIn('adaptive-run.py cpu 2 15', yuck)
        self.assertIn('LAPTOP POWER', yuck)
        self.assertIn('START WEB CTF', yuck)


if __name__ == '__main__':
    unittest.main()
