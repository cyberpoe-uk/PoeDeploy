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
import shutil
import subprocess
import termios
import tempfile
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
# Workflow tests mock commands; dedicated timeout tests restore this helper
# and execute GNU timeout against harmless fixture processes.
original_boot_check=$(declare -f run_boot_verification_check)
run_boot_verification_check() {
    local label="$1"
    shift
    info "$label" >&2
    sudo "$@"
}
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

    def test_default_mode_opens_empty_section_selection(self):
        self.check_run(r'''
choose_setup_modules
[[ "$RUN_MODE" == selected && ${#SELECTED_SETUP_MODULES[@]} == 1 ]]
[[ "${SELECTED_SETUP_MODULES[plymouth]}" == true ]]
''', "\n6\nrun\n")

    def test_welcome_exit_and_eof_clear_selection(self):
        for answer in ("3\n", "", "quit\n"):
            with self.subTest(answer=answer):
                self.check_run(r'''
SELECTED_SETUP_MODULES=([update]=true)
if choose_setup_modules; then exit 90; fi
[[ ${#SELECTED_SETUP_MODULES[@]} == 0 ]]
''', answer)

    def test_invalid_welcome_input_reprompts(self):
        output = self.check_run(r'''
choose_run_mode
[[ "$RUN_MODE" == selected ]]
''', "yes\n99\n1\n")
        self.assertEqual(output.count("Choose 1, 2 or 3."), 2)

    def test_welcome_gum_has_three_inline_choices_and_safe_default(self):
        self.check_run(r'''
can_use_checklist() { return 0; }
gum() {
    [[ "$*" != *'--no-limit'* ]] || return 91
    [[ "$*" == *'--selected=Choose sections (Select specific setup tasks)'* ]] || return 92
    [[ "$*" == *'--cursor.foreground=#004FFE'* ]] || return 93
    local -a options=()
    mapfile -t options
    [[ ${#options[@]} == 3 && "${options[2]}" == Exit ]] || return 94
    printf '%s\n' "${options[1]}"
}
choose_setup_modules
[[ "$RUN_MODE" == full && ${#SELECTED_SETUP_MODULES[@]} == ${#SETUP_MODULE_IDS[@]} ]]
''')

    def test_welcome_gum_failure_ignores_partial_selection(self):
        self.check_run(r'''
can_use_checklist() { return 0; }
gum() { cat >/dev/null; echo 'Full setup (Go through all setup, with optional choices.)'; return 130; }
if choose_setup_modules; then exit 90; fi
[[ ${#SELECTED_SETUP_MODULES[@]} == 0 ]]
''')

    def test_header_contains_embedded_logo_and_version_without_external_tools(self):
        output = self.check_run(r'''
figlet() { exit 91; }
clear() { exit 92; }
SCRIPT_VERSION=vtest
show_header
''')
        self.assertIn("/ __ \\____", output)
        self.assertIn("Version: vtest", output)
        self.assertNotIn("\x1b", output)

    def test_hyprmod_uses_optional_aur_install_flow(self):
        output = self.check_run(r'''
gum() { :; }
choose_checklist() {
    [[ -z "$2" ]] || return 91
    local options
    options=$(cat)
    [[ "$options" == *'HyprMod (Hyprland settings)'* ]] || return 92
    echo 'HyprMod (Hyprland settings)'
}
select_applications
[[ "${SELECTED_PACKAGES[*]}" == hyprmod ]]
pacman() { return 1; }
yay() { [[ "$*" == '-Si hyprmod' ]]; }
install_optional_package() {
    [[ "$*" == 'hyprmod yay -S --needed --noconfirm hyprmod' ]] || exit 93
    echo HYPRMOD_INSTALL
}
hyprmod() { exit 94; }
install_selected_applications
''')
        self.assertIn("HYPRMOD_INSTALL", output)

    def test_hyprmod_already_installed_is_not_reinstalled_or_launched(self):
        self.check_run(r'''
SELECTED_PACKAGES=(hyprmod)
pacman() { [[ "$*" == '-Q hyprmod' ]]; }
install_optional_package() { exit 91; }
hyprmod() { exit 92; }
install_selected_applications
[[ "${INSTALLED_PACKAGES[*]}" == hyprmod ]]
''')

    def test_ml4w_download_validation_execution_and_cleanup(self):
        cases = (
            ("partial", "download failed", False),
            ("empty", "invalid download", False),
            ("invalid", "invalid download", False),
            ("success", "installed successfully", True),
            ("failure", "installation failed", True),
        )
        for fixture, expected, ran in cases:
            with self.subTest(fixture=fixture):
                output = self.check_run(f'fixture={fixture}\n' + r'''
download_path=''
curl() {
    [[ "$*" == *'--connect-timeout 15 --max-time 180 --retry 2'* ]] || return 91
    while (($#)); do
        if [[ "$1" == --output ]]; then download_path="$2"; break; fi
        shift
    done
    [[ -f "$download_path" ]] || return 92
    case "$fixture" in
        partial) printf 'echo INSTALLER_RAN\n' > "$download_path"; return 22 ;;
        empty) : ;;
        invalid) printf 'echo INSTALLER_RAN\nif then\n' > "$download_path" ;;
        success) printf 'echo INSTALLER_RAN\n' > "$download_path" ;;
        failure) printf 'echo INSTALLER_RAN\nexit 42\n' > "$download_path" ;;
    esac
}
install_ml4w
[[ -n "$download_path" && ! -e "$download_path" ]]
printf 'ACTION:%s\n' "$ML4W_ACTION"
''' , "y\n")
                self.assertIn("ACTION:" + expected, output)
                self.assertEqual("INSTALLER_RAN" in output, ran)

    def test_ml4w_skip_and_tempfile_failure_do_not_download(self):
        for answer, expected in (("n\n", "skipped"), ("y\n", "download failed")):
            with self.subTest(answer=answer):
                output = self.check_run(r'''
curl() { exit 91; }
mktemp() { return 1; }
install_ml4w
[[ "$ML4W_ENABLED" == false ]]
printf 'ACTION:%s\n' "$ML4W_ACTION"
''', answer)
                self.assertIn("ACTION:" + expected, output)

    def test_full_setup_selects_every_section(self):
        self.check_run(r'''
choose_setup_modules
[[ "$RUN_MODE" == full ]]
[[ ${#SELECTED_SETUP_MODULES[@]} == ${#SETUP_MODULE_IDS[@]} ]]
''', "2\n")

    def test_uki_cmdline_update_has_no_redundant_confirmation(self):
        script_text = Path(SCRIPT).read_text()
        start = script_text.index("prepare_uki_kernel_cmdline() {")
        end = script_text.index("\n}\n\nrestore_failed_uki_setup()", start)
        function_text = script_text[start:end]
        self.assertNotIn("Write this to /etc/kernel/cmdline?", function_text)
        self.assertIn("sudo may request your password", function_text)
        self.assertIn("kernel command line was derived", function_text)

    def test_selected_mode_selects_only_secure_boot(self):
        self.check_run(r'''
choose_setup_modules
[[ "$RUN_MODE" == selected ]]
[[ ${#SELECTED_SETUP_MODULES[@]} == 1 ]]
[[ "${SELECTED_SETUP_MODULES[secure_boot]}" == true ]]
''', "1\n15\nrun\n")

    def test_checklist_selects_sections_in_dependency_order(self):
        output = self.check_run(r'''
can_use_checklist() { return 0; }
choose_run_mode() { RUN_MODE=selected; }
choose_checklist() {
    [[ "$1" == 'Setup sections' && -z "${2:-}" ]] || return 91
    local options
    options=$(cat)
    [[ "$options" == *'Plymouth boot theme'* ]] || return 92
    printf '%s\n' 'Secure Boot: keys, enrollment and signing' 'Plymouth boot theme'
}
choose_setup_modules
[[ "$RUN_MODE" == selected && ${#SELECTED_SETUP_MODULES[@]} == 2 ]]
run_setup_module() { printf 'VISIT:%s\n' "$1"; }
run_selected_setup_modules
''')
        self.assertEqual(
            [line for line in output.splitlines() if line.startswith("VISIT:")],
            ["VISIT:plymouth", "VISIT:secure_boot"],
        )

    def test_checklist_cancellation_does_not_keep_partial_output(self):
        self.check_run(r'''
can_use_checklist() { return 0; }
choose_run_mode() { RUN_MODE=selected; }
choose_checklist() { cat >/dev/null; echo 'Plymouth boot theme'; return 130; }
if choose_setup_modules; then exit 90; fi
[[ ${#SELECTED_SETUP_MODULES[@]} == 0 ]]
''')

    def test_empty_checklist_reprompts_without_selecting_everything(self):
        output = self.check_run(r'''
can_use_checklist() { return 0; }
choose_run_mode() { RUN_MODE=selected; }
choose_checklist() { cat >/dev/null; return 0; }
warning() {
    printf '%s\n' "$1"
    choose_checklist() { cat >/dev/null; echo 'Plymouth boot theme'; }
}
choose_setup_modules
[[ ${#SELECTED_SETUP_MODULES[@]} == 1 ]]
[[ "${SELECTED_SETUP_MODULES[plymouth]}" == true ]]
''')
        self.assertIn("Select at least one section", output)

    def test_unknown_checklist_label_cancels_selection(self):
        self.check_run(r'''
can_use_checklist() { return 0; }
choose_run_mode() { RUN_MODE=selected; }
choose_checklist() { cat >/dev/null; printf '%s\n' 'Plymouth boot theme' 'Unknown'; }
if choose_setup_modules; then exit 90; fi
[[ ${#SELECTED_SETUP_MODULES[@]} == 0 ]]
''')

    def test_noninteractive_input_uses_numbered_menu(self):
        self.check_run(r'''
gum() { echo UNEXPECTED_CHECKLIST >&2; return 91; }
if can_use_checklist; then exit 90; fi
choose_setup_modules
[[ ${#SELECTED_SETUP_MODULES[@]} == 1 ]]
''', "1\n6\nrun\n")

    def test_shared_checklist_style_and_explicit_defaults(self):
        self.check_run(r'''
gum() {
    [[ "$1" == choose && "$*" == *'--no-limit'* ]] || return 91
    [[ "$*" == *'--selected.foreground=#004FFE'* ]] || return 92
    [[ "$*" == *'--header=Test menu'* ]] || return 93
    [[ "$3" == "--selected=$expected" ]] || return 94
    cat
}
expected=''
[[ $(printf 'Item\n' | choose_checklist 'Test menu') == Item ]]
expected='*'
[[ $(printf 'Item\n' | choose_checklist 'Test menu' '*') == Item ]]
''')

    def test_application_checklist_starts_empty_and_preserves_vlc_plugins(self):
        for mode, default in (("full", ""), ("selected", "")):
            with self.subTest(mode=mode):
                self.check_run(f'RUN_MODE={mode}\nexpected="{default}"\n' + r'''
gum() { :; }
APPLICATIONS=([VLC]=vlc [Firefox]=firefox)
choose_checklist() {
    [[ "$1" == 'Select applications' && "$2" == "$expected" ]] || return 91
    cat >/dev/null
    echo VLC
}
select_applications
[[ "${SELECTED_APPS[*]}" == VLC ]]
[[ "${SELECTED_PACKAGES[*]}" == 'vlc vlc-plugins-all' ]]
''')

    def test_application_checklist_cancel_and_empty_clear_previous_selection(self):
        for status in (0, 130):
            with self.subTest(status=status):
                self.check_run(f'status={status}\n' + r'''
gum() { :; }
SELECTED_APPS=(Firefox)
SELECTED_PACKAGES=(firefox)
choose_checklist() { cat >/dev/null; return "$status"; }
select_applications
[[ ${#SELECTED_APPS[@]} == 0 && ${#SELECTED_PACKAGES[@]} == 0 ]]
if [[ "$status" == 0 ]]; then
    [[ "$APPLICATIONS_ACTION" == 'none selected' ]]
else
    [[ "$APPLICATIONS_ACTION" == 'selection cancelled' ]]
fi
''')

    def test_toggle_clear_invalid_and_leading_zero_input(self):
        self.check_run(r'''
choose_setup_modules
[[ ${#SELECTED_SETUP_MODULES[@]} == 2 ]]
[[ "${SELECTED_SETUP_MODULES[applications]}" == true ]]
[[ "${SELECTED_SETUP_MODULES[sddm]}" == true ]]
''', "1\nrun\nall\nnone\n99\n1;echo injected\n11,10\n010\n10\n10\n08\n08\nrun\n")

    def test_empty_run_and_eof_make_no_changes(self):
        output = self.check_run(r'''
if choose_setup_modules; then exit 90; fi
printf 'CANCELLED\n'
''', "1\nrun\n")
        self.assertIn("CANCELLED", output)

    def test_menu_quit(self):
        self.check_run("if choose_setup_modules; then exit 90; fi", "1\nq\n")

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

    def test_plymouth_selection_does_not_add_secure_boot_setup(self):
        self.check_run(r'''
SELECTED_SETUP_MODULES=([plymouth]=true)
firmware_secure_boot_enabled() { return 0; }
[[ "${SELECTED_SETUP_MODULES[plymouth]}" == true ]]
[[ "${SELECTED_SETUP_MODULES[secure_boot]:-false}" == false ]]
''')

    def test_plymouth_rebuild_verifies_existing_secure_boot_signatures(self):
        output = self.check_run(r'''
firmware_secure_boot_enabled() { return 0; }
sbctl() { :; }
get_configured_uki_paths() { printf '/boot/EFI/Linux/arch-linux.efi\n'; }
sudo() {
    [[ "$*" == 'sbctl --json verify /boot/EFI/Linux/arch-linux.efi' ]] || exit 97
    printf '%s\n' '[{"file_name":"/boot/EFI/Linux/arch-linux.efi","is_signed":1}]'
}
verify_secure_boot_after_uki_rebuild
[[ "$SECURE_BOOT_ACTION" == 'not selected' ]]
[[ "$SECURE_BOOT_VERIFY_STATUS" == 'UKI and identified boot loader signatures verified' ]]
''')
        self.assertIn("Signature verified: /boot/EFI/Linux/arch-linux.efi", output)
        self.assertIn("Existing keys were not changed", output)

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
ensure_command_dependencies() { [[ "$*" == 'objcopy:binutils jq:jq' ]]; }
install_uki_black_splash() { echo UNEXPECTED_SPLASH; exit 92; }
setup_secure_boot() {
    [[ "$BOOTLOADER" == systemd-boot && "$UKI_ENABLED" == true && "$UKI_BOOTED" == true ]]
    printf 'SECURE_BOOT_ONLY\n'
}
main
[[ "${PROCESSED_SETUP_MODULES[*]}" == secure_boot ]]
''', "1\n15\nrun\ny\n")
        self.assertIn("SECURE_BOOT_ONLY", output)
        self.assertNotIn("UNEXPECTED", output)

    def test_targeted_verification_does_not_report_unrequested_files(self):
        output = self.check_run(r'''
