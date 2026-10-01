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
        self.assertIn('DASH ON', poe_controls)
        self.assertIn('DASH OFF', poe_controls)
        pen_controls = (root / 'apps/pendash/dashboard/scripts/DashboardModule.qml').read_text()
        self.assertIn('󰍹', pen_controls)
        self.assertIn('󰶐', pen_controls)
        for controls in (poe_controls, pen_controls):
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
