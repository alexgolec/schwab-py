import datetime

import pytest

import schwab


_PH = schwab.client.Client.PriceHistory


def _dt(y, m, d):
    return datetime.datetime(y, m, d, tzinfo=datetime.timezone.utc)


def _ms(dt):
    return int(dt.timestamp() * 1000)


def _now():
    return datetime.datetime.now(datetime.timezone.utc)


def _check_candle(candle):
    assert set(candle) == {
            'open', 'high', 'low', 'close', 'volume', 'datetime'}
    for key in ('open', 'high', 'low', 'close'):
        price = candle[key]
        assert isinstance(price, (int, float))
        assert price > 0
    assert candle['low'] <= candle['open'] <= candle['high']
    assert candle['low'] <= candle['close'] <= candle['high']
    assert isinstance(candle['volume'], int)
    assert candle['volume'] >= 0
    assert isinstance(candle['datetime'], int)
    assert 0 < candle['datetime'] <= _ms(_now())


def _gaps(candles):
    return [candles[i]['datetime'] - candles[i - 1]['datetime']
            for i in range(1, len(candles))]


def _check_minute_response(resp, granularity_ms):
    '''Shared structure asserts for minute-granularity responses on a
    relative window: non-empty, sorted, session-aligned, gaps are
    multiples of the granularity with the granularity the minimum.'''
    assert resp.status_code == 200
    data = resp.json()
    candles = data['candles']
    assert data['empty'] is False
    assert len(candles) > 0
    for candle in candles:
        _check_candle(candle)
    gaps = _gaps(candles)
    assert min(gaps) == granularity_ms
    assert all(g % granularity_ms == 0 for g in gaps)
    assert all(c['datetime'] % granularity_ms == 0 for c in candles)
    return candles


def _days_ago(n):
    return _now() - datetime.timedelta(days=n)


def _old_window_is_empty(fn, live_client, start_days_ago, end_days_ago):
    '''Requests a window entirely older than a granularity's measured
    retention horizon and asserts the API's out-of-retention contract:
    HTTP 200 with empty=true and zero candles.'''
    resp = fn('AAPL', start_datetime=_days_ago(start_days_ago),
              end_datetime=_days_ago(end_days_ago))
    assert resp.status_code == 200
    data = resp.json()
    assert data['empty'] is True
    assert data['candles'] == []


# Measured retention horizons (Nov 2026 probing):
#   1-minute:    ~48 days    (60-55d ago empty; data back to ~52d)
#   5-30 minute: ~9 months   (320-280d ago empty; data back to ~265d)
#   day/week:    effectively unlimited (full history since 1985/1984)
_MINUTE_RETENTION_WINDOW = (70, 60)      # comfortably beyond ~48d
_COARSE_RETENTION_WINDOW = (320, 280)    # comfortably beyond ~9mo


################################################################################
# every_minute

def test_minute_old_window_empty(live_client):
    '''One-minute retention is ~48 days. A window entirely beyond it
    (here 60-70 days ago, measured empty while data exists back to
    ~52 days) returns empty=true with zero candles rather than an
    error or truncated data. A window that only partially overlaps
    the horizon instead returns just the overlapping portion.'''
    _old_window_is_empty(live_client.get_price_history_every_minute,
                         live_client, *_MINUTE_RETENTION_WINDOW)


def test_minute_recent_window_structure(live_client):
    '''Inside the ~48-day retention horizon, a minute window returns
    well-formed candles at exactly one-minute spacing. Requests a
    relative window from 10 days ago to 5 days ago, checks every
    candle's OHLCV format, and asserts all consecutive gaps are
    whole multiples of 60000ms with the smallest gap being exactly
    the granularity (no sub-minute spacing, thin minutes skipped
    rather than empty).'''
    resp = live_client.get_price_history_every_minute(
            'AAPL', start_datetime=_days_ago(10),
            end_datetime=_days_ago(5))
    candles = _check_minute_response(resp, 60000)
    assert candles[0]['datetime'] <= _ms(_days_ago(5))