firmware_secure_boot_enabled() { return 0; }
get_configured_uki_paths() { printf '/boot/EFI/Linux/arch-linux.efi\n'; }
sbctl() { :; }
sudo() {
    [[ "$*" == 'sbctl --json verify /boot/EFI/Linux/arch-linux.efi' ]] || exit 97
    printf '%s\n' '[
      {"file_name":"/boot/EFI/Linux/arch-linux.efi","is_signed":1},
      {"file_name":"/boot/EFI/BOOT/BOOTX64.EFI","is_signed":0},
      {"file_name":"/boot/vmlinuz-linux","is_signed":0}]'
}
verify_secure_boot_after_uki_rebuild
[[ "$SECURE_BOOT_OTHER_FILES_WARNING" == false ]]
[[ "$SECURE_BOOT_VERIFY_STATUS" == 'UKI and identified boot loader signatures verified' ]]
[[ "$SECURE_BOOT_ACTION" == 'not selected' ]]
check_graphical_environment() { :; }
pacman() { return 1; }
show_final_summary
''')
        self.assertNotIn("Additional boot file reported unsigned", output)
        self.assertIn("Unrelated EFI files were not scanned", output)
        self.assertIn("Secure Boot setup: not selected", output)
        self.assertIn("Signature check:   UKI and identified boot loader signatures verified", output)

    def test_systemd_boot_discovery_identifies_fallback_and_normalizes_paths(self):
        self.check_run(r'''
