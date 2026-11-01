#!/usr/bin/env python3
"""Read upcoming events from Thunderbird's enabled local calendars without syncing."""
import configparser
from contextlib import closing
from datetime import datetime, timedelta, timezone
import itertools
import json
import os
from pathlib import Path
import re
import signal
import sqlite3
import sys
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

# A small, licensed source subset is bundled to keep refreshes package-free.
sys.path.insert(0, str(Path(__file__).with_name('calendar-vendor')))
from dateutil import rrule

UTC = timezone.utc
WEEKDAYS = {name: getattr(rrule, name) for name in ('MO', 'TU', 'WE', 'TH', 'FR', 'SA', 'SU')}


def local_zone():
    try:
        name = os.environ.get('TZ') or str(Path('/etc/localtime').resolve()).split('/zoneinfo/', 1)[1]
        return ZoneInfo(name)
    except (IndexError, ValueError, ZoneInfoNotFoundError):
        return datetime.now().astimezone().tzinfo


def profile(home):
    roots = (home / '.thunderbird', home / '.config/thunderbird',
             home / '.var/app/org.mozilla.Thunderbird/.thunderbird')
    for root in roots:
        parser = configparser.ConfigParser(interpolation=None)
        try:
            parser.read(root / 'profiles.ini')
            install = next((parser[s]['Default'] for s in parser.sections()
                            if s.startswith('Install') and parser[s].get('Default')), None)
            if install:
                return root / install
            sections = [parser[s] for s in parser.sections() if s.startswith('Profile') and parser[s].get('Path')]
            if sections:
                selected = next((s for s in sections if s.get('Default') == '1'), sections[0])
                return root / selected['Path'] if selected.get('IsRelative', '1') == '1' else Path(selected['Path'])
        except (OSError, KeyError, configparser.Error):
            continue
    return None


def calendars(path):
    result = {}
    try:
        prefs = (path / 'prefs.js').read_text()
    except OSError:
        return result
    pattern = r'user_pref\("calendar\.registry\.([^".]+)\.([^" ]+)",\s*(.+)\);'
    for identifier, key, raw in re.findall(pattern, prefs):
        try:
            result.setdefault(identifier, {})[key] = json.loads(raw)
        except ValueError:
            continue
    return {key: value for key, value in result.items()
            if value.get('type') and not value.get('disabled', False)}


def zone(name, fallback):
    if not name or name == 'floating':
        return fallback
    if name.startswith('BEGIN:VTIMEZONE'):
        match = re.search(r'(?:^|\n)TZID:([^\r\n]+)', name)
        name = match[1] if match else 'UTC'
    try:
        return ZoneInfo(name)
    except (ValueError, ZoneInfoNotFoundError):
        return UTC


def native_time(value, tz, local, all_day=False):
    result = datetime.fromtimestamp(int(value) / 1_000_000, UTC)
    if all_day or not tz or tz == 'floating':
        return result.replace(tzinfo=local)
    return result.astimezone(zone(tz, local))


def ical_time(value, tz):
    value = value.strip()
    if re.fullmatch(r'\d{8}', value):
        return datetime.strptime(value, '%Y%m%d').replace(tzinfo=tz)
    if value.endswith('Z'):
        return datetime.strptime(value, '%Y%m%dT%H%M%SZ').replace(tzinfo=UTC)
    return datetime.strptime(value, '%Y%m%dT%H%M%S').replace(tzinfo=tz)


def rule(value, start):
    fields = dict(part.split('=', 1) for part in value.split(';'))
    frequency = fields.pop('FREQ')
    # Sub-day rules can generate unbounded historical data in a dashboard poll.
    if frequency not in ('DAILY', 'WEEKLY', 'MONTHLY', 'YEARLY'):
        raise ValueError('Unsupported sub-day recurrence')
    args = {'dtstart': start}
    for key, raw in fields.items():
        if key in ('INTERVAL', 'COUNT'):
            args[key.lower()] = int(raw)
        elif key == 'UNTIL':
            args['until'] = ical_time(raw, start.tzinfo)
        elif key == 'WKST':
            args['wkst'] = WEEKDAYS[raw]
        elif key == 'BYDAY':
            values = []
            for item in raw.split(','):
                match = re.fullmatch(r'([+-]?\d+)?(MO|TU|WE|TH|FR|SA|SU)', item)
                if not match:
                    raise ValueError('Invalid recurrence weekday')
                day = WEEKDAYS[match[2]]
                values.append(day(int(match[1])) if match[1] else day)
            args['byweekday'] = values
        elif key in ('BYSETPOS', 'BYMONTH', 'BYMONTHDAY', 'BYYEARDAY', 'BYWEEKNO', 'BYHOUR', 'BYMINUTE', 'BYSECOND'):
            args[key.lower()] = [int(item) for item in raw.split(',')]
        else:
            raise ValueError('Unsupported recurrence field')
    return rrule.rrule(getattr(rrule, frequency), **args)