def test_minute_retention_horizon(live_client):
    '''Minute data is retained for roughly 48 days: a window wider
    than the horizon returns candles from the retention boundary to
    the present — the most recent data, not the start of the
    requested window. The candle count is density-dependent (traded
    minutes only, thin minutes skipped) and not part of the
    contract; the contract is the clamped reach and the recency of
    the final candle.'''
    resp = live_client.get_price_history_every_minute(
            'AAPL', start_datetime=_days_ago(365), end_datetime=_now())
    candles = _check_minute_response(resp, 60000)
    assert candles[-1]['datetime'] > _ms(_days_ago(7))
    assert candles[0]['datetime'] < _ms(_days_ago(30))


def test_minute_default_no_dates(live_client):
    '''With no dates the helper normalizes start to 1971 and end to
    ~now, which produces the same retention-clamped response as an
    explicit very wide window: reaches the horizon, ends at the
    present.'''
    resp = live_client.get_price_history_every_minute('AAPL')
    candles = _check_minute_response(resp, 60000)
    assert candles[-1]['datetime'] > _ms(_days_ago(7))
    assert candles[0]['datetime'] < _ms(_days_ago(30))


################################################################################
# every_five_minutes

def test_five_minute_old_window_empty(live_client):
    '''Five-minute retention is ~9 months. A window entirely beyond
    it (here 280-320 days ago, measured empty while data exists
    back to ~265 days) returns empty=true with zero candles.'''
    _old_window_is_empty(
            live_client.get_price_history_every_five_minutes,
            live_client, *_COARSE_RETENTION_WINDOW)


def test_five_minute_recent_window_structure(live_client):
    '''Inside the ~9-month retention horizon, a five-minute window
    returns well-formed candles at exactly five-minute spacing.
    Requests a relative 10-to-5-days-ago window and asserts all gaps
    are multiples of 300000ms with the smallest gap equal to the
    granularity.'''
    resp = live_client.get_price_history_every_five_minutes(
            'AAPL', start_datetime=_days_ago(10),
            end_datetime=_days_ago(5))
    _check_minute_response(resp, 300000)


def test_five_minute_retention_horizon(live_client):
    '''Five-minute data is retained for roughly 200 days: a window
    wider than the horizon returns candles from the retention
    boundary to the present, not the requested window's oldest.
    As with minute data the count is density-dependent and not part
    of the contract.'''
    resp = live_client.get_price_history_every_five_minutes(
            'AAPL', start_datetime=_days_ago(365), end_datetime=_now())
    candles = _check_minute_response(resp, 300000)
    assert candles[-1]['datetime'] > _ms(_days_ago(7))
    assert candles[0]['datetime'] < _ms(_days_ago(150))


def test_five_minute_default_no_dates(live_client):
    '''Default date normalization (1971 to ~now) produces the same
    retention-clamped response as an explicit wide window: reaches
    the horizon, ends at the present.'''
    resp = live_client.get_price_history_every_five_minutes('AAPL')
    candles = _check_minute_response(resp, 300000)
    assert candles[-1]['datetime'] > _ms(_days_ago(7))
    assert candles[0]['datetime'] < _ms(_days_ago(150))


################################################################################
# every_ten_minutes

def test_ten_minute_old_window_empty(live_client):
    '''Ten-minute retention is ~9 months. A window entirely beyond
    it (here 280-320 days ago, measured empty while data exists
    back to ~265 days) returns empty=true with zero candles.'''
    _old_window_is_empty(
            live_client.get_price_history_every_ten_minutes,
            live_client, *_COARSE_RETENTION_WINDOW)


def test_ten_minute_recent_window_structure(live_client):
    '''Inside the ~9-month retention horizon, a ten-minute window
    returns well-formed candles at exactly ten-minute spacing.
    Requests a relative 10-to-5-days-ago window and asserts all gaps
    are multiples of 600000ms with the smallest gap equal to the
    granularity.'''
    resp = live_client.get_price_history_every_ten_minutes(
            'AAPL', start_datetime=_days_ago(10),
            end_datetime=_days_ago(5))
    _check_minute_response(resp, 600000)


