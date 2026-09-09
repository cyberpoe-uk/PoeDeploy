"""Safe workflow tests: all privileged operations are replaced with test doubles.

Run with: python3 -m unittest discover -s tests -v
The PTY tests send real Ctrl+C to a foreground Bash process and its child.
"""

import errno
import os
from pathlib import Path
import pty
import select
import signal
import subprocess
import time
import unittest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = str(ROOT / "poedeploy.sh")
SLOW_PACKAGE = str(ROOT / "tests/fixtures/slow-package.sh")
PRELUDE = r'''
source "$1"
trap - ERR
sudo() { printf 'UNEXPECTED PRIVILEGED OPERATION: %s\n' "$*" >&2; exit 97; }
wait_for_pacman_lock() { :; }
'''


def run_bash(body, stdin=""):
    return subprocess.run(
        ["bash", "--noprofile", "--norc", "-c", PRELUDE + body, "test", SCRIPT],
        input=stdin, text=True, capture_output=True, timeout=10, cwd=ROOT,
    )


class SetupSelectionTests(unittest.TestCase):
    def check_run(self, body, stdin=""):
        result = run_bash(body, stdin)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        return result.stdout

    def test_first_run_selects_every_section(self):
        self.check_run(r'''
choose_setup_modules
[[ "$RUN_MODE" == full ]]
[[ ${#SELECTED_SETUP_MODULES[@]} == ${#SETUP_MODULE_IDS[@]} ]]
''', "no\n")

    def test_repeat_run_selects_only_secure_boot(self):
        self.check_run(r'''
choose_setup_modules
[[ "$RUN_MODE" == selected ]]
[[ ${#SELECTED_SETUP_MODULES[@]} == 1 ]]
[[ "${SELECTED_SETUP_MODULES[secure_boot]}" == true ]]
''', "yes\n15\nrun\n")

    def test_toggle_clear_invalid_and_leading_zero_input(self):
        self.check_run(r'''
choose_setup_modules
[[ ${#SELECTED_SETUP_MODULES[@]} == 2 ]]
[[ "${SELECTED_SETUP_MODULES[applications]}" == true ]]
[[ "${SELECTED_SETUP_MODULES[sddm]}" == true ]]
''', "y\nrun\nall\nnone\n99\n1;echo injected\n11,10\n010\n10\n10\n08\n08\nrun\n")

    def test_empty_run_and_eof_make_no_changes(self):
        output = self.check_run(r'''
if choose_setup_modules; then exit 90; fi
printf 'CANCELLED\n'
''', "yes\nrun\n")
        self.assertIn("CANCELLED", output)

    def test_menu_quit(self):
        self.check_run("if choose_setup_modules; then exit 90; fi", "yes\nq\n")

    def test_dispatch_uses_dependency_order(self):
        output = self.check_run(r'''
SELECTED_SETUP_MODULES=([secure_boot]=true [applications]=true [uki]=true)
run_setup_module() { printf 'VISIT:%s\n' "$1"; }
run_selected_setup_modules
''')
        self.assertEqual(
            [line for line in output.splitlines() if line.startswith("VISIT:")],
            ["VISIT:uki", "VISIT:applications", "VISIT:secure_boot"],
        )

    def test_plymouth_rebuild_adds_signing_when_secure_boot_is_enabled(self):
        output = self.check_run(r'''
SELECTED_SETUP_MODULES=([plymouth]=true)
firmware_secure_boot_enabled() { return 0; }
add_required_setup_modules
[[ "${SELECTED_SETUP_MODULES[plymouth]}" == true ]]
[[ "${SELECTED_SETUP_MODULES[secure_boot]}" == true ]]
''')
        self.assertIn("added automatically", output)

    def test_plymouth_rebuild_does_not_add_signing_when_secure_boot_is_disabled(self):
        self.check_run(r'''
SELECTED_SETUP_MODULES=([plymouth]=true)
firmware_secure_boot_enabled() { return 1; }
add_required_setup_modules
[[ "${SELECTED_SETUP_MODULES[secure_boot]:-false}" == false ]]
''')

    def test_main_secure_boot_only_skips_updates_and_installers(self):
        output = self.check_run(r'''
load_version() { :; }
show_header() { :; }
check_not_root() { :; }
check_arch() { :; }
detect_gpu() { :; }
detect_bootloader() { BOOTLOADER=systemd-boot; }
detect_uki() { UKI_ENABLED=true; UKI_BOOTED=true; }
detect_filesystem() { :; }
check_graphical_environment() { :; }
save_initial_graphical_status() { :; }
show_summary() { :; }
show_final_summary() { :; }
check_internet() { echo UNEXPECTED_NETWORK_CHECK; exit 92; }
update_system() { echo UNEXPECTED_UPDATE; exit 92; }
install_yay() { echo UNEXPECTED_YAY; exit 92; }
install_base_tools() { echo UNEXPECTED_BASE; exit 92; }
ensure_command_dependencies() { [[ "$*" == 'objcopy:binutils' ]]; }
install_uki_black_splash() { echo UNEXPECTED_SPLASH; exit 92; }
setup_secure_boot() {
    [[ "$BOOTLOADER" == systemd-boot && "$UKI_ENABLED" == true && "$UKI_BOOTED" == true ]]
    printf 'SECURE_BOOT_ONLY\n'
}
main
[[ "${PROCESSED_SETUP_MODULES[*]}" == secure_boot ]]
''', "yes\n15\nrun\ny\n")
        self.assertIn("SECURE_BOOT_ONLY", output)
        self.assertNotIn("UNEXPECTED", output)

    def test_selected_section_failure_stops_dependents(self):
        result = run_bash(r'''
SELECTED_SETUP_MODULES=([update]=true [secure_boot]=true)
update_system() { return 7; }
setup_secure_boot() { echo MUST_NOT_RUN; }
run_selected_setup_modules
''')
        self.assertEqual(result.returncode, 7, result.stdout + result.stderr)
        self.assertNotIn("MUST_NOT_RUN", result.stdout)

    def test_sddm_runs_without_ml4w_installer(self):
        output = self.check_run(r'''
SELECTED_SETUP_MODULES=([sddm]=true)
setup_sddm() { [[ "$CONFIGURE_ML4W_SDDM" == true ]]; echo SDDM_ONLY; }
install_ml4w() { exit 91; }
run_selected_setup_modules
[[ "$ML4W_ENABLED" == false ]]
''', "y\nn\n")
        self.assertIn("SDDM_ONLY", output)

    def test_tailscale_runs_without_application_menu(self):
        output = self.check_run(r'''
RUN_MODE=selected
pacman() { [[ "$*" == '-Q tailscale' ]]; }
systemctl() { return 0; }
configure_tailscale
''')
        self.assertIn("Tailscale is installed and running", output)

    def test_cancelled_tailscale_is_not_reinstalled(self):
        output = self.check_run(r'''
RUN_MODE=selected
SKIPPED_PACKAGES=(tailscale)
pacman() { echo MUST_NOT_QUERY; exit 91; }
configure_tailscale
''')
        self.assertNotIn("MUST_NOT_QUERY", output)
        self.assertIn("cancelled", output)

    def test_failure_and_skip_accounting_are_separate(self):
        self.check_run(r'''
install_optional_package failed bash -c 'exit 1'
install_optional_package cancelled bash -c 'exit 130'
install_optional_package good true
[[ "${FAILED_PACKAGES[*]}" == failed ]]
[[ "${SKIPPED_PACKAGES[*]}" == cancelled ]]
[[ "${INSTALLED_PACKAGES[*]}" == good ]]
''', "s\n")

    def test_vlc_skip_also_skips_plugins_and_continues(self):
        self.check_run(r'''
SELECTED_PACKAGES=(vlc vlc-plugins-all firefox)
pacman() { [[ "$1" == -Si ]]; }
sudo() {
    if [[ "$*" == *' vlc' ]]; then return 130; fi
    [[ "$*" == *' firefox' ]]
}
install_selected_applications
[[ "${SKIPPED_PACKAGES[*]}" == 'vlc vlc-plugins-all' ]]
[[ "${INSTALLED_PACKAGES[*]}" == firefox ]]
[[ ${#FAILED_PACKAGES[@]} == 0 ]]
''', "s\n")

    def test_repository_priority_and_aur_fallback(self):
        self.check_run(r'''
SELECTED_PACKAGES=(firefox localsend)
pacman() { [[ "$*" == '-Si firefox' ]]; }
yay() {
    case "$*" in
        '-Si localsend'|'-S --needed --noconfirm localsend') return 0 ;;
        *) exit 91 ;;
    esac
}
sudo() { [[ "$*" == 'pacman -S --needed --noconfirm firefox' ]]; }
install_selected_applications
[[ "${INSTALLED_PACKAGES[*]}" == 'firefox localsend' ]]
''')

    def test_enrollment_guidance_explains_repeat_run(self):
        output = self.check_run(r'''
SECURE_BOOT_ACTION='keys created but not enrolled'
show_secure_boot_next_steps
''')
        self.assertIn("select only Secure Boot", output)
        self.assertIn("ENROLL and SIGN", output)

    def test_plymouth_hook_follows_systemd_or_udev(self):
        self.check_run(r'''
[[ "$(order_mkinitcpio_plymouth_hook base systemd autodetect plymouth kms)" == \
   'base systemd plymouth autodetect kms ' ]]
[[ "$(order_mkinitcpio_plymouth_hook base udev autodetect plymouth kms)" == \
   'base udev plymouth autodetect kms ' ]]
''')

    def test_uki_splash_replaces_arch_option_and_preserves_other_options(self):
        self.check_run(r'''
preset=$(mktemp -t poedeploy-preset-test-XXXXXX)
trap 'rm -f "$preset"' EXIT
printf '%s\n' \
    'PRESETS=(default)' \
    'default_uki="/boot/EFI/Linux/test.efi"' \
    'default_options="-S autodetect --splash /usr/share/systemd/bootctl/splash-arch.bmp"' > "$preset"
sudo() { command "$@"; }
set_mkinitcpio_preset_splash "$preset" default /usr/share/poedeploy/uki/poedeploy-black.bmp
grep -Fxq 'default_options="-S autodetect --splash /usr/share/poedeploy/uki/poedeploy-black.bmp"' "$preset"
[[ $(grep -c '^default_options=' "$preset") == 1 ]]
''')


