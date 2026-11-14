import datetime

import schwab


_EPOCH_2020_MS = int(datetime.datetime(
    2020, 1, 1, tzinfo=datetime.timezone.utc).timestamp() * 1000)


def _check_quote_entry(symbol, entry):
    assert entry['symbol'] == symbol
    assert entry['assetMainType'] == 'EQUITY'

    quote = entry['quote']
    now_ms = int(datetime.datetime.now(
        datetime.timezone.utc).timestamp() * 1000)

    for price_key in ('bidPrice', 'askPrice', 'mark',
                      'highPrice', 'lowPrice'):
        price = quote[price_key]
        assert isinstance(price, (int, float))
        assert price >= 0

    for price_key in ('lastPrice', 'closePrice'):
        price = quote[price_key]
        assert isinstance(price, (int, float))
        assert price > 0

    for time_key in ('bidTime', 'askTime', 'quoteTime', 'tradeTime'):
        ts = quote[time_key]
        assert isinstance(ts, int)
        assert _EPOCH_2020_MS <= ts <= now_ms

    for size_key in ('bidSize', 'askSize', 'lastSize', 'totalVolume'):
        size = quote[size_key]
        assert isinstance(size, int)
        assert size >= 0

    assert quote['lowPrice'] <= quote['highPrice']
    assert quote['52WeekLow'] <= quote['52WeekHigh']


def _check_reference(entry):
    reference = entry['reference']
    cusip = reference['cusip']
    assert isinstance(cusip, str)
    assert len(cusip) == 9
    assert cusip.isalnum()
    assert reference['exchange']
    assert reference['exchangeName']


def test_get_equity_quote(live_client):
    resp = live_client.get_quote('AAPL')

    assert resp.status_code == 200
    quotes = resp.json()
    assert 'AAPL' in quotes
    _check_quote_entry('AAPL', quotes['AAPL'])
    _check_reference(quotes['AAPL'])


def test_get_equity_quotes_multiple_symbols(live_client):
    resp = live_client.get_quotes(['AAPL', 'MSFT'])

    assert resp.status_code == 200
    quotes = resp.json()
    for symbol in ('AAPL', 'MSFT'):
        assert symbol in quotes
        _check_quote_entry(symbol, quotes[symbol])


def test_get_equity_quotes_string_input(live_client):
    resp = live_client.get_quotes('AAPL')

    assert resp.status_code == 200
    quotes = resp.json()
    assert 'AAPL' in quotes
    _check_quote_entry('AAPL', quotes['AAPL'])


def test_get_equity_quote_fields_filter(live_client):
    resp = live_client.get_quote(
            'AAPL', fields=[schwab.client.Client.Quote.Fields.QUOTE])

    assert resp.status_code == 200
    entry = resp.json()['AAPL']
    assert 'quote' in entry
    assert 'fundamental' not in entry
    assert 'extended' not in entry


def test_get_equity_quotes_fields_fundamental(live_client):
    resp = live_client.get_quotes(
            ['AAPL'],
            fields=[schwab.client.Client.Quote.Fields.FUNDAMENTAL])

    assert resp.status_code == 200
    entry = resp.json()['AAPL']
    assert 'fundamental' in entry
    assert 'quote' not in entry
    assert 'reference' not in entry

    fundamental = entry['fundamental']
    assert isinstance(fundamental['peRatio'], (int, float))
    assert isinstance(fundamental['divYield'], (int, float))


def test_get_equity_quotes_fields_extended(live_client):
    resp = live_client.get_quotes(
            ['AAPL'],
            fields=[schwab.client.Client.Quote.Fields.EXTENDED])

    assert resp.status_code == 200
    entry = resp.json()['AAPL']
    assert 'extended' in entry
    assert 'quote' not in entry
    assert 'reference' not in entry

    now_ms = int(datetime.datetime.now(
        datetime.timezone.utc).timestamp() * 1000)
    extended = entry['extended']
    for price_key in ('bidPrice', 'askPrice', 'lastPrice', 'mark'):
        price = extended[price_key]
        assert isinstance(price, (int, float))
        assert price >= 0
    for time_key in ('quoteTime', 'tradeTime'):
        ts = extended[time_key]
        assert isinstance(ts, int)
        # The API uses 0 as a sentinel for missing extended-session data
        assert ts == 0 or _EPOCH_2020_MS <= ts <= now_ms
    for size_key in ('bidSize', 'askSize', 'lastSize', 'totalVolume'):
        size = extended[size_key]
        assert isinstance(size, int)
        assert size >= 0


def test_get_equity_quotes_fields_and_indicative(live_client):
    resp = live_client.get_quotes(
            ['AAPL'],
            fields=[schwab.client.Client.Quote.Fields.QUOTE],
            indicative=True)

    assert resp.status_code == 200
    entry = resp.json()['AAPL']
    assert 'quote' in entry


def test_get_equity_quote_invalid_symbol(live_client):
    resp = live_client.get_quote('NOT_A_SYMBOL')

    assert resp.status_code == 404
