"""Optional-app planning and real keyboard tests; no system changes."""
import errno
import os
import pty
import select
import shutil
import signal
import termios
import time
import unittest
from test_workflows import PRELUDE, SCRIPT, run_bash


class OptionalAppsAndThemes(unittest.TestCase):
    def check(self, body):
        result = run_bash(body)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        return result.stdout

    def test_proton_is_opt_in_and_uses_arch_packages(self):
        self.check(r'''
gum() { :; }
choose_checklist() {
    [[ -z "$2" ]] || exit 90
    options=$(cat)
    [[ "$options" == *'Proton VPN'* ]] || exit 91
    echo 'Proton VPN'
}
select_applications
[[ "${SELECTED_PACKAGES[*]}" == 'proton-vpn-gtk-app networkmanager gnome-keyring' ]]
pacman() { [[ "$1" == -Si ]]; }
yay() { exit 92; }
install_optional_package() {
    local package="$1"; shift
    [[ "$*" == "sudo pacman -S --needed --noconfirm $package" ]] || exit 93
    INSTALLED_PACKAGES+=("$package")
}
install_selected_applications
[[ ${#INSTALLED_PACKAGES[@]} == 3 ]]
''')

    def test_plymouth_cancellation_ignores_partial_output(self):
        self.check(r'''
can_use_checklist() { return 0; }
get_remote_plymouth_themes() { echo poedeploy; }
plymouth-set-default-theme() { echo spinner; }
gum() { echo 'PoeDeploy (PoeDeploy theme)'; return 130; }
install_remote_plymouth_theme() { exit 91; }
if select_plymouth_theme; then exit 92; fi
''')

    def test_remote_theme_is_installed_before_apply(self):
        self.check(r'''
can_use_checklist() { return 0; }
get_remote_plymouth_themes() { echo poedeploy; }
plymouth-set-default-theme() { echo spinner; }
gum() { echo 'PoeDeploy (PoeDeploy theme)'; }
plymouth_theme_is_available() { return 1; }
events=()
install_remote_plymouth_theme() { events+=("install:$1"); }
sudo() { events+=("$*"); }
select_plymouth_theme
[[ "${events[*]}" == 'install:poedeploy plymouth-set-default-theme poedeploy' ]]
''')

    def test_keep_current_does_not_apply_a_theme(self):
        self.check(r'''
can_use_checklist() { return 0; }
get_remote_plymouth_themes() { :; }
plymouth-set-default-theme() { echo spinner; }
gum() { echo 'Keep current theme'; }
select_plymouth_theme
''')


@unittest.skipUnless(shutil.which('gum'), 'gum required for keyboard test')
class PlymouthKeyboard(unittest.TestCase):
    def test_navigation_and_cancellation(self):
        cases = [
            ([b'\x1b[B', b'\r'], b'APPLIED:theme01'),
            ([b'j', b'j', b'k', b'\r'], b'APPLIED:theme01'),
            ([b'l', b'\r'], b'APPLIED:theme12'),
            ([b'l', b'h', b'j', b'\r'], b'APPLIED:theme01'),
            ([b'j', b'g', b'\r'], b'Keeping current Plymouth theme.'),
            ([b'G', b'\r'], b'APPLIED:theme14'),
            ([b'\x1b[C', b'\x1b[D', b'\x1b[B', b'\r'], b'APPLIED:theme01'),
            ([b'\x1b'], b'CANCELLED'),
            ([b'\x03'], b'CANCELLED'),
        ]
        for keys, expected in cases:
            with self.subTest(keys=keys):
                pid, fd = pty.fork()
                if pid == 0:
                    os.environ['TERM'] = 'xterm-256color'
                    termios.tcsetwinsize(0, (30, 100))
                    body = PRELUDE + r'''
get_remote_plymouth_themes() { :; }
plymouth-set-default-theme() {
    if [[ "${1:-}" == -l ]]; then printf 'theme%02d\n' {1..14}; else echo theme01; fi
}
sudo() { [[ "$1" == plymouth-set-default-theme ]] || exit 97; echo "APPLIED:$2"; }
if select_plymouth_theme; then echo DONE; else echo CANCELLED; fi
'''
                    os.execvp('bash', ['bash', '--noprofile', '--norc', '-c', body, 'test', SCRIPT])
                output = b''
                done = 0
                sent = False
                deadline = time.monotonic() + 8
                try:
                    while time.monotonic() < deadline:
                        if select.select([fd], [], [], 0.05)[0]:
                            try:
                                output += os.read(fd, 8192)
                            except OSError as exc:
                                if exc.errno != errno.EIO:
                                    raise
                        if not sent and b'Select Plymouth theme' in output:
                            for key in keys:
                                os.write(fd, key)
                                time.sleep(0.1)
                            sent = True
                        done, status = os.waitpid(pid, os.WNOHANG)
                        if done:
                            while select.select([fd], [], [], 0.05)[0]:
                                try:
                                    chunk = os.read(fd, 8192)
                                except OSError:
                                    break
                                if not chunk:
                                    break
                                output += chunk
                            break
                    self.assertTrue(done, output)
                    self.assertEqual(os.waitstatus_to_exitcode(status), 0, output)
                    self.assertIn(expected, output)
                    if expected == b'CANCELLED' or b'Keeping' in expected:
                        self.assertNotIn(b'APPLIED:', output)
                finally:
                    if not done:
                        os.killpg(pid, signal.SIGTERM)
                        os.waitpid(pid, 0)
                    os.close(fd)