def test_ten_minute_year_window_coverage(live_client):
    '''Ten-minute data is retention-bound rather than cap-bound:
    Schwab retains ~9 months of it (measured back to ~265 days),
    which fits under 40,000 candles, so a one-year window returns
    everything retained rather than exactly 40,000 most-recent
    candles. Asserts a non-empty result strictly below the cap.'''
    resp = live_client.get_price_history_every_ten_minutes(
            'AAPL', start_datetime=_days_ago(365), end_datetime=_now())
    candles = _check_minute_response(resp, 600000)
    assert len(candles) < 40000


def test_ten_minute_default_no_dates(live_client):
    '''With no dates the helper requests 1971 to ~now, but ten-minute
    retention only reaches ~9 months back, so the response contains
    everything retained and stays under the 40,000 cap.'''
    resp = live_client.get_price_history_every_ten_minutes('AAPL')
    candles = _check_minute_response(resp, 600000)
    assert len(candles) < 40000


################################################################################
# every_fifteen_minutes

def test_fifteen_minute_old_window_empty(live_client):
    '''Fifteen-minute retention is ~9 months. A window entirely
    beyond it (here 280-320 days ago, measured empty while data
    exists back to ~265 days) returns empty=true with zero candles.'''
    _old_window_is_empty(
            live_client.get_price_history_every_fifteen_minutes,
            live_client, *_COARSE_RETENTION_WINDOW)


def test_fifteen_minute_recent_window_structure(live_client):
    '''Inside the ~9-month retention horizon, a fifteen-minute window
    returns well-formed candles at exactly fifteen-minute spacing.
    Requests a relative 10-to-5-days-ago window and asserts all gaps
    are multiples of 900000ms with the smallest gap equal to the
    granularity.'''
    resp = live_client.get_price_history_every_fifteen_minutes(
            'AAPL', start_datetime=_days_ago(10),
            end_datetime=_days_ago(5))
    _check_minute_response(resp, 900000)


def test_fifteen_minute_year_window_coverage(live_client):
    '''Fifteen-minute data is retention-bound rather than cap-bound:
    the ~9 months retained (measured back to ~265 days) fits under
    40,000 candles, so a one-year window returns everything retained
    rather than a truncated, exactly-40,000 response. Asserts
    non-empty and strictly below the cap.'''
    resp = live_client.get_price_history_every_fifteen_minutes(
            'AAPL', start_datetime=_days_ago(365), end_datetime=_now())
    candles = _check_minute_response(resp, 900000)
    assert len(candles) < 40000


def test_fifteen_minute_default_no_dates(live_client):
    '''With no dates the helper requests 1971 to ~now, but
    fifteen-minute retention only reaches ~9 months back, so the
    response contains everything retained and stays under the
    40,000 cap.'''
    resp = live_client.get_price_history_every_fifteen_minutes('AAPL')
    candles = _check_minute_response(resp, 900000)
    assert len(candles) < 40000


################################################################################
# every_thirty_minutes

def test_thirty_minute_old_window_empty(live_client):
    '''Thirty-minute retention is ~9 months. A window entirely beyond
    it (here 280-320 days ago, measured empty while data exists back
    to ~265 days) returns empty=true with zero candles.'''
    _old_window_is_empty(
            live_client.get_price_history_every_thirty_minutes,
            live_client, *_COARSE_RETENTION_WINDOW)


def test_thirty_minute_recent_window_structure(live_client):
    '''Inside the ~9-month retention horizon, a thirty-minute window
    returns well-formed candles at exactly thirty-minute spacing.
    Requests a relative 10-to-5-days-ago window and asserts all gaps
    are multiples of 1800000ms with the smallest gap equal to the
    granularity.'''
    resp = live_client.get_price_history_every_thirty_minutes(
            'AAPL', start_datetime=_days_ago(10),
            end_datetime=_days_ago(5))
    _check_minute_response(resp, 1800000)


