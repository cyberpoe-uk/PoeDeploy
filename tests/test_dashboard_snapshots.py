"""Snapshot requests never restore, escalate in the background or fake fresh data."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

SCRIPTS = Path(__file__).resolve().parents[1] / 'apps/poedash/assets/scripts'
sys.path.insert(0, str(SCRIPTS))
import dashboard_collect as collect
import dashboard_model as model
import snapshots
import snapshots_admin as admin

LIST = '''Timeshift v26.09.0
Device : /dev/nvme0n1p2
Num     Name                 Tags  Description
------------------------------------------------------------------------------
0    >  2026-11-15_10-00-00   D W   Before update
1    >  2026-11-16_11-00-00   O     Manual with spaces
2    >  2026-11-14_09-00-00         Untagged snapshot
'''


class Snapshots(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.config = self.root / 'timeshift.json'
        self.data = {'backup_device_uuid': 'disk-uuid', 'btrfs_mode': 'true',
                     'do_first_run': 'false', 'include_btrfs_home_for_backup': 'true',
                     'include_btrfs_home_for_restore': 'false', 'exclude': ['/keep/**'],
                     'custom_unknown_setting': {'keep': True}}
        self.config.write_text(json.dumps(self.data))
        for module in (snapshots, admin):
            patcher = patch.object(module, 'CONFIG', self.config)
            patcher.start(); self.addCleanup(patcher.stop)
        self.repository = admin.repository(self.data)

    def schedule(self):
        return {level: {'enabled': level in ('daily','weekly'), 'keep': 5} for level in admin.LEVELS}

    def test_parser_keeps_names_tags_descriptions_and_newest_first(self):
        items = admin.parse_list('\x1b[32m' + LIST + '\x1b[0m')
        self.assertEqual(items[0], {'name': '2026-11-16_11-00-00', 'tags': 'O', 'description': 'Manual with spaces'})
        self.assertEqual(items[1]['tags'], 'D W')
        self.assertEqual(items[2]['tags'], '')
        self.assertEqual(items[2]['description'], 'Untagged snapshot')
        self.assertEqual(admin.parse_list('No snapshots found'), [])
        with self.assertRaises(RuntimeError): admin.parse_list('Failed to mount disk')

    def test_empty_list_nonzero_is_accepted_but_mount_errors_are_not(self):
        with patch.object(admin.subprocess, 'run', return_value=subprocess.CompletedProcess([], 1, 'No snapshots found', '')):
            self.assertIn('No snapshots', admin.timeshift(['--list'], allow_empty=True))
        with patch.object(admin.subprocess, 'run', return_value=subprocess.CompletedProcess([], 1, 'No snapshots found', 'E: Failed to mount device')):
            with self.assertRaises(RuntimeError): admin.timeshift(['--list'], allow_empty=True)

    def test_collection_does_not_authenticate_and_keeps_list_timestamp(self):
        checked = time.time()-1000
        model.atomic_json(self.root/'state/snapshots.json', {'repository': self.repository, 'checked': checked,
                                                          'items': admin.parse_list(LIST)})
        def run(argv, **kwargs):
            self.assertNotIn('pkexec', ' '.join(argv))
            return subprocess.CompletedProcess(argv, 0, 'active\n' if argv[0]=='systemctl' else '{"filesystems":[]}', '')
        with patch.object(snapshots.subprocess, 'run', side_effect=run):
            value = collect.Collectors(self.root).collect('snapshots', model.defaults())
        self.assertTrue(value['list_loaded']); self.assertTrue(value['stale'])
        self.assertEqual(value['checked'], checked)
        self.assertTrue(value['home_backup']); self.assertFalse(value['home_restore'])
        self.assertEqual(value['scheduler'], 'active')

    def test_unknown_or_malformed_cache_is_not_an_empty_current_list(self):
        cases = [{'repository': ['other','true'], 'checked': time.time(), 'items': []},
                 {'repository': self.repository, 'checked': time.time(), 'items': [None]}, []]
        with patch.object(snapshots.subprocess, 'run', return_value=subprocess.CompletedProcess([],0,'{}','')):
            for cache in cases:
                model.atomic_json(self.root/'state/snapshots.json',cache)
                self.assertFalse(snapshots.status(self.root)['list_loaded'])

    def test_delete_requires_an_exact_existing_snapshot_and_never_deletes_all(self):
        for name in ('--delete-all','../2026-11-16_11-00-00','',None):
            with patch.object(admin,'timeshift') as run:
                with self.assertRaises(ValueError): admin.execute('delete',{'repository':self.repository,'name':name})
                run.assert_not_called()
        with patch.object(admin,'timeshift',return_value=LIST) as run:
            result=admin.execute('delete',{'repository':self.repository,'name':'2026-11-16_11-00-00'})
            self.assertTrue(result['changed'])
            self.assertEqual(run.call_args_list[1].args[0],['--delete','--snapshot','2026-11-16_11-00-00','--yes'])
        with patch.object(admin,'timeshift',return_value=LIST) as run:
            with self.assertRaises(RuntimeError):admin.execute('delete',{'repository':self.repository,'name':'2000-01-01_00-00-00'})
            self.assertEqual(run.call_count,1)

    def test_create_uses_manual_tag_and_refresh_failure_does_not_repeat_creation(self):
        with patch.object(admin,'timeshift',side_effect=['created',RuntimeError('busy')]) as run:
            result=admin.execute('create',{'repository':self.repository,'description':'Before update'})
        self.assertTrue(result['changed']); self.assertIn('Snapshot created',result['message'])
        self.assertEqual(result['refresh_error'],'busy')
        self.assertEqual(run.call_args_list[0].args[0],['--create','--comments','Before update','--tags','O'])

    def test_restore_unknown_actions_and_changed_devices_are_rejected(self):
        with patch.object(admin,'timeshift') as run:
            for action in ('restore','delete-all','shell'):
                with self.assertRaises(ValueError):admin.execute(action,{'repository':self.repository})
            with self.assertRaises(RuntimeError):admin.execute('create',{'repository':['other','true']})
            run.assert_not_called()

    def test_schedule_write_is_atomic_preserves_other_settings_and_backs_up(self):
        original=self.config.read_bytes()
        with patch.object(admin,'timeshift_running',return_value=False):
            admin.save_schedule(self.schedule(),hashlib.sha256(original).hexdigest())
        data=json.loads(self.config.read_text())
        for key in self.data:self.assertEqual(data[key],self.data[key])
        self.assertEqual(data['schedule_daily'],'true');self.assertEqual(data['count_daily'],'5')
        backups=list(self.root.glob('timeshift.json.poedash-*.bak'))
        self.assertEqual(len(backups),1);self.assertEqual(backups[0].read_bytes(),original)
        self.assertEqual(list(self.root.glob('.poedash-*')),[])

    def test_schedule_conflict_busy_and_bad_values_leave_config_untouched(self):
        original=self.config.read_bytes()
        bad=deepcopy(self.schedule());bad['daily']['keep']=0
        for value in (bad,{'daily':{'enabled':True,'keep':5}}):
            with self.assertRaises(ValueError):admin.save_schedule(value,'unused')
        with patch.object(admin,'timeshift_running',return_value=True):
            with self.assertRaises(RuntimeError):admin.save_schedule(self.schedule(),hashlib.sha256(original).hexdigest())
        with patch.object(admin,'timeshift_running',return_value=False):
            with self.assertRaises(RuntimeError):admin.save_schedule(self.schedule(),'stale fingerprint')
        self.assertEqual(self.config.read_bytes(),original)

    def test_authentication_cancel_keeps_the_last_successful_cache(self):
        cache=self.root/'state/snapshots.json';model.atomic_json(cache,{'keep':True})
        with patch.object(snapshots.shutil,'which',return_value='/usr/bin/pkexec'), \
             patch.object(snapshots.subprocess,'run',return_value=subprocess.CompletedProcess([],126,'','')):
            with self.assertRaisesRegex(RuntimeError,'cancelled'):snapshots.perform(self.root,'list',{})
        self.assertEqual(json.loads(cache.read_text()),{'keep':True})

    def test_privileged_bridge_is_isolated_and_does_not_use_shell_or_user_imports(self):
        response={'cache':{'items':[],'checked':time.time(),'repository':self.repository},'message':'Refreshed'}
        with patch.object(snapshots.shutil,'which',return_value='/usr/bin/pkexec'), \
             patch.object(snapshots.subprocess,'run',return_value=subprocess.CompletedProcess([],0,json.dumps(response),'')) as run:
            snapshots.perform(self.root,'list',{'repository':self.repository})
        argv=run.call_args.args[0]
        self.assertEqual(argv[:4],['/usr/bin/pkexec','/usr/bin/python3','-I','-c'])
        self.assertEqual(argv[5],'list');self.assertNotIn('shell',run.call_args.kwargs)
        self.assertEqual(json.loads((self.root/'state/snapshots.json').read_text()),response['cache'])


if __name__=='__main__':unittest.main()
