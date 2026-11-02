"""Package popup behavior without installing packages or opening the live launcher."""
import gzip
import importlib.util
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('packages', ROOT / 'apps/poedash/assets/scripts/packages.py')
packages = importlib.util.module_from_spec(spec)
spec.loader.exec_module(packages)


class PackageDataTests(unittest.TestCase):
    def test_index_is_sorted_sanitized_and_cached_for_per_letter_search(self):
        with tempfile.TemporaryDirectory() as tmp:
            cache = Path(tmp)
            with patch.object(packages, 'fetch', return_value=gzip.compress(b'# AUR names\nzebra\nalpha\nalpha\ninvalid;name\n')) as fetch:
                self.assertEqual(packages.aur_names(cache), (['alpha', 'zebra'], ''))
                self.assertEqual(packages.aur_names(cache), (['alpha', 'zebra'], ''))
                fetch.assert_called_once()

    def test_network_failure_uses_stale_index_with_explicit_status(self):
        with tempfile.TemporaryDirectory() as tmp:
            cache = Path(tmp)
            (cache / 'aur-names.json').write_text('["alpha"]')
            with patch.object(packages, 'json_cache', return_value=None), \
                 patch.object(packages, 'fetch', side_effect=OSError('offline')):
                names, note = packages.aur_names(cache)
                self.assertEqual(names, ['alpha'])
                self.assertIn('offline', note)
            (cache / 'aur-names.json').unlink()
            with patch.object(packages, 'fetch', side_effect=OSError('offline')):
                self.assertEqual(packages.aur_names(cache)[0], [])

    def test_repo_priority_and_deduplication(self):
        text = 'core alpha 2-1\nextra alpha 3-1\nextra zebra 1-1 [installed]\n'
        with patch.object(packages, 'run', return_value=text):
            data = packages.repository_packages()
        self.assertEqual(data['alpha']['source'], 'core')
        self.assertEqual(data['alpha']['version'], '2-1')
        self.assertEqual(data['zebra']['version'], '1-1')

    def test_catalog_alphabetical_with_repo_preferred_and_aur_versions(self):
        repo = {'zebra': dict(name='zebra', source='extra', version='1', aur=False)}
        with patch.object(packages, 'installed_packages', return_value={'alpha': '1'}), \
             patch.object(packages, 'repository_packages', return_value=repo), \
             patch.object(packages, 'repository_updates', return_value=({}, 'cached')), \
             patch.object(packages, 'aur_names', return_value=(['zebra', 'alpha'], '')), \
             patch.object(packages, 'aur_info', return_value={'alpha': '2'}):
            rows, installed, _ = packages.catalog('both')
        self.assertEqual([p['name'] for p in rows], ['alpha', 'zebra'])
        self.assertEqual(rows[1]['source'], 'extra')
        self.assertEqual(rows[0]['version'], '2')

    def test_fresh_update_check_is_cached_and_does_not_sync_system_database(self):
        with tempfile.TemporaryDirectory() as tmp, \
             patch.object(packages.shutil, 'which', return_value='/usr/bin/checkupdates'), \
             patch.object(packages, 'run', return_value='alpha 1 -> 2\n') as command:
            cache = Path(tmp)
            self.assertEqual(packages.repository_updates(cache)[0], {'alpha': '2'})
            self.assertEqual(packages.repository_updates(cache)[0], {'alpha': '2'})
            command.assert_called_once_with(['checkupdates'], timeout=30, codes=(0, 2))

    def test_installed_update_and_unknown_states_are_distinct(self):
        item = dict(name='alpha', source='core', version='2', aur=False)
        self.assertEqual(packages.status(item, {}), 'Not installed')
        with patch.object(packages, 'compare', return_value=1):
            self.assertIn('Update available', packages.status(item, {'alpha': '1'}))
        with patch.object(packages, 'compare', return_value=0):
            self.assertIn('up to date', packages.status(item, {'alpha': '2'}))
        item['version'] = None
        self.assertIn('status unknown', packages.status(item, {'alpha': '1'}))

    def test_rows_use_available_icons_or_generic_fallback_and_strip_controls(self):
        item = dict(name='alpha', source='core', version='2', aur=False)
        self.assertIn('\0icon\x1fapp-icon', packages.row(item, {}, {'alpha': 'app-icon'}))
        self.assertIn('\0icon\x1fpackage-x-generic', packages.row(item, {}, {}))
        self.assertEqual(packages.clean('one\n\0two'), 'one  two')

    def test_aur_rpc_validates_metadata_and_encodes_names(self):
        data = {'type': 'multiinfo', 'results': [{'Name': 'alpha++', 'Version': '2'}, {'Name': 'bad;name', 'Version': '1'}]}
        with patch.object(packages, 'fetch', return_value=json.dumps(data).encode()) as fetch:
            self.assertEqual(packages.aur_info(['alpha++']), {'alpha++': '2'})
            self.assertIn('alpha%2B%2B', fetch.call_args.args[0])
        with patch.object(packages, 'fetch', return_value=b'[]'), self.assertRaises(RuntimeError):
            packages.aur_info(['alpha'])


