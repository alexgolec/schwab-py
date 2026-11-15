import datetime

import pytest


def _dt(y, m, d):
    return datetime.datetime(y, m, d, tzinfo=datetime.timezone.utc)


def _ms(dt):
    return int(dt.timestamp() * 1000)


def _now():
    return datetime.datetime.now(datetime.timezone.utc)


def _check_candle(candle):
    for key in ('open', 'high', 'low', 'close'):
        price = candle[key]
        assert isinstance(price, (int, float))
        assert price > 0
    assert candle['low'] <= candle['high']
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


def test_minute_candle_cap(live_client):
    '''Minute responses are hard-capped at 40,000 candles: a window
    wider than what 40,000 minutes of trading fills returns exactly
    40,000 candles ending at the present, i.e. the most recent data,
    not the start of the requested window. Requests a year of data
    and asserts the exact count plus a recent final candle.'''
    resp = live_client.get_price_history_every_minute(
            'AAPL', start_datetime=_days_ago(365), end_datetime=_now())
    candles = _check_minute_response(resp, 60000)
    assert len(candles) == 40000
    assert candles[-1]['datetime'] > _ms(_days_ago(7))


def test_minute_default_no_dates(live_client):
    '''With no dates the helper normalizes start to 1971 and end to
    ~now, which produces the same cap-bound response as an explicit
    very wide window. Calls with no arguments and asserts the exact
    40,000-candle result.'''
    resp = live_client.get_price_history_every_minute('AAPL')
    candles = _check_minute_response(resp, 60000)
    assert len(candles) == 40000


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


def test_five_minute_candle_cap(live_client):
    '''The 40,000-candle cap applies to five-minute data as well:
    a year-long window returns exactly 40,000 of the most recent
    candles, not the requested window's oldest.'''
    resp = live_client.get_price_history_every_five_minutes(
            'AAPL', start_datetime=_days_ago(365), end_datetime=_now())
    candles = _check_minute_response(resp, 300000)
    assert len(candles) == 40000


def test_five_minute_default_no_dates(live_client):
    '''Default date normalization (1971 to ~now) produces the same
    cap-bound response as an explicit wide window. Calls with no
    arguments and asserts exactly 40,000 candles.'''
    resp = live_client.get_price_history_every_five_minutes('AAPL')
    candles = _check_minute_response(resp, 300000)
    assert len(candles) == 40000


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
            'AAPL', start_datetime=_dt(2025, 1, 13),
            end_datetime=_dt(2025, 1, 18))

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
            'AAPL', start_datetime=_dt(2025, 1, 6),
            end_datetime=_dt(2026, 11, 15))

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
            'AAPL', start_datetime=_dt(1971, 1, 1), end_datetime=_now())

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
            'AAPL', start_datetime=_dt(2025, 1, 13),
            end_datetime=_dt(2025, 1, 18))

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
            'AAPL', start_datetime=_dt(2026, 1, 1),
            end_datetime=_dt(2026, 11, 15))

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
            'AAPL', start_datetime=_dt(1971, 1, 1), end_datetime=_now())

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
