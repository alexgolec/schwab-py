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


_OLD_WINDOW_START = _dt(2025, 1, 13)
_OLD_WINDOW_END = _dt(2025, 1, 18)


def _old_window_is_empty(fn, live_client):
    resp = fn('AAPL', start_datetime=_OLD_WINDOW_START,
              end_datetime=_OLD_WINDOW_END)
    assert resp.status_code == 200
    data = resp.json()
    assert data['empty'] is True
    assert data['candles'] == []


################################################################################
# every_minute

def test_minute_old_window_empty(live_client):
    _old_window_is_empty(live_client.get_price_history_every_minute,
                         live_client)


def test_minute_recent_window_structure(live_client):
    resp = live_client.get_price_history_every_minute(
            'AAPL', start_datetime=_days_ago(10),
            end_datetime=_days_ago(5))
    candles = _check_minute_response(resp, 60000)
    assert candles[0]['datetime'] <= _ms(_days_ago(5))


def test_minute_candle_cap(live_client):
    # Requests wider than retention return the most recent 40,000
    resp = live_client.get_price_history_every_minute(
            'AAPL', start_datetime=_days_ago(365), end_datetime=_now())
    candles = _check_minute_response(resp, 60000)
    assert len(candles) == 40000
    assert candles[-1]['datetime'] > _ms(_days_ago(7))


def test_minute_default_no_dates(live_client):
    resp = live_client.get_price_history_every_minute('AAPL')
    candles = _check_minute_response(resp, 60000)
    assert len(candles) == 40000


################################################################################
# every_five_minutes

def test_five_minute_old_window_empty(live_client):
    _old_window_is_empty(
            live_client.get_price_history_every_five_minutes, live_client)


def test_five_minute_recent_window_structure(live_client):
    resp = live_client.get_price_history_every_five_minutes(
            'AAPL', start_datetime=_days_ago(10),
            end_datetime=_days_ago(5))
    _check_minute_response(resp, 300000)


def test_five_minute_candle_cap(live_client):
    resp = live_client.get_price_history_every_five_minutes(
            'AAPL', start_datetime=_days_ago(365), end_datetime=_now())
    candles = _check_minute_response(resp, 300000)
    assert len(candles) == 40000


def test_five_minute_default_no_dates(live_client):
    resp = live_client.get_price_history_every_five_minutes('AAPL')
    candles = _check_minute_response(resp, 300000)
    assert len(candles) == 40000


################################################################################
# every_ten_minutes

def test_ten_minute_old_window_empty(live_client):
    _old_window_is_empty(
            live_client.get_price_history_every_ten_minutes, live_client)


def test_ten_minute_recent_window_structure(live_client):
    resp = live_client.get_price_history_every_ten_minutes(
            'AAPL', start_datetime=_days_ago(10),
            end_datetime=_days_ago(5))
    _check_minute_response(resp, 600000)


def test_ten_minute_year_window_coverage(live_client):
    # A 1y window fits under the cap: full coverage, not truncated
    resp = live_client.get_price_history_every_ten_minutes(
            'AAPL', start_datetime=_days_ago(365), end_datetime=_now())
    candles = _check_minute_response(resp, 600000)
    assert len(candles) < 40000


def test_ten_minute_default_no_dates(live_client):
    # Retention-bound rather than cap-bound: everything Schwab
    # has (~9 months back), which is under 40,000 candles
    resp = live_client.get_price_history_every_ten_minutes('AAPL')
    candles = _check_minute_response(resp, 600000)
    assert len(candles) < 40000


################################################################################
# every_fifteen_minutes

def test_fifteen_minute_old_window_empty(live_client):
    _old_window_is_empty(
            live_client.get_price_history_every_fifteen_minutes,
            live_client)


def test_fifteen_minute_recent_window_structure(live_client):
    resp = live_client.get_price_history_every_fifteen_minutes(
            'AAPL', start_datetime=_days_ago(10),
            end_datetime=_days_ago(5))
    _check_minute_response(resp, 900000)


def test_fifteen_minute_year_window_coverage(live_client):
    resp = live_client.get_price_history_every_fifteen_minutes(
            'AAPL', start_datetime=_days_ago(365), end_datetime=_now())
    candles = _check_minute_response(resp, 900000)
    assert len(candles) < 40000


