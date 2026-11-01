import importlib.util
import hashlib
import io
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch, MagicMock

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('security_tools', ROOT / 'installer/security-tools.py')
p = importlib.util.module_from_spec(spec)
spec.loader.exec_module(p)

def burp_download_page(checksum):
    return f'''<input id="CurrentVersion" value="2026.10.1">
        <a class="btn-download-small" data-type="Linux" data-build-id="123">Download</a>
        <a class="btn-download-small" data-type="LinuxArm64" data-build-id="124">Download</a>
        <div class="checksum-panel" data-build-id="123">
          <code class="hash-value sha-256-checksum">{checksum}</code></div>
        <div class="checksum-panel" data-build-id="124">
          <code class="hash-value sha-256-checksum">{'a' * 64}</code></div>'''

class OfficialBurpTests(unittest.TestCase):
    def test_download_uses_current_native_release_for_each_architecture(self):
        for arch, kind, checksum in (('x86_64', 'Linux', 'b' * 64),
                                     ('aarch64', 'LinuxArm64', 'a' * 64)):
            version, url, digest = p.burp_release(burp_download_page('b' * 64), arch)
            self.assertEqual(version, '2026.10.1')
            self.assertEqual(url, f'https://portswigger.net/burp/releases/download?product=desktop&version=2026.10.1&type={kind}')
            self.assertEqual(digest, checksum)

    def test_missing_metadata_or_unsupported_architecture_fails(self):
        for page, arch in (('', 'x86_64'), (burp_download_page(''), 'x86_64'),
                           (burp_download_page('b' * 64), 'i686')):
            with self.assertRaises(RuntimeError):
                p.burp_release(page, arch)

    def test_verified_download_installs_without_sudo_and_creates_launcher(self):
        script = b'#!/bin/sh\n# harmless official installer fixture\n'
        checksum = hashlib.sha256(script).hexdigest()
        with tempfile.TemporaryDirectory(prefix="burp user's home ") as tmp:
            home = Path(tmp)
            seen = []
            def install(argv):
                seen.append(argv)
                self.assertEqual(Path(argv[1]).read_bytes(), script)
                self.assertEqual(argv[2:4], ['-q', '-dir'])
                destination = Path(argv[4])
                destination.mkdir(parents=True)
                binary = destination / 'BurpSuite'
                binary.write_text('#!/bin/sh\nprintf "%s\\n" "$1"\n')
                binary.chmod(0o755)
            with patch.object(p, 'HOME', home), patch.object(p, 'BACKUP', home / 'backup'), \
                    patch.object(p, 'official_burp', return_value=None), \
                    patch.object(p.platform, 'machine', return_value='x86_64'), \
                    patch.object(p.urllib.request, 'urlopen', side_effect=[io.BytesIO(burp_download_page(checksum).encode()), io.BytesIO(script)]), \
                    patch.object(p, 'run', side_effect=install):
                p.install_burp(False)
            self.assertFalse(Path(seen[0][1]).exists())
            result = subprocess.run([home / '.local/bin/burpsuite', 'argument with spaces'], capture_output=True, text=True, check=True)
            self.assertEqual(result.stdout, 'argument with spaces\n')

    def test_corrupt_download_never_runs_or_writes_launcher(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(p, 'HOME', Path(tmp)), \
                patch.object(p, 'official_burp', return_value=None), \
                patch.object(p.platform, 'machine', return_value='x86_64'), \
                patch.object(p.urllib.request, 'urlopen', side_effect=[io.BytesIO(burp_download_page('0' * 64).encode()), io.BytesIO(b'corrupt')]), \
                patch.object(p, 'run') as command:
            with self.assertRaisesRegex(RuntimeError, 'SHA-256 mismatch'):
                p.install_burp(False)
            command.assert_not_called()
            self.assertFalse((Path(tmp) / '.local/bin/burpsuite').exists())

    def test_existing_native_install_and_dry_run_do_not_download(self):
        for existing, dry_run in ((Path('/existing/BurpSuite'), False), (None, True)):
            with patch.object(p, 'official_burp', return_value=existing), \
                    patch.object(p.urllib.request, 'urlopen') as network, patch.object(p, 'run') as command:
                p.install_burp(dry_run)
                network.assert_not_called()
                command.assert_not_called()

class InstallerTests(unittest.TestCase):
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
            p.install_packages(['nmap', 'ffuf', 'chromium'], False)
            command.assert_called_once_with(['sudo', 'pacman', '-Syu', '--needed', 'nmap'])

class ExistingNativeInstallation(unittest.TestCase):
    def test_native_burp_launcher_is_discovered_without_reinstallation(self):
        with tempfile.TemporaryDirectory(prefix='burp with spaces ') as tmp:
            home = Path(tmp)
            binary = home / 'previous-install/BurpSuite'
            binary.parent.mkdir()
            binary.write_text('#!/bin/sh\n')
            binary.chmod(0o755)
            launcher = home / '.local/bin/burpsuite'
            launcher.parent.mkdir(parents=True)
            import shlex
            launcher.write_text('#!/bin/sh\nexec ' + shlex.quote(str(binary)) + ' "$@"\n')
            with patch.object(p, 'HOME', home), patch.object(p.urllib.request, 'urlopen') as download:
                self.assertEqual(p.official_burp(), binary)
                p.install_burp(False)
                download.assert_not_called()

    def test_tool_installation_never_installs_dashboard_dependencies(self):
        with patch.object(p.subprocess, 'check_output', return_value=''), patch.object(p, 'run') as run:
            p.install_packages(['nmap'], False)
        run.assert_called_once_with(['sudo', 'pacman', '-Syu', '--needed', 'nmap'])