class InterruptTests(unittest.TestCase):
    def terminal_session(self, action, quit_expected=False):
        body = PRELUDE + r'''
trap 'printf "PREVIOUS_TRAP_RESTORED\n"' INT
attempts=0
package_command() {
    attempts=$((attempts + 1))
    if ((attempts == 1)); then bash "$2"; else printf 'RETRY_SUCCEEDED\n'; fi
}
install_optional_package localsend package_command unused "$2"
printf 'SKIPPED:%s\n' "${SKIPPED_PACKAGES[*]}"
printf 'INSTALLED:%s\n' "${INSTALLED_PACKAGES[*]}"
kill -s INT "$$"
printf 'NEXT_APP\n'
'''
        pid, fd = pty.fork()
        if pid == 0:
            os.execvp("bash", ["bash", "--noprofile", "--norc", "-c", body, "test", SCRIPT, SLOW_PACKAGE])

        output = b""
        sent_interrupt = False
        sent_action = False
        status = None
        done = 0
        deadline = time.monotonic() + 8
        try:
            while time.monotonic() < deadline:
                if select.select([fd], [], [], 0.05)[0]:
                    try:
                        chunk = os.read(fd, 8192)
                    except OSError as error:
                        if error.errno != errno.EIO:
                            raise
                        chunk = b""
                    if chunk:
                        output += chunk
                if b"PACKAGE_READY" in output and not sent_interrupt:
                    # Allow the fixture to enter its foreground build command;
                    # the test models cancelling an ongoing build, not fork startup.
                    time.sleep(0.1)
                    os.write(fd, b"\x03")
                    sent_interrupt = True
                if b"[s] Skip this package" in output and not sent_action:
                    self.assertIn(b"PACKAGE_EXITED", output)
                    os.write(fd, action.encode() + b"\n")
                    sent_action = True
                done, status = os.waitpid(pid, os.WNOHANG)
                if done:
                    break
            else:
                self.fail("Terminal session timed out:\n" + output.decode(errors="replace"))
        finally:
            if status is None or not done:
                os.killpg(pid, signal.SIGTERM)
                os.waitpid(pid, 0)
            os.close(fd)

        result = output.decode(errors="replace")
        self.assertEqual(os.waitstatus_to_exitcode(status), 130 if quit_expected else 0, result)
        self.assertTrue(sent_interrupt and sent_action, result)
        return result

    def test_ctrl_c_skip_waits_for_exit_and_continues(self):
        output = self.terminal_session("s")
        self.assertIn("SKIPPED:localsend", output)
        self.assertIn("NEXT_APP", output)
        self.assertIn("PREVIOUS_TRAP_RESTORED", output)

    def test_ctrl_c_retry_installs_same_package(self):
        output = self.terminal_session("r")
        self.assertIn("RETRY_SUCCEEDED", output)
        self.assertIn("INSTALLED:localsend", output)
        self.assertNotIn("SKIPPED:localsend", output)

    def test_ctrl_c_quit_stops_next_app(self):
        output = self.terminal_session("q", quit_expected=True)
        self.assertNotIn("NEXT_APP", output)