sudo() {
    case "$*" in
        'bootctl --print-esp-path') printf '/boot/\n' ;;
        'bootctl --print-loader-path') printf '/boot//EFI/systemd/systemd-bootx64.efi\n' ;;
        'bootctl status'*) echo UNEXPECTED_STATUS >&2; return 137 ;;
        *) exit 97 ;;
    esac
}
is_systemd_boot_binary() {
    case "$1" in
        /boot/EFI/systemd/systemd-bootx64.efi|/boot/EFI/BOOT/BOOTX64.EFI) return 0 ;;
        *) return 1 ;;
    esac
}
[[ "$(get_systemd_boot_files)" == $'/boot/EFI/BOOT/BOOTX64.EFI\n/boot/EFI/systemd/systemd-bootx64.efi' ]]
''')

    def test_systemd_boot_discovery_refuses_unidentified_current_loader(self):
        self.check_run(r'''
sudo() {
    case "$*" in
        'bootctl --print-esp-path') printf '/boot\n' ;;
        'bootctl --print-loader-path') printf '/boot/EFI/BOOT/BOOTX64.EFI\n' ;;
        *) exit 97 ;;
    esac
}
is_systemd_boot_binary() { return 1; }
if get_systemd_boot_files; then exit 90; fi
''')

    def test_loader_marker_requires_mz_and_systemd_boot_product(self):
        with tempfile.TemporaryDirectory(prefix="poedeploy-loader-test-") as directory:
            fixture = Path(directory) / "loader.efi"
            cases = (
                (b"MZ\0#### LoaderInfo: systemd-boot 261.2-1-arch ####\0", True),
                (b"MZ\0#### LoaderInfo: systemd-stub 261 ####\0", False),
                (b"MZ\0#### LoaderInfo: shim 15.8 ####\0", False),
                (b"MZ\0systemd-boot\0", False),
                (b"#### LoaderInfo: systemd-boot 261 ####", False),
            )
            for data, valid in cases:
                with self.subTest(data=data):
                    fixture.write_bytes(data)
                    self.check_run(f'fixture={str(fixture)!r}\nexpected={str(valid).lower()}\n' + r'''
