"""Keep failed-unit links exact, scoped, read-only, and useful after recovery."""
from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import patch

SCRIPTS = Path(__file__).resolve().parents[1] / 'apps/poedash/assets/scripts'
sys.path.insert(0, str(SCRIPTS))
import dashboard_collect as collect
import service_health as services


class ServiceDiagnostics(unittest.TestCase):
    def test_collection_keeps_system_and_user_units_distinct(self):
        collector = collect.Collectors('/tmp/unused')
        name = 'example@' + 'instance-' * 15 + '.service'
        with patch.object(collector, 'run', side_effect=[name + ' loaded failed failed',
                                                       name + ' loaded failed failed']) as run:
            health = collector.collect('health', {})
        self.assertEqual(health['failed'], [{'unit': name, 'scope': 'system'},
                                             {'unit': name, 'scope': 'user'}])
        self.assertTrue(all('--full' in call.args[0] for call in run.call_args_list))
        issues = collect.health_issues({'health': health})
        self.assertEqual([(i['unit'], i['scope']) for i in issues], [(name, 'system'), (name, 'user')])

    def test_legacy_samples_and_escaped_instances_still_work(self):
        name = r'worker@some\x2dinstance.service'
        self.assertEqual(services.failed_units([name, name, {'unit': name, 'scope': 'user'}]),
                         [{'unit': name, 'scope': 'system'}, {'unit': name, 'scope': 'user'}])

    def test_invalid_names_and_scopes_never_run_commands(self):
        for unit, scope in [('--all', 'system'), ('*.service', 'user'),
                            ('bad/name.service', 'user'), ('a.service;true', 'user'),
                            ('a.service', 'other')]:
            with self.subTest(unit=unit, scope=scope), patch.object(services.subprocess, 'run') as run:
                with self.assertRaises(ValueError): services.service_details(unit, scope)
                run.assert_not_called()

    def test_failed_status_exit_code_keeps_diagnostics_and_exact_scope(self):
        for scope in ('system', 'user'):
            with self.subTest(scope=scope), patch.object(services.subprocess, 'run', side_effect=[
                    subprocess.CompletedProcess([], 3, 'Active: failed\nResult: exit-code', ''),
                    subprocess.CompletedProcess([], 0, 'Application error details', '')]) as run:
                result = services.service_details('example@instance.service', scope)
                self.assertIn('Result: exit-code', result['status'])
                self.assertEqual(result['journal'], 'Application error details')
                status, journal = [call.args[0] for call in run.call_args_list]
                self.assertEqual(status[-2:], ['--', 'example@instance.service'])
                self.assertEqual('--user' in status, scope == 'user')
                self.assertIn('--user-unit' if scope == 'user' else '--unit', journal)
                self.assertTrue(all(call.kwargs['timeout'] == 5 for call in run.call_args_list))
                self.assertTrue(all(not call.kwargs.get('shell') for call in run.call_args_list))

    def test_resolved_or_missing_units_show_current_state(self):
        for output in ('Active: active (running)', 'Unit example.service could not be found.'):
            with self.subTest(output=output), patch.object(services.subprocess, 'run', return_value=
                    subprocess.CompletedProcess([], 4, output, '')):
                self.assertEqual(services.service_details('example.service', 'system')['status'], output)

    def test_permission_errors_and_timeouts_are_visible_without_escalation(self):
        with patch.object(services.subprocess, 'run', side_effect=[
                subprocess.TimeoutExpired('systemctl', 5),
                subprocess.CompletedProcess([], 1, '', 'Permission denied opening journal')]):
            result = services.service_details('example.service', 'system')
        self.assertIn('timed out', result['status'])
        self.assertIn('Permission denied', result['journal'])


if __name__ == '__main__':
    unittest.main()
