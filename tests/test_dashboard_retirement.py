"""Complete removal of retired dashboard integrations, preserving independent apps."""
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('retirement', ROOT / 'apps/poedash/migration.py')
migration = importlib.util.module_from_spec(spec)
spec.loader.exec_module(migration)


class Retirement(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.home = Path(self.temp.name)
        self.config = self.home / '.config'
        self.old = self.config / 'eww'
        self.old.mkdir(parents=True)
        (self.old / 'eww.yuck').write_text('(label :text "PenDash")')
        self.backup = self.home / 'backup'
        self.backup.mkdir()
        self.new = self.config / 'poedash'
        self.env = patch.dict(os.environ, HOME=str(self.home), XDG_CACHE_HOME=str(self.home/'.cache'))
        self.env.start()
        self.addCleanup(self.env.stop)

    def file(self, relative, text):
        path = self.home / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
        return path

    def retire(self):
        with patch.object(migration.shutil, 'which', return_value=None):
            return migration.retire(self.config,self.backup,self.new)

    def test_removes_runtime_launchers_hooks_and_themes_but_keeps_tools(self):
        custom=self.file('.config/hypr/custom.lua','-- BEGIN PENDASH\nhl.exec_cmd("~/.config/eww/scripts/start.sh")\n-- END PENDASH\n-- keep this\n')
        autostart=self.file('.config/autostart/pendash.desktop','[Desktop Entry]\nExec=pendash\n')
        launcher=self.file('.local/bin/pendash','old launcher')
        lib=self.file('.local/lib/pendash/helper.py','old helper')
        tool=self.file('.local/share/pendash/burp/BurpSuite','keep native security application')
        browser=self.file('.config/chromium/Default/data','keep browser data')
        theme=self.file('.config/matugen/config.toml','[config]\n[templates.eww]\noutput_path="~/.config/eww/colors.scss"\n[templates.other]\noutput_path="other.scss"\n')
        self.assertTrue(self.retire())
        for path in (self.old,autostart,launcher,lib): self.assertFalse(path.exists())
        self.assertEqual(custom.read_text(),'-- keep this\n')
        self.assertNotIn('templates.eww',theme.read_text())
        self.assertIn('templates.other',theme.read_text())
        self.assertTrue(tool.exists())
        self.assertTrue(browser.exists())
        self.assertTrue((self.backup/'retired-legacy-eww/eww.yuck').exists())
        self.assertTrue((self.backup/'retired-files/.local/bin/pendash').exists())

    def test_rewrites_waybar_and_quickshell_to_the_new_dashboard(self):
        bar=self.file('.config/waybar/config.jsonc','// comment\n'+json.dumps({'modules-right':['clock','custom/pendash','custom/pendash-update'], 'custom/pendash':{'exec':'old'},'custom/pendash-update':{'on-click':'old'},'clock':{'format':'keep'}}))
        module=self.file('.config/quickshell/StatusbarApp/DashboardModule.qml','property string root: "~/.config/eww"\nproperty string name: "PenDash"\n')
        self.retire()
        data=json.loads(bar.read_text().split('\n',1)[1])
        self.assertEqual(data['modules-right'],['clock','custom/poedash','custom/poedash-update'])
        self.assertIn(str(self.new),data['custom/poedash']['exec'])
        self.assertEqual(data['clock']['format'],'keep')
        self.assertNotIn('pendash',module.read_text().lower())
        self.assertIn(str(self.new),module.read_text())

    def test_existing_new_controls_are_not_duplicated(self):
        original=json.dumps({'modules-right':['custom/pendash','custom/poedash','clock'], 'custom/pendash':{'exec':'old'},'custom/poedash':{'exec':'keep'}})
        data=json.loads(migration.rewrite_waybar(original,self.new,[self.old]))
        self.assertEqual(data['modules-right'],['custom/poedash','clock'])
        self.assertNotIn('custom/pendash',data)
        self.assertEqual(data['custom/poedash']['exec'],'keep')

    def test_symlinked_config_is_unlinked_without_deleting_dotfiles_source(self):
        actual=self.home/'dotfiles/eww'
        actual.parent.mkdir()
        self.old.rename(actual)
        self.old.symlink_to(actual,target_is_directory=True)
        palette = self.home / 'palette.scss'
        palette.write_text('// keep palette')
        (actual/'colors.scss').symlink_to('../../palette.scss')
        self.retire()
        self.assertEqual((self.backup/'retired-legacy-eww/colors.scss').read_text(),'// keep palette')
        self.assertFalse(self.old.is_symlink())
        self.assertTrue(actual.exists())

    def test_unrecognised_eww_is_untouched_and_repeated_install_is_safe(self):
        (self.old/'eww.yuck').write_text('unrelated widgets')
        self.assertFalse(self.retire())
        self.assertTrue(self.old.exists())
        (self.old/'eww.yuck').write_text('PenDash')
        self.assertTrue(self.retire())
        self.assertFalse(self.retire())

    def test_duplicate_last_module_and_default_autostart_are_cleaned(self):
        original=json.dumps({'modules-right':['custom/poedash','clock','custom/pendash'], 'custom/poedash':{'exec':'keep'},'custom/pendash':{'exec':'old'}})
        data=json.loads(migration.rewrite_waybar(original,self.new,[self.old]))
        self.assertEqual(data['modules-right'],['custom/poedash','clock'])
        startup=self.file('.config/hypr/autostart.conf','exec-once = eww daemon\nexec-once = eww open dashboard\nexec-once = eww --config /other/widgets daemon\n')
        self.retire()
        self.assertEqual(startup.read_text(),'exec-once = eww --config /other/widgets daemon\n')

    def test_unrelated_managed_block_is_preserved(self):
        config=self.file('.config/hypr/custom.lua','-- BEGIN OTHER\nhl.exec_cmd("~/.config/eww/scripts/start.sh")\n-- keep other configuration\n-- END OTHER\n')
        self.retire()
        self.assertIn('-- keep other configuration',config.read_text())
        self.assertIn('-- BEGIN OTHER',config.read_text())
        self.assertNotIn('start.sh',config.read_text())

    def test_owned_user_service_and_enabled_link_are_removed(self):
        unit=self.file('.config/systemd/user/pendash.service','[Service]\nExecStart='+str(self.old/'scripts/start.sh')+'\n')
        wants=unit.parent/'default.target.wants'
        wants.mkdir()
        link=wants/unit.name
        link.symlink_to('../'+unit.name)
        with patch.object(migration.subprocess,'run',return_value=subprocess.CompletedProcess([],0,'','')) as command:
            self.retire()
        self.assertFalse(unit.exists())
        self.assertFalse(link.is_symlink())
        self.assertTrue(any(c.args[0][2:]==['disable','--now','pendash.service'] for c in command.call_args_list))

    def test_failed_service_stop_does_not_remove_its_configuration(self):
        unit=self.file('.config/systemd/user/pendash.service','[Service]\nExecStart='+str(self.old/'scripts/start.sh')+'\n')
        with patch.object(migration.subprocess,'run',return_value=subprocess.CompletedProcess([],1,'','user bus unavailable')):
            with self.assertRaisesRegex(RuntimeError,'Could not stop retired'):
                self.retire()
        self.assertTrue(unit.exists())
        self.assertTrue(self.old.exists())

    def test_security_tool_autostart_is_retained_and_bar_styles_are_migrated(self):
        tool=self.file('.config/autostart/burp.desktop','[Desktop Entry]\nExec='+str(self.home/'.local/share/pendash/burp/BurpSuite')+'\n')
        startup=self.file('.config/hypr/tools.conf','exec-once = '+str(self.home/'.local/share/pendash/burp/BurpSuite')+'\n')
        image=self.home/'.config/waybar/icon.png'
        image.parent.mkdir(parents=True,exist_ok=True)
        image.write_bytes(b'\xff\x00\xfe')
        style=self.file('.config/waybar/style.css','#custom-pendash { color: red; }\n#clock { color: blue; }\n')
        self.retire()
        self.assertTrue(tool.exists())
        self.assertIn('BurpSuite',startup.read_text())
        self.assertIn('#custom-poedash',style.read_text())
        self.assertIn('#clock { color: blue; }',style.read_text())

    def test_orphaned_old_worker_is_stopped(self):
        script=self.file('.config/eww/scripts/workspace.py','import time\nfrom pathlib import Path\nPath(__file__).with_suffix(".ready").touch()\ntime.sleep(60)\n')
        child=subprocess.Popen([sys.executable,str(script)])
        self.addCleanup(lambda: child.poll() is None and child.kill())
        for _ in range(100):
            if script.with_suffix('.ready').exists(): break
            time.sleep(.01)
        self.assertTrue(script.with_suffix('.ready').exists())
        self.retire()
        self.assertLess(child.wait(timeout=3),0)

    def test_current_upgrade_stops_old_workers_but_keeps_the_updater_running(self):
        root=self.new
        (root/'scripts').mkdir(parents=True)
        (root/'eww.yuck').write_text('old dashboard')
        children=[]
        try:
            for name in ('workspace.py','dashboard-control.py'):
                script=root/'scripts'/name
                script.write_text('import time\nfrom pathlib import Path\nPath(__file__).with_suffix(".ready").touch()\ntime.sleep(60)\n')
                child=subprocess.Popen([sys.executable,str(script)])
                children.append(child)
                for _ in range(100):
                    if script.with_suffix('.ready').exists():break
                    time.sleep(.01)
                self.assertTrue(script.with_suffix('.ready').exists())
            with patch.object(migration.shutil,'which',return_value=None):
                migration.stop_legacy_surface(root)
            self.assertLess(children[0].wait(timeout=3),0)
            self.assertIsNone(children[1].poll())
        finally:
            for child in children:
                if child.poll() is None:child.terminate()
                child.wait(timeout=3)