def test_thirty_minute_year_window_coverage(live_client):
    '''Thirty-minute data is retention-bound rather than cap-bound:
    the ~9 months retained (measured back to ~265 days) fits under
    40,000 candles, so a one-year window returns everything retained
    rather than a truncated, exactly-40,000 response. Asserts
    non-empty and strictly below the cap.'''
    resp = live_client.get_price_history_every_thirty_minutes(
            'AAPL', start_datetime=_days_ago(365), end_datetime=_now())
    candles = _check_minute_response(resp, 1800000)
    assert len(candles) < 40000


def test_thirty_minute_default_no_dates(live_client):
    '''With no dates the helper requests 1971 to ~now, but
    thirty-minute retention only reaches ~9 months back, so the
    response contains everything retained and stays under the
    40,000 cap.'''
    resp = live_client.get_price_history_every_thirty_minutes('AAPL')
    candles = _check_minute_response(resp, 1800000)
    assert len(candles) < 40000


################################################################################
# every_day

def test_day_deterministic_week(live_client):
    '''A fixed historical window returns deterministic daily data:
    AAPL's Mon Jan 13 through Fri Jan 17 2025 is exactly five
    candles. Asserts the count, the first and last candles' exact
    OHLCV and 06:00-UTC session timestamps, and generic candle
    format on the remaining days.'''
    resp = live_client.get_price_history_every_day(
            'AAPL', start_date=datetime.date(2025, 1, 13),
            end_date=datetime.date(2025, 1, 18))

    assert resp.status_code == 200
    data = resp.json()
    assert data['empty'] is False
    candles = data['candles']
    assert len(candles) == 5

    first = candles[0]
    assert first['datetime'] == _ms(_dt(2025, 1, 13)) + 6 * 3600000
    assert first['open'] == 233.53
    assert first['high'] == 234.67
    assert first['low'] == 229.72
    assert first['close'] == 234.4
    assert first['volume'] == 49630725

    last = candles[-1]
    assert last['datetime'] == _ms(_dt(2025, 1, 17)) + 6 * 3600000
    assert last['open'] == 232.115
    assert last['high'] == 232.29
    assert last['low'] == 228.48
    assert last['close'] == 229.98
    assert last['volume'] == 68488301

    for candle in candles:
        _check_candle(candle)


def test_day_gap_structure(live_client):
    '''Enshrines each observed daily gap case at a concrete calendar
    date. Candle timestamps are midnight US Eastern, so gaps are
    whole-day multiples *except* across DST transitions: the
    spring-forward Friday-to-Monday gap is 71h and the fall-back one
    is 73h instead of 72h. Also covered: the 24h weekday pair, the
    48h mid-week holiday pair (Thanksgiving), and the 96h holiday
    weekend (MLK). Requests Jan 2025 through Nov 2026 and asserts
    the exact millisecond gap for each named date pair.'''
    resp = live_client.get_price_history_every_day(
            'AAPL', start_date=datetime.date(2025, 1, 6),
            end_date=datetime.date(2026, 11, 15))

    assert resp.status_code == 200
    candles = resp.json()['candles']
    by_date = {
            datetime.datetime.fromtimestamp(
                    c['datetime'] / 1000, datetime.timezone.utc).date():
            c['datetime'] for c in candles}

    def gap(d1, d2):
        return by_date[d2] - by_date[d1]

    HOUR = 3600000
    assert gap(datetime.date(2025, 1, 13),   # Mon -> Tue: 24h
               datetime.date(2025, 1, 14)) == 24 * HOUR
    assert gap(datetime.date(2025, 1, 10),   # Fri -> Mon weekend: 72h
               datetime.date(2025, 1, 13)) == 72 * HOUR
    assert gap(datetime.date(2025, 11, 26),  # Wed -> Fri, Thanksgiving
               datetime.date(2025, 11, 28)) == 48 * HOUR
    assert gap(datetime.date(2025, 1, 17),   # Fri -> Tue, MLK weekend
               datetime.date(2025, 1, 21)) == 96 * HOUR
    assert gap(datetime.date(2026, 3, 6),    # Fri -> Mon spring-forward
               datetime.date(2026, 3, 9)) == 71 * HOUR
    assert gap(datetime.date(2026, 10, 30),  # Fri -> Mon fall-back
               datetime.date(2026, 11, 2)) == 73 * HOUR