sudo() {
    case "$1" in test|head|grep) command "$@" ;; *) exit 97 ;; esac
}
actual=false
if is_systemd_boot_binary "$fixture"; then actual=true; fi
[[ "$actual" == "$expected" ]]
if is_systemd_boot_binary "${fixture}.missing"; then exit 90; fi
''')

    def test_discovery_reports_path_query_failure(self):
        for option in ("--print-esp-path", "--print-loader-path"):
            with self.subTest(option=option):
                result = run_bash(f'failed_option={option}\n' + r'''
sudo() {
    [[ "$*" != "bootctl $failed_option" ]] || return 137
    [[ "$*" == 'bootctl --print-esp-path' ]] || exit 97
    echo /boot
}
if get_systemd_boot_files; then exit 90; fi
''')
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                self.assertIn(option, result.stderr)

    def test_discovery_refuses_loader_outside_esp(self):
        self.check_run(r'''
sudo() {
    case "$*" in
        'bootctl --print-esp-path') echo /boot ;;
        'bootctl --print-loader-path') echo /other/EFI/systemd/systemd-bootx64.efi ;;
        *) exit 97 ;;
    esac
}
is_systemd_boot_binary() { return 0; }
if get_systemd_boot_files; then exit 90; fi
''')

    def test_bootloader_detection_uses_targeted_query_not_status(self):
        output = self.check_run(r'''
bootctl() { echo UNEXPECTED_STATUS >&2; return 137; }
sudo() {
    [[ "$*" == 'bootctl --print-loader-path' ]] || exit 97
    echo /boot/EFI/systemd/systemd-bootx64.efi
}
is_systemd_boot_binary() { [[ "$1" == /boot/EFI/systemd/systemd-bootx64.efi ]]; }
detect_bootloader
[[ "$BOOTLOADER" == systemd-boot ]]
''')
        self.assertIn("Bootloader: systemd-boot", output)

    def run_active_chain_case(self, body):
        return run_bash(r'''
BOOTLOADER=systemd-boot
UKI_BOOTED=true
test_loader=/boot/EFI/systemd/systemd-bootx64.efi
test_uki=/boot/EFI/Linux/arch-linux.efi
fallback=/boot/EFI/BOOT/BOOTX64.EFI
loader_signed=1
uki_signed=1
fallback_signed=0
kernel_signed=0
sign_calls=0
sign_fails=false
sign_ineffective=false
signature_fail_path=''
signature_fail_code=124
identify_status=0
second_uki_signed=1
VERIFIED_PLYMOUTH_UKIS["$test_uki"]=true
firmware_secure_boot_enabled() { return 0; }
get_configured_uki_paths() { printf '%s\n' "$test_uki"; }
original_discovery=$(declare -f get_systemd_boot_files)
original_fallback_discovery=$(declare -f get_present_fallback_boot_paths)
get_systemd_boot_files() { printf '%s\n' "$test_loader" "$fallback"; }
get_present_fallback_boot_paths() { printf '%s\n' "$fallback"; }
sbctl() { :; }
sudo() {
    case "$*" in
        'bootctl --print-esp-path') printf '/boot\n' ;;
        'test -f /boot/EFI/BOOT/BOOTX64.EFI') return 0 ;;
        'test -f /boot/EFI/BOOT/BOOTIA32.EFI'|'test -f /boot/EFI/BOOT/BOOTAA64.EFI') return 1 ;;
        'bootctl status'*) echo UNEXPECTED_STATUS >&2; return 137 ;;
        'bootctl --print-loader-path') printf '%s\n' "$test_loader" ;;
        'bootctl --print-stub-path') printf '%s\n' "$test_uki" ;;
        "bootctl kernel-identify $test_uki") printf 'uki\n'; return "$identify_status" ;;
        'sbctl --json verify /boot/EFI/Linux/second.efi')
            printf '[{"file_name":"/boot/EFI/Linux/second.efi","is_signed":%s}]\n' "$second_uki_signed" ;;
        "sbctl --json verify $test_loader"|"sbctl --json verify $test_uki"|"sbctl --json verify $fallback")
            [[ "$4" != "$signature_fail_path" ]] || return "$signature_fail_code"
            printf '[{"file_name":"%s","is_signed":%s},' "$test_loader" "$loader_signed"
            printf '{"file_name":"%s","is_signed":%s},' "$test_uki" "$uki_signed"
            printf '{"file_name":"%s","is_signed":%s},' "$fallback" "$fallback_signed"
            printf '{"file_name":"/boot/vmlinuz-linux","is_signed":%s}]\n' "$kernel_signed"
            ;;
        "sbctl sign -s $fallback")
            sign_calls=$((sign_calls + 1))
            [[ "$sign_fails" == false ]] || return 1
            if [[ "$sign_ineffective" == false ]]; then fallback_signed=1; fi
            ;;
        *) printf 'UNEXPECTED COMMAND: %s\n' "$*" >&2; exit 97 ;;
    esac
}
''' + body)

    def test_active_chain_verifies_when_full_bootctl_status_is_killed(self):
        result = self.run_active_chain_case(r'''
eval "$original_discovery"
is_systemd_boot_binary() { [[ "$1" == "$test_loader" || "$1" == "$fallback" ]]; }
verify_secure_boot_after_uki_rebuild
[[ "$SECURE_BOOT_VERIFY_STATUS" == 'active Secure Boot chain verified' ]]
[[ "$sign_calls" == 1 ]]
''')
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertNotIn("UNEXPECTED_STATUS", result.stdout + result.stderr)

    def test_required_signature_timeout_stops_without_signing(self):
        result = self.run_active_chain_case(r'''
signature_fail_path="$test_uki"
if verify_secure_boot_after_uki_rebuild; then exit 90; fi
[[ "$sign_calls" == 0 ]]
[[ "$SECURE_BOOT_VERIFY_STATUS" == 'verification failed' ]]
''')
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertNotIn("Active Secure Boot chain verified.", result.stdout)
        self.assertIn("Checking signature: /boot/EFI/Linux/arch-linux.efi", result.stderr)

    def test_active_chain_discovers_each_path_once_per_verification(self):
        result = self.run_active_chain_case(r'''
