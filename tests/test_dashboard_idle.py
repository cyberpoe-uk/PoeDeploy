"""Existing Hypridle config preservation, validation and transactional activation."""
import importlib.util
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

SCRIPT = Path(__file__).resolve().parents[1] / 'apps/poedash/assets/scripts/idle-control.py'
spec = importlib.util.spec_from_file_location('idle_control', SCRIPT)
idle = importlib.util.module_from_spec(spec)
spec.loader.exec_module(idle)
CONFIG = '''general {
    lock_cmd = pidof hyprlock || hyprlock
    before_sleep_cmd = loginctl lock-session
    after_sleep_cmd = hyprctl dispatch dpms on
}
listener {
    timeout = 300
    on-timeout = loginctl lock-session
}
listener {
    timeout = 3600
    on-timeout = hyprctl dispatch dpms off
    on-resume = hyprctl dispatch dpms on
}
listener {
    timeout = 120
    on-timeout = brightnessctl set 20%
    on-resume = brightnessctl set 80%
}
'''


class IdleConfiguration(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.config = self.root / 'real.conf'
        self.config.write_text(CONFIG)

    def test_reads_actual_minutes_and_preserves_unrelated_behaviour(self):
        self.assertEqual(idle.load(self.config)[2], dict(screen=60, lock=5, suspend=0))
        updated = idle.plan(self.config, dict(screen=5, lock=10, suspend=30))[self.config]
        self.assertIn('before_sleep_cmd = loginctl lock-session', updated)
        self.assertIn('on-resume = hyprctl dispatch dpms on', updated)
        self.assertIn('timeout = 120\n    on-timeout = brightnessctl', updated)
        self.config.write_text(updated)
        self.assertEqual(idle.load(self.config)[2], dict(screen=5, lock=10, suspend=30))

    def test_zero_disables_each_timer_independently(self):
        for disabled in idle.KINDS:
            values = dict(screen=5, lock=10, suspend=30)
            values[disabled] = 0
            self.config.write_text(CONFIG)
            self.config.write_text(idle.plan(self.config, values)[self.config])
            self.assertEqual(idle.load(self.config)[2], values)
            self.assertIn('before_sleep_cmd', self.config.read_text())

    def test_invalid_precision_boolean_and_injected_values_rejected(self):
        for value in (-1, 1/7, float('nan'), float('inf'), 10**500, True, '5; touch /tmp/unsafe', 1441, None):
            with self.subTest(value=value), self.assertRaises(ValueError):
                idle.plan(self.config, dict(screen=value, lock=5, suspend=0))

    def test_sources_and_symlink_targets_are_preserved(self):
        parent = self.root / 'main.conf'
        parent.write_text('source = real.conf\n')
        link = self.root / 'link.conf'
        link.symlink_to(parent)
        config = link.resolve()
        updated = idle.plan(config, dict(screen=7, lock=5, suspend=0))
        idle.atomic(self.config, updated[self.config])
        self.assertTrue(link.is_symlink())
        self.assertEqual(parent.read_text(), 'source = real.conf\n')
        self.assertEqual(idle.load(config)[2]['screen'], 7)

    def test_duplicate_and_custom_actions_fail_without_writing(self):
        for extra in ('listener {\n timeout = 600\n on-timeout = loginctl lock-session\n}\n',
                      'listener {\n timeout = 600\n on-timeout = custom-lock && systemctl suspend\n}\n'):
            self.config.write_text(CONFIG + extra)
            with self.assertRaises(RuntimeError): idle.plan(self.config, dict(screen=6, lock=5, suspend=0))
            self.assertEqual(self.config.read_text(), CONFIG + extra)

    def test_apply_verifies_runtime_and_configuration_and_creates_backups(self):
        proc = {'pid': 123}
        with patch.object(idle, 'discover', return_value=(self.config, proc)), patch.object(idle.shutil, 'which', return_value='/bin/tool'), patch.object(idle, 'activate', return_value=456) as activate:
            values = dict(screen=7, lock=5, suspend=0)
            self.assertEqual(idle.apply(values, self.root), values)
            activate.assert_called_once_with(self.config, proc, self.root)
        backups = list((self.root / 'state/idle-backups').glob('*/0.conf'))
        self.assertEqual(backups[0].read_text(), CONFIG)

    def test_failed_activation_rolls_back_and_reports_failure(self):
        with patch.object(idle, 'discover', return_value=(self.config, {'pid': 123})), patch.object(idle.shutil, 'which', return_value='/bin/tool'), patch.object(idle, 'processes', return_value=[{'pid': 456}]), patch.object(idle, 'activate', side_effect=[RuntimeError('daemon rejected syntax'), 789]):
            with self.assertRaisesRegex(RuntimeError, 'daemon rejected syntax.*restored and reactivated'):
                idle.apply(dict(screen=7, lock=5, suspend=0), self.root)
        self.assertEqual(self.config.read_text(), CONFIG)

    def test_missing_or_stopped_manager_never_claims_active_settings(self):
        with patch.object(idle, 'discover', return_value=(self.config, None)):
            self.assertFalse(idle.snapshot()['supported'])
            with self.assertRaisesRegex(RuntimeError, 'not running'):
                idle.apply(dict(screen=1, lock=2, suspend=0), self.root)

    def test_custom_lock_scripts_are_reported_instead_of_duplicating_timers(self):
        self.config.write_text(CONFIG.replace('on-timeout = loginctl lock-session', 'on-timeout = ~/.config/ml4w/scripts/lock.sh'))
        with self.assertRaisesRegex(RuntimeError, 'manual review'):
            idle.load(self.config)

    def test_activation_can_restore_a_daemon_that_exited_after_rejecting_config(self):
        (self.root / 'state').mkdir()
        proc = dict(pid=123, args=['hypridle'], env={}, cwd=self.root)
        def command(argv):
            if argv[0] == 'systemctl': return '0'
            if argv[:2] == ['hyprctl','eval']:
                (self.root / 'state/idle-activation.log').write_text('Registered timeout rule\n' * 3 + 'wayland done\n')
            return ''
        with patch.object(idle, 'run', side_effect=command), patch.object(idle.os, 'kill', side_effect=ProcessLookupError), patch.object(idle, 'processes', side_effect=[[], [dict(pid=456)]]):
            self.assertEqual(idle.activate(self.config, proc, self.root),456)

    def test_unknown_idle_state_is_not_reported_as_zero(self):
        with patch.object(idle,'discover',side_effect=RuntimeError('missing idle config')):
            self.assertFalse(idle.snapshot()['known'])
        with patch.object(idle,'discover',return_value=(self.config,{'pid':123})):
            self.assertTrue(idle.snapshot()['known'])
            self.assertEqual(idle.snapshot()['screen'],60)


class ModernHyprland(unittest.TestCase):
    def test_lua_actions_and_second_precision_are_preserved(self):
        off = """hyprctl dispatch 'hl.dsp.dpms({ action = "disable" })'"""
        resume = """hyprctl dispatch 'hl.dsp.dpms({ action = "enable" })' && brightnessctl -r"""
        config = CONFIG.replace('timeout = 3600','timeout = 330').replace('hyprctl dispatch dpms off',off).replace('on-resume = hyprctl dispatch dpms on','on-resume = '+resume)
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp)/'hypridle.conf'
            path.write_text(config)
            values=idle.load(path)[2]
            self.assertEqual(values['screen'],5.5)
            changed=idle.plan(path,dict(values,lock=10))[path]
            self.assertIn('timeout = 330',changed)
            self.assertIn(off,changed)
            self.assertIn(resume,changed)
            path.write_text(changed)
            changed=idle.plan(path,dict(values,screen=6.5,lock=10))[path]
            self.assertIn('timeout = 390',changed)
            self.assertNotIn('390.0',changed)
            self.assertEqual(idle.display_values(dict(values,known=True))['screen_text'],'5.5')

    def test_recogniser_accepts_only_literal_off_actions(self):
        valid = [
            """hyprctl dispatch 'hl.dsp.dpms({action="off"})'""",
            """hyprctl eval 'hl.dispatch(hl.dsp.dpms({ monitor="eDP-1", action="disable", }))'""",
            """hyprctl dispatch "hl.dsp.dpms({action='disable'})" """,
        ]
        invalid = [
            """hyprctl dispatch 'hl.dsp.dpms({action="toggle"})'""",
            """hyprctl dispatch 'hl.dsp.dpms({action=read_state()})'""",
            """hyprctl dispatch 'hl.dsp.dpms({action="disable"}); run_other()'""",
            """hyprctl dispatch 'hl.dsp.dpms({action="disable"})' && other-command""",
            """hyprctl dispatch 'hl.dsp.dpms({action="disable", action="enable"})'""",
        ]
        for action in valid:
            with self.subTest(action=action): self.assertTrue(idle.screen_off_action(action))
        for action in invalid:
            with self.subTest(action=action): self.assertFalse(idle.screen_off_action(action))

    def test_fractional_minutes_keep_exact_seconds_when_adjusting_other_fields(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'idle.conf'
            path.write_text(CONFIG.replace('timeout = 3600','timeout = 500'))
            values=idle.load(path)[2]
            data=idle.display_values(dict(values,known=True))
            self.assertEqual(data['screen_text'],'8.33')
            self.assertIn('500 seconds',data['screen_detail'])
            changed=idle.plan(path,dict(values,lock=8))[path]
            self.assertIn('timeout = 500',changed)
            path.write_text(changed)
            self.assertTrue(idle.same_values(idle.load(path)[2],dict(values,lock=8)))

    def test_new_screen_timer_uses_modern_off_and_resume_commands(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'idle.conf'
            path.write_text('general {\n lock_cmd = hyprlock\n}\n')
            content=idle.plan(path,dict(screen=5,lock=0,suspend=0))[path]
            self.assertIn('action = "disable"',content)
            self.assertIn('action = "enable"',content)
            path.write_text(content)
            self.assertEqual(idle.load(path)[2]['screen'],5)