def test_day_full_history(live_client):
    '''Daily data has no candle-count cap: requesting from 1971
    returns Schwab's entire AAPL history, which begins at the
    1985-01-02 session (10k+ candles). Asserts the first candle's
    exact timestamp and split-adjusted OHLCV as an anchor for
    full-history reach.'''
    resp = live_client.get_price_history_every_day(
            'AAPL', start_date=datetime.date(1971, 1, 1))

    assert resp.status_code == 200
    candles = resp.json()['candles']
    first = candles[0]
    assert first['datetime'] == _ms(_dt(1985, 1, 2)) + 6 * 3600000
    assert first['open'] == 0.1300225
    assert first['high'] == 0.1300225
    assert first['low'] == 0.12444215
    assert first['close'] == 0.12444215
    assert first['volume'] == 175302400


def test_day_default_no_dates(live_client):
    '''With no dates the helper normalizes start to 1971 and end to
    ~now, so a bare call returns the same full history: the first
    candle is the 1985-01-02 session, identical to an explicit
    1971 start.'''
    resp = live_client.get_price_history_every_day('AAPL')

    assert resp.status_code == 200
    candles = resp.json()['candles']
    assert candles[0]['datetime'] == _ms(_dt(1985, 1, 2)) + 6 * 3600000


def _mlk(year):
    '''Martin Luther King Jr. Day: the third Monday of January, a
    market holiday.'''
    jan15 = datetime.date(year, 1, 15)
    return jan15 + datetime.timedelta(days=(7 - jan15.weekday()) % 7)


def _ud(d):
    '''UTC midnight on the given date.'''
    return _dt(d.year, d.month, d.day)


def _et(d, hh=0, mm=0):
    '''A datetime in US Eastern Standard Time (UTC-5) on the given
    date. A fixed offset is used so these tests are deterministic
    without tzdata; the boundary tests only use January dates,
    which always fall in EST.'''
    return datetime.datetime(
            d.year, d.month, d.day, hh, mm,
            tzinfo=datetime.timezone(datetime.timedelta(hours=-5)))


def _stamp(d):
    '''The millisecond candle stamp for a session date in EST:
    01:00 EST of that day = 06:00 UTC.'''
    return _ms(_ud(d)) + 6 * 3600000


