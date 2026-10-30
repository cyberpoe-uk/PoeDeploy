"""State and logging tests for the static installer dashboard."""

from pathlib import Path
import errno
import os
import pty
import select
import signal
import termios
import time
import unittest

from test_workflows import PRELUDE, SCRIPT, run_bash


class DashboardStateTests(unittest.TestCase):
    def check(self, body):
        result = run_bash(body)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        return result.stdout + result.stderr

    def check_pty(self, body, replies):
        pid, fd = pty.fork()
        if pid == 0:
            os.environ['TERM'] = 'xterm-256color'
            os.environ.pop('NO_COLOR', None)
            termios.tcsetwinsize(0, (28, 100))
            os.execvp('bash', ['bash', '--noprofile', '--norc', '-c',
                              PRELUDE + body, 'test', SCRIPT])
        output = b''
        done = 0
        position = 0
        deadline = time.monotonic() + 15
        try:
            while time.monotonic() < deadline:
                if select.select([fd], [], [], 0.05)[0]:
                    try:
                        output += os.read(fd, 8192)
                    except OSError as exc:
                        if exc.errno != errno.EIO:
                            raise
                if replies and replies[0][0] in output[position:]:
                    marker, answer = replies.pop(0)
                    position = output.index(marker, position) + len(marker)
                    # Slowly type: a competing dashboard reader used to steal
                    # individual password characters, including its L/Q keys.
                    for value in answer:
                        os.write(fd, bytes([value]))
                        time.sleep(0.03)
                done, status = os.waitpid(pid, os.WNOHANG)
                if done:
                    break
            self.assertTrue(done, output)
            self.assertEqual(os.waitstatus_to_exitcode(status), 0, output)
            self.assertFalse(replies, output)
            self.assertIn(b'PTY_REGRESSION_DONE', output)
            return output
        finally:
            if not done:
                os.killpg(pid, signal.SIGTERM)
                os.waitpid(pid, 0)
            os.close(fd)

    def test_utf8_rows_have_equal_width_and_colour_does_not_change_padding(self):
        output = self.check(r'''
export LC_ALL=C.UTF-8
_pd_set_glyphs
NC=$'\033[0m'
BLUE=$'\033[34m'
_pd_row '████░░  50%' 24
_pd_row '→ Applications' 24 "$BLUE"
''')
        import re
        rows = re.sub(r'\x1b\[[0-9;]*m', '', output).splitlines()
        self.assertEqual([len(row) for row in rows], [28, 28])
        self.assertIn('\x1b[34m', output)

    def test_chroot_probe_permission_denied_is_quiet_and_not_positive(self):
        output = self.check(r'''
systemd-detect-virt() { echo 'Failed to check for chroot() environment: Permission denied' >&2; return 1; }
stat() { return 1; }
POEDEPLOY_IN_CHROOT=true
detect_chroot
[[ "$POEDEPLOY_IN_CHROOT" == false ]]
echo CHROOT_CHECK_DONE
''')
        self.assertEqual(output.strip(), 'CHROOT_CHECK_DONE')

    def test_sudo_retry_and_followup_prompt_keep_exclusive_keyboard_access(self):
        output = self.check_pty(r'''
fixture_dir=$(mktemp -d)
cat >"$fixture_dir/sudo" <<'SH'
#!/usr/bin/env bash
if [[ "$1" == -n ]]; then exit 1; fi
if [[ "$1" == -v ]]; then
    printf 'FIXTURE_PASSWORD: ' >&2
    IFS= read -rs answer
    printf '\n' >&2
    if [[ "$answer" != Lq-tests-123 ]]; then
        printf 'Sorry, try again.\nFIXTURE_RETRY: ' >&2
        IFS= read -rs answer
        printf '\n' >&2
    fi
    [[ "$answer" == Lq-tests-123 ]]
    exit $?
fi
printf 'FIXTURE_COMMAND_PASSWORD: ' >/dev/tty
IFS= read -rs answer </dev/tty
printf '\n' >/dev/tty
[[ "$answer" == Lq-tests-123 ]] || exit 19
printf 'PRIVILEGED_FIXTURE_DONE\n'
SH
chmod +x "$fixture_dir/sudo"
PATH="$fixture_dir:$PATH"
check_not_root
POEDEPLOY_LOG="$fixture_dir/install.log"
touch "$POEDEPLOY_LOG"
run_setup_module() {
    sudo harmless-fixture
    ui_prompt answer 'VISIBLE_QUESTION: '
    [[ "$answer" == yes ]]
}
initialise_ui
ui_progress_init 'Authentication fixture'
ui_dashboard_start
run_dashboard_stage fixture 1 'Authentication fixture'
ui_complete
ui_cleanup 0
grep -q PRIVILEGED_FIXTURE_DONE "$POEDEPLOY_LOG"
if grep -Eq 'FIXTURE_PASSWORD|FIXTURE_RETRY|Lq-tests-123' "$POEDEPLOY_LOG"; then exit 93; fi
rm -rf -- "$fixture_dir"
echo PTY_REGRESSION_DONE
''', [(b'FIXTURE_PASSWORD: ', b'wrong\n'),
      (b'FIXTURE_RETRY: ', b'Lq-tests-123\n'),
      (b'FIXTURE_COMMAND_PASSWORD: ', b'Lq-tests-123\n'),
      (b'VISIBLE_QUESTION: ', b'yes\n')])
        self.assertIn(b'Sorry, try again.', output)
        self.assertNotIn(b'Lq-tests-123', output)
        self.assertIn(b'\x1b[38;2;0;79;254m', output)

    def test_external_installer_prompt_and_failure_restore_dashboard(self):
        self.check_pty(r'''
POEDEPLOY_LOG=$(mktemp)
run_setup_module() {
    if ui_run_interactive bash -c '
        printf "NESTED_PASSWORD: " >&2
        IFS= read -rs answer
        printf "\n" >&2
        [[ "$answer" == Lq-tests-123 ]] || exit 19
        exit 42
    '; then exit 94; else status=$?; fi
    [[ "$status" == 42 ]]
    ui_prompt answer 'RESTORED_QUESTION: '
    [[ "$answer" == yes ]]
}
ui_progress_init 'External installer fixture'
ui_dashboard_start
run_dashboard_stage fixture 1 'External installer fixture'
ui_complete
ui_cleanup 0
rm -f -- "$POEDEPLOY_LOG"
echo PTY_REGRESSION_DONE
''', [(b'NESTED_PASSWORD: ', b'Lq-tests-123\n'),
      (b'RESTORED_QUESTION: ', b'yes\n')])

    def test_progress_is_stage_based_and_state_is_central(self):
        self.check(r'''
PD_UI_ACTIVE=true
PD_UI_DIR=$(mktemp -d)
POEDEPLOY_LOG="$PD_UI_DIR/install.log"
ui_progress_init 'Base system' 'Applications' 'Secure Boot'
ui_step_start 1 'Base system'
ui_set_operation 'Installing packages'
ui_step_complete 1
grep -Fx 'completed=1' "$PD_UI_DIR/state"
grep -Fx 'total=3' "$PD_UI_DIR/state"
grep -Fx 'operation=Completed Base system' "$PD_UI_DIR/state"
grep -Fx 'item=complete|Base system' "$PD_UI_DIR/state"
grep -Fx 'item=pending|Secure Boot' "$PD_UI_DIR/state"
rm -rf -- "$PD_UI_DIR"
''')

    def test_run_cmd_logs_output_without_printing_it(self):
        output = self.check(r'''
PD_UI_ACTIVE=false
POEDEPLOY_LOG=$(mktemp)
captured=$(run_cmd 'Harmless command' bash -c 'echo command-output; echo diagnostic >&2')
[[ -z "$captured" ]]
grep -F 'command-output' "$POEDEPLOY_LOG"
grep -F 'diagnostic' "$POEDEPLOY_LOG"
rm -f -- "$POEDEPLOY_LOG"
''')
        self.assertIn('command-output', output)

    def test_all_runtime_components_are_shipped(self):
        root = Path(__file__).resolve().parents[1]
        expected = [
            'ui/logger.sh', 'ui/progress.sh', 'ui/keyboard.sh',
            'ui/dashboard.sh', 'installer/applications.sh',
        ]
        for relative in expected:
            self.assertTrue((root / relative).is_file(), relative)

    def test_dashboard_installers_are_fully_bundled(self):
        root = Path(__file__).resolve().parents[1]
        expected = [
            'apps/poedash/install.sh', 'apps/poedash/poedash.py',
            'apps/poedash/assets/templates/eww.yuck',
            'apps/poedash/assets/scripts/DashboardModule.qml',
            'apps/poedash/assets/scripts/dashboard-control.py',
            'apps/pendash/install.sh', 'apps/pendash/pendash.py',
            'apps/pendash/dashboard/eww.yuck', 'apps/pendash/assets/custom.lua',
            'apps/pendash/dashboard/scripts/DashboardModule.qml',
            'apps/pendash/dashboard/scripts/dashboard-control.py',
        ]
        for relative in expected:
            self.assertTrue((root / relative).is_file(), relative)
        installer = (root / 'installer/applications.sh').read_text()
        self.assertNotIn('cyberpoe.uk', installer)
        self.assertNotIn('github.com', installer)
        self.assertNotIn('curl ', installer)
        poe_controls = (root / 'apps/poedash/assets/scripts/DashboardModule.qml').read_text()
        pen_controls = (root / 'apps/pendash/dashboard/scripts/DashboardModule.qml').read_text()
        for controls in (poe_controls, pen_controls):
            self.assertIn('󰍹', controls)
            self.assertIn('󰶐', controls)
            self.assertIn('Quickshell.execDetached', controls)

    def test_live_log_switch_and_terminal_cleanup_in_a_real_pty(self):
        pid, fd = pty.fork()
        if pid == 0:
            os.environ['TERM'] = 'xterm-256color'
            termios.tcsetwinsize(0, (28, 100))
            body = PRELUDE + r'''
POEDEPLOY_LOG=$(mktemp)
run_setup_module() {
    info 'Running harmless fixture'
    echo 'FIXTURE_LOG_LINE'
    sleep 1
}
ui_progress_init 'Harmless fixture'
ui_dashboard_start
run_dashboard_stage fixture 1 'Harmless fixture'
ui_complete
ui_cleanup 0
echo PTY_DASHBOARD_DONE
rm -f -- "$POEDEPLOY_LOG"
'''
            os.execvp('bash', ['bash', '--noprofile', '--norc', '-c', body, 'test', SCRIPT])

        output = b''
        done = 0
        opened_log = False
        returned = False
        deadline = time.monotonic() + 10
        try:
            while time.monotonic() < deadline:
                if select.select([fd], [], [], 0.05)[0]:
                    try:
                        output += os.read(fd, 8192)
                    except OSError as exc:
                        if exc.errno != errno.EIO:
                            raise
                if not opened_log and b'POEDEPLOY' in output:
                    os.write(fd, b'L')
                    opened_log = True
                if opened_log and not returned and b'POEDEPLOY LIVE LOG' in output:
                    os.write(fd, b'q')
                    returned = True
                done, status = os.waitpid(pid, os.WNOHANG)
                if done:
                    break
            self.assertTrue(done, output)
            self.assertEqual(os.waitstatus_to_exitcode(status), 0, output)
            self.assertIn(b'POEDEPLOY LIVE LOG', output)
            self.assertIn(b'PTY_DASHBOARD_DONE', output)
            self.assertIn(b'\x1b[?25h', output)
        finally:
            if not done:
                os.killpg(pid, signal.SIGTERM)
                os.waitpid(pid, 0)
            os.close(fd)