eval "$original_discovery"
eval "$original_fallback_discovery"
is_systemd_boot_binary() { [[ "$1" == "$test_loader" || "$1" == "$fallback" ]]; }
fallback_signed=1
verify_secure_boot_after_uki_rebuild
verify_secure_boot_after_uki_rebuild
''')
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        # No duplicate queries within a check, but fresh discovery next time.
        self.assertEqual(result.stderr.count("Locating the EFI partition"), 2)
        self.assertEqual(result.stderr.count("Locating the active bootloader"), 2)
        self.assertEqual(result.stderr.count("Locating the current UKI"), 2)

    def test_final_summary_aligns_all_field_values(self):
        output = self.check_run(r'''
check_graphical_environment() { :; }
pacman() { return 1; }
show_final_summary
''')
        rows = [line for line in output.splitlines() if line.startswith("  ") and ":" in line]
        self.assertGreater(len(rows), 20)
        for row in rows:
            with self.subTest(row=row):
                prefix = row[:21]
                self.assertIn(":", prefix)
                self.assertTrue(prefix.endswith(" "))
                self.assertTrue(row[21:], row)
                self.assertFalse(row[21].isspace(), row)

    def test_additional_configured_uki_must_also_be_signed(self):
        result = self.run_active_chain_case(r'''
get_configured_uki_paths() { printf '%s\n' "$test_uki" /boot/EFI/Linux/second.efi; }
second_uki_signed=0
if verify_secure_boot_after_uki_rebuild; then exit 90; fi
[[ "$sign_calls" == 0 ]]
[[ "$SECURE_BOOT_VERIFY_STATUS" == 'verification failed' ]]
''')
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("Rebuilt UKI is unsigned or unverified: /boot/EFI/Linux/second.efi", result.stdout)

    def test_next_steps_do_not_recommend_a_full_signature_scan(self):
        output = self.check_run(r'''
SECURE_BOOT_ACTION='configured and verified'
show_secure_boot_next_steps
''')
        self.assertNotIn('sudo sbctl verify', output)
        self.assertIn('individually verified', output)

    def test_partial_uki_identification_output_does_not_override_failure(self):
        result = self.run_active_chain_case(r'''
identify_status=124
if verify_secure_boot_after_uki_rebuild; then exit 90; fi
[[ "$sign_calls" == 0 ]]
''')
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertNotIn("Current UKI is signed.", result.stdout)

    def test_fallback_timeout_never_authorizes_signing(self):
        result = self.run_active_chain_case(r'''
signature_fail_path="$fallback"
verify_secure_boot_after_uki_rebuild
[[ "$sign_calls" == 0 ]]
[[ "$SECURE_BOOT_OTHER_FILES_WARNING" == true ]]
[[ "$SECURE_BOOT_VERIFY_STATUS" == 'active Secure Boot chain verified, additional boot file warnings' ]]
''')
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("Fallback signature check failed. Signing will not be attempted", result.stdout)

    def test_missing_fallback_never_authorizes_signing(self):
        result = self.run_active_chain_case(r'''
fallback_signed=-1
verify_secure_boot_after_uki_rebuild
[[ "$sign_calls" == 0 && "$SECURE_BOOT_OTHER_FILES_WARNING" == true ]]
''')
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("Fallback bootloader is missing", result.stdout)

    def test_targeted_report_deduplicates_paths_and_refuses_no_arguments(self):
        output = self.check_run(r'''
if read_sbctl_signature_report; then exit 90; fi
sudo() {
    [[ $# == 4 && "$1 $2 $3" == 'sbctl --json verify' ]] || exit 97
    printf 'CHECKED:%s\n' "$4" >&2
    jq -cn --arg path "$4" '[{file_name:$path,is_signed:1}]'
}
report=$(read_sbctl_signature_report /boot//test.efi /boot/test.efi /boot/second.efi)
[[ $(jq length <<< "$report") == 2 ]]
sbctl_report_has_signature "$report" /boot//test.efi
printf '%s\n' "$report"
''')
        self.assertIn('"/boot/test.efi"', output)

    def test_fallback_discovery_checks_only_standard_paths(self):
        self.check_run(r'''
sudo() {
    case "$*" in
        'bootctl --print-esp-path') echo /boot/ ;;
        'test -f /boot/EFI/BOOT/BOOTX64.EFI') return 0 ;;
        'test -f /boot/EFI/BOOT/BOOTIA32.EFI'|'test -f /boot/EFI/BOOT/BOOTAA64.EFI') return 1 ;;
        *) exit 97 ;;
    esac
}
[[ "$(get_present_fallback_boot_paths)" == /boot/EFI/BOOT/BOOTX64.EFI ]]
''')

    def test_real_verification_timeout_terminates_harmless_process(self):
        for command, expected in (("sleep 5", 124), ('sh -c \'trap "" TERM; sleep 5\'', 137)):
            with self.subTest(command=command):
                result = run_bash(r'''
eval "$original_boot_check"
sudo() {
    [[ "$1 $2 $3" == 'timeout --kill-after=5s 30s' ]] || exit 97
    shift 3
    # Keep the actual timeout implementation; shorten only the test duration.
    command timeout --kill-after=0.1s 0.1s "$@"
}
status=0
''' + f'run_boot_verification_check "Test verification" {command} || status=$?\n' +
                    f'[[ "$status" == {expected} ]]\n')
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                self.assertIn("Verification is incomplete", result.stderr)
                self.assertIn("Test verification", result.stderr)

    def test_verification_check_keeps_json_separate_from_progress(self):
        result = run_bash(r'''
eval "$original_boot_check"
sudo() {
    [[ "$1 $2 $3" == 'timeout --kill-after=5s 30s' ]] || exit 97
    shift 3
    command "$@"
}
report=$(run_boot_verification_check "Test verification" printf '[{"ok":true}]')
[[ "$report" == '[{"ok":true}]' ]]
printf '%s\n' "$report"
''')
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(result.stdout.strip(), '[{"ok":true}]')
        self.assertIn("Test verification", result.stderr)

    def test_unsigned_fallback_is_automatically_signed_and_verified_once(self):
        result = self.run_active_chain_case(r'''
