import datetime

import pytest

import schwab


_EPOCH_2020_MS = int(datetime.datetime(
    2020, 1, 1, tzinfo=datetime.timezone.utc).timestamp() * 1000)


def _now_ms():
    return int(datetime.datetime.now(
        datetime.timezone.utc).timestamp() * 1000)


def _check_time(ts):
    assert isinstance(ts, int)
    assert ts == 0 or _EPOCH_2020_MS <= ts <= _now_ms()


def _check_price(price, positive=False):
    assert isinstance(price, (int, float))
    if positive:
        assert price > 0
    else:
        assert price >= 0


def _check_size(size):
    assert isinstance(size, int)
    assert size >= 0


################################################################################
# Shared protocol contract

def test_batch_partial_success(live_client):
    resp = live_client.get_quotes(['AAPL', 'NOT_A_SYMBOL'])

    assert resp.status_code == 200
    quotes = resp.json()
    assert 'AAPL' in quotes
    assert 'NOT_A_SYMBOL' in quotes['errors']['invalidSymbols']


def test_unsupported_symbol_types(live_client):
    # Bond CUSIP, preferred stock, crypto: rejected per-symbol
    symbols = ['912810TM6', 'BAC.PR.B', 'BTC/USD']
    resp = live_client.get_quotes(symbols)

    assert resp.status_code == 200
    quotes = resp.json()
    for symbol in symbols:
        assert symbol not in quotes or quotes[symbol] is None
        assert symbol in quotes['errors']['invalidSymbols']


def test_get_quote_slash_symbol_wrong_instrument(live_client):
    # The symbol is embedded in the URL path, so '/ES' loses its
    # leading slash and resolves to ticker 'ES' — Eversource Energy,
    # an unrelated EQUITY. Enshrines the docstring warning: use
    # get_quotes for any symbol containing '/'.
    resp = live_client.get_quote('/ES')

    assert resp.status_code == 200
    entry = resp.json()['ES']
    assert entry['assetMainType'] == 'EQUITY'


################################################################################
# Equity


def _check_equity_quote_entry(symbol, entry):
    assert entry['symbol'] == symbol
    assert entry['assetMainType'] == 'EQUITY'

    quote = entry['quote']

    for price_key in ('bidPrice', 'askPrice', 'mark',
                      'highPrice', 'lowPrice'):
        _check_price(quote[price_key])

    for price_key in ('lastPrice', 'closePrice'):
        _check_price(quote[price_key], positive=True)

    for time_key in ('bidTime', 'askTime', 'quoteTime', 'tradeTime'):
        _check_time(quote[time_key])

    for size_key in ('bidSize', 'askSize', 'lastSize', 'totalVolume'):
        _check_size(quote[size_key])

    assert quote['lowPrice'] <= quote['highPrice']
    assert quote['52WeekLow'] <= quote['52WeekHigh']


def _check_equity_reference(entry):
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
    _check_equity_quote_entry('AAPL', quotes['AAPL'])
    _check_equity_reference(quotes['AAPL'])


def test_get_equity_quotes_multiple_symbols(live_client):
    resp = live_client.get_quotes(['AAPL', 'MSFT'])

    assert resp.status_code == 200
    quotes = resp.json()
    for symbol in ('AAPL', 'MSFT'):
        assert symbol in quotes
        _check_equity_quote_entry(symbol, quotes[symbol])


def test_get_equity_quotes_string_input(live_client):
    resp = live_client.get_quotes('AAPL')

    assert resp.status_code == 200
    quotes = resp.json()
    assert 'AAPL' in quotes
    _check_equity_quote_entry('AAPL', quotes['AAPL'])


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

    extended = entry['extended']
    for price_key in ('bidPrice', 'askPrice', 'lastPrice', 'mark'):
        _check_price(extended[price_key])
    for time_key in ('quoteTime', 'tradeTime'):
        _check_time(extended[time_key])
    for size_key in ('bidSize', 'askSize', 'lastSize', 'totalVolume'):
        _check_size(extended[size_key])


def test_get_equity_quote_regular_section(live_client):
    resp = live_client.get_quote('AAPL')

    assert resp.status_code == 200
    regular = resp.json()['AAPL']['regular']
    _check_price(regular['regularMarketLastPrice'], positive=True)
    _check_price(regular['regularMarketNetChange'])
    assert isinstance(regular['regularMarketPercentChange'], (int, float))
    _check_size(regular['regularMarketLastSize'])
    _check_time(regular['regularMarketTradeTime'])


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


################################################################################
# Index

