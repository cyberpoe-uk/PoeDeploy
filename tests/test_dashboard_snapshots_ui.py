"""Snapshot card and drawers on an isolated GTK display; system actions are mocked."""
from copy import deepcopy
import os
from pathlib import Path
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'apps/poedash/assets/scripts'))


@unittest.skipUnless(os.environ.get('POEDASH_GUI_TEST')=='1','Requires an isolated GTK display')
class SnapshotControls(unittest.TestCase):
    def setUp(self):
        import dashboard_native as native
        self.native=native
        self.temporary=tempfile.TemporaryDirectory(prefix='poedash-snapshot-ui-')
        self.addCleanup(self.temporary.cleanup)
        root=Path(self.temporary.name)
        settings=native.Settings(root);settings.profile['visible']=['snapshots'];settings.save()
        with patch.object(native.Engine,'start'),patch.object(native.Dashboard,'spawn_listener'), \
                patch.object(native.Dashboard,'start_ipc'),patch.object(native.Dashboard,'smoke_test',return_value=False):
            self.app=native.Dashboard(root,preview=True,smoke=True,size=(1200,800))
        self.data={'available':True,'configured':True,'mode':'Btrfs','repository':['disk','true'],
                   'fingerprint':'current-config','scheduler':'active','home_backup':True,'home_restore':False,
                   'schedule':{level:{'enabled':level=='daily','keep':5} for level in native.SNAPSHOT_LEVELS},
                   'list_loaded':True,'checked':time.time()-10,'free_gib':90,
                   'items':[{'name':'2026-11-16_11-00-00','tags':'O','description':'Before update'}]}
        self.app.receive({'snapshots':{'value':deepcopy(self.data),'updated':time.time(),'error':''}})
        self.pump()

    def pump(self,condition=None):
        context=self.native.GLib.MainContext.default();deadline=time.monotonic()+(3 if condition else .1)
        while time.monotonic()<deadline:
            while context.pending():context.iteration(False)
            if condition and condition():return
            time.sleep(.003)
        if condition:self.fail('Snapshot operation did not finish')

    def descendants(self,parent):
        yield parent
        if isinstance(parent,self.native.Gtk.Container):
            for child in parent.get_children():yield from self.descendants(child)

    def button(self,title,parent=None):
        return next(item for item in self.descendants(parent or self.app.drawer)
                    if isinstance(item,self.native.Gtk.Button) and item.get_label()==title)

    def test_card_displays_status_and_opens_snapshot_list(self):
        card=self.app.cards['snapshots']
        texts=[item.get_text() for item in self.descendants(card) if isinstance(item,self.native.Gtk.Label)]
        self.assertIn('Timeshift · Btrfs',texts);self.assertIn('90 GiB free',texts)
        self.button('Manage snapshots',card).clicked()
        self.assertIsNotNone(self.button('Delete snapshot'))
        self.assertIsNone(self.app.transaction)

    def test_delete_requires_confirmation_and_keep_never_authenticates(self):
        with patch.object(self.native,'snapshot_perform') as action:
            self.app.show_snapshots();self.button('Delete snapshot').clicked()
            self.assertIsNotNone(self.button('Permanently delete snapshot'))
            action.assert_not_called()
            self.button('Keep snapshot').clicked();action.assert_not_called()

    def test_confirmed_delete_uses_exact_id_and_blocks_duplicate_requests(self):
        started=threading.Event();release=threading.Event()
        self.addCleanup(release.set)
        def perform(*args):
            started.set();release.wait(2);return {'message':'Snapshot deleted.'}
        with patch.object(self.native,'snapshot_perform',side_effect=perform) as action, \
                patch.object(self.native,'snapshot_status',return_value=self.data):
            self.app.show_snapshots();self.button('Delete snapshot').clicked()
            self.button('Permanently delete snapshot').clicked()
            self.assertTrue(started.wait(1));self.assertTrue(self.app.snapshot_busy)
            self.app.snapshot_action('delete',{'name':'2026-11-16_11-00-00'})
            self.assertEqual(action.call_count,1)
            self.assertEqual(action.call_args.args[1:],('delete',{'repository':['disk','true'],'name':'2026-11-16_11-00-00'}))
            release.set();self.pump(lambda:not self.app.snapshot_busy)

    def test_authentication_cancel_keeps_creation_description_and_reenables_form(self):
        self.app.show_snapshot_create()
        entry=next(item for item in self.descendants(self.app.drawer) if isinstance(item,self.native.Gtk.Entry))
        entry.set_text('Before important update')
        with patch.object(self.native,'snapshot_perform',side_effect=RuntimeError('Authentication cancelled')), \
                patch.object(self.native,'snapshot_status',return_value=self.data):
            self.button('Create snapshot').clicked();self.pump(lambda:not self.app.snapshot_busy)
        self.assertEqual(entry.get_text(),'Before important update')
        self.assertTrue(self.app.snapshot_form.get_sensitive())
        self.assertIn('cancelled',self.app.snapshot_notice)

    def test_schedule_uses_draft_values_and_original_config_fingerprint(self):
        self.app.show_snapshot_schedule()
        checks=[item for item in self.descendants(self.app.drawer) if isinstance(item,self.native.Gtk.CheckButton)]
        weekly=next(item for item in checks if item.get_label()=='Weekly');weekly.set_active(True)
        spin=next(item for item in self.descendants(self.app.drawer) if isinstance(item,self.native.Gtk.SpinButton)
                  and item.get_accessible().get_name()=='Weekly snapshots to keep')
        self.assertTrue(spin.get_sensitive());spin.set_value(7)
        with patch.object(self.native,'snapshot_perform',return_value={'message':'Snapshot schedule saved.'}) as action, \
                patch.object(self.native,'snapshot_status',return_value=self.data):
            self.button('Apply schedule').clicked();self.pump(lambda:not self.app.snapshot_busy)
        payload=action.call_args.args[2]
        self.assertEqual(payload['expected'],'current-config')
        self.assertEqual(payload['schedule']['weekly'],{'enabled':True,'keep':7})
        self.assertFalse(payload['schedule']['hourly']['enabled'])

    def test_refresh_is_explicit_and_settings_drafts_block_snapshot_actions(self):
        with patch.object(self.native,'snapshot_perform',return_value={'message':'Snapshot list refreshed.'}) as action, \
                patch.object(self.native,'snapshot_status',return_value=self.data):
            self.app.cards['snapshots'].refresh_button.clicked();self.pump(lambda:not self.app.snapshot_busy)
            self.assertEqual(action.call_args.args[1],'list')
        self.app.begin()
        with patch.object(self.native,'snapshot_perform') as action:
            self.app.snapshot_action('list');action.assert_not_called()
        self.assertIn('Save or cancel',self.app.status.get_text())

    def test_late_completion_does_not_replace_another_open_panel(self):
        started=threading.Event();release=threading.Event();self.addCleanup(release.set)
        def perform(*args):
            started.set();release.wait(2);return {'message':'Snapshot list refreshed.'}
        with patch.object(self.native,'snapshot_perform',side_effect=perform), \
                patch.object(self.native,'snapshot_status',return_value=self.data):
            self.app.show_snapshots();self.app.snapshot_action('list');self.assertTrue(started.wait(1))
            self.app.drawer_page('Another panel',editable=False)
            generation=self.app.drawer_generation
            release.set();self.pump(lambda:not self.app.snapshot_busy)
            self.assertEqual(self.app.drawer_generation,generation)

    def tearDown(self):
        with patch.object(self.native.Gtk,'main_quit'):
            self.app.quit();self.app.window.destroy()
        self.pump()


if __name__=='__main__':unittest.main()