verify_secure_boot_after_uki_rebuild
[[ "$sign_calls" == 1 ]]
[[ "$SECURE_BOOT_AUTOMATIC_ACTION" == 'systemd-boot fallback signed and registered' ]]
[[ "$SECURE_BOOT_OTHER_FILES_WARNING" == false ]]
[[ "$SECURE_BOOT_VERIFY_STATUS" == 'active Secure Boot chain verified' ]]
[[ "$SECURE_BOOT_ACTION" == 'not selected' ]]
verify_secure_boot_after_uki_rebuild
[[ "$sign_calls" == 1 ]]
''')
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("Active bootloader is signed:", result.stdout)
        self.assertIn("Current UKI is signed.", result.stdout)
        self.assertIn("Fallback bootloader is signed:", result.stdout)
        self.assertIn("not checked or signed separately for this UKI boot", result.stdout)

    def test_failed_or_ineffective_fallback_signing_keeps_separate_warning(self):
        for failure in ('sign_fails', 'sign_ineffective'):
            with self.subTest(failure=failure):
                result = self.run_active_chain_case(failure + '=true\n' + r'''
verify_secure_boot_after_uki_rebuild
[[ "$sign_calls" == 1 ]]
[[ "$SECURE_BOOT_OTHER_FILES_WARNING" == true ]]
[[ "$SECURE_BOOT_VERIFY_STATUS" == 'active Secure Boot chain verified, additional boot file warnings' ]]
''')
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                self.assertIn("Fallback bootloader remains unsigned or unverified:", result.stdout)
                self.assertNotIn("Fallback bootloader is signed:", result.stdout)

    def test_active_chain_failure_never_triggers_automatic_signing(self):
        for failure in ('loader_signed=0', 'uki_signed=0', 'VERIFIED_PLYMOUTH_UKIS=()'):
            with self.subTest(failure=failure):
                result = self.run_active_chain_case(failure + '\n' + r'''
if verify_secure_boot_after_uki_rebuild; then exit 90; fi
[[ "$sign_calls" == 0 ]]
[[ "$SECURE_BOOT_VERIFY_STATUS" == 'verification failed' ]]
''')
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                self.assertNotIn("Active Secure Boot chain verified.", result.stdout)

    def test_unidentified_fallback_is_reported_but_never_signed(self):
        result = self.run_active_chain_case(r'''
get_systemd_boot_files() { printf '%s\n' "$test_loader"; }
verify_secure_boot_after_uki_rebuild
[[ "$sign_calls" == 0 ]]
[[ "$SECURE_BOOT_OTHER_FILES_WARNING" == true ]]
''')
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("Fallback is not identified as systemd-boot and was not checked or signed:", result.stdout)

    def test_signed_standalone_kernel_is_reported_without_resigning(self):
        result = self.run_active_chain_case(r'''
fallback_signed=1
kernel_signed=1
verify_secure_boot_after_uki_rebuild
[[ "$sign_calls" == 0 ]]
''')
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("Standalone /boot/vmlinuz-* kernels are not checked or signed separately", result.stdout)
        self.assertNotIn("Standalone kernel is signed:", result.stdout)

    def test_embedded_cmdline_preserves_required_root_and_plymouth_options(self):
        self.check_run(r'''
test_dir=$(mktemp -d -t poedeploy-cmdline-test-XXXXXX)
trap 'rm -rf -- "$test_dir"' EXIT
printf '# persistent boot parameters\nroot=PARTUUID=correct rootflags=subvol=@ rw quiet splash bgrt_disable\n' > "$test_dir/expected"
printf 'root=PARTUUID=correct rootflags=subvol=@ rw quiet splash bgrt_disable extra=yes\0' > "$test_dir/embedded"
uki_cmdline_matches_file "$test_dir/embedded" "$test_dir/expected"
printf 'root=PARTUUID=wrong rootflags=subvol=@ rw quiet splash bgrt_disable\0' > "$test_dir/embedded"
if uki_cmdline_matches_file "$test_dir/embedded" "$test_dir/expected"; then exit 90; fi
printf 'root=PARTUUID=correct rootflags=subvol=@ rw quiet nosplash bgrt_disable\0' > "$test_dir/embedded"
if uki_cmdline_matches_file "$test_dir/embedded" "$test_dir/expected"; then exit 90; fi
''')

    def test_unsigned_standalone_kernel_is_informational_for_verified_uki_boot(self):
        output = self.check_run(r'''
UKI_BOOTED=true
sbctl() { :; }
sudo() {
    printf '%s\n' '[{"file_name":"/boot/test.efi","is_signed":1},
        {"file_name":"/boot/vmlinuz-linux","is_signed":0}]'
}
verify_secure_boot_files /boot/test.efi
[[ "$SECURE_BOOT_OTHER_FILES_WARNING" == false ]]
''')
        self.assertIn("Only the listed boot files were checked", output)

    def test_unsigned_required_uki_fails_even_when_sbctl_exits_zero(self):
        self.check_run(r'''
sbctl() { :; }
sudo() { printf '%s\n' '[{"file_name":"/boot/test.efi","is_signed":0}]'; return 0; }
if verify_secure_boot_files /boot/test.efi; then exit 90; fi
[[ "$SECURE_BOOT_VERIFY_STATUS" == 'verification failed' ]]
''')

    def test_unusable_signature_reports_never_pass(self):
        for report in (
            '[]', 'null', 'invalid JSON',
            '[{"file_name":"/boot/test.efi","is_signed":-1}]',
            '[{"file_name":"/boot/other.efi","is_signed":1}]',
            '[{"file_name":"/boot/test.efi","is_signed":true}]',
        ):
            with self.subTest(report=report):
                self.check_run(r'''
IFS= read -r report
sbctl() { :; }
sudo() { printf '%s\n' "$report"; }
if verify_secure_boot_files /boot/test.efi; then exit 90; fi
[[ "$SECURE_BOOT_VERIFY_STATUS" == 'verification failed' ]]
''', report + '\n')

    def test_signature_verification_disabled_does_not_claim_success(self):
        self.check_run(r'''
firmware_secure_boot_enabled() { return 1; }
verify_secure_boot_after_uki_rebuild
[[ "$SECURE_BOOT_VERIFY_STATUS" == 'not run (Secure Boot not detected as enabled)' ]]
''')

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

    def test_uki_splash_deduplicates_single_quoted_options(self):
        self.check_run(r'''
preset=$(mktemp -t poedeploy-preset-test-XXXXXX)
trap 'rm -f "$preset"' EXIT
printf '%s\n' \
    "PRESETS=('default')" \
    "default_uki='/boot/EFI/Linux/test.efi'" \
    "default_options='--splash /usr/share/poedeploy/uki/poedeploy-black.bmp'" > "$preset"