def test_day_window_resolves_to_eastern_calendar_days(live_client):
    '''DOCUMENTING OBSERVED BEHAVIOR, NOT ENDORSING: the API resolves
    the instant-valued startDate/endDate to their US-Eastern
    calendar days and filters candles day-wise. A bound expressed
    in UTC can therefore select a different ET day than its UTC
    date suggests, and any time-of-day within an ET day selects the
    same day.

    Window: the week before the previous year's MLK Day, which is
    always a full trading week, plus the MLK week itself for
    non-trading-day bounds. January is always EST, so candle
    stamps are 06:00Z = 01:00 EST of the session day.'''
    mlk = _mlk(datetime.date.today().year - 1)
    mon = mlk - datetime.timedelta(days=7)
    tue, fri, sat = (mon + datetime.timedelta(days=d)
                     for d in (1, 4, 5))
    sun = mon - datetime.timedelta(days=1)

    # every_day now accepts only calendar dates, so the instant-level
    # boundary probes go through get_price_history with the same wire
    # params the helper sends.
    def candles_between(start, end):
        resp = live_client.get_price_history(
                'AAPL',
                period_type=_PH.PeriodType.YEAR,
                period=_PH.Period.TWENTY_YEARS,
                frequency_type=_PH.FrequencyType.DAILY,
                frequency=_PH.Frequency.DAILY,
                start_datetime=start, end_datetime=end)
        assert resp.status_code == 200
        return [c['datetime'] for c in resp.json()['candles']]

    # A start of midnight UTC Tuesday is 19:00 EST *Monday*, so the
    # window opens on Monday's candle even though its UTC date is
    # Tuesday.
    stamps = candles_between(_ud(tue), _ud(sat))
    assert stamps[0] == _stamp(mon)

    # The same clock time on Tuesday in ET (00:00 EST = 05:00Z)
    # resolves to ET-day Tuesday instead.
    stamps = candles_between(_et(tue), _ud(sat))
    assert stamps[0] == _stamp(tue)

    # Sub-day precision is a no-op: a start *after* the candle's own
    # 01:00-EST stamp but on the same ET day still includes it.
    stamps = candles_between(_et(mon, 1, 30), _ud(sat))
    assert stamps[0] == _stamp(mon)

    # The end bound discriminates day-vs-instant filtering: an end
    # at 00:30 EST Tuesday precedes Tuesday's candle stamp yet the
    # candle is still included because the day itself is in range.
    stamps = candles_between(_ud(sun), _et(tue, 0, 30))
    assert stamps[-1] == _stamp(tue)

    # An end one ET-day boundary earlier drops that candle.
    stamps = candles_between(_ud(sun), _et(mon, 23, 59))
    assert stamps[-1] == _stamp(mon)

    # A bound on a non-trading day resolves to its ET day like any
    # other: start on MLK Monday opens on Tuesday's candle, and an
    # end on that Monday sees no candle at all.
    stamps = candles_between(_et(mlk), _ud(mlk + datetime.timedelta(days=5)))
    assert stamps[0] == _stamp(mlk + datetime.timedelta(days=1))

    stamps = candles_between(_ud(mlk), _et(mlk))
    assert stamps == []


################################################################################
# every_week

def test_week_deterministic_week(live_client):
    '''A fixed historical window returns deterministic weekly data:
    AAPL's Jan 13-17 2025 trading week collapses into exactly one
    candle stamped at the Monday 06:00-UTC session open. Asserts the
    count, the timestamp, and the candle's exact OHLCV — which is a
    correct aggregation of that week's five daily candles (Monday's
    open, Friday's close, the week's extremes, summed volume).'''
    resp = live_client.get_price_history_every_week(
            'AAPL', start_date=datetime.date(2025, 1, 13),
            end_date=datetime.date(2025, 1, 18))

    assert resp.status_code == 200
    data = resp.json()
    assert data['empty'] is False
    candles = data['candles']
    assert len(candles) == 1

    candle = candles[0]
    assert candle['datetime'] == _ms(_dt(2025, 1, 13)) + 6 * 3600000
    assert candle['open'] == 233.53
    assert candle['high'] == 238.96
    assert candle['low'] == 228.03
    assert candle['close'] == 229.98
    assert candle['volume'] == 269145341


def test_week_gap_structure(live_client):
    '''Weekly candles are stamped at the Monday session open, seven
    days apart, subject to the same midnight-US-Eastern DST shift as
    daily candles: the week containing spring-forward is 167h apart,
    the one containing fall-back is 169h, and ordinary weeks are
    168h. Requests Jan-Nov 2026 and asserts the exact millisecond
    gap for each named Monday pair.'''
    resp = live_client.get_price_history_every_week(
            'AAPL', start_date=datetime.date(2026, 1, 1),
            end_date=datetime.date(2026, 11, 15))

    assert resp.status_code == 200
    candles = resp.json()['candles']
    by_date = {
            datetime.datetime.fromtimestamp(
                    c['datetime'] / 1000, datetime.timezone.utc).date():
            c['datetime'] for c in candles}

    def gap(d1, d2):
        return by_date[d2] - by_date[d1]

    HOUR = 3600000
    assert gap(datetime.date(2026, 1, 5),    # ordinary week: 168h
               datetime.date(2026, 1, 12)) == 168 * HOUR
    assert gap(datetime.date(2026, 3, 2),    # spring-forward week
               datetime.date(2026, 3, 9)) == 167 * HOUR
    assert gap(datetime.date(2026, 10, 26),  # fall-back week
               datetime.date(2026, 11, 2)) == 169 * HOUR