class PopupTests(unittest.TestCase):
    def test_rofi_inherits_user_config_and_preserves_alphabetical_order(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = Path(tmp) / 'rofi/config.rasi'
            config.parent.mkdir()
            config.write_text('window { width: 56em; height: 35em; }')
            with patch.dict(packages.os.environ, {'XDG_CONFIG_HOME': tmp}), \
                 patch.object(packages.subprocess, 'run', return_value=Mock(returncode=0, stdout='1')) as run:
                self.assertEqual(packages.choose(['alpha', 'zebra'], 'Packages'), 1)
            argv = run.call_args.args[0]
            self.assertIn('-no-sort', argv)
            self.assertEqual(argv[argv.index('-matching') + 1], 'normal')
            self.assertEqual(argv[argv.index('-config') + 1], str(config))
            self.assertNotIn('-theme-str', argv)
            self.assertNotIn('-width', argv)

    def test_cancel_or_invalid_selection_never_selects_a_package(self):
        for code, output in [(1, '0'), (0, '-1'), (0, '999'), (0, 'shell text')]:
            with patch.object(packages.subprocess, 'run', return_value=Mock(returncode=code, stdout=output)):
                self.assertIsNone(packages.choose(['alpha'], 'Packages'))

    def test_browser_cancel_does_not_query_or_install_packages(self):
        with tempfile.TemporaryDirectory() as tmp, \
             patch.object(packages, 'CACHE', Path(tmp)), \
             patch.object(packages.shutil, 'which', return_value='/bin/test'), \
             patch.object(packages, 'choose', return_value=None), \
             patch.object(packages, 'catalog') as catalog, \
             patch.object(packages.subprocess, 'Popen') as launch:
            packages.open_browser()
            catalog.assert_not_called()
            launch.assert_not_called()

    def test_install_requires_confirmation_and_launches_interactive_terminal(self):
        item = dict(name='alpha', source='extra', version='2', aur=False)
        with tempfile.TemporaryDirectory() as tmp, \
             patch.object(packages, 'CACHE', Path(tmp)), \
             patch.object(packages.shutil, 'which', return_value='/bin/test'), \
             patch.object(packages, 'choose', side_effect=[1, 0, 1]), \
             patch.object(packages, 'catalog', return_value=([item], {}, '')), \
             patch.object(packages, 'icons', return_value={}), patch.object(packages, 'notify'), \
             patch.object(packages.subprocess, 'Popen') as launch:
            packages.open_browser()
            argv = launch.call_args.args[0]
            self.assertEqual(argv[0], 'kitty')
            self.assertEqual(argv[-3:], ['transaction', 'repo', 'extra/alpha'])
            self.assertNotIn('sudo', argv)

    def test_current_installed_package_has_no_reinstall_action(self):
        item = dict(name='alpha', source='extra', version='2', aur=False)
        with tempfile.TemporaryDirectory() as tmp, \
             patch.object(packages, 'CACHE', Path(tmp)), \
             patch.object(packages.shutil, 'which', return_value='/bin/test'), \
             patch.object(packages, 'choose', side_effect=[1, 0, 0, None]), \
             patch.object(packages, 'catalog', return_value=([item], {'alpha': '2'}, '')), \
             patch.object(packages, 'compare', return_value=0), \
             patch.object(packages, 'icons', return_value={}), patch.object(packages, 'notify'), \
             patch.object(packages.subprocess, 'Popen') as launch:
            packages.open_browser()
            launch.assert_not_called()


class TransactionTests(unittest.TestCase):
    def test_full_upgrade_commands_keep_prompts_and_aur_runs_as_user(self):
        self.assertEqual(packages.transaction_command('repo', 'extra/alpha'),
                         ['sudo', 'pacman', '-Syu', '--needed', '--', 'extra/alpha'])
        with patch.object(packages.shutil, 'which', return_value='/usr/bin/yay'):
            self.assertEqual(packages.transaction_command('aur', 'alpha'),
                             ['yay', '-Syu', '--needed', '--', 'alpha'])

    def test_missing_yay_and_invalid_targets_are_actionable(self):
        with patch.object(packages.shutil, 'which', return_value=None), self.assertRaisesRegex(RuntimeError, 'yay'):
            packages.transaction_command('aur', 'alpha')
        for source, target in [('repo', '--bad'), ('aur', 'alpha;touch /tmp/bad'), ('aur', 'repo/pkg'), ('repo', 'a/../b')]:
            with self.subTest(source=source, target=target), self.assertRaises(ValueError):
                packages.transaction_command(source, target)

    def test_root_or_declined_terminal_confirmation_never_runs_package_manager(self):
        with patch.object(packages.os, 'geteuid', return_value=0), self.assertRaises(RuntimeError):
            packages.transaction('repo', 'extra/alpha')
        with patch.object(packages.os, 'geteuid', return_value=1000), \
             patch('builtins.input', return_value='n'), patch.object(packages.subprocess, 'run') as run:
            packages.transaction('repo', 'extra/alpha')
            run.assert_not_called()


if __name__ == '__main__':
    unittest.main()