def test_index_quote_format(live_client):
    resp = live_client.get_quotes(['$SPX', '$VIX', '$DJI'])

    assert resp.status_code == 200
    quotes = resp.json()
    for symbol in ('$SPX', '$VIX', '$DJI'):
        entry = quotes[symbol]
        assert entry['assetMainType'] == 'INDEX'

        # Indices have no book and no extended/regular sections
        assert 'extended' not in entry
        assert 'regular' not in entry

        quote = entry['quote']
        assert 'bidPrice' not in quote
        assert 'askPrice' not in quote
        _check_price(quote['lastPrice'], positive=True)
        _check_price(quote['closePrice'], positive=True)
        _check_time(quote['tradeTime'])


def test_index_via_get_quote(live_client):
    # '$' survives URL-path encoding, unlike '/'
    resp = live_client.get_quote('$SPX')

    assert resp.status_code == 200
    entry = resp.json()['$SPX']
    assert entry['assetMainType'] == 'INDEX'


################################################################################
# Futures

def test_futures_root_auto_resolution(live_client):
    resp = live_client.get_quotes(['/ES'])

    assert resp.status_code == 200
    quotes = resp.json()
    assert len(quotes) == 1

    # The root resolves to the active contract, e.g. '/ESZ26': month
    # code + two-digit year suffix on the requested root.
    resolved = next(iter(quotes.keys()))
    assert resolved != '/ES'
    assert resolved.startswith('/ES')
    import re
    assert re.fullmatch(r'/ES[A-Z]\d{2}', resolved)
    assert quotes[resolved]['assetMainType'] == 'FUTURE'


def test_futures_quote_format(live_client):
    resp = live_client.get_quotes(['/ES'])

    assert resp.status_code == 200
    entry = next(iter(resp.json().values()))

    # Futures return only quote + reference
    assert 'extended' not in entry
    assert 'fundamental' not in entry
    assert 'regular' not in entry

    quote = entry['quote']
    _check_price(quote['mark'], positive=True)
    _check_price(quote['lastPrice'])
    _check_size(quote['openInterest'])
    assert isinstance(quote['futurePercentChange'], (int, float))
    assert isinstance(quote['quotedInSession'], bool)
    _check_time(quote['quoteTime'])
    _check_time(quote['settleTime'])


################################################################################
# Forex

def test_forex_quote_format(live_client):
    resp = live_client.get_quotes(['EUR/USD'])

    assert resp.status_code == 200
    entry = resp.json()['EUR/USD']
    assert entry['assetMainType'] == 'FOREX'

    assert 'extended' not in entry
    assert 'fundamental' not in entry
    assert 'regular' not in entry

    quote = entry['quote']
    _check_price(quote['bidPrice'], positive=True)
    _check_price(quote['askPrice'], positive=True)
    _check_price(quote['tick'])
    _check_price(quote['tickAmount'])
    _check_time(quote['quoteTime'])


def test_forex_requires_slash_separator(live_client):
    resp = live_client.get_quotes(['EURUSD'])

    assert resp.status_code == 200
    assert 'EURUSD' in resp.json()['errors']['invalidSymbols']


################################################################################
# Option


def _option_symbol(live_client):
    chain = live_client.get_option_chain('AAPL').json()
    exp_map = chain['callExpDateMap']
    first_exp = next(iter(exp_map.values()))
    return next(iter(first_exp.values()))[0]['symbol']


def test_option_quote_format(live_client):
    symbol = _option_symbol(live_client)
    resp = live_client.get_quotes([symbol])

    assert resp.status_code == 200
    entry = resp.json()[symbol]
    assert entry['assetMainType'] == 'OPTION'

    assert 'extended' not in entry
    assert 'fundamental' not in entry
    assert 'regular' in entry

    quote = entry['quote']
    # Option quotes carry greeks
    _check_price(quote['mark'])
    assert isinstance(quote['delta'], (int, float))
    # Deep-ITM deltas can exceed the theoretical [-1, 1] bound
    assert abs(quote['delta']) <= 1.5
    assert isinstance(quote['gamma'], (int, float))
    assert quote['gamma'] >= 0
    assert isinstance(quote['impliedYield'], (int, float))


def test_option_symbol_in_path(live_client):
    # OCC symbols contain spaces; whether they survive the URL path
    # determines if get_quote can quote options at all.
    symbol = _option_symbol(live_client)
    resp = live_client.get_quote(symbol)

    assert resp.status_code == 200
    entry = resp.json()[symbol]
    assert entry['assetMainType'] == 'OPTION'


################################################################################
# Mutual fund

def test_mutual_fund_quote_format(live_client):
    resp = live_client.get_quotes(['SWPPX'])

    assert resp.status_code == 200
    entry = resp.json()['SWPPX']
    assert entry['assetMainType'] == 'MUTUAL_FUND'
    assert entry['assetSubType'] == 'OEF'

    quote = entry['quote']
    # NAV-priced: no intraday book
    assert 'bidPrice' not in quote
    assert 'askPrice' not in quote
    _check_price(quote['nAV'], positive=True)
    _check_price(quote['closePrice'], positive=True)
    _check_time(quote['tradeTime'])
