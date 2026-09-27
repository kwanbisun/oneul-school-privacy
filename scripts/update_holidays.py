"""Build a public holiday feed from KASI. Run only on the publisher, never in the app.

KASI_SERVICE_KEY is a CI secret. Do not print URLs/errors containing it.
Official API: https://www.data.go.kr/data/15012690/openapi.do
Unknown/partial future years are not advertised as supported.
"""
import argparse
import datetime as dt
import json
import os
from pathlib import Path
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET

ENDPOINT = 'https://apis.data.go.kr/B090041/openapi/service/SpcdeInfoService/getRestDeInfo'
ANCHORS = ('01-01', '03-01', '05-05', '06-06', '08-15', '10-03', '10-09', '12-25')


def parse_year(raw, year):
    if len(raw) > 128 * 1024 or b'<!DOCTYPE' in raw.upper() or b'<!ENTITY' in raw.upper():
        raise ValueError('Invalid XML')
    root = ET.fromstring(raw)
    if root.findtext('./header/resultCode') != '00':
        raise ValueError('API error')
    items = root.findall('./body/items/item')
    if int(root.findtext('./body/totalCount', '-1')) != len(items):
        raise ValueError('Incomplete page')
    days = {}
    for item in items:
        if item.findtext('isHoliday') != 'Y':
            continue
        day = dt.datetime.strptime(item.findtext('locdate', ''), '%Y%m%d').date()
        name = (item.findtext('dateName') or '').strip()
        if day.year != year or not name or len(name) > 60 or any(ord(c) < 32 or c in '<>' for c in name):
            raise ValueError('Invalid date or name')
        # Two legal holidays can coincide. Keep both names, one calendar date.
        previous = days.get(day.isoformat())
        days[day.isoformat()] = ' · '.join(dict.fromkeys([previous, name])) if previous and previous != name else name
        if len(days[day.isoformat()]) > 60:
            raise ValueError('Combined name too long')
    if not days:
        return None
    if not 16 <= len(days) <= 64 or not all(f'{year}-{day}' in days for day in ANCHORS):
        return None
    return days


def fetch_year(year, key):
    params = urllib.parse.urlencode({'serviceKey': key, 'solYear': year, 'numOfRows': 100, 'pageNo': 1})
    request = urllib.request.Request(ENDPOINT + '?' + params, headers={'User-Agent': 'CalendarToYou-HolidayPublisher'})
    # urllib errors may contain the secret URL: callers must never print exception details.
    with urllib.request.urlopen(request, timeout=30) as response:
        raw = response.read(128 * 1024 + 1)
    return parse_year(raw, year)


def build(previous, fetched, today):
    by_year = {}
    for item in previous['holidays']:
        year = dt.date.fromisoformat(item['date']).year
        by_year.setdefault(year, {})[item['date']] = item['name']
    # Do not replace a known full year with an unavailable/partial response.
    for year, days in fetched.items():
        if days is not None:
            # A stale/partial upstream response must not remove already verified holidays.
            # Genuine cancellations require a reviewed seed change before automatic publishing.
            if not set(by_year.get(year, {})).issubset(days):
                raise ValueError(f'Previously verified dates missing for {year}; review required')
            by_year[year] = days
    values = [{'date': day, 'name': name} for year in sorted(by_year)
              for day, name in sorted(by_year[year].items())]
    # Stable content means no new revision; clients still record a successful weekly check.
    if values == previous['holidays']:
        return previous
    revision = max(previous['revision'] + 1, int(today.strftime('%Y%m%d')) * 100)
    return {'schema': 1, 'revision': revision, 'checkedAt': today.isoformat(),
            'years': sorted(by_year), 'holidays': values}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--feed', type=Path, default=Path('holidays.json'))
    args = parser.parse_args()
    key = os.environ.get('KASI_SERVICE_KEY', '').strip()
    if not key:
        raise SystemExit('Set the KASI_SERVICE_KEY repository secret (Decoding key).')
    previous = json.loads(args.feed.read_text(encoding='utf-8'))
    fetched = {}
    for year in range(2026, 2036):
        try:
            fetched[year] = fetch_year(year, key)
        except Exception:
            raise SystemExit(f'Official request failed for {year}; existing feed was preserved. Check API approval/key/service status.') from None
    # A failure of an existing covered year must not be disguised as a successful refresh.
    missing = [year for year in previous['years'] if fetched.get(year) is None]
    if missing:
        raise SystemExit(f'Incomplete official data for existing years {missing}; existing feed preserved.')
    result = build(previous, fetched, dt.datetime.now(dt.timezone.utc).date())
    if result != previous:
        tmp = args.feed.with_suffix('.tmp')
        tmp.write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
        tmp.replace(args.feed)
    print('Supported years:', ', '.join(map(str, result['years'])))
    missing_future = [year for year, days in fetched.items() if days is None]
    if missing_future:
        print('Future years without complete official data:', ', '.join(map(str, missing_future)))


if __name__ == '__main__':
    main()
