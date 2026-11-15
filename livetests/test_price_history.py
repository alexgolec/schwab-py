import datetime

import pytest

import schwab


_PH = schwab.client.Client.PriceHistory
_EPOCH_2020_MS = int(datetime.datetime(
    2020, 1, 1, tzinfo=datetime.timezone.utc).timestamp() * 1000)


def _now_ms():
    return int(datetime.datetime.now(
        datetime.timezone.utc).timestamp() * 1000)


def _check_candle(candle):
    for key in ('open', 'high', 'low', 'close'):
        price = candle[key]
        assert isinstance(price, (int, float))
        assert price > 0
    assert candle['low'] <= candle['high']
    assert isinstance(candle['volume'], int)
    assert candle['volume'] >= 0
    assert isinstance(candle['datetime'], int)
    # Multi-year requests legitimately return decades-old candles
    assert 0 < candle['datetime'] <= _now_ms()


def _check_response(resp):
    assert resp.status_code == 200
    data = resp.json()
    assert data['symbol'] == 'AAPL'
    assert data['empty'] is False
    candles = data['candles']
    assert len(candles) > 0
    datetimes = []
    for candle in candles:
        _check_candle(candle)
        datetimes.append(candle['datetime'])
    assert datetimes == sorted(datetimes)
    return candles


def test_get_price_history_default(live_client):
    # Defaults to day/10/minute/1: ten days of one-minute candles.
    # Thin minutes may produce no candle, so gaps are multiples of
    # 60s with 60s the smallest.
    candles = _check_response(live_client.get_price_history('AAPL'))
    gaps = {candles[i]['datetime'] - candles[i - 1]['datetime']
            for i in range(1, len(candles))}
    assert min(gaps) == 60000
    assert all(gap % 60000 == 0 for gap in gaps)


@pytest.mark.parametrize('period_type,period,frequency_type,frequency', [
    (_PH.PeriodType.DAY, _PH.Period.ONE_DAY,
     _PH.FrequencyType.MINUTE, _PH.Frequency.EVERY_MINUTE),
    (_PH.PeriodType.DAY, _PH.Period.FIVE_DAYS,
     _PH.FrequencyType.MINUTE, _PH.Frequency.EVERY_THIRTY_MINUTES),
    (_PH.PeriodType.MONTH, _PH.Period.ONE_MONTH,
     _PH.FrequencyType.DAILY, _PH.Frequency.DAILY),
    (_PH.PeriodType.MONTH, _PH.Period.SIX_MONTHS,
     _PH.FrequencyType.WEEKLY, _PH.Frequency.DAILY),
    (_PH.PeriodType.YEAR, _PH.Period.ONE_YEAR,
     _PH.FrequencyType.DAILY, _PH.Frequency.DAILY),
    (_PH.PeriodType.YEAR, _PH.Period.TWENTY_YEARS,
     _PH.FrequencyType.MONTHLY, _PH.Frequency.DAILY),
    (_PH.PeriodType.YEAR_TO_DATE, _PH.Period.YEAR_TO_DATE,
     _PH.FrequencyType.DAILY, _PH.Frequency.DAILY),
])
def test_valid_period_frequency_combos(
        live_client, period_type, period, frequency_type, frequency):
    resp = live_client.get_price_history(
            'AAPL', period_type=period_type, period=period,
            frequency_type=frequency_type, frequency=frequency)
    _check_response(resp)


