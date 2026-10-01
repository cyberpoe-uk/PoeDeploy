import importlib.util
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import burp_ca as ca


class CertificateTests(unittest.TestCase):
    def test_real_nss_import_repeat_replace_remove_and_consent(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            db = home / '.local/share/pki/nssdb'
            def generate(name, is_ca=True):
                pem = home / (name + '.pem')
                subprocess.run(['openssl', 'req', '-x509', '-newkey', 'rsa:2048', '-nodes',
                    '-keyout', str(home / (name + '.key')), '-out', str(pem), '-days', '1',
                    '-subj', '/CN=' + name, '-addext', 'basicConstraints=critical,CA:' + ('TRUE' if is_ca else 'FALSE')],
                    check=True, capture_output=True)
                return pem
            first, second = generate('first'), generate('second')
            with patch.object(ca, 'database', return_value=db), patch.object(ca, 'confirm', return_value=False):
                ca.main('import', first)
                self.assertFalse(db.exists())
            with patch.object(ca, 'database', return_value=db), patch.object(ca, 'confirm', return_value=True) as consent:
                ca.main('import', first)
                self.assertEqual(ca.current(db)[3], 'C,,')
                consent.reset_mock()
                ca.main('import', first)
                consent.assert_not_called()
                ca.main('import', second)
                self.assertEqual(ca.current(db)[1], ca.certificate(second.read_bytes())[1])
                ca.main('remove')
                self.assertIsNone(ca.current(db))
            with self.assertRaises(RuntimeError):
                ca.certificate(generate('leaf', False).read_bytes())

    def test_database_legacy_and_version_rules(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(ca.Path, 'home', return_value=Path(tmp)):
            with patch.object(ca, 'execute', return_value=type('Result', (), {'stdout': 'Chromium 146.0'})()):
                self.assertEqual(ca.database(), Path(tmp) / '.local/share/pki/nssdb')
            legacy = Path(tmp) / '.pki/nssdb'
            legacy.mkdir(parents=True)
            self.assertEqual(ca.database(), legacy)

    def test_launcher_url_and_fail_closed_contract(self):
        text = (ROOT / 'assets/ctf-chromium').read_text()
        self.assertIn('socket.create_connection', text)
        self.assertIn('--proxy-bypass-list="<-loopback>"', text)
        self.assertNotIn('--user-data-dir', text)
        self.assertNotIn('--ignore-certificate-errors', text)
        self.assertIn('--new-window "$@"', text)


class IntegrationTests(unittest.TestCase):
    def test_install_twice_preserves_browser_data_and_unrelated_flags(self):
        import pendash as p
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            flags = home / '.config/chromium-flags.conf'
            flags.parent.mkdir()
            flags.write_text('--enable-features=Example\n--proxy-server=http://old:9999\n')
            cookies = home / '.config/chromium/Default/Cookies'
            cookies.parent.mkdir(parents=True)
            cookies.write_bytes(b'keep existing cookies')
            with patch.object(p, 'HOME', home), patch.object(p, 'BACKUP', home / 'backups'):
                p.install_browser(False)
                first = flags.read_text()
                p.install_browser(False)
            self.assertEqual(first, flags.read_text())
            self.assertIn('--enable-features=Example', first)
            self.assertEqual(first.count('--proxy-server='), 1)
            self.assertEqual(cookies.read_bytes(), b'keep existing cookies')
            self.assertTrue((home / '.local/bin/ctf-chromium').stat().st_mode & 0o111)

    def test_saved_target_passed_after_burp_and_listener_ready(self):
        spec = importlib.util.spec_from_file_location('ctf', ROOT / 'dashboard/scripts/ctf-control.py')
        control = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(control)
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            with patch.object(control, 'STATE', home / 'state'), patch.object(control, 'CACHE', home / 'cache'), \
                 patch.object(control, 'ensure') as ensure, patch.object(control, 'dispatch'), \
                 patch('socket.create_connection'):
                target = 'https://example.test/path?x=1&y=$(touch bad)'  # whitespace is forbidden
                with self.assertRaises(ValueError):
                    control.save_target(target)
                target = 'https://example.test/path?x=1&y=2'
                control.save_target(target)
                self.assertEqual(control.read_target(), target)
                self.assertEqual(control.launch('web-ctf'), 0)
                self.assertEqual(ensure.call_args_list[0].args, ('burp',))
                self.assertEqual(ensure.call_args_list[1].kwargs['target'], target)
