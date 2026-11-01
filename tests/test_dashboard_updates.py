"""Run dashboard update/download paths with local fixtures, without the network."""
import io
import os
from pathlib import Path
import subprocess
import tarfile
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
UPDATERS = {
    'pendash': ROOT / 'apps/pendash/dashboard/scripts/update.sh',
    'poedash': ROOT / 'apps/poedash/assets/scripts/update.sh',
}


class FixtureCommands(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='dashboard update ')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.bin = self.root / 'bin'
        self.bin.mkdir()
        self.downloads = self.root / 'downloads'
        self.downloads.mkdir()
        self.record = self.root / 'installer-arguments'
        self.git_record = self.root / 'git-arguments'
        self.env = os.environ | {
            'PATH': str(self.bin) + os.pathsep + os.environ['PATH'],
            'TMPDIR': str(self.downloads), 'RECORD': str(self.record),
            'GIT_RECORD': str(self.git_record),
        }

    def command(self, name, body):
        path = self.bin / name
        path.write_text('#!/usr/bin/env bash\nset -euo pipefail\n' + body + '\n')
        path.chmod(0o755)

    def run_script(self, script, *args):
        result = subprocess.run(['bash', str(script), *args], env=self.env,
            stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=10)
        self.assertEqual(list(self.downloads.iterdir()), [], 'download directory must be cleaned up')
        return result


class DashboardUpdates(FixtureCommands):
    def setUp(self):
        super().setUp()
        self.command('git', '''
printf '%s\\n' "$@" >> "$GIT_RECORD"
[[ "${FAIL_DOWNLOAD:-0}" == 0 ]] || exit 22
[[ "$1" == clone ]] || exit 97
destination="${@: -1}"
mkdir -p "$destination"
cat > "$destination/poedeploy.sh" <<'INSTALLER'
#!/usr/bin/env bash
printf '%s\\n' "$@" > "$RECORD"
exit "${INSTALL_EXIT:-0}"
INSTALLER
''')

    def test_both_updates_use_poedeploy_main_and_the_correct_dashboard(self):
        for slug, script in UPDATERS.items():
            with self.subTest(slug=slug):
                self.git_record.unlink(missing_ok=True)
                result = self.run_script(script)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(self.record.read_text().splitlines(), ['--install-dashboard', slug])
                args = self.git_record.read_text().splitlines()
                self.assertEqual(args[:5], ['clone', '--depth=1', '--single-branch', '--branch', 'main'])
                self.assertIn('https://github.com/cyberpoe-uk/PoeDeploy.git', args)
                self.assertNotIn('ls-remote', args)

    def test_failed_download_never_runs_the_installer(self):
        self.env['FAIL_DOWNLOAD'] = '1'
        for script in UPDATERS.values():
            with self.subTest(script=script):
                result = self.run_script(script)
                self.assertNotEqual(result.returncode, 0)
                self.assertFalse(self.record.exists())

    def test_installer_failure_is_preserved(self):
        self.env['INSTALL_EXIT'] = '42'
        for script in UPDATERS.values():
            with self.subTest(script=script):
                self.assertEqual(self.run_script(script).returncode, 42)