def test_fifteen_minute_default_no_dates(live_client):
    resp = live_client.get_price_history_every_fifteen_minutes('AAPL')
    candles = _check_minute_response(resp, 900000)
    assert len(candles) < 40000


################################################################################
# every_thirty_minutes

def test_thirty_minute_old_window_empty(live_client):
    _old_window_is_empty(
            live_client.get_price_history_every_thirty_minutes,
            live_client)


def test_thirty_minute_recent_window_structure(live_client):
    resp = live_client.get_price_history_every_thirty_minutes(
            'AAPL', start_datetime=_days_ago(10),
            end_datetime=_days_ago(5))
    _check_minute_response(resp, 1800000)


def test_thirty_minute_year_window_coverage(live_client):
    resp = live_client.get_price_history_every_thirty_minutes(
            'AAPL', start_datetime=_days_ago(365), end_datetime=_now())
    candles = _check_minute_response(resp, 1800000)
    assert len(candles) < 40000


def test_thirty_minute_default_no_dates(live_client):
    resp = live_client.get_price_history_every_thirty_minutes('AAPL')
    candles = _check_minute_response(resp, 1800000)
    assert len(candles) < 40000


################################################################################
# every_day

def test_day_deterministic_week(live_client):
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

    for candle in candles:
        _check_candle(candle)


def test_day_gap_structure(live_client):
    resp = live_client.get_price_history_every_day(
            'AAPL', start_datetime=_days_ago(90), end_datetime=_now())
    candles = resp.json()['candles']
    day_ms = 86400000
    for gap in _gaps(candles):
        # Gaps are N trading-session days apart, N in {1,3,4}
        # (weekends, holiday weekends), plus or minus an hour for
        # DST transitions in the candle timestamps themselves
        assert abs(gap % day_ms) <= 3600000 or \
                abs(gap % day_ms - day_ms) <= 3600000
        assert 23 * 3600000 <= gap <= 97 * 3600000


def test_day_full_history(live_client):
    resp = live_client.get_price_history_every_day(
            'AAPL', start_datetime=_dt(1971, 1, 1), end_datetime=_now())

    assert resp.status_code == 200
    candles = resp.json()['candles']
    # Schwab's AAPL daily data begins 1985-01-02
    assert candles[0]['datetime'] == _ms(_dt(1985, 1, 2)) + 6 * 3600000


def test_day_default_no_dates(live_client):
    resp = live_client.get_price_history_every_day('AAPL')

    assert resp.status_code == 200
    candles = resp.json()['candles']
    assert candles[0]['datetime'] == _ms(_dt(1985, 1, 2)) + 6 * 3600000


################################################################################
# every_week

def test_week_deterministic_week(live_client):
    resp = live_client.get_price_history_every_week(
            'AAPL', start_datetime=_dt(2025, 1, 13),
            end_datetime=_dt(2025, 1, 18))

    assert resp.status_code == 200
    data = resp.json()
    assert data['empty'] is False
    candles = data['candles']
    assert len(candles) == 1
    _check_candle(candles[0])
    assert candles[0]['datetime'] == _ms(_dt(2025, 1, 13)) + 6 * 3600000


def test_week_gap_structure(live_client):
    resp = live_client.get_price_history_every_week(
            'AAPL', start_datetime=_days_ago(365), end_datetime=_now())
    candles = resp.json()['candles']
    week_ms = 604800000
    for gap in _gaps(candles):
        # ~7 days; DST transitions shift a few hours either way
        assert abs(gap - week_ms) < 6 * 3600000


def test_week_full_history(live_client):
    resp = live_client.get_price_history_every_week(
            'AAPL', start_datetime=_dt(1971, 1, 1), end_datetime=_now())

    assert resp.status_code == 200
    candles = resp.json()['candles']
    assert candles[0]['datetime'] == _ms(_dt(1984, 12, 31)) + 6 * 3600000


def test_week_default_no_dates(live_client):
    resp = live_client.get_price_history_every_week('AAPL')

    assert resp.status_code == 200
    candles = resp.json()['candles']
    assert candles[0]['datetime'] == _ms(_dt(1984, 12, 31)) + 6 * 3600000
