"""Dashboard controls must keep their identity and refresh without setup actions."""
import importlib.util
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from test_workflows import run_bash

ROOT = Path(__file__).resolve().parents[1]
CONTROLS = {
    'poedash': ROOT / 'apps/poedash/assets/scripts/dashboard-control.py',
    'pendash': ROOT / 'apps/pendash/dashboard/scripts/dashboard-control.py',
}


class DashboardRouting(unittest.TestCase):
    def test_provider_identity_does_not_depend_on_directory_name(self):
        for slug, script in CONTROLS.items():
            with self.subTest(slug=slug), tempfile.TemporaryDirectory() as tmp:
                spec = importlib.util.spec_from_file_location('control_' + slug, script)
                control = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(control)
                root = Path(tmp) / 'custom-name'
                root.mkdir()
                (root / 'dashboard-id').write_text(slug + '\n')
                with patch.dict(os.environ, {'XDG_CONFIG_HOME': tmp}), patch.object(control.subprocess, 'Popen') as launch:
                    control.update(root)
                self.assertEqual(control.DASHBOARD_ID, slug)
                argv = launch.call_args.args[0]
                self.assertEqual(argv[3], 'Update ' + control.DASHBOARD_NAME)
                self.assertEqual(argv[4:], ['bash', str(root / 'scripts/update.sh'), str(root)])

    def test_stale_controls_and_mismatched_installed_files_never_launch_updates(self):
        for slug, script in CONTROLS.items():
            other = 'pendash' if slug == 'poedash' else 'poedash'
            for mismatch in ('selection', 'installed identity'):
                with self.subTest(slug=slug, mismatch=mismatch), tempfile.TemporaryDirectory() as tmp:
                    spec = importlib.util.spec_from_file_location('control_' + slug, script)
                    control = importlib.util.module_from_spec(spec)
                    spec.loader.exec_module(control)
                    root = Path(tmp) / 'dashboard'
                    root.mkdir()
                    (root / 'dashboard-id').write_text(other if mismatch == 'installed identity' else slug)
                    selection = Path(tmp) / 'poedeploy/dashboard'
                    selection.parent.mkdir()
                    selection.write_text(other if mismatch == 'selection' else slug)
                    with patch.dict(os.environ, {'XDG_CONFIG_HOME': tmp}), patch.object(control.subprocess, 'Popen') as launch:
                        with self.assertRaises(RuntimeError):
                            control.update(root)
                        launch.assert_not_called()

    def test_old_pendash_button_cannot_refresh_selected_poedash(self):
        result = run_bash(r'''
config_root=$(mktemp -d)
trap 'rm -rf -- "$config_root"' EXIT
export XDG_CONFIG_HOME="$config_root"
mkdir -p "$config_root/poedeploy"
printf 'poedash\n' > "$config_root/poedeploy/dashboard"
load_version() { :; }
check_not_root() { :; }
check_arch() { :; }
pd_logger_init() { exit 91; }
install_bundled_dashboard_application() { exit 92; }
if main --install-dashboard pendash; then exit 93; fi
''')
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn('selected dashboard is poedash', result.stdout + result.stderr)

    def test_refresh_dispatch_disables_package_setup_for_both_dashboards(self):
        result = run_bash(r'''
load_version() { :; }
check_not_root() { :; }
check_arch() { :; }
validate_dashboard_update_target() { :; }
pd_logger_init() { :; }
install_bundled_dashboard_application() {
    case "$2" in
        poedash) [[ "$*" == 'PoeDash update poedash --skip-deps --non-interactive' ]] || exit 91 ;;
        pendash) [[ "$*" == 'PenDash update pendash --update-dashboard --skip-packages' ]] || exit 92 ;;
        *) exit 93 ;;
    esac
}
main --install-dashboard poedash
main --install-dashboard pendash
''')
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_cancelled_installer_reports_failure_without_an_unset_log_error(self):
        result = run_bash(r'''
unset POEDEPLOY_LOG
ensure_command_dependencies() { :; }
ui_run_interactive() { return 130; }
install_bundled_dashboard_application 'PoeDash update' poedash --skip-deps --non-interactive
[[ "${FAILED_PACKAGES[*]}" == 'PoeDash update' ]]
''')
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn('installation failed', result.stdout + result.stderr)
        self.assertNotIn('unbound variable', result.stdout + result.stderr)

    def test_refresh_does_not_bootstrap_packages_or_an_aur_helper(self):
        result = run_bash(r'''
ensure_command_dependencies() { exit 91; }
install_yay() { exit 92; }
command() {
    case "$*" in '-v eww'|'-v paru'|'-v yay') return 1 ;; esac
    builtin command "$@"
}
ui_run_interactive() { :; }
install_bundled_dashboard_application 'PoeDash update' poedash --skip-deps --non-interactive
install_bundled_dashboard_application 'PenDash update' pendash --update-dashboard --skip-packages
[[ ${#FAILED_PACKAGES[@]} == 0 ]]
''')
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_missing_python_on_refresh_fails_without_installing_it(self):
        result = run_bash(r'''
ensure_command_dependencies() { exit 91; }
install_yay() { exit 92; }
ui_run_interactive() { exit 93; }
command() {
    if [[ "$*" == '-v python3' ]]; then return 1; fi
    builtin command "$@"
}
install_bundled_dashboard_application 'PoeDash update' poedash --skip-deps --non-interactive
[[ "${FAILED_PACKAGES[*]}" == 'PoeDash update' ]]
''')
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn('needs Python 3', result.stdout + result.stderr)


if __name__ == '__main__':
    unittest.main()