@pytest.mark.parametrize('kwargs,detail_fragment', [
    (dict(period_type=_PH.PeriodType.DAY,
          period=_PH.Period.TWENTY_YEARS),
     'valid values for period'),
    (dict(period_type=_PH.PeriodType.MONTH,
          period=_PH.Period.TEN_DAYS),
     'valid values for period'),
    (dict(period_type=_PH.PeriodType.MONTH,
          period=_PH.Period.ONE_MONTH,
          frequency_type=_PH.FrequencyType.DAILY,
          frequency=_PH.Frequency.EVERY_FIVE_MINUTES),
     'valid values for frequency'),
    (dict(period_type=_PH.PeriodType.DAY,
          period=_PH.Period.ONE_DAY,
          frequency_type=_PH.FrequencyType.DAILY,
          frequency=_PH.Frequency.DAILY),
     'valid values'),
    (dict(period_type=_PH.PeriodType.YEAR_TO_DATE,
          period=_PH.Period.FIVE_DAYS),
     'valid values for period'),
])
def test_invalid_combos_rejected(live_client, kwargs, detail_fragment):
    resp = live_client.get_price_history('AAPL', **kwargs)

    assert resp.status_code == 400
    errors = resp.json()['errors']
    assert detail_fragment in errors[0]['detail']


def test_start_end_datetime_window(live_client):
    now = datetime.datetime.now(datetime.timezone.utc)
    start = now - datetime.timedelta(days=30)
    resp = live_client.get_price_history(
            'AAPL', start_datetime=start, end_datetime=now)

    candles = _check_response(resp)
    end_ms = int(now.timestamp() * 1000)
    for candle in candles:
        assert candle['datetime'] <= end_ms

    # The API snaps startDate to the enclosing market session, so the
    # first candle can precede the requested start by hours (observed
    # ~14h when the start falls on a weekend).
    start_ms = int(start.timestamp() * 1000)
    assert candles[0]['datetime'] >= start_ms - 48 * 3600000


def test_period_ignored_when_datetimes_given(live_client):
    # The docstring says period "should not be provided" with dates;
    # the API accepts both and the dates win.
    now = datetime.datetime.now(datetime.timezone.utc)
    start = now - datetime.timedelta(days=30)
    resp = live_client.get_price_history(
            'AAPL', period_type=_PH.PeriodType.DAY,
            period=_PH.Period.FIVE_DAYS,
            start_datetime=start, end_datetime=now)

    candles = _check_response(resp)
    # If period won, the first candle would be ~5 days ago, not ~30.
    start_ms = int(start.timestamp() * 1000)
    assert candles[0]['datetime'] - start_ms < 86400000


def test_extended_hours_flag(live_client):
    kwargs = dict(period_type=_PH.PeriodType.DAY,
                  period=_PH.Period.ONE_DAY,
                  frequency_type=_PH.FrequencyType.MINUTE,
                  frequency=_PH.Frequency.EVERY_MINUTE)
    with_extended = _check_response(live_client.get_price_history(
        'AAPL', need_extended_hours_data=True, **kwargs))
    without = _check_response(live_client.get_price_history(
        'AAPL', need_extended_hours_data=False, **kwargs))

    assert len(with_extended) > len(without)


def test_previous_close_flag(live_client):
    resp = live_client.get_price_history(
            'AAPL', need_previous_close=True)

    assert resp.status_code == 200
    data = resp.json()
    prev_close = data['previousClose']
    assert isinstance(prev_close, (int, float))
    assert prev_close > 0
    # The API serializes this one as a float, unlike candle datetimes
    prev_close_date = data['previousCloseDate']
    assert isinstance(prev_close_date, (int, float))
    assert _EPOCH_2020_MS <= prev_close_date <= _now_ms()

    resp = live_client.get_price_history(
            'AAPL', need_previous_close=False)
    assert 'previousClose' not in resp.json()
    assert 'previousCloseDate' not in resp.json()


def test_empty_for_ancient_window(live_client):
    resp = live_client.get_price_history(
            'AAPL',
            start_datetime=datetime.datetime(
                1970, 1, 4, tzinfo=datetime.timezone.utc),
            end_datetime=datetime.datetime(
                1970, 1, 5, tzinfo=datetime.timezone.utc))

    assert resp.status_code == 200
    data = resp.json()
    assert data['empty'] is True
    assert data['candles'] == []
