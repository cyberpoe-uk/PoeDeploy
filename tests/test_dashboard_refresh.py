"""Independent media cadence, power transitions and bounded background work."""
import asyncio
import os
import shutil
from unittest.mock import patch
import importlib.util
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / 'apps/poedash/assets/scripts'
sys.path.insert(0, str(SCRIPTS))
spec = importlib.util.spec_from_file_location('refresh', SCRIPTS / 'refresh.py')
refresh = importlib.util.module_from_spec(spec)
spec.loader.exec_module(refresh)


class Cadence(unittest.TestCase):
    def test_battery_metrics_are_two_seconds_and_ac_cadences_are_retained(self):
        for key, cadence in refresh.CADENCE.items():
            if key not in ('media', 'power'):
                self.assertEqual(refresh.interval(key, True), 2)
                self.assertEqual(refresh.interval(key, False), cadence)

    def test_power_card_uses_five_seconds_on_battery_and_one_on_ac(self):
        self.assertEqual(refresh.interval('power', True), 5)
        self.assertEqual(refresh.interval('power', False), 1)

    def test_media_only_uses_one_second_while_playing(self):
        for power in (False, True):
            self.assertEqual(refresh.interval('media', power, {'status': 'Playing'}), 1)
            for status in ('Paused', 'Stopped'):
                self.assertEqual(refresh.interval('media', power, {'status': status}), 5)

    def test_there_is_one_scheduler_and_no_duplicate_metric_polls(self):
        text = (ROOT / 'apps/poedash/assets/templates/eww.yuck').read_text()
        self.assertEqual(text.count('exec ./scripts/refresh.py'), 1)
        self.assertIn('dashboard-surface ${refresh_status}', text)
        for key in refresh.CADENCE:
            self.assertIn('(defvar ' + key + ' ', text)
            self.assertNotIn('(defpoll ' + key + ' ', text)


