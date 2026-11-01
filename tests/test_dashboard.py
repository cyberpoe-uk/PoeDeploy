"""State and logging tests for the static installer dashboard."""

from pathlib import Path
import base64
import errno
import os
import pty
import re
import select
import signal
import shutil
import termios
import time
import unittest
import unicodedata

from test_workflows import PRELUDE, SCRIPT, run_bash


class DashboardStateTests(unittest.TestCase):
    def check(self, body):
        result = run_bash(body)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        return result.stdout + result.stderr

    def check_pty(self, body, replies, size=(28, 100), expected_exit=0):
        pid, fd = pty.fork()
        if pid == 0:
            os.environ['TERM'] = 'xterm-256color'
            os.environ.pop('NO_COLOR', None)
            termios.tcsetwinsize(0, size)
            os.execvp('bash', ['bash', '--noprofile', '--norc', '-c',
                              PRELUDE + body, 'test', SCRIPT])
        output = b''
        done = 0
        position = 0
        deadline = time.monotonic() + 25
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
                    while select.select([fd], [], [], 0.01)[0]:
                        try:
                            chunk = os.read(fd, 8192)
                        except OSError:
                            break
                        if not chunk:
                            break
                        output += chunk
                    break
            self.assertTrue(done, output)
            self.assertEqual(os.waitstatus_to_exitcode(status), expected_exit, output)
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
        rows = re.sub(r'\x1b\[[0-?]*[ -/]*[@-~]', '', output).splitlines()
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

    def test_prompt_eof_is_failure_for_visible_and_secret_input(self):
        self.check(r'''
for silent in false true; do
    response=old-value
    if ui_prompt response 'Prompt: ' "$silent" </dev/null; then exit 91; fi
    [[ -z "$response" ]]
done
''')

    def test_command_helpers_preserve_failures(self):
        self.check(r'''
POEDEPLOY_LOG=$(mktemp)
if run_cmd 'Failing command' bash -c 'exit 19'; then exit 91; else [[ $? == 19 ]]; fi
if run_cmd_capture result 'Failing capture' bash -c 'exit 23'; then exit 92; else [[ $? == 23 ]]; fi
grep -q 'exit code 19' "$POEDEPLOY_LOG"
grep -q 'exit code 23' "$POEDEPLOY_LOG"
rm -f -- "$POEDEPLOY_LOG"
''')

    def test_all_interactive_stages_keep_context_and_persist_results(self):
        output = self.check_pty(r'''
ensure_command_dependencies() { :; }
curl() {
    local output_path
    while (($#)); do
        if [[ "$1" == --output ]]; then output_path="$2"; shift 2; else shift; fi
    done
    cat >"$output_path" <<'SH'
printf 'ML4W_EXTERNAL_CHOICE: ' >&2
IFS= read -r value
[[ "$value" == Lq-fixture ]] || exit 19
# Simulate an external installer leaving changed terminal modes behind.
stty -onlcr -echo
SH
}
xdg-settings() { [[ "$*" == 'get default-web-browser' ]] || exit 97; echo fixture.desktop; }
xdg-mime() { [[ "$1" == query ]] || exit 97; echo fixture.desktop; }
discover_installed_browsers() { printf 'Fixture browser\tfixture.desktop\n'; }
UKI_ENABLED=false
POEDEPLOY_LOG=$(mktemp)
initialise_ui
original_tty=$(stty -g)
ui_progress_init 'ML4W' 'SDDM' 'UKI' 'Browser' 'Shares' 'Secure Boot'
ui_dashboard_start
run_dashboard_stage ml4w 1 ML4W
[[ "$ML4W_ACTION" == 'installed successfully' && "$ML4W_ENABLED" == true ]]
ui_dashboard_pause
[[ "$(stty -g)" == "$original_tty" ]]
ui_dashboard_resume
run_dashboard_stage sddm 2 SDDM
[[ "$SDDM_ACTION" == skipped ]]
run_dashboard_stage uki 3 UKI
[[ "$UKI_ACTION" == skipped ]]
run_dashboard_stage browser 4 Browser
[[ "$DEFAULT_BROWSER_ACTION" == 'kept current default' ]]
run_dashboard_stage shares 5 Shares
[[ "$NETWORK_SHARES_ACTION" == skipped ]]
run_dashboard_stage secure_boot 6 'Secure Boot'
[[ "$SECURE_BOOT_ACTION" == skipped ]]
ui_complete
ui_cleanup 0
rm -f -- "$POEDEPLOY_LOG"
echo PTY_REGRESSION_DONE
''', [(b'Install ML4W Hyprland? [Y/n]: ', b'y\n'),
      (b'ML4W_EXTERNAL_CHOICE: ', b'Lq-fixture\n'),
      (b'Install and configure SDDM graphical login? [Y/n]: ', b'n\n'),
      (b'Create UKIs alongside the existing boot images? [y/N]: ', b'n\n'),
      (b'Select the default browser [0-1]: ', b'0\n'),
      (b'Select an option [0-3]: ', b'0\n'),
      (b'Configure Secure Boot with sbctl? [y/N]: ', b'n\n')])
        self.assertIn(b'Fixture browser (fixture.desktop)', output)
        self.assertIn(b'[1] SMB only', output)
        self.assertIn(b'[2] NFS only', output)

    def test_interactive_stage_failure_does_not_continue_dependent_commands(self):
        output = self.check_pty(r'''
POEDEPLOY_LOG=$(mktemp)
run_setup_module() {
    echo CRITICAL_STAGE_CONTEXT
    false
    echo SHOULD_NEVER_EXECUTE
}
ui_progress_init ML4W
ui_dashboard_start
trap 'ui_cleanup 0; rm -f -- "$POEDEPLOY_LOG"; echo PTY_REGRESSION_DONE' EXIT
run_dashboard_stage ml4w 1 ML4W
''', [(b'[R]etry, [L]og, [A]bort: ', b'a')], expected_exit=1)
        self.assertIn(b'CRITICAL_STAGE_CONTEXT', output)
        self.assertNotIn(b'SHOULD_NEVER_EXECUTE', output)

    def test_repeated_handoffs_do_not_leave_renderer_on_prompt_screen(self):
        replies = [(f'QUESTION_{index}: '.encode(), b'Lq\n') for index in range(12)]
        output = self.check_pty(r'''
POEDEPLOY_LOG=$(mktemp)
run_setup_module() {
    for ((i = 0; i < 12; i++)); do
        ui_prompt answer "QUESTION_$i: "
        [[ "$answer" == Lq ]]
    done
}
ui_progress_init Fixture
ui_dashboard_start
run_dashboard_stage fixture 1 Fixture
ui_complete
ui_cleanup 0
rm -f -- "$POEDEPLOY_LOG"
echo PTY_REGRESSION_DONE
''', replies)
        for index in range(12):
            prompt = f'QUESTION_{index}: '.encode()
            start = output.index(prompt) + len(prompt)
            # No alternate-screen entry or redraw may occur before the answer.
            self.assertNotIn(b'\x1b', output[start:output.index(b'\n', start)])

    def test_resize_switches_to_compact_view_and_back(self):
        output = self.check_pty(r'''
POEDEPLOY_LOG=$(mktemp)
ui_progress_init Fixture
ui_dashboard_start
sleep 0.5
stty rows 10 cols 35
sleep 0.5
stty rows 28 cols 100
sleep 0.5
ui_complete
ui_cleanup 0
rm -f -- "$POEDEPLOY_LOG"
echo PTY_REGRESSION_DONE
''', [])
        self.assertIn(b'POEDEPLOY 0%', output)
        self.assertGreaterEqual(output.count(b'Arch Linux installer'), 2)

    def test_cleanup_clears_task_that_already_exited(self):
        self.check(r'''
PD_UI_DIR=$(mktemp -d)
PD_UI_ACTIVE=true
PD_DASHBOARD_PID=""
# This process has exited and been reaped before cleanup begins.
true &
PD_TASK_PID=$!
wait "$PD_TASK_PID"
ui_cleanup 0
[[ -z "$PD_TASK_PID" && "$PD_UI_ACTIVE" == false && ! -d "$PD_UI_DIR" ]]
''')

    def test_ctrl_c_stops_interactive_worker_and_restores_terminal(self):
        output = self.check_pty(r'''
POEDEPLOY_LOG=$(mktemp)
run_setup_module() {
    echo INTERRUPT_FIXTURE_READY
    sleep 30
    echo SHOULD_NEVER_EXECUTE
}
ui_progress_init ML4W
ui_dashboard_start
trap 'status=$?; ui_cleanup 0; [[ -z "$PD_TASK_PID" ]]; rm -f -- "$POEDEPLOY_LOG"; echo PTY_REGRESSION_DONE; exit "$status"' EXIT
trap 'exit 130' INT
run_dashboard_stage ml4w 1 ML4W
''', [(b'INTERRUPT_FIXTURE_READY', b'\x03')], expected_exit=130)
        self.assertNotIn(b'SHOULD_NEVER_EXECUTE', output)
        self.assertIn(b'\x1b[?25h', output)

    def test_interactive_helper_preserves_state_and_warning_counts(self):
        self.check_pty(r'''
POEDEPLOY_LOG=$(mktemp)
change_state() {
    ML4W_ACTION=fixture-action
    warning 'Fixture warning stays visible and counted'
}
run_setup_module() { ui_run_interactive change_state; }
ui_progress_init Fixture
ui_dashboard_start
run_dashboard_stage fixture 1 Fixture
[[ "$ML4W_ACTION" == fixture-action && "$PD_WARNING_COUNT" == 1 ]]
ui_complete
ui_cleanup 0
grep -q 'Fixture warning' "$POEDEPLOY_LOG"
rm -f -- "$POEDEPLOY_LOG"
echo PTY_REGRESSION_DONE
''', [])

    def test_dashboard_and_log_frames_fit_real_terminal_dimensions(self):
        for size in ((1, 8), (8, 35), (10, 35), (15, 40), (24, 80), (28, 100)):
            with self.subTest(size=size):
                output = self.check_pty(r'''
export LC_ALL=C.UTF-8 COLUMNS=200 LINES=100
POEDEPLOY_LOG=$(mktemp)
PD_UI_DIR=$(mktemp -d)
PD_UI_ACTIVE=true
initialise_ui
ui_progress_init 'Base tools' 'Applications' 'Secure Boot'
ui_step_start 2 Applications
ui_set_operation $'Progress\r\033[999;999H\033]0;UNSAFE_TITLE\a\t软件安装 软件安装 软件安装'
printf 'Package\r\033[999;999H\033[31merror\033[0m\t软件安装 软件安装 软件安装\n' >"$POEDEPLOY_LOG"
_pd_set_glyphs
stty -onlcr
for draw in _pd_dashboard_draw _pd_log_draw; do
    frame=$("$draw")
    printf 'FRAME_DATA:'
    printf '%s' "$frame" | base64 -w0
    printf '\n'
done
rm -rf -- "$PD_UI_DIR"
rm -f -- "$POEDEPLOY_LOG"
echo PTY_REGRESSION_DONE
''', [], size=size)
                frames = re.findall(rb'FRAME_DATA:([A-Za-z0-9+/=]+)', output)
                self.assertEqual(len(frames), 2)
                for encoded in frames:
                    frame = base64.b64decode(encoded).decode()
                    self.assertNotIn('\x1b[999;999H', frame)
                    self.assertNotIn('UNSAFE_TITLE', frame)
                    text = re.sub(r'\x1b\[[0-?]*[ -/]*[@-~]', '', frame)
                    self.assertNotIn('\t', text)
                    self.assertNotIn('\n', text.replace('\r\n', ''))
                    rows = text.split('\r\n')
                    self.assertLessEqual(len(rows), size[0])
                    for row in rows:
                        width = sum(0 if unicodedata.combining(c) else
                                    2 if unicodedata.east_asian_width(c) in ('F', 'W') else 1
                                    for c in row)
                        self.assertLess(width, size[1])

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

    def check_plymouth_stage(self, use_gum, cancel):
        setup = '' if use_gum else 'can_use_checklist() { return 1; }\n'
        body = setup + r'''
get_remote_plymouth_themes() { :; }
plymouth-set-default-theme() {
    if [[ "${1:-}" == -l ]]; then printf '%s\n' spinner fixture-theme; else echo spinner; fi
}
sudo() {
    [[ "$*" == 'plymouth-set-default-theme spinner' ]] || exit 97
    echo APPLIED_FIXTURE_THEME
}
POEDEPLOY_LOG=$(mktemp)
run_setup_module() {
    if select_plymouth_theme; then echo PICKER_SUCCESS; else echo PICKER_CANCELLED; fi
    ui_prompt answer 'AFTER_PLYMOUTH: '
    [[ "$answer" == yes ]]
}
initialise_ui
ui_progress_init 'Plymouth fixture'
ui_dashboard_start
run_dashboard_stage fixture 1 'Plymouth fixture'
ui_complete
ui_cleanup 0
grep -q PICKER_EXPECTED_RESULT "$POEDEPLOY_LOG"
if grep -Eq 'Current theme:|Keep current theme|Select Plymouth theme' "$POEDEPLOY_LOG"; then exit 93; fi
rm -f -- "$POEDEPLOY_LOG"
echo PTY_REGRESSION_DONE
'''
        body = body.replace('PICKER_EXPECTED_RESULT',
                            'PICKER_CANCELLED' if cancel else 'PICKER_SUCCESS')
        marker = b'> Keep current theme' if use_gum else b'Select a theme [0-2]: '
        answer = (b'\x1b' if cancel else b'j\r') if use_gum else b'1\n'
        output = self.check_pty(body, [(marker, answer), (b'AFTER_PLYMOUTH: ', b'yes\n')])
        self.assertIn(b'Current theme: spinner', output)
        if cancel:
            self.assertNotIn(b'APPLIED_FIXTURE_THEME', output)
        else:
            self.assertIn(b'APPLIED_FIXTURE_THEME', output)

    def test_plymouth_numbered_menu_visible_during_dashboard_stage(self):
        self.check_plymouth_stage(use_gum=False, cancel=False)

    @unittest.skipUnless(shutil.which('gum'), 'gum required for keyboard test')
    def test_plymouth_picker_selection_during_dashboard_stage(self):
        self.check_plymouth_stage(use_gum=True, cancel=False)

    @unittest.skipUnless(shutil.which('gum'), 'gum required for keyboard test')
    def test_plymouth_picker_cancellation_during_dashboard_stage(self):
        self.check_plymouth_stage(use_gum=True, cancel=True)

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
            'ui/dashboard.sh', 'installer/applications.sh', 'installer/tailscale.sh',
            'installer/fingerprint.sh', 'installer/fingerprint_config.py',
        ]
        for relative in expected:
            self.assertTrue((root / relative).is_file(), relative)

    def test_only_one_dashboard_source_is_shipped(self):
        apps = Path(__file__).resolve().parents[1] / 'apps'
        self.assertEqual({p.name for p in apps.iterdir() if p.is_dir()}, {'poedash', 'shared'})

    def test_dashboard_installers_are_fully_bundled(self):
        root = Path(__file__).resolve().parents[1]
        expected = [
            'apps/poedash/install.sh', 'apps/poedash/poedash.py',
            'apps/poedash/assets/templates/eww.yuck',
            'apps/poedash/assets/scripts/DashboardModule.qml',
            'apps/poedash/assets/scripts/dashboard-control.py',
        ]
        for relative in expected:
            self.assertTrue((root / relative).is_file(), relative)
        installer = (root / 'installer/applications.sh').read_text()
        self.assertNotIn('cyberpoe.uk', installer)
        self.assertNotIn('github.com', installer)
        self.assertNotIn('curl ', installer)
        poe_controls = (root / 'apps/poedash/assets/scripts/DashboardModule.qml').read_text()
        for controls in (poe_controls,):
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
