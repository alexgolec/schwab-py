import pytest

import schwab


_P = schwab.client.Client.Instrument.Projection


def _instruments(live_client, symbol, projection):
    resp = live_client.get_instruments(symbol, projection)
    assert resp.status_code == 200
    return resp.json()


def _check_instrument(entry):
    '''Core instrument fields present on every result: a non-empty
    symbol and description, a recognized assetType, and an exchange
    string. cusip is present on equities but not universal.'''
    assert isinstance(entry['symbol'], str)
    assert entry['symbol'] != ''
    assert isinstance(entry['description'], str)
    assert isinstance(entry['assetType'], str)
    assert entry['assetType'] != ''
    assert isinstance(entry['exchange'], str)


################################################################################
# SYMBOL_SEARCH

def test_symbol_search_exact_match(live_client):
    '''SYMBOL_SEARCH is exact matching, returning the full public
    record for the symbol. AAPL's record is pinned literally.'''
    data = _instruments(live_client, 'AAPL', _P.SYMBOL_SEARCH)
    instruments = data['instruments']
    assert len(instruments) == 1
    entry = instruments[0]
    assert entry['symbol'] == 'AAPL'
    assert entry['cusip'] == '037833100'
    assert entry['assetType'] == 'EQUITY'
    assert entry['exchange'] == 'NASDAQ'
    assert entry['description'] == 'APPLE INC'


def test_symbol_search_is_not_prefix(live_client):
    '''A partial symbol does not prefix-match: 'AAP' resolves to
    the literal ticker AAP (Advance Auto Parts), not AAPL or a
    list of AAP-prefixed symbols.'''
    instruments = _instruments(
            live_client, 'AAP', _P.SYMBOL_SEARCH)['instruments']
    assert len(instruments) == 1
    assert instruments[0]['symbol'] == 'AAP'


def test_symbol_search_multiple_symbols(live_client):
    '''A list of symbols returns one instrument per symbol.'''
    instruments = _instruments(
            live_client, ['AAPL', 'MSFT'], _P.SYMBOL_SEARCH)[
            'instruments']
    assert {i['symbol'] for i in instruments} == {'AAPL', 'MSFT'}


def test_symbol_search_covers_other_asset_types(live_client):
    '''Lookup is not equity-only: the mutual fund SWPPX resolves
    with assetType MUTUAL_FUND.'''
    instruments = _instruments(
            live_client, 'SWPPX', _P.SYMBOL_SEARCH)['instruments']
    assert len(instruments) == 1
    assert instruments[0]['assetType'] == 'MUTUAL_FUND'


def test_symbol_search_no_match_empty_object(live_client):
    '''No match returns 200 with an empty object — not an error,
    and not even an empty instruments list.'''
    assert _instruments(live_client, 'XYZQW', _P.SYMBOL_SEARCH) == {}


################################################################################
# SYMBOL_REGEX

def test_symbol_regex_matches_universe(live_client):
    '''SYMBOL_REGEX applies the regex to every symbol in the
    instrument universe across asset types: 'AAP.*' returns
    thousands of hits dominated by structured-note funds, all
    whose symbols start with AAP.'''
    instruments = _instruments(
            live_client, 'AAP.*', _P.SYMBOL_REGEX)['instruments']
    assert len(instruments) > 1000
    for entry in instruments:
        assert entry['symbol'].startswith('AAP')
        _check_instrument(entry)


def test_symbol_regex_requires_full_match(live_client):
    '''The pattern must match the entire symbol, not a substring:
    'AAPL' matches only AAPL itself even though symbols like
    '$NY2LAAPL' contain it, while '.*AAPL' matches them all.
    Wildcards are required for partial matching.'''
    instruments = _instruments(
            live_client, 'AAPL', _P.SYMBOL_REGEX)['instruments']
    assert len(instruments) == 1
    assert instruments[0]['symbol'] == 'AAPL'


@pytest.mark.parametrize('pattern', ['L', 'LE', 'AAP'])
def test_symbol_regex_minimum_length(live_client, pattern):
    '''Patterns shorter than four characters are rejected client-
    visible with a 400 whose detail reads "Symbol length should be
    atleast : N" — where N is oddly max(3, len(pattern)+1).'''
    resp = live_client.get_instruments(pattern, _P.SYMBOL_REGEX)
    assert resp.status_code == 400
    error = resp.json()['errors'][0]
    assert error['source']['parameter'] == 'symbol'
    assert 'Symbol length' in error['detail']


