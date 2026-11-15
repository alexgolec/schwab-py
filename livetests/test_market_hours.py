import datetime

import pytest

import schwab


_Market = schwab.client.Client.MarketHours.Market


def _hours(live_client, markets, date=None):
    kwargs = {} if date is None else {'date': date}
    resp = live_client.get_market_hours(markets, **kwargs)
    assert resp.status_code == 200
    return resp.json()


def _today():
    return datetime.date.today()


def test_market_hours_all_markets(live_client):
    '''Requesting all five markets returns a top-level key per
    market, each containing product-keyed entries whose
    marketType is the uppercase of the requested market and whose
    isOpen flag is a boolean.'''
    data = _hours(live_client, list(_Market))
    for market in _Market:
        assert market.value in data
        products = data[market.value]
        assert len(products) > 0
        for entry in products.values():
            datetime.date.fromisoformat(entry['date'])
            assert entry['marketType'] == market.value.upper()
            assert isinstance(entry['product'], str)
            assert entry['product'] != ''
            assert isinstance(entry['isOpen'], bool)


def test_market_hours_single_vs_multi(live_client):
    '''The markets param scopes the response: a single market yields
    exactly its own top-level key; two markets yield exactly two.'''
    assert set(_hours(live_client, [_Market.FOREX])) == {'forex'}
    assert set(_hours(live_client,
                      [_Market.EQUITY, _Market.FOREX])) == {
            'equity', 'forex'}


def test_market_hours_equity_product_key(live_client):
    '''Equity's nested product key is data-dependent: a closed entry
    is keyed 'equity' with minimal fields, while a scheduled
    session entry is keyed 'EQ' with product 'EQ' and productName
    'equity'. Enshrines the asymmetry so callers take the nested
    dict's first value rather than assuming a fixed key.'''
    closed = _hours(live_client, [_Market.EQUITY])['equity']
    assert 'equity' in closed
    assert closed['equity']['product'] == 'equity'

    today = _today()
    for offset in range(1, 8):
        entry = _hours(live_client, [_Market.EQUITY],
                       date=today + datetime.timedelta(
                               days=offset))['equity']
        if 'EQ' in entry:
            assert entry['EQ']['product'] == 'EQ'
            assert entry['EQ']['productName'] == 'equity'
            return
    pytest.fail('no EQ-keyed equity entry found in the next 7 days')


def test_market_hours_weekend_dates_closed(live_client):
    '''Equity has no session on a Saturday regardless of holidays:
    the next Saturday within the accepted date window reports
    isOpen false.'''
    today = _today()
    saturday = today + datetime.timedelta(
            days=(5 - today.weekday()) % 7)
    products = _hours(live_client, [_Market.EQUITY],
                      date=saturday)['equity']
    entry = next(iter(products.values()))
    assert entry['isOpen'] is False
    assert 'sessionHours' not in entry


def test_market_hours_equity_session_hours(live_client):
    '''On a scheduled session day the equity entry carries
    sessionHours with pre/regular/post segments, each a list of
    ISO-offset start/end pairs, chained end-to-start, with the
    regular session running 09:30-16:00 Eastern (6.5 hours).
    Scans forward up to 7 days for an open day — every such
    window contains one — rather than assuming tomorrow opens.'''
    entry = None
    today = _today()
    for offset in range(1, 8):
        products = _hours(live_client, [_Market.EQUITY],
                          date=today + datetime.timedelta(
                                  days=offset))['equity']
        candidate = next(iter(products.values()))
        if candidate['isOpen']:
            entry = candidate
            break
    assert entry is not None, \
            'no open equity session found in the next 7 days'

    sessions = entry['sessionHours']
    for name in ('preMarket', 'regularMarket', 'postMarket'):
        assert name in sessions
        assert len(sessions[name]) > 0

    def parse(iso):
        return datetime.datetime.fromisoformat(iso)

    for name in ('preMarket', 'regularMarket', 'postMarket'):
        for span in sessions[name]:
            assert parse(span['start']) < parse(span['end'])

    # Segments chain contiguously
    assert parse(sessions['preMarket'][0]['end']) == \
            parse(sessions['regularMarket'][0]['start'])
    assert parse(sessions['regularMarket'][-1]['end']) == \
            parse(sessions['postMarket'][0]['start'])

    # Regular session is 09:30-16:00
    reg_start = parse(sessions['regularMarket'][0]['start'])
    reg_end = parse(sessions['regularMarket'][-1]['end'])
    assert (reg_start.hour, reg_start.minute) == (9, 30)
    assert (reg_end.hour, reg_end.minute) == (16, 0)


def test_market_hours_date_bounds(live_client):
    '''The accepted date window is [today-7d, today+1y], narrower
    than the docstring's "one year from today" implies: both ends
    fail with structured 400s whose source.parameter is 'date'.'''
    for delta, detail_fragment in [
            (-8, 'past'), (400, '1 year')]:
        resp = live_client.get_market_hours(
                [_Market.EQUITY],
                date=_today() + datetime.timedelta(days=delta))
        assert resp.status_code == 400
        error = resp.json()['errors'][0]
        assert error['source']['parameter'] == 'date'
        assert detail_fragment in error['detail'].lower()

    # The near bound itself is accepted
    assert live_client.get_market_hours(
            [_Market.EQUITY],
            date=_today() - datetime.timedelta(days=7)
            ).status_code == 200


def test_market_hours_invalid_market(live_client):
    '''A non-enum market is rejected client-side with ValueError by
    enforce_enums; the request never reaches the API.'''
    with pytest.raises(ValueError):
        live_client.get_market_hours(['NOT_A_MARKET'])