sudo() { command "$@"; }
set_mkinitcpio_preset_splash "$preset" default /usr/share/poedeploy/uki/poedeploy-black.bmp
[[ $(grep -o -- '--splash' "$preset" | wc -l) == 1 ]]
grep -Fxq 'default_options="--splash /usr/share/poedeploy/uki/poedeploy-black.bmp"' "$preset"
''')

    def test_uki_paths_only_include_active_presets(self):
        self.check_run(r'''
preset_dir=$(mktemp -d -t poedeploy-preset-dir-test-XXXXXX)
trap 'rm -rf -- "$preset_dir"' EXIT
preset="$preset_dir/linux.preset"
printf '%s\n' \
    "PRESETS=('default')" \
    "default_uki='/boot/EFI/Linux/arch-linux.efi'" \
    "fallback_uki='/boot/EFI/Linux/arch-linux-fallback.efi'" > "$preset"
definition=$(declare -f get_configured_uki_paths)
definition=${definition//\/etc\/mkinitcpio.d\/*.preset/$preset_dir\/*.preset}
eval "$definition"
[[ "$(get_configured_uki_paths)" == /boot/EFI/Linux/arch-linux.efi ]]
''')

    def test_splash_native_and_legacy_options_are_normalized_idempotently(self):
        self.check_run(r'''
preset=$(mktemp -t poedeploy-native-preset-XXXXXX)
trap 'rm -f "$preset"' EXIT
printf '%s\n' \
    "ALL_splash='/shared.bmp'" \
    "default_splash='/old.bmp'" \
    "default_options='-S autodetect --splash /old.bmp --splash=/duplicate.bmp'" \
    "fallback_options='-S autodetect'" > "$preset"
sudo() { command "$@"; }
set_mkinitcpio_preset_splash "$preset" default /black.bmp
first=$(< "$preset")
set_mkinitcpio_preset_splash "$preset" default /black.bmp
[[ "$(< "$preset")" == "$first" ]]
source "$preset"
[[ "$default_splash" == /black.bmp ]]
[[ "$default_options" == '-S autodetect' ]]
[[ "$ALL_splash" == /shared.bmp ]]
[[ "$fallback_options" == '-S autodetect' ]]
''')

    @unittest.skipUnless(shutil.which("objcopy"), "requires GNU objcopy")
    @unittest.skipUnless(Path("/usr/lib/systemd/boot/efi/linuxx64.efi.stub").is_file(), "requires a systemd EFI stub")
    def test_real_pe_cmdline_extraction_and_absent_section(self):
        self.check_run(r'''
test_dir=$(mktemp -d -t poedeploy-pe-test-XXXXXX)
trap 'rm -rf -- "$test_dir"' EXIT
printf 'root=PARTUUID=test quiet splash\0' > "$test_dir/input"
objcopy --add-section ".cmdline=$test_dir/input" \
    /usr/lib/systemd/boot/efi/linuxx64.efi.stub "$test_dir/test.efi"
before=$(sha256sum "$test_dir/test.efi")
extract_uki_section "$test_dir/test.efi" .cmdline "$test_dir/cmdline"
cmp "$test_dir/input" "$test_dir/cmdline"
[[ "$(sha256sum "$test_dir/test.efi")" == "$before" ]]
if extract_uki_section "$test_dir/test.efi" .missing "$test_dir/missing"; then exit 90; fi
''')

    def run_plymouth_case(self, body, stdin="1\n"):
        return run_bash(r'''
UKI_ENABLED=true
events=()
install_plymouth() { :; }
install_uki_black_splash() { UKI_SPLASH_PATH=/black.bmp; }
prepare_uki_kernel_cmdline() { :; }
configure_mkinitcpio_plymouth() { :; }
configure_bootloader_plymouth() { :; }
install_poedeploy_plymouth_theme() { :; }
configure_uki_splash() { :; }
get_remote_plymouth_themes() { printf 'poedeploy\n'; }
plymouth-set-default-theme() { printf 'poedeploy\n'; }
sudo() {
    case "$*" in
        'plymouth-set-default-theme poedeploy') events+=(select) ;;
        'mkinitcpio -P') events+=(build) ;;
        *) exit 97 ;;
    esac
}
verify_uki_plymouth_setup() { events+=(theme_check); }
verify_secure_boot_after_uki_rebuild() { events+=(signature_check); }
''' + body, stdin)

    def test_plymouth_selects_then_rebuilds_once(self):
        result = self.run_plymouth_case(r'''
setup_plymouth
[[ "${events[*]}" == 'select build theme_check signature_check' ]]
''')
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_plymouth_keep_current_still_rebuilds_once(self):
        result = self.run_plymouth_case(r'''
setup_plymouth
[[ "${events[*]}" == 'build theme_check signature_check' ]]
''', "0\n")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_plymouth_failure_stops_dependents_and_still_checks_signatures(self):
        result = self.run_plymouth_case(r'''
verify_uki_plymouth_setup() { return 1; }
verify_secure_boot_after_uki_rebuild() { echo SIGNATURE_CHECKED; }
SELECTED_SETUP_MODULES=([plymouth]=true [secure_boot]=true)
run_setup_module() {
    case "$1" in
        plymouth) setup_plymouth ;;
        *) echo MUST_NOT_RUN ;;
    esac
}
run_selected_setup_modules
echo MUST_NOT_REPORT_SUCCESS
''')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("SIGNATURE_CHECKED", result.stdout)
        self.assertNotIn("MUST_NOT", result.stdout)

    def test_plymouth_signature_failure_propagates(self):
        result = self.run_plymouth_case(r'''
verify_secure_boot_after_uki_rebuild() { return 1; }
setup_plymouth
echo MUST_NOT_REPORT_SUCCESS
''')
        self.assertNotEqual(result.returncode, 0)
        self.assertNotIn("MUST_NOT", result.stdout)

    def test_plymouth_build_failure_stops_verification(self):
        result = self.run_plymouth_case(r'''
sudo() { [[ "$1" == plymouth-set-default-theme ]]; }
verify_uki_plymouth_setup() { echo MUST_NOT_VERIFY; }
setup_plymouth
echo MUST_NOT_REPORT_SUCCESS
''')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("boot image rebuild failed", result.stdout)
        self.assertNotIn("MUST_NOT", result.stdout)

    def test_plymouth_selection_eof_does_not_rebuild(self):
        result = self.run_plymouth_case(r'''
