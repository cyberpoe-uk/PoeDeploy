"""Package popup behavior without installing packages or opening the live launcher."""
import gzip
import importlib.util
import io
import tarfile
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
ORIGINAL_REPOSITORY_DESCRIPTIONS = packages.repository_descriptions


class PackageDataTests(unittest.TestCase):
    def setUp(self):
        for name in ('aur_descriptions', 'repository_descriptions'):
            mocked = patch.object(packages, name, return_value={})
            mocked.start()
            self.addCleanup(mocked.stop)

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
        self.assertEqual([p['name'] for p in rows], ['alpha', 'zebra', 'zebra'])
        self.assertEqual([p['source'] for p in rows[1:]], ['AUR', 'extra'])
        self.assertEqual(rows[0]['version'], '2')

    def test_fresh_update_check_is_cached_and_does_not_sync_system_database(self):
        with tempfile.TemporaryDirectory() as tmp, \
             patch.object(packages.shutil, 'which', return_value='/usr/bin/checkupdates'), \
             patch.object(packages, 'run', return_value='alpha 1 -> 2\n') as command:
            cache = Path(tmp)
            self.assertEqual(packages.repository_updates(cache)[0], {'alpha': '2'})
            self.assertEqual(packages.repository_updates(cache)[0], {'alpha': '2'})
            command.assert_called_once_with(['checkupdates'], timeout=30, codes=(0, 2),
                                            extra_env={'CHECKUPDATES_DB': str(cache / 'repo-db')})

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

    def test_force_refresh_bypasses_recent_aur_cache(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(packages, 'fetch') as fetch:
            cache = Path(tmp)
            (cache / 'aur-names.json').write_text('["old"]')
            fetch.return_value = gzip.compress(b'new\n')
            self.assertEqual(packages.aur_names(cache, refresh=True)[0], ['new'])
            fetch.assert_called_once()

    def test_icon_group_precedes_plain_group_with_alphabetical_order_inside_each(self):
        data = [dict(name=name, source='AUR') for name in
                ('spotify-zeta', 'spotify-adblock', 'spotify-launcher', 'spotify')]
        result = packages.ranked(data, {'spotify': 'spotify', 'spotify-launcher': 'spotify'})
        self.assertEqual([p['name'] for p in result],
                         ['spotify', 'spotify-launcher', 'spotify-adblock', 'spotify-zeta'])
        self.assertEqual(packages.ranked(data, {}, 'extra'), [])

    def test_subtitle_is_markup_on_second_line_without_splitting_rofi_rows(self):
        value = packages.row(dict(name='alpha', source='extra', version='1'), {}, {})
        self.assertIn('alpha&#10;<span size="small">extra', value)
        self.assertNotIn('\n', value)

    def test_specific_repositories_keep_duplicate_names_and_actual_versions(self):
        with patch.object(packages, 'run', return_value='core alpha 2\nextra alpha 3\n'):
            data = packages.repository_packages(all_repositories=True)
        self.assertEqual(len(data), 2)
        self.assertEqual(packages.ranked(list(data.values()), {}, 'extra')[0]['version'], '3')


    def test_incomplete_search_snapshot_falls_back_to_local_catalog(self):
        with tempfile.TemporaryDirectory() as tmp:
            cache = Path(tmp)
            (cache / 'repo-db/sync').mkdir(parents=True)
            item = dict(name='alpha', source='core', version='1', aur=False)
            with patch.object(packages, 'installed_packages', return_value={}), \
                 patch.object(packages, 'repository_updates', return_value=({}, 'offline')), \
                 patch.object(packages, 'repository_packages', side_effect=[RuntimeError('missing database'), {'alpha': item}]) as read:
                data, _, note = packages.catalog('repo', cache, refresh=True)
            self.assertEqual(data, [item])
            self.assertIn('Using local pacman databases', note)
            self.assertEqual(read.call_args_list[-1].args, (None,))

    def test_every_open_refreshes_even_recent_repository_metadata(self):
        with tempfile.TemporaryDirectory() as tmp, \
             patch.object(packages.shutil, 'which', return_value='/usr/bin/checkupdates'), \
             patch.object(packages, 'run', return_value='alpha 1 -> 2\n') as command:
            cache = Path(tmp)
            packages.repository_updates(cache, refresh=True)
            packages.repository_updates(cache, refresh=True)
            self.assertEqual(command.call_count, 2)
            self.assertEqual(command.call_args.kwargs['extra_env']['CHECKUPDATES_DB'], str(cache / 'repo-db'))

    def test_appstream_cached_images_supply_package_icon_metadata(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / 'metainfo').mkdir()
            (root / 'metainfo/app.xml').write_text('<component><pkgname>alpha</pkgname><icon type="cached">alpha.png</icon></component>')
            icon = root / 'swcatalog/icons/test/64x64/alpha.png'
            icon.parent.mkdir(parents=True)
            icon.write_bytes(b'image fixture')
            with patch.dict(packages.os.environ, {'XDG_DATA_HOME': tmp, 'XDG_DATA_DIRS': tmp}):
                self.assertEqual(packages.icons()['alpha'], str(icon))

    def test_custom_typed_input_never_selects_an_arbitrary_package(self):
        process = Mock(returncode=0)
        process.stdin = io.StringIO()
        process.communicate.return_value = ('-1\x1fnot-a-selected-package\n', '')
        process.poll.return_value = 0
        with patch.object(packages.subprocess, 'Popen', return_value=process):
            self.assertIsNone(packages.package_picker(lambda: ['alpha']))


    def test_bulk_metadata_stream_handles_records_across_chunks(self):
        data = [{'Name': 'alpha', 'Description': 'x' * 70000}, {'Name': 'beta', 'Description': 'Music player'}]
        compressed = gzip.compress(json.dumps(data).encode())
        self.assertEqual([item['Name'] for item in packages.metadata_records(compressed)], ['alpha', 'beta'])
        with self.assertRaises(ValueError):
            list(packages.metadata_records(gzip.compress(b'[{"Name":"alpha"}')))

    def test_repository_description_reader_does_not_extract_archives(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / 'sync').mkdir()
            text = b'%NAME%\nalpha\n\n%DESC%\nA sample package description\n\n'
            with tarfile.open(root / 'sync/extra.db', 'w:gz') as tar:
                info = tarfile.TarInfo('alpha-1/desc');info.size = len(text)
                tar.addfile(info, io.BytesIO(text))
            self.assertEqual(ORIGINAL_REPOSITORY_DESCRIPTIONS(root),
                             {('extra', 'alpha'): 'A sample package description'})
            self.assertFalse((root / 'alpha-1').exists())

    def test_inline_description_is_escaped_for_pango(self):
        item = dict(name='alpha', source='extra', description='A < B & music', version='1')
        self.assertIn('A &lt; B &amp; music', packages.row(item, {}, {}))



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

    def test_picker_opens_before_loading_and_returns_repository_shortcut_query(self):
        process = Mock(returncode=10)
        process.stdin = io.StringIO()
        process.communicate.return_value = ('-1\x1fspotify\n', '')
        process.poll.return_value = 10
        def loader():
            self.assertIn('Choose repository', process.stdin.getvalue())
            return ['spotify']
        with patch.object(packages.subprocess, 'Popen', return_value=process) as launch:
            result = packages.package_picker(loader)
        self.assertEqual(result, {'filter': True, 'query': 'spotify'})
        argv = launch.call_args.args[0]
        self.assertIn('-markup-rows', argv)
        self.assertIn('Alt+r', argv)
        self.assertNotIn('-no-custom', argv)  # Rofi forces sync input when this is set.

    def test_repository_filter_preserves_search_and_does_not_reload_catalog(self):
        data = [dict(name='alpha', source=repo, version='1', aur=False) for repo in ('core', 'extra')]
        replies = iter([{'filter': True, 'query': 'alp'}, None])
        def picker(loader, query, repository):
            rows = loader()
            if repository == 'extra':
                self.assertEqual(query, 'alp')
                self.assertEqual(len(rows), 1)
                self.assertIn('extra', rows[0])
            return next(replies)
        with tempfile.TemporaryDirectory() as tmp, patch.object(packages, 'CACHE', Path(tmp)), \
             patch.object(packages.shutil, 'which', return_value='/bin/test'), \
             patch.object(packages, 'catalog', return_value=(data, {}, '')) as load, \
             patch.object(packages, 'icons', return_value={}), \
             patch.object(packages, 'package_picker', side_effect=picker), \
             patch.object(packages, 'choose', return_value=2):
            packages.open_browser()
            load.assert_called_once_with('both', Path(tmp), refresh=True)

    def test_cancel_or_invalid_selection_never_selects_a_package(self):
        for code, output in [(1, '0'), (0, '-1'), (0, '999'), (0, 'shell text')]:
            with patch.object(packages.subprocess, 'run', return_value=Mock(returncode=code, stdout=output)):
                self.assertIsNone(packages.choose(['alpha'], 'Packages'))

    def test_browser_cancel_does_not_query_or_install_packages(self):
        with tempfile.TemporaryDirectory() as tmp, \
             patch.object(packages, 'CACHE', Path(tmp)), \
             patch.object(packages.shutil, 'which', return_value='/bin/test'), \
             patch.object(packages, 'package_picker', return_value=None), \
             patch.object(packages, 'catalog') as catalog, \
             patch.object(packages.subprocess, 'Popen') as launch:
            packages.open_browser()
            catalog.assert_not_called()
            launch.assert_not_called()

    def check_install_selection(self, selection):
        def picker(loader, *args):
            loader()
            return {'index': 0, 'query': 'alpha'}
        item = dict(name='alpha', source='extra', version='2', aur=False)
        with tempfile.TemporaryDirectory() as tmp, \
             patch.object(packages, 'CACHE', Path(tmp)), \
             patch.object(packages.shutil, 'which', return_value='/bin/test'), \
             patch.object(packages, 'package_picker', side_effect=picker), \
             patch.object(packages, 'choose', return_value=selection) as menu, \
             patch.object(packages, 'catalog', return_value=([item], {}, '')), \
             patch.object(packages, 'icons', return_value={}), patch.object(packages, 'notify'), \
             patch.object(packages.subprocess, 'Popen') as launch:
            packages.open_browser()
            self.assertEqual(menu.call_args_list[-1].args[0], ['Install', 'Install and upgrade', 'Full description', 'Cancel'])
            argv = launch.call_args.args[0]
            self.assertEqual(argv[0], 'kitty')
            tail = ['transaction', 'repo', 'extra/alpha'] + (['--upgrade'] if selection == 1 else [])
            self.assertEqual(argv[-len(tail):], tail)
            self.assertNotIn('sudo', argv)

    def test_install_only_is_first_choice(self):
        self.check_install_selection(0)

    def test_install_and_upgrade_preserves_choice_in_terminal(self):
        self.check_install_selection(1)

    def test_current_installed_package_has_no_reinstall_action(self):
        replies = iter([{'index': 0, 'query': 'alpha'}, None])
        def picker(loader, *args):
            loader()
            return next(replies)
        item = dict(name='alpha', source='extra', version='2', aur=False)
        with tempfile.TemporaryDirectory() as tmp, \
             patch.object(packages, 'CACHE', Path(tmp)), \
             patch.object(packages.shutil, 'which', return_value='/bin/test'), \
             patch.object(packages, 'package_picker', side_effect=picker), \
             patch.object(packages, 'choose', return_value=0), \
             patch.object(packages, 'catalog', return_value=([item], {'alpha': '2'}, '')), \
             patch.object(packages, 'compare', return_value=0), \
             patch.object(packages, 'icons', return_value={}), patch.object(packages, 'notify'), \
             patch.object(packages.subprocess, 'Popen') as launch:
            packages.open_browser()
            launch.assert_not_called()


class TransactionTests(unittest.TestCase):
    def test_full_upgrade_commands_keep_prompts_and_aur_runs_as_user(self):
        self.assertEqual(packages.transaction_command('repo', 'extra/alpha', upgrade=True),
                         ['sudo', 'pacman', '-Syu', '--needed', '--', 'extra/alpha'])
        with patch.object(packages.shutil, 'which', return_value='/usr/bin/yay'):
            self.assertEqual(packages.transaction_command('aur', 'alpha', upgrade=True),
                             ['yay', '-Syu', '--needed', '--', 'alpha'])

    def test_install_only_does_not_refresh_databases_or_upgrade_system(self):
        self.assertEqual(packages.transaction_command('repo', 'extra/alpha'),
                         ['sudo', 'pacman', '-S', '--needed', '--', 'extra/alpha'])
        with patch.object(packages.shutil, 'which', return_value='/usr/bin/yay'):
            self.assertEqual(packages.transaction_command('aur', 'alpha'),
                             ['yay', '-S', '--needed', '--', 'alpha'])

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
