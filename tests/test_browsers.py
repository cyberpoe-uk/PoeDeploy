"""Browser fixtures and mocked XDG commands never change desktop settings."""

import os
from pathlib import Path
import subprocess
import tempfile
import unittest

from test_workflows import PRELUDE, SCRIPT, run_bash


class BrowserDiscoveryTests(unittest.TestCase):
    def test_desktop_discovery_respects_precedence_and_real_launchers(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            user = root / 'user'
            system = root / 'system'
            exports = user / 'flatpak/exports/share'
            for base in (user, system, exports):
                (base / 'applications').mkdir(parents=True)

            def entry(base, filename, name, extra='', category='WebBrowser', executable='/bin/true'):
                path = base / 'applications' / filename
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(
                    f'[Desktop Entry]\nType=Application\nName={name}\n'
                    f'Exec={executable} %U\nCategories={category};\n{extra}',
                )

            entry(system, 'firefox.desktop', 'Firefox')
            entry(system, 'vendor/zen.desktop', 'Zen')
            entry(exports, 'org.example.Browser.desktop', 'Flatpak Browser')
            entry(system, 'custom.desktop', 'Old Name')
            entry(user, 'custom.desktop', 'User Browser')
            entry(system, 'hidden.desktop', 'Hidden Browser')
            (user / 'applications/hidden.desktop').write_text('[Desktop Entry]\nHidden=true\n')
            entry(system, 'nodisplay.desktop', 'Invisible Browser', 'NoDisplay=true\n')
            entry(system, 'missing.desktop', 'Missing', executable='/not/installed/browser')
            entry(system, 'try.desktop', 'Missing TryExec', 'TryExec=/not/installed/browser\n')
            entry(system, 'editor.desktop', 'HTML Editor', 'MimeType=text/html;\n', category='TextEditor')
            entry(system, 'mime.desktop', 'MIME Browser',
                  'MimeType=x-scheme-handler/http;x-scheme-handler/https;\n', category='Network')
            entry(system, 'actions.desktop', 'Main Browser',
                  '[Desktop Action Private]\nName=Private Window\nExec=/not/installed/browser\n')
            entry(system, 'quoted.desktop', 'Quoted Browser', executable='"/bin/true"')
            result = subprocess.run(
                ['bash', '-c', PRELUDE + r'''
find() {
    [[ "$1" == "$BROWSER_FIXTURE/"* ]] || return 0
    command find "$@"
}
discover_installed_browsers
''', 'test', SCRIPT],
                env={**os.environ, 'XDG_DATA_HOME': str(user),
                     'XDG_DATA_DIRS': str(system), 'BROWSER_FIXTURE': str(root)},
                text=True, capture_output=True, timeout=10,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            found = dict(line.split('\t') for line in result.stdout.splitlines())
            self.assertEqual(found, {
                'Firefox': 'firefox.desktop', 'Zen': 'vendor-zen.desktop',
                'Flatpak Browser': 'org.example.Browser.desktop',
                'User Browser': 'custom.desktop', 'MIME Browser': 'mime.desktop',
                'Main Browser': 'actions.desktop', 'Quoted Browser': 'quoted.desktop',
            })


MOCK_XDG = r'''
discover_installed_browsers() {
    printf 'Zen Browser\tapp.zen_browser.zen.desktop\nFirefox\tfirefox.desktop\n'
}
xdg-settings() {
    case "$1" in
        get) printf 'old-browser.desktop\n' ;;
        set) printf 'SET_BROWSER %s\n' "$3" ;;
        check) printf '%s\n' "${CHECK_RESULT:-true}" ;;
    esac
}
declare -A mime_defaults=()
xdg-mime() {
    if [[ "$1" == default ]]; then
        printf 'SET_MIME %s %s\n' "$2" "$3"
        mime_defaults[$3]="$2"
    else
        printf '%s\n' "${mime_defaults[$3]:-old-browser.desktop}"
    fi
}
'''


class BrowserSelectionTests(unittest.TestCase):
    def test_keep_default_and_eof_never_write(self):
        for answer in ('\n', '0\n', ''):
            with self.subTest(answer=answer):
                result = run_bash(MOCK_XDG + 'select_default_browser', answer)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertIn('Current default browser: old-browser.desktop', result.stdout)
                self.assertNotIn('SET_', result.stdout)

    def test_selection_sets_and_verifies_external_links_and_html(self):
        result = run_bash(MOCK_XDG + 'select_default_browser', '2\n')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('SET_BROWSER app.zen_browser.zen.desktop', result.stdout)
        for mime in ('x-scheme-handler/http', 'x-scheme-handler/https', 'text/html', 'application/xhtml+xml'):
            self.assertIn(f'SET_MIME app.zen_browser.zen.desktop {mime}', result.stdout)
        self.assertNotIn('mailto', result.stdout)
        self.assertIn('associations verified', result.stdout)

    def test_false_verification_does_not_report_success(self):
        for change in (
            'CHECK_RESULT=false',
            'xdg-mime() { [[ "$1" != query ]] || printf "wrong.desktop\\n"; }',
            'xdg-settings() { [[ "$1" != set ]]; }',
        ):
            with self.subTest(change=change):
                result = run_bash(MOCK_XDG + change + '\nselect_default_browser', '1\n')
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertIn('could not be fully configured', result.stdout)
                self.assertNotIn('Default browser set to', result.stdout)

    def test_no_browsers_preserves_settings(self):
        result = run_bash(MOCK_XDG + 'discover_installed_browsers() { :; }\nselect_default_browser')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('No installed browser desktop entries', result.stdout)
        self.assertNotIn('SET_', result.stdout)

    def test_invalid_input_and_leading_zero(self):
        result = run_bash(MOCK_XDG + 'select_default_browser', '08\n999999999999999999999999\n01\n')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.count('Invalid selection.'), 2)
        self.assertIn('Default browser set to Firefox', result.stdout)
