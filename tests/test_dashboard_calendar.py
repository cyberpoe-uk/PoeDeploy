"""Read-only Thunderbird calendar selection, cached events and recurrence."""
from contextlib import closing
from datetime import datetime, timedelta, timezone
import importlib.util
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('dashboard_calendar', ROOT / 'apps/shared/thunderbird-calendar.py')
calendar = importlib.util.module_from_spec(spec)
spec.loader.exec_module(calendar)
UTC = timezone.utc
NOW = datetime(2026, 11, 1, 8, tzinfo=UTC)


class ThunderbirdCalendar(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.home = Path(self.temporary.name)
        root = self.home / '.thunderbird'
        root.mkdir()
        (root / 'profiles.ini').write_text('[InstallExample]\nDefault=chosen\n\n[Profile0]\nPath=other\nIsRelative=1\nDefault=1\n')
        self.profile = root / 'chosen'
        self.profile.mkdir()
        (self.profile / 'prefs.js').write_text(
            'user_pref("calendar.registry.work.type", "caldav");\n'
            'user_pref("calendar.registry.work.name", "Work");\n')
        (self.profile / 'calendar-data').mkdir()
        self.database = self.profile / 'calendar-data/cache.sqlite'
        with closing(sqlite3.connect(self.database)) as connection, connection:
            connection.executescript('''CREATE TABLE cal_events (
                cal_id TEXT, id TEXT, title TEXT, flags INTEGER, event_start INTEGER,
                event_end INTEGER, event_start_tz TEXT, event_end_tz TEXT,
                recurrence_id INTEGER, recurrence_id_tz TEXT, ical_status TEXT, offline_journal INTEGER);
                CREATE TABLE cal_recurrence (cal_id TEXT, item_id TEXT, icalString TEXT);''')

    def event(self, start, end=None, **extra):
        value = {'cal_id': 'work', 'id': 'event', 'title': 'Planning', 'flags': 0,
                 'event_start': int(start.timestamp() * 1_000_000),
                 'event_end': int((end or start.replace(hour=start.hour + 1)).timestamp() * 1_000_000),
                 'event_start_tz': 'UTC', 'event_end_tz': 'UTC',
                 'recurrence_id': None, 'recurrence_id_tz': 'UTC', 'ical_status': 'CONFIRMED', 'offline_journal': None}
        value.update(extra)
        with closing(sqlite3.connect(self.database)) as connection, connection:
            connection.execute('INSERT INTO cal_events (' + ','.join(value) + ') VALUES (' + ','.join('?' for _ in value) + ')', tuple(value.values()))

    def recurrence(self, text):
        with closing(sqlite3.connect(self.database)) as connection, connection:
            connection.execute('INSERT INTO cal_recurrence VALUES (?,?,?)', ('work', 'event', text))

    def read(self, now=NOW, tz=UTC):
        with patch.object(calendar, 'local_zone', return_value=tz):
            return calendar.reading(self.home, now)

    def test_install_default_profile_wins_over_legacy_profile_default(self):
        self.assertEqual(calendar.profile(self.home), self.profile)

    def test_no_profile_or_calendar_configuration_stays_empty(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertFalse(calendar.reading(Path(tmp), NOW)['connected'])
            self.assertEqual(list(Path(tmp).iterdir()), [])
        (self.profile / 'prefs.js').write_text('')
        self.assertEqual(self.read()['events'], [])
        self.assertFalse(self.read()['connected'])

    def test_upcoming_window_is_fourteen_days_not_the_entire_month(self):
        self.event(NOW+timedelta(days=13),id='within',title='Within window')
        self.event(NOW+timedelta(days=14),id='boundary',title='At boundary')
        self.event(NOW+timedelta(days=20),id='later',title='Later this month')
        data=self.read()
        self.assertEqual([event['title'] for event in data['events']],['Within window'])
        self.assertIn('14 days',data['status'])

    def test_upcoming_events_are_read_without_changing_the_database(self):
        self.event(NOW.replace(hour=10))
        before = self.database.read_bytes()
        result = self.read()
        self.assertEqual(result['events'], [{'when': 'Today · 10:00', 'title': 'Planning', 'calendar': 'Work'}])
        self.assertEqual(self.database.read_bytes(), before)

    def test_cancelled_disabled_and_removed_calendars_do_not_appear(self):
        self.event(NOW.replace(hour=10), ical_status='CANCELLED')
        self.event(NOW.replace(hour=11), id='removed', cal_id='removed')
        self.assertEqual(self.read()['events'], [])
        with (self.profile / 'prefs.js').open('a') as stream:
            stream.write('user_pref("calendar.registry.work.disabled", true);\n')
        self.assertFalse(self.read()['connected'])

    def test_recurring_events_obey_count_exclusions_and_moved_occurrences(self):
        start = NOW.replace(hour=10)
        self.event(start, flags=16)
        self.recurrence('RRULE:FREQ=DAILY;COUNT=4')
        self.recurrence('EXDATE:20261103T100000Z')
        original = datetime(2026, 11, 2, 10, tzinfo=UTC)
        self.event(original.replace(hour=12), title='Moved planning', recurrence_id=int(original.timestamp() * 1_000_000))
        result = self.read()['events']
        self.assertEqual(len(result), 3)
        self.assertEqual([item['title'] for item in result], ['Planning', 'Moved planning', 'Planning'])
        self.assertIn('12:00', result[1]['when'])

    def test_all_day_events_keep_their_calendar_date(self):
        self.event(NOW.replace(hour=0), datetime(2026, 11, 2, tzinfo=UTC), flags=8)
        self.assertEqual(self.read()['events'][0]['when'], 'Today · All day')

    def test_weekly_recurrence_preserves_wall_time_across_dst(self):
        london = ZoneInfo('Europe/London')
        start = datetime(2026, 10, 18, 9, tzinfo=london)
        self.event(start, flags=16, event_start_tz='Europe/London', event_end_tz='Europe/London')
        self.recurrence('RRULE:FREQ=WEEKLY;COUNT=2;BYDAY=SU')
        result = self.read(datetime(2026, 10, 24, 8, tzinfo=UTC), london)['events']
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]['when'], 'Sun 25 Oct · 09:00')

    def test_missing_offline_cache_and_corrupt_database_are_nonfatal(self):
        self.database.unlink()
        self.assertEqual(self.read()['events'], [])
        self.database.write_bytes(b'not a database')
        self.assertIn('unavailable', self.read()['status'])

    def test_monthly_ordinal_rules_use_the_bundled_recurrence_engine(self):
        start = datetime(2026, 10, 5, 9, tzinfo=UTC)
        self.event(start, flags=16)
        self.recurrence('RRULE:FREQ=MONTHLY;BYDAY=1MO;COUNT=3')
        self.assertEqual(self.read()['events'][0]['when'], 'Mon 02 Nov · 09:00')


if __name__ == '__main__':
    unittest.main()