def occurrences(start, lines, lower, upper):
    schedule = rrule.rruleset()
    schedule.rdate(start)
    for text in lines:
        for line in re.sub(r'\r?\n[ \t]', '', text).splitlines():
            header, value = line.split(':', 1)
            kind = header.split(';')[0]
            if kind in ('RRULE', 'EXRULE'):
                getattr(schedule, 'rrule' if kind == 'RRULE' else 'exrule')(rule(value, start))
            elif kind in ('RDATE', 'EXDATE'):
                match = re.search(r'TZID=([^;]+)', header)
                tz = zone(match[1], start.tzinfo) if match else start.tzinfo
                for date in value.split(','):
                    getattr(schedule, 'rdate' if kind == 'RDATE' else 'exdate')(ical_time(date, tz))
    for item in itertools.islice(schedule.xafter(lower, inc=True), 64):
        if item >= upper:
            break
        yield item


def database_events(path, enabled, now, local):
    end = now + timedelta(days=14)
    lower = now.replace(hour=0, minute=0, second=0, microsecond=0)
    events, partial = [], False
    with closing(sqlite3.connect(path.as_uri() + '?mode=ro', uri=True, timeout=0.2)) as connection:
        connection.row_factory = sqlite3.Row
        connection.execute('PRAGMA query_only=ON')
        identifiers = list(enabled)
        placeholders = ','.join('?' for _ in identifiers)
        rows = [dict(row) for row in connection.execute(
            'SELECT * FROM cal_events WHERE cal_id IN (' + placeholders + ') AND '
            '(recurrence_id IS NOT NULL OR (event_start < ? AND (event_end >= ? OR flags & 16 != 0))) LIMIT 5000',
            (*identifiers, int((end + timedelta(days=1)).timestamp() * 1_000_000),
             int((lower - timedelta(days=1)).timestamp() * 1_000_000)))]
        partial = len(rows) == 5000
        recurring = {}
        try:
            for row in connection.execute('SELECT cal_id, item_id, icalString FROM cal_recurrence WHERE cal_id IN (' + placeholders + ') LIMIT 10000', identifiers):
                if row['cal_id'] in enabled:
                    recurring.setdefault((row['cal_id'], row['item_id']), []).append(row['icalString'])
        except sqlite3.Error:
            partial = True
    overrides = {}
    for row in rows:
        if row.get('recurrence_id') is not None:
            try:
                day = bool((row.get('flags') or 0) & 512)
                original = native_time(row['recurrence_id'], row.get('recurrence_id_tz'), local, day)
                overrides[(row['cal_id'], row['id'], original)] = row
            except (ValueError, TypeError, OverflowError):
                partial = True
    for row in rows:
        try:
            if row.get('ical_status') == 'CANCELLED' or row.get('offline_journal') == 3:
                continue
            all_day = bool((row.get('flags') or 0) & 8)
            start = native_time(row['event_start'], row.get('event_start_tz'), local, all_day)
            finish = native_time(row.get('event_end') or row['event_start'], row.get('event_end_tz'), local, all_day)
            duration = max(timedelta(0), finish - start)
            recurrence = recurring.get((row['cal_id'], row['id']), []) if row.get('recurrence_id') is None else []
            starts = occurrences(start, recurrence, lower - duration, end) if recurrence else [start]
            for occurrence in starts:
                if row.get('recurrence_id') is None and (row['cal_id'], row['id'], occurrence) in overrides:
                    continue
                last = occurrence + duration
                if occurrence >= end or (last <= now and not (duration == timedelta(0) and occurrence >= now)):
                    continue
                displayed = occurrence.astimezone(local)
                day = 'Today' if displayed.date() == now.date() else displayed.strftime('%a %d %b')
                when = day + (' · All day' if all_day else displayed.strftime(' · %H:%M'))
                events.append({'key': (row['cal_id'], row['id'], occurrence.isoformat()),
                               'sort': occurrence.timestamp(), 'when': when,
                               'title': row.get('title') or 'Untitled event',
                               'calendar': enabled[row['cal_id']].get('name', 'Calendar')})
        except (ValueError, TypeError, KeyError, OverflowError):
            partial = True
    return events, partial


def reading(home=None, now=None):
    home = Path.home() if home is None else home
    local = local_zone()
    now = datetime.now(local) if now is None else now.astimezone(local)
    selected = profile(home)
    enabled = calendars(selected) if selected else {}
    if not enabled:
        return {'connected': False, 'status': 'No Thunderbird calendars connected', 'events': []}
    values, partial = {}, False
    for filename in ('local.sqlite', 'cache.sqlite'):
        path = selected / 'calendar-data' / filename
        if not path.is_file():
            continue
        try:
            events, failed = database_events(path, enabled, now, local)
            partial = partial or failed
            for event in events:
                values[event['key']] = event
        except (OSError, sqlite3.Error):
            partial = True
    events = sorted(values.values(), key=lambda event: event['sort'])[:8]
    status = 'Thunderbird · next 14 days' if events else 'No cached events · next 14 days'
    if partial:
        status = 'Some Thunderbird calendar data is unavailable'
    return {'connected': True, 'status': status,
            'events': [{key: event[key] for key in ('when', 'title', 'calendar')} for event in events]}


if __name__ == '__main__':
    try:
        def timeout(signum, frame):
            raise TimeoutError('Calendar poll exceeded its time budget')
        signal.signal(signal.SIGALRM, timeout)
        signal.alarm(4)
        print(json.dumps(reading()))
    except (OSError, ValueError, sqlite3.Error, TimeoutError):
        print(json.dumps({'connected': False, 'status': 'Thunderbird calendar unavailable', 'events': []}))
