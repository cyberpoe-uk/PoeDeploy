"""Reversible planning: fake every choice, never run a package transaction."""
import unittest
from test_workflows import run_bash


class Navigation(unittest.TestCase):
    def check(self, body):
        result = run_bash(body)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        return result

    def test_full_setup_skips_unmatched_huawei_without_any_privileged_commands(self):
        self.check(r'''
matebook_audio_product_matches() { return 1; }
matebook_audio_subsystem_matches() { exit 91; }
ui_nav_choose() {
    case "$1" in
        Welcome) echo 'Full setup' ;;
        'Optional applications') : ;;
        'Review plan') echo 'Install selected sections' ;;
        *) exit 92 ;;
    esac
}
interactive_plan
[[ "$RUN_MODE" == full && "${SELECTED_SETUP_MODULES[matebook_audio]:-false}" == false ]]
[[ ${#SELECTED_SETUP_MODULES[@]} == $((${#SETUP_MODULE_IDS[@]} - 1)) ]]
''')

    def test_matching_huawei_is_in_full_plan_but_still_requires_its_runtime_opt_in(self):
        self.check(r'''
matebook_audio_product_matches() { return 0; }
matebook_audio_subsystem_matches() { return 0; }
ui_nav_choose() {
    case "$1" in Welcome) echo 'Full setup' ;; 'Optional applications') : ;; 'Review plan') echo 'Install selected sections' ;; esac
}
interactive_plan
[[ "${SELECTED_SETUP_MODULES[matebook_audio]}" == true ]]
''')

    def test_escape_and_backspace_revisit_previous_choices(self):
        self.check(r'''
navigation_index=$(mktemp)
echo 0 > "$navigation_index"
ui_nav_choose() {
    local i
    read -r i < "$navigation_index"
    echo "$((i + 1))" > "$navigation_index"
    case "$i" in
        0) [[ "$1" == Welcome ]]; echo 'Choose sections' ;;
        1) echo 'System update' ;;
        2) [[ "$1" == 'Review plan' ]]; return 125 ;;
        3) [[ "$1" == 'Setup sections' && "$3" == *'System update'* ]]; return 126 ;;
        4) [[ "$1" == Welcome ]]; echo 'Choose sections' ;;
        5) [[ "$3" == *'System update'* ]]; echo 'System update' ;;
        6) echo 'Install selected sections' ;;
        *) exit 93 ;;
    esac
}
interactive_plan
[[ "${SELECTED_SETUP_MODULES[update]}" == true && ${#SELECTED_SETUP_MODULES[@]} == 1 ]]
rm "$navigation_index"
''')

    def test_subtitle_back_edits_apps_instead_of_installing_old_selection(self):
        self.check(r'''
app_round=$(mktemp)
echo 0 > "$app_round"
ui_nav_choose() {
    case "$1" in
        Welcome) echo 'Choose sections' ;;
        'Setup sections') echo 'Optional applications' ;;
        'Optional applications')
            local n
            read -r n < "$app_round"
            echo "$((n + 1))" > "$app_round"
            if ((n == 0)); then echo 'PoeDash (dashboard)'; else echo 'Firefox'; fi ;;
        'Review plan') echo 'Install selected sections' ;;
    esac
}
ui_nav_prompt() { return 125; }
interactive_plan
[[ "${SELECTED_PACKAGES[*]}" == firefox ]]
rm "$app_round"
''')

    def test_backspace_at_welcome_does_not_cancel_until_escape(self):
        self.check(r'''nav_counter=$(mktemp)
echo 0 > "$nav_counter"
ui_nav_choose() {
    local n
    read -r n < "$nav_counter"
    echo "$((n + 1))" > "$nav_counter"
    if ((n == 0)); then return 126; else return 125; fi
}
if interactive_plan; then exit 95; fi
[[ "$(cat "$nav_counter")" == 2 ]]
rm "$nav_counter"
''')

    def test_root_backspace_stays_at_start_and_ctrl_c_aborts(self):
        self.check(r'''
ui_nav_choose() { return 130; }
if interactive_plan; then exit 94; else [[ "$?" == 130 ]]; fi
''')


if __name__ == '__main__':
    unittest.main()