@unittest.skipIf(os.geteuid() == 0, 'Public installers intentionally refuse root')
class DashboardBootstraps(FixtureCommands):
    def setUp(self):
        super().setUp()
        self.archive = self.root / 'fixture.tar.gz'
        self.env['FIXTURE'] = str(self.archive)
        self.command('pacman', 'exit 98')
        self.command('curl', '''
printf '%s\\n' "$@" > "$GIT_RECORD"
[[ "${FAIL_DOWNLOAD:-0}" == 0 ]] || exit 22
while (( $# )); do
    if [[ "$1" == --output ]]; then cp "$FIXTURE" "$2"; exit 0; fi
    shift
done
exit 97
''')

    def archive_for(self, slug, valid=True):
        files = {'install.sh': '#!/usr/bin/env bash\nprintf "%s\\n" "$@" > "$RECORD"\nexit "${INSTALL_EXIT:-0}"\n'}
        if valid:
            files[slug + '.py'] = ''
            if slug == 'pendash':
                files.update({'dashboard/eww.yuck': '', 'assets/custom.lua': ''})
            else:
                files['assets/settings.example.json'] = ''
        with tarfile.open(self.archive, 'w:gz') as archive:
            for name, content in files.items():
                data = content.encode()
                info = tarfile.TarInfo(f'PoeDeploy-main/apps/{slug}/{name}')
                info.size = len(data)
                archive.addfile(info, io.BytesIO(data))

    def test_install_and_refresh_use_the_bundled_application_and_forward_arguments(self):
        for slug in UPDATERS:
            self.archive_for(slug)
            for update in (False, True):
                with self.subTest(slug=slug, update=update):
                    args = ['--dry-run']
                    if update:
                        args.append('--update-dashboard')
                    args += ['--example-option', 'a path with spaces']
                    result = self.run_script(ROOT / 'apps' / slug / 'bootstrap.sh', *args)
                    self.assertEqual(result.returncode, 0, result.stderr)
                    expected = ['--non-interactive' if arg == '--update-dashboard' and slug == 'poedash' else arg for arg in args]
                    self.assertEqual(self.record.read_text().splitlines(), expected)
                    self.assertIn('https://codeload.github.com/cyberpoe-uk/PoeDeploy/tar.gz/refs/heads/main', self.git_record.read_text())

    def test_failed_download_and_incomplete_archive_never_run_installer(self):
        for slug in UPDATERS:
            for invalid_archive in (False, True):
                with self.subTest(slug=slug, invalid_archive=invalid_archive):
                    self.archive_for(slug, valid=not invalid_archive)
                    self.env['FAIL_DOWNLOAD'] = '0' if invalid_archive else '1'
                    result = self.run_script(ROOT / 'apps' / slug / 'bootstrap.sh')
                    self.assertNotEqual(result.returncode, 0)
                    self.assertFalse(self.record.exists())

    def test_installer_failure_is_preserved(self):
        self.env['INSTALL_EXIT'] = '42'
        for slug in UPDATERS:
            with self.subTest(slug=slug):
                self.archive_for(slug)
                self.assertEqual(self.run_script(ROOT / 'apps' / slug / 'bootstrap.sh').returncode, 42)


@unittest.skipIf(os.geteuid() == 0 or not Path('/etc/arch-release').exists(), 'PoeDeploy bootstrap requires a normal Arch user')
class PoeDeployBootstrap(FixtureCommands):
    def setUp(self):
        super().setUp()
        self.command('sudo', 'exit 98')
        self.command('pacman', 'exit 98')
        self.command('git', '''
printf '%s\\n' "$@" >> "$GIT_RECORD"
if [[ "$1" == ls-remote ]]; then
    printf 'fixture\\trefs/tags/v9.9.9\\n'
    exit 0
fi
[[ "$1" == clone ]] || exit 97
destination="${@: -1}"
mkdir -p "$destination"
printf 'v9.9.9\\n' > "$destination/VERSION"
cat > "$destination/poedeploy.sh" <<'INSTALLER'
#!/usr/bin/env bash
printf '%s\\n' "$@" > "$RECORD"
INSTALLER
''')

    def test_dashboard_actions_use_main_while_full_setup_uses_stable(self):
        for slug in ('pendash', 'poedash', None):
            with self.subTest(slug=slug):
                self.git_record.unlink(missing_ok=True)
                args = ['--install-dashboard', slug] if slug else []
                result = self.run_script(ROOT / 'poedeploy-latest', *args)
                self.assertEqual(result.returncode, 0, result.stderr)
                git_args = self.git_record.read_text().splitlines()
                branch = git_args[git_args.index('--branch') + 1]
                self.assertEqual(branch, 'main' if slug else 'v9.9.9')
                self.assertEqual('ls-remote' in git_args, slug is None)


if __name__ == '__main__':
    unittest.main()