def test_symbol_regex_covers_all_asset_types(live_client):
    '''The regex universe is not equity-only: '.*AAPL' returns AAPL
    plus index and futures symbols that merely end in AAPL, e.g.
    '$NY2LAAPL' and '/SAAPLZ26:XCME'.'''
    instruments = _instruments(
            live_client, '.*AAPL', _P.SYMBOL_REGEX)['instruments']
    symbols = {i['symbol'] for i in instruments}
    assert 'AAPL' in symbols
    assert len(symbols) > 1


################################################################################
# SEARCH

def test_search_matches_symbol_or_description(live_client):
    '''SEARCH applies the regex to symbol OR description, broader
    than SYMBOL_REGEX: 'AAP.*' returns the same AAP-prefixed set
    plus instruments like PUSOF whose description ('AAPKI VENTURES
    INC') matches even though the symbol does not.'''
    instruments = _instruments(
            live_client, 'AAP.*', _P.SEARCH)['instruments']
    assert len(instruments) > 1000
    for entry in instruments:
        assert (entry['symbol'].startswith('AAP')
                or 'AAP' in entry['description'].upper())
    # At least one description-only match proves the broader field
    assert any(not i['symbol'].startswith('AAP')
               for i in instruments)


################################################################################
# DESCRIPTION_SEARCH

def test_description_search_substring(live_client):
    '''DESCRIPTION_SEARCH is a substring search over instrument
    descriptions: 'apple' returns several instruments whose
    descriptions all contain APPLE.'''
    instruments = _instruments(
            live_client, 'apple', _P.DESCRIPTION_SEARCH)[
            'instruments']
    assert len(instruments) >= 5
    for entry in instruments:
        assert 'APPLE' in entry['description'].upper()
        _check_instrument(entry)


def test_description_search_multiword(live_client):
    '''Multiword description queries behave differently than single
    words: 'APPLE INC' was observed returning an empty object even
    though 'apple' returns matches including APPLE INC.'''
    assert _instruments(
            live_client, 'APPLE INC', _P.DESCRIPTION_SEARCH) == {}


################################################################################
# DESCRIPTION_REGEX

def test_description_regex_requires_full_match(live_client):
    '''DESCRIPTION_REGEX anchors the pattern to the whole
    description: 'Apple' alone matches nothing (no instrument's
    description is exactly 'Apple'), while '.*Apple.*' matches.'''
    assert _instruments(
            live_client, 'Apple', _P.DESCRIPTION_REGEX) == {}

    instruments = _instruments(
            live_client, '.*Apple.*', _P.DESCRIPTION_REGEX)[
            'instruments']
    assert len(instruments) > 0
    for entry in instruments:
        assert 'Apple' in entry['description']
        _check_instrument(entry)


################################################################################
# FUNDAMENTAL

def test_fundamental_projection(live_client):
    '''FUNDAMENTAL is the only projection that changes entry shape:
    the instrument record gains a fundamental sub-object with 52w
    range, dividend, and valuation fields.'''
    instruments = _instruments(
            live_client, 'AAPL', _P.FUNDAMENTAL)['instruments']
    assert len(instruments) == 1
    entry = instruments[0]
    assert entry['symbol'] == 'AAPL'

    fundamental = entry['fundamental']
    assert fundamental['high52'] > fundamental['low52'] > 0
    assert fundamental['peRatio'] > 0
    assert isinstance(fundamental['dividendAmount'], (int, float))
    assert isinstance(fundamental['dividendYield'], (int, float))


################################################################################
# get_instrument_by_cusip

def test_instrument_by_cusip(live_client):
    '''CUSIP lookup returns the same instruments envelope with the
    matching record: 037833100 resolves to AAPL.'''
    resp = live_client.get_instrument_by_cusip('037833100')
    assert resp.status_code == 200
    instruments = resp.json()['instruments']
    assert len(instruments) == 1
    assert instruments[0]['symbol'] == 'AAPL'
    assert instruments[0]['cusip'] == '037833100'


def test_instrument_by_cusip_not_found(live_client):
    '''An unknown CUSIP fails with HTTP 400 whose embedded error
    status reads '404' — transport status and error title disagree,
    and both are pinned here.'''
    resp = live_client.get_instrument_by_cusip('999999999')
    assert resp.status_code == 400
    assert resp.json()['errors'][0]['status'] == '404'
