"""Fingerprint workflow checks; no hardware or privileged changes."""
import importlib.util
from pathlib import Path
import tempfile
import unittest

from test_workflows import ROOT, run_bash

spec = importlib.util.spec_from_file_location('fingerprint_config', ROOT / 'installer/fingerprint_config.py')
config = importlib.util.module_from_spec(spec)
spec.loader.exec_module(config)

PAM = '''#%PAM-1.0
auth        include     system-login
-auth optional pam_gnome_keyring.so
account include system-login
session include system-login
password include system-login
'''


class FingerprintConfigTests(unittest.TestCase):
    def test_sddm_preserves_password_stack_and_restrictions(self):
        result = config.configured(PAM, 'sddm')
        self.assertIn('pam_fprintd.so max-tries=1 timeout=10', result)
        self.assertIn(PAM.split('\n', 1)[1], result)
        self.assertLess(result.index('pam_nologin.so'), result.index('pam_fprintd.so'))
        self.assertLess(result.index('pam_shells.so'), result.index('pam_fprintd.so'))
        self.assertEqual(config.configured(result, 'sddm'), result)

    def test_hyprlock_keeps_password_and_is_idempotent(self):
        result = config.configured('general {\n    ignore_empty_input = true\n}\n', 'hyprlock')
        self.assertIn('pam {\n        enabled = true', result)
        self.assertIn('fingerprint {\n        enabled = true', result)
        self.assertEqual(config.configured(result, 'hyprlock'), result)

    def test_refuses_custom_auth_and_broken_managed_blocks(self):
        for text, kind in [
            ('auth { pam { enabled = false } }', 'hyprlock'),
            ('auth sufficient pam_fprintd.so\n' + PAM, 'sddm'),
            ('auth sufficient custom.so', 'sddm'),
            (config.BEGIN + '\nunfinished', 'sddm'),
        ]:
            with self.subTest(text=text), self.assertRaises(ValueError):
                config.configured(text, kind)

    def test_backups_permissions_and_color_include(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'hyprlock.conf'
            original = 'source = colors.conf\ngeneral {}\n'
            path.write_text(original)
            path.chmod(0o640)
            (path.parent / 'colors.conf').write_text('$primary = rgba(ffffffff)\n')
            config.update(path, 'hyprlock')
            backups = list(path.parent.glob('*.backup-*'))
            self.assertEqual(len(backups), 1)
            self.assertEqual(backups[0].read_text(), original)
            self.assertEqual(path.stat().st_mode & 0o777, 0o640)
            config.update(path, 'hyprlock')
            self.assertEqual(len(list(path.parent.glob('*.backup-*'))), 1)

    def test_included_auth_is_not_overridden(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'hyprlock.conf'
            original = 'source = auth.conf\n'
            path.write_text(original)
            (path.parent / 'auth.conf').write_text('auth { pam { enabled = false } }\n')
            with self.assertRaises(ValueError):
                config.update(path, 'hyprlock')
            self.assertEqual(path.read_text(), original)
            self.assertFalse(list(path.parent.glob('*.backup-*')))


MOCKS = r'''
ui_heading() { :; }
ui_prompt() { printf -v "$1" '%s' "${answers[$answer_index]:-n}"; answer_index=$((answer_index + 1)); }
answer_index=0
fingerprint_uses_goodix_spi() { return 1; }
sudo() { printf 'SUDO:%s\n' "$*"; }
fprintd-list() { echo 'found 1 devices'; }
fprintd-verify() { echo 'Verify result: verify-match (done)'; }
'''


class FingerprintWorkflowTests(unittest.TestCase):
    def run_workflow(self, body):
        result = run_bash(MOCKS + body)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        return result.stdout

    def test_section_order_and_terminal_ownership(self):
        self.run_workflow(r'''
[[ "${SETUP_MODULE_IDS[*]}" == *'sddm fingerprint applications'* ]]
setup_module_needs_terminal fingerprint
setup_fingerprint() { echo DISPATCHED; }
run_setup_module fingerprint
''')

    def test_chroot_and_declined_setup_do_not_install(self):
        for body in ('POEDEPLOY_IN_CHROOT=true; answers=(y); setup_fingerprint',
                     'answers=(n); setup_fingerprint'):
            output = self.run_workflow(body)
            self.assertNotIn('SUDO:', output)

    def test_goodix_consent_and_complete_dependencies(self):
        output = self.run_workflow(r'''
fingerprint_uses_goodix_spi() { return 0; }
install_goodix_fingerprint_driver() { echo BUILT_GOODIX; }
answers=(y y n n)
setup_fingerprint
''')
        self.assertIn('BUILT_GOODIX', output)
        self.assertIn('glib2-devel', output)
        self.assertIn('libgpiod', output)
        self.assertNotIn('fingerprint_config.py', output)

    def test_declining_experimental_driver_does_not_install(self):
        output = self.run_workflow(r'''
fingerprint_uses_goodix_spi() { return 0; }
answers=(y n)
setup_fingerprint
''')
        self.assertNotIn('SUDO:', output)

    def test_no_device_does_not_enroll_or_enable_login(self):
        output = self.run_workflow(r'''
fprintd-list() { echo 'No devices available'; return 1; }
fprintd-enroll() { exit 98; }
answers=(y y y)
setup_fingerprint
''')
        self.assertIn('Login settings were not changed', output)
        self.assertNotIn('fingerprint_config.py', output)

    def test_zero_exit_without_match_never_enables_login(self):
        output = self.run_workflow(r'''
fprintd-verify() { echo 'Verify result: verify-no-match (done)'; }
answers=(y n y)
setup_fingerprint
''')
        self.assertIn('No successful fingerprint match', output)
        self.assertNotIn('fingerprint_config.py', output)

    def test_enrollment_failure_stops_before_login_changes(self):
        result = run_bash(MOCKS + r'''
ui_run_interactive() { "$@"; }
fprintd-enroll() { return 42; }
answers=(y y y)
setup_fingerprint
echo UNEXPECTED_CONTINUATION
''')
        self.assertEqual(result.returncode, 42, result.stdout + result.stderr)
        self.assertNotIn('fingerprint_config.py', result.stdout)
        self.assertNotIn('UNEXPECTED_CONTINUATION', result.stdout)

    def test_verified_match_can_enable_sddm_with_existing_print(self):
        output = self.run_workflow(r'''
HOME=$(mktemp -d)
answers=(y n y)
setup_fingerprint
rmdir "$HOME"
''')
        self.assertIn('verify-match (done)', output)
        self.assertIn('--sddm /etc/pam.d/sddm', output)
        self.assertNotIn('/etc/pam.d/system-auth', output)


if __name__ == '__main__':
    unittest.main()