if setup_plymouth; then exit 90; fi
[[ ${#events[@]} == 0 ]]
''', "")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_protected_uki_is_staged_through_sudo_for_verification(self):
        self.check_run(r'''
verify_dir=$(mktemp -d -t poedeploy-uki-verify-test-XXXXXX)
trap 'rm -rf -- "$verify_dir"' EXIT
destination="$verify_dir/uki.efi"
sudo() {
    [[ "$1" == install ]]
    [[ "$*" == *' /boot/EFI/Linux/arch-linux.efi '* ]]
    printf 'MZ-protected-uki' > "${@: -1}"
}
stage_uki_for_verification /boot/EFI/Linux/arch-linux.efi "$destination"
[[ "$(< "$destination")" == MZ-protected-uki ]]
''')

    def test_plymouth_checks_consume_producer_output_after_match(self):
        self.check_run(r'''
plymouth-set-default-theme() {
    printf 'poedeploy\n'
    for ((line = 0; line < 20000; line++)); do
        printf 'theme-%s\n' "$line"
    done
}
lsinitcpio() {
    printf 'usr/share/plymouth/themes/poedeploy/poedeploy.plymouth\n'
    for ((line = 0; line < 20000; line++)); do
        printf 'usr/lib/module-%s\n' "$line"
    done
}
plymouth_theme_is_available poedeploy
uki_contains_plymouth_theme /protected/arch-linux.efi poedeploy
''')

    def test_hybrid_gpu_detection_excludes_storage_with_3d_in_its_name(self):
        output = self.check_run(r'''
lspci() {
    printf '%s\n' \
        '00:02.0 VGA compatible controller: Intel Corporation CoffeeLake-H GT2 [UHD Graphics 630]' \
        '01:00.0 3D controller: NVIDIA Corporation TU116M [GeForce GTX 1660 Ti Mobile] (rev a1)' \
        '06:00.0 Non-Volatile memory controller: Sandisk Corp SanDisk Ultra 3D / WD Blue SN570 NVMe SSD (DRAM-less)'
}
detect_gpu
[[ "$GPU_VENDOR" == NVIDIA ]]
[[ "$GPU_MODEL" == 'CoffeeLake-H GT2 [UHD Graphics 630] + TU116M [GeForce GTX 1660 Ti Mobile] (rev a1)' ]]
''')
        self.assertNotIn("Non-Volatile memory controller", output)
        self.assertNotIn("SanDisk Ultra 3D", output)


@unittest.skipUnless(shutil.which("gum"), "gum is needed for real checklist tests")
class ChecklistTerminalTests(unittest.TestCase):
    def test_real_keyboard_selection_and_cancellation(self):
        cases = (
            ((b"\r",), b"\x1b[Bx\r", b"CHOSEN:yay", 100),
            ((b"\r",), b"\x1b[Bx\r", b"CHOSEN:yay", 40),
            ((b"\r",), b"\x1b", b"CANCELLED", 100),
            ((b"\r",), b"\x03", b"CANCELLED", 100),
            ((b"\x1b[B", b"\r"), None, b"MODE:full", 100),
            ((b"\x1b[B", b"\x1b[B", b"\r"), None, b"CANCELLED", 100),
            ((b"\x1b",), None, b"CANCELLED", 100),
            ((b"\x03",), None, b"CANCELLED", 100),
        )
        for welcome_keys, keys, expected, width in cases:
            with self.subTest(welcome_keys=welcome_keys, keys=keys, width=width):
                pid, fd = pty.fork()
                if pid == 0:
                    os.environ["TERM"] = "xterm-256color"
                    os.environ.pop("NO_COLOR", None)
                    termios.tcsetwinsize(0, (30, width))
                    body = PRELUDE + r'''
SCRIPT_VERSION=vtest
show_header
if choose_setup_modules; then
    printf 'MODE:%s\n' "$RUN_MODE"
    printf 'CHOSEN:%s\n' "${!SELECTED_SETUP_MODULES[@]}"
else
    [[ ${#SELECTED_SETUP_MODULES[@]} == 0 ]] || exit 91
    echo CANCELLED
fi
'''
                    os.execvp("bash", ["bash", "--noprofile", "--norc", "-c",
                                       body, "test", SCRIPT])
                output = b""
                answered = pressed = False
                done = 0
                status = None
                deadline = time.monotonic() + 8
                try:
                    while time.monotonic() < deadline:
                        if select.select([fd], [], [], 0.05)[0]:
                            try:
                                output += os.read(fd, 8192)
                            except OSError as error:
                                if error.errno != errno.EIO:
                                    raise
                        if b"What would you like to do?" in output and not answered:
                            for key in welcome_keys:
                                os.write(fd, key)
                                time.sleep(0.1)
                            answered = True
                        if keys is not None and b"Setup sections" in output and not pressed:
                            if keys == b"\x1b[Bx\r":
                                # Separate keypresses, rather than one pasted chunk.
                                for key in (b"\x1b[B", b"x", b"\r"):
                                    os.write(fd, key)
                                    time.sleep(0.1)
                            else:
                                os.write(fd, keys)
                            pressed = True
                        done, status = os.waitpid(pid, os.WNOHANG)
                        if done:
                            # The child can exit while its final output is still
                            # buffered in the PTY, especially after key delays.
                            while select.select([fd], [], [], 0.05)[0]:
                                try:
                                    chunk = os.read(fd, 8192)
                                except OSError as error:
                                    if error.errno != errno.EIO:
                                        raise
                                    break
                                if not chunk:
                                    break
                                output += chunk
                            break
                    else:
                        self.fail("Checklist timed out: " + output.decode(errors="replace"))
                finally:
                    if not done:
                        os.killpg(pid, signal.SIGTERM)
                        os.waitpid(pid, 0)
                    os.close(fd)
                self.assertEqual(os.waitstatus_to_exitcode(status), 0, output)
                self.assertTrue(answered, output)
                if keys is not None:
                    self.assertTrue(pressed, output)
                self.assertIn(expected, output)
                self.assertIn(b'\x1b[38;2;0;79;254m', output)
                if width == 40:
                    self.assertIn(b'PoeDeploy', output)
                    self.assertNotIn(b'/ __ \\____', output)
                else:
                    self.assertIn(b'/ __ \\____', output)


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
