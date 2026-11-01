import importlib.util
import hashlib
import io
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
from unittest.mock import MagicMock

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
spec = importlib.util.spec_from_file_location('pendash', REPO / 'pendash.py')
p = importlib.util.module_from_spec(spec)
spec.loader.exec_module(p)


class InstallerTests(unittest.TestCase):
    def test_pendash_restores_curated_tools_and_keeps_chromium(self):
        for options in ([], ['--non-interactive']):
            with self.subTest(options=options), \
                 patch.object(p.sys, 'argv', ['pendash.py', *options]), \
                 patch.object(p.os, 'geteuid', return_value=1000), \
                 patch.object(p, 'ensure_blackarch') as repository, \
                 patch.object(p, 'install_packages') as packages, \
                 patch.object(p, 'install_dashboard') as dashboard, \
                 patch.object(p, 'run') as command:
                self.assertEqual(p.main(), 0)
                repository.assert_called_once_with(False)
                packages.assert_called_once()
                selected = packages.call_args.args[0]
                self.assertTrue({'chromium', 'burpsuite', 'ffuf', 'gobuster', 'nmap',
                                 'sqlmap', 'wfuzz', 'wireshark-qt', 'jwt-tool'}.issubset(selected))
                self.assertFalse(set(selected).intersection({
                    'nvidia-prime', 'hypridle', 'hyprlock', 'power-profiles-daemon',
                    'tailscale', 'proton-vpn-gtk-app', 'blackarch',
                }))
                dashboard.assert_called_once_with(False)
                command.assert_not_called()

    def test_retired_system_setup_flags_are_rejected_before_installation(self):
        for options in (['--tool-mode', 'all'], ['--skip-nvidia'], ['--burp-installer', '/tmp/installer.sh'], ['setup-burp-ca']):
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

    def test_check_reports_missing_tools_without_modifying_the_system(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            dashboard = home / '.config/eww/eww.yuck'
            dashboard.parent.mkdir(parents=True)
            dashboard.touch()
            with patch.object(p, 'HOME', home), \
                 patch.object(p.os, 'geteuid', return_value=1000), \
                 patch.object(p.sys, 'argv', ['pendash.py', '--check']), \
                 patch.object(p.subprocess, 'check_output', return_value='\n'.join(p.CURATED + ['chromium'])), \
                 patch.object(p, 'run') as command:
                self.assertEqual(p.main(), 0)
                dashboard.unlink()
                self.assertEqual(p.main(), 2)
                command.assert_not_called()

    def test_dashboard_update_preserves_user_data_without_packages_or_repositories(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            root = home / '.config/eww'
            root.mkdir(parents=True)
            (root / 'eww.yuck').write_text('old')
            (root / 'browser.json').write_text('{"browser": "chromium"}')
            (root / 'colors.scss').write_text('custom palette')
            (root / 'disabled').touch()
            (root / 'layout.json').write_text('{"density":"comfortable"}')
            flags = home / '.config/chromium-flags.conf'
            flags.write_text('--proxy-server=http://manual:9999\n--custom-option\n')
            cookies = home / '.config/chromium/Default/Cookies'
            cookies.parent.mkdir(parents=True)
            cookies.write_bytes(b'keep cookies')
            (root / 'obsolete-interface-file').write_text('remove me')
            profile = root / 'state/chromium-ctf'
            profile.mkdir(parents=True)
            (profile / 'keep').write_text('profile data')
            with patch.dict(os.environ, {'XDG_CONFIG_HOME': str(home / '.config')}), patch.object(p.shutil, 'which', return_value='/usr/bin/mock'), patch.object(p, 'HOME', home), patch.object(p, 'BACKUP', home / 'backup'), patch.object(p.sys, 'argv', ['pendash.py', '--update-dashboard']), patch.object(p, 'ensure_blackarch') as repository, patch.object(p, 'install_packages') as packages, patch.object(p, 'dashboard_enabled') as enable:
                self.assertEqual(p.main(), 0)
            repository.assert_not_called()
            packages.assert_not_called()
            self.assertEqual((home / '.config/poedeploy/dashboard').read_text(), 'pendash\n')
            enable.assert_not_called()
            self.assertEqual((root / 'colors.scss').read_text(), 'custom palette')
            self.assertFalse((root / 'browser.json').exists())
            self.assertEqual(flags.read_text(), '--proxy-server=http://manual:9999\n--custom-option\n')
            self.assertEqual(cookies.read_bytes(), b'keep cookies')
            self.assertEqual((profile / 'keep').read_text(), 'profile data')
            self.assertTrue((root / 'disabled').exists())
            self.assertEqual((root / 'layout.json').read_text(), '{"density":"comfortable"}')
            self.assertFalse((root / 'obsolete-interface-file').exists())
            self.assertIn('defwindow', (root / 'eww.yuck').read_text())
            for name in ('layout.py', 'media.py', 'media-control.sh', 'system-info.py', 'processes.py', 'shares.py'):
                self.assertTrue((root / 'scripts' / name).stat().st_mode & 0o111)
            for name in ('ctf-control.py', 'ctf-status.sh', 'target.sh', 'launch-app.sh'):
                self.assertFalse((root / 'scripts' / name).exists())

    def test_managed_lua_block_is_idempotent_and_preserves_user_content(self):
        block = (REPO / 'assets/custom.lua').read_text()
        first = p.replace_block('-- user setting\n', block)
        second = p.replace_block(first, block)
        self.assertEqual(first, second)
        self.assertIn('-- user setting', first)
        self.assertEqual(first.count(p.BEGIN), 1)

    def test_repository_bootstrap_checks_checksum_and_cleans_up(self):
        script = b'#!/bin/sh\n# harmless bootstrap fixture\n'
        digest = hashlib.sha1(script).hexdigest()
        for checksum, succeeds in ((digest, True), ('0' * 40, False)):
            with self.subTest(checksum=checksum), tempfile.TemporaryDirectory() as tmp:
                config = Path(tmp) / 'pacman.conf'
                config.write_text('[core]\n')
                mirror = Path(tmp) / 'blackarch-mirrorlist'
                page = MagicMock()
                page.__enter__.return_value.read.return_value = f'echo {checksum} strap.sh | sha1sum -c'.encode()
                body = MagicMock()
                body.__enter__.return_value.read.return_value = script
                seen = []
                def execute(argv):
                    self.assertEqual(argv[:2], ['sudo', 'bash'])
                    self.assertEqual(argv[2].read_bytes(), script)
                    seen.append(argv[2])
                with patch.object(p, 'PACMAN_CONFIG', config), patch.object(p, 'BLACKARCH_MIRRORLIST', mirror), \
                     patch.object(p.urllib.request, 'urlopen', side_effect=[page, body]), patch.object(p, 'run', side_effect=execute) as command:
                    if succeeds:
                        p.ensure_blackarch(False)
                        command.assert_called_once()
                        self.assertFalse(seen[0].exists())
                    else:
                        with self.assertRaisesRegex(RuntimeError, 'checksum mismatch'):
                            p.ensure_blackarch(False)
                        command.assert_not_called()

    def test_existing_repository_and_dry_run_do_not_download_or_execute(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = Path(tmp) / 'pacman.conf'
            config.write_text('[blackarch]\nInclude = mirrorlist\n')
            mirror = Path(tmp) / 'blackarch-mirrorlist'
            mirror.touch()
            with patch.object(p, 'PACMAN_CONFIG', config), patch.object(p, 'BLACKARCH_MIRRORLIST', mirror), \
                 patch.object(p.urllib.request, 'urlopen') as network, patch.object(p, 'run') as command:
                p.ensure_blackarch(False)
                mirror.unlink()
                p.ensure_blackarch(True)
                network.assert_not_called()
                command.assert_not_called()

    def test_package_installation_adds_missing_tools_with_full_upgrade(self):
        with patch.object(p.subprocess, 'check_output', return_value='ffuf\nchromium\n'), \
             patch.object(p.shutil, 'which', return_value='/usr/bin/eww'), \
             patch.object(p, 'run') as command:
            p.install_packages(['burpsuite', 'ffuf', 'chromium'], False)
            command.assert_called_once_with(['sudo', 'pacman', '-Syu', '--needed', 'burpsuite'])

    def test_legacy_cleanup_is_backed_up_and_preserves_manual_settings(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            launcher = home / '.local/bin/ctf-chromium'
            launcher.parent.mkdir(parents=True)
            content = b'legacy generated launcher fixture\n'
            launcher.write_bytes(content)
            flags = home / '.config/chromium-flags.conf'
            flags.parent.mkdir()
            flags.write_text('--custom-option\n--proxy-server=http://127.0.0.1:8080\n--proxy-bypass-list=<-loopback>\n--proxy-server=http://manual:9999\n')
            flags.chmod(0o600)
            certificate = home / '.local/share/pki/nssdb/cert9.db'
            certificate.parent.mkdir(parents=True)
            certificate.write_bytes(b'keep trust store')
            backups = home / 'backups'
            with patch.object(p, 'HOME', home), patch.object(p, 'BACKUP', backups), \
                 patch.object(p, 'LEGACY_BROWSER_FILES', {'.local/bin/ctf-chromium': hashlib.sha256(content).hexdigest()}):
                p.cleanup_legacy_browser_setup()
                p.cleanup_legacy_browser_setup()
            self.assertFalse(launcher.exists())
            self.assertEqual(flags.read_text(), '--custom-option\n--proxy-server=http://manual:9999\n')
            self.assertEqual(flags.stat().st_mode & 0o777, 0o600)
            self.assertEqual(certificate.read_bytes(), b'keep trust store')
            self.assertTrue(list(backups.rglob('ctf-chromium')))
            self.assertTrue(list(backups.rglob('chromium-flags.conf')))

    def test_customised_launcher_and_flags_are_retained(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            launcher = home / '.local/bin/ctf-chromium'
            launcher.parent.mkdir(parents=True)
            launcher.write_bytes(b'user customised launcher')
            flags = home / '.config/chromium-flags.conf'
            flags.parent.mkdir()
            flags.write_text('--proxy-server=http://127.0.0.1:8080\n')
            with patch.object(p, 'HOME', home), patch.object(p, 'BACKUP', home / 'backups'):
                p.cleanup_legacy_browser_setup()
            self.assertEqual(launcher.read_bytes(), b'user customised launcher')
            self.assertEqual(flags.read_text(), '--proxy-server=http://127.0.0.1:8080\n')

    def test_dashboard_keeps_adaptive_and_hidden_polling(self):
        yuck = (REPO / 'dashboard/eww.yuck').read_text()
        self.assertIn(':run-while home_visible', yuck)
        self.assertIn('adaptive-run.py cpu 2 15', yuck)
        self.assertIn('LAPTOP POWER', yuck)
        for feature in ('CONNECTIVITY', 'Tailscale IP', 'SMB / NFS SHARES',
                        'SPECIFICATIONS', 'TOP PROCESSES', 'media.art', 'media-control.sh'):
            self.assertIn(feature, yuck)
        for removed in ('QUICK LAUNCH', 'START WEB CTF', 'ctf_status', 'ctf_target', 'launch-app.sh'):
            self.assertNotIn(removed, yuck)


if __name__ == '__main__':
    unittest.main()