def test_week_full_history(live_client):
    '''Weekly data has no candle-count cap either: requesting from
    1971 returns all of AAPL's history, whose first weekly bucket is
    stamped 1984-12-31 (the Monday of the week containing
    1985-01-02). Asserts that bucket's exact timestamp and
    split-adjusted OHLCV.'''
    resp = live_client.get_price_history_every_week(
            'AAPL', start_date=datetime.date(1971, 1, 1))

    assert resp.status_code == 200
    candles = resp.json()['candles']
    first = candles[0]
    assert first['datetime'] == _ms(_dt(1984, 12, 31)) + 6 * 3600000
    assert first['open'] == 0.1300225
    assert first['high'] == 0.1300225
    assert first['low'] == 0.12444215
    assert first['close'] == 0.126674275
    assert first['volume'] == 479180800


def test_week_default_no_dates(live_client):
    '''With no dates the helper normalizes start to 1971 and end to
    ~now, so a bare call returns the same full weekly history: the
    first candle is the 1984-12-31 bucket, identical to an explicit
    1971 start.'''
    resp = live_client.get_price_history_every_week('AAPL')

    assert resp.status_code == 200
    candles = resp.json()['candles']
    assert candles[0]['datetime'] == _ms(_dt(1984, 12, 31)) + 6 * 3600000


def test_week_window_resolves_to_eastern_calendar_days(live_client):
    '''DOCUMENTING OBSERVED BEHAVIOR, NOT ENDORSING: weekly windows
    resolve bounds to US-Eastern calendar days as daily ones do,
    but the two bounds key on different days of the candle's week:
    the start bound compares against the candle's *stamped* Monday
    while the end bound must reach the week's first *trading* day.
    On holiday-shortened weeks those differ.

    Window: the week before the previous year's MLK Day, the
    holiday-shortened MLK week (stamped Monday, first trading day
    Tuesday), and the following full week.'''
    mlk = _mlk(datetime.date.today().year - 1)
    pmon, nmon = (mlk + datetime.timedelta(days=d) for d in (-7, 7))

    # every_week now accepts only calendar dates, so the instant-level
    # boundary probes go through get_price_history with the same wire
    # params the helper sends.
    def candles_between(start, end):
        resp = live_client.get_price_history(
                'AAPL',
                period_type=_PH.PeriodType.YEAR,
                period=_PH.Period.TWENTY_YEARS,
                frequency_type=_PH.FrequencyType.WEEKLY,
                frequency=_PH.Frequency.WEEKLY,
                start_datetime=start, end_datetime=end)
        assert resp.status_code == 200
        return [c['datetime'] for c in resp.json()['candles']]

    # A Tuesday-midnight-UTC start is 19:00 EST Monday: the Monday-
    # stamped weekly candle is still selected. The end resolves to
    # the holiday Monday, which does not reach the MLK week's first
    # trading day and so excludes it.
    stamps = candles_between(
            _ud(pmon + datetime.timedelta(days=1)),
            _ud(mlk + datetime.timedelta(days=1)))
    assert stamps == [_stamp(pmon)]

    # A start on the holiday Monday itself also selects the week:
    # the start bound keys on the stamp day, not a trading day.
    stamps = candles_between(_et(mlk), _ud(mlk + datetime.timedelta(days=5)))
    assert stamps == [_stamp(mlk)]

    # But a start on Tuesday — the week's first trading day —
    # misses it entirely, because the stamp day precedes the bound.
    stamps = candles_between(
            _et(mlk + datetime.timedelta(days=1)),
            _ud(nmon + datetime.timedelta(days=1)))
    assert stamps == [_stamp(nmon)]

    # The end bound is stricter: an end resolving to the holiday
    # Monday does NOT include the week — it must reach the first
    # trading day (Tuesday).
    stamps = candles_between(_ud(pmon), _et(mlk, 19))
    assert stamps == [_stamp(pmon)]

    stamps = candles_between(_ud(pmon), _et(mlk + datetime.timedelta(days=1), 19))
    assert stamps == [_stamp(pmon), _stamp(mlk)]