class Scheduling(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.calls, self.batches = [], []
        async def collect(key):
            self.calls.append(key)
            return {'status': 'Playing'} if key == 'media' else 50
        async def publish(data):
            self.batches.append(data)
            return True
        self.scheduler = refresh.Scheduler(Path(self.temp.name), collect, publish)

    async def asyncTearDown(self):
        await self.scheduler.close()

    async def settle(self, now, battery=True, visible=True):
        await self.scheduler.step(now, battery, visible)
        await asyncio.sleep(0.01)
        await self.scheduler.step(now + 0.02, battery, visible)
        await asyncio.sleep(0.01)
        await self.scheduler.step(now + 0.04, battery, visible)

    async def test_media_refreshes_between_general_samples(self):
        await self.settle(0)
        self.calls.clear()
        await self.settle(1.1)
        self.assertEqual(self.calls, ['media'])
        self.calls.clear()
        await self.settle(2.2)
        self.assertEqual(set(self.calls), set(refresh.CADENCE) - {'power'})

    async def test_unchanged_values_do_not_trigger_redundant_updates(self):
        await self.settle(0)
        await self.settle(2.1)
        self.assertEqual(len(self.batches), 1)

    async def test_ac_and_battery_transitions_reschedule_once(self):
        await self.settle(0, battery=False)
        self.calls.clear()
        await self.settle(0.5, battery=True)
        self.assertEqual(len(self.calls), len(refresh.CADENCE))
        self.calls.clear()
        await self.settle(0.7, battery=True)
        self.assertEqual(self.calls, [])
        await self.settle(1, battery=False)
        self.assertEqual(len(self.calls), len(refresh.CADENCE))

    async def test_hidden_dashboard_pauses_collectors_and_resumes_fresh(self):
        await self.settle(0)
        self.calls.clear()
        await self.settle(100, visible=False)
        self.assertEqual(self.calls, [])
        await self.settle(101, visible=True)
        self.assertEqual(set(self.calls), set(refresh.CADENCE))

    async def test_hidden_ac_dashboard_keeps_collecting(self):
        await self.settle(0, battery=False, visible=False)
        self.assertEqual(set(self.calls), set(refresh.CADENCE))
        self.calls.clear()
        await self.settle(1.1, battery=False, visible=False)
        self.assertIn('power', self.calls)
        self.assertIn('media', self.calls)

    async def test_hidden_cable_changes_pause_then_resume_without_showing_workspace(self):
        await self.settle(0, battery=False, visible=False)
        self.calls.clear()
        await self.settle(10, battery=True, visible=False)
        self.assertEqual(self.calls, [])
        await self.settle(11, battery=False, visible=False)
        self.assertEqual(set(self.calls), set(refresh.CADENCE))

    async def test_hiding_on_battery_cancels_inflight_publisher(self):
        gate = asyncio.Event()
        async def publish(data):
            await gate.wait()
            self.batches.append(data)
        self.scheduler.publish = publish
        await self.settle(0)
        await self.settle(1, battery=True, visible=False)
        gate.set()
        await asyncio.sleep(.01)
        self.assertEqual(self.batches, [])
        self.assertIsNone(self.scheduler.publisher)

    async def test_slow_general_collectors_do_not_delay_media_or_duplicate_jobs(self):
        gate = asyncio.Event()
        async def collect(key):
            self.calls.append(key)
            if key != 'media':
                await gate.wait()
            return {'status': 'Playing'} if key == 'media' else 50
        self.scheduler.collect = collect
        await self.settle(0)
        await self.settle(1.1)
        self.assertEqual(self.calls.count('media'), 2)
        for key in refresh.CADENCE:
            if key != 'media':
                self.assertLessEqual(self.calls.count(key), 1)
        self.assertEqual(len(self.scheduler.running), len(refresh.CADENCE) - 1)
        gate.set()

    async def test_power_transition_during_media_collection_does_not_kill_worker(self):
        gate = asyncio.Event()
        async def collect(key):
            self.calls.append(key)
            if key == 'media': await gate.wait()
            return {'status':'Playing'} if key == 'media' else 50
        self.scheduler.collect = collect
        await self.scheduler.step(0, False, True)
        await asyncio.sleep(.01)
        await self.scheduler.step(.1, True, True)
        self.assertNotIn('media', self.scheduler.due)
        gate.set()
        await asyncio.sleep(.01)
        await self.scheduler.step(.2, True, True)
        await self.settle(62, battery=True)
        self.assertEqual(self.scheduler.values['media']['status'],'Playing')
        self.assertGreaterEqual(self.calls.count('arch'),2)

    @unittest.skipUnless(shutil.which('jq'), 'Arch collector requires jq')
    async def test_real_arch_collector_publishes_uptime_after_boot(self):
        root=self.scheduler.root
        (root/'scripts').mkdir()
        shutil.copy2(SCRIPTS/'arch-status.sh',root/'scripts/arch-status.sh')
        binary=root/'bin'
        binary.mkdir()
        cut=binary/'cut'
        cut.write_text('#!/bin/sh\nIFS=. read -r value rest < "$UPTIME_FIXTURE"\nprintf "%s\\n" "$value"\n')
        cut.chmod(0o755)
        uptime=root/'uptime'
        uptime.write_text('0.00\n')
        async def collect(key):
            if key=='arch': return await self.scheduler.read(key)
            return {'status':'Playing'} if key=='media' else 50
        self.scheduler.collect=collect
        async def sample(now, expected):
            for _ in range(200):
                await self.scheduler.step(now,False,True)
                await asyncio.sleep(.01)
                if self.scheduler.values.get('arch',{}).get('uptime')==expected:
                    await self.scheduler.step(now,False,True)
                    await asyncio.sleep(.01)
                    return
            self.fail('Arch uptime did not refresh')
        with patch.dict(os.environ,PATH=str(binary)+os.pathsep+os.environ['PATH'],UPTIME_FIXTURE=str(uptime)):
            await sample(0,'0h 0m')
            uptime.write_text('600.00\n')
            await sample(61,'0h 10m')
        self.assertTrue(any(batch.get('arch',{}).get('uptime')=='0h 10m' for batch in self.batches))


if __name__ == '__main__':
    unittest.main()