class LockSafetyTests(unittest.TestCase):
    def run_lock_case(self, body):
        # Restore the real function with ONLY its lock path changed to an isolated
        # test fixture. No test is allowed to touch the real Pacman database.
        fixture = r'''
test_dir=$(mktemp -d -t poedeploy-lock-test-XXXXXX)
trap 'rm -rf -- "$test_dir"' EXIT
test_lock="$test_dir/db.lck"
touch "$test_lock"
source "$1"
trap - ERR
definition=$(declare -f wait_for_pacman_lock)
definition=${definition//\/var\/lib\/pacman\/db.lck/$test_lock}
eval "$definition"
pgrep() { return 1; }
sudo() {
    case "$1" in
        fuser) return 1 ;;
        rm)
            [[ "$*" == "rm -f -- $test_lock" ]] || exit 97
            command rm -f -- "$test_lock"
            echo REMOVED
            ;;
        *) exit 97 ;;
    esac
}
sleep() { :; }
'''
        result = run_bash(fixture + body)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        return result.stdout

    def test_active_manager_with_closed_lock_descriptor_is_not_removed(self):
        output = self.run_lock_case(r'''
pgrep() { return 0; }
sleep() { [[ "$1" == 5 ]]; command rm -- "$test_lock"; }
wait_for_pacman_lock
''')
        self.assertNotIn("REMOVED", output)
        self.assertIn("Waiting for it to finish", output)

    def test_stale_lock_is_rechecked_before_removal(self):
        output = self.run_lock_case(r'''
grace_waits=0
sleep() { [[ "$1" == 2 ]]; grace_waits=$((grace_waits + 1)); }
wait_for_pacman_lock
[[ "$grace_waits" == 1 ]]
[[ ! -e "$test_lock" ]]
''')
        self.assertIn("REMOVED", output)

    def test_inspection_error_leaves_lock_intact(self):
        output = self.run_lock_case(r'''
sudo() { echo 'Inspection failed' >&2; return 1; }
if wait_for_pacman_lock; then exit 91; fi
[[ -e "$test_lock" ]]
''')
        self.assertNotIn("REMOVED", output)

    def test_inspection_abnormal_exit_leaves_lock_intact(self):
        output = self.run_lock_case(r'''
sudo() { return 137; }
if wait_for_pacman_lock; then exit 91; fi
[[ -e "$test_lock" ]]
''')
        self.assertNotIn("REMOVED", output)

    def test_replaced_lock_gets_another_grace_period(self):
        self.run_lock_case(r'''
grace_waits=0
sleep() {
    grace_waits=$((grace_waits + 1))
    if ((grace_waits == 1)); then
        mv "$test_lock" "$test_dir/old.lck"
        touch "$test_lock"
    fi
}
wait_for_pacman_lock
[[ "$grace_waits" == 2 ]]
[[ ! -e "$test_lock" ]]
''')


if __name__ == "__main__":
    unittest.main()
