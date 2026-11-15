import datetime
import re

import conftest
import pytest

import schwab


_O = schwab.client.Client.Options


def _chain(live_client, symbol='AAPL', **kwargs):
    resp = live_client.get_option_chain(symbol, **kwargs)
    assert resp.status_code == 200, resp.text[:200]
    return resp.json()


def _all_contracts(data):
    '''Flattens both expiration maps into (side, contract) pairs.'''
    for side, key in (('CALL', 'callExpDateMap'),
                      ('PUT', 'putExpDateMap')):
        for strikes in data[key].values():
            for contracts in strikes.values():
                for contract in contracts:
                    yield side, contract


def _live_strike(live_client):
    '''A strike AAPL actually lists right now, pulled from the
    chain itself so the exact-strike filter has a guaranteed
    target.'''
    data = _chain(live_client, strike_count=1)
    strikes = next(iter(data['callExpDateMap'].values()))
    return float(next(iter(strikes)))


_EXP_KEY = re.compile(r'(\d{4}-\d{2}-\d{2}):(\d+)')


def _exp_key_date(key):
    return _EXP_KEY.match(key).group(1)


################################################################################
# Grid shape

def test_option_chain_default_format(live_client):
    '''AAPL's default chain is the full grid: status SUCCESS, both
    expiration maps populated, expiry keys in 'YYYY-MM-DD:DTE'
    form, decimal strike keys, boolean truncation/delay flags, and
    a null underlying quote unless requested.'''
    data = _chain(live_client)
    assert data['symbol'] == 'AAPL'
    assert data['status'] == 'SUCCESS'
    assert data['strategy'] == 'SINGLE'
    assert isinstance(data['isDelayed'], bool)
    assert isinstance(data['isChainTruncated'], bool)
    assert data['underlying'] is None
    assert data['numberOfContracts'] > 0

    for key in ('callExpDateMap', 'putExpDateMap'):
        assert len(data[key]) > 0
        for exp_key, strikes in data[key].items():
            assert _EXP_KEY.match(exp_key)
            for strike_key, contracts in strikes.items():
                float(strike_key)
                assert len(contracts) > 0


def test_expiration_key_matches_dte(live_client):
    '''The ':N' suffix of each expiration-map key is the contracts'
    own daysToExpiration — the two indexing layers never disagree.'''
    data = _chain(live_client, strike_count=1)
    for key in ('callExpDateMap', 'putExpDateMap'):
        for exp_key, strikes in data[key].items():
            dte = int(_EXP_KEY.match(exp_key).group(2))
            for contracts in strikes.values():
                for contract in contracts:
                    assert contract['daysToExpiration'] == dte


def test_strike_key_matches_contract_strike(live_client):
    '''Each strike-map key equals the strikePrice of every contract
    filed under it.'''
    data = _chain(live_client, strike_count=1)
    for key in ('callExpDateMap', 'putExpDateMap'):
        for strikes in data[key].values():
            for strike_key, contracts in strikes.items():
                for contract in contracts:
                    assert contract['strikePrice'] == float(strike_key)


def test_contract_field_format(live_client):
    '''Contract records carry the standard option fields: putCall
    matching their map side, greeks within delta's [-1,1] domain,
    non-negative prices, integer open interest, and an inTheMoney
    flag consistent with the strike versus the underlying price.'''
    data = _chain(live_client, strike_count=2)
    underlying = data['underlyingPrice']
    assert underlying > 0
    count = 0
    for side, contract in _all_contracts(data):
        assert contract['putCall'] == side
        assert contract['symbol'].startswith('AAPL')
        assert isinstance(contract['optionRoot'], str)
        assert -1.0 <= contract['delta'] <= 1.0
        for field in ('bid', 'ask', 'mark', 'last', 'openInterest'):
            assert contract[field] >= 0
        assert isinstance(contract['openInterest'], int)
        # volatility carries a -999.0 missing-data sentinel on
        # contracts without a usable market, alongside real
        # non-negative values
        assert contract['volatility'] == -999.0 \
                or contract['volatility'] >= 0
        assert isinstance(contract['inTheMoney'], bool)
        strike = contract['strikePrice']
        expected_itm = (strike < underlying) if side == 'CALL' \
                else (strike > underlying)
        assert contract['inTheMoney'] == expected_itm
        count += 1
    assert count > 0


################################################################################
# contract_type

@pytest.mark.parametrize('contract_type', list(_O.ContractType))
def test_contract_type(live_client, contract_type):
    '''contractType zeroes the opposite map: CALL yields only call
    contracts under a populated callExpDateMap and an empty
    putExpDateMap, PUT mirrors, ALL fills both.'''
    data = _chain(live_client, contract_type=contract_type)
    calls = data['callExpDateMap']
    puts = data['putExpDateMap']
    if contract_type is _O.ContractType.CALL:
        assert len(calls) > 0 and len(puts) == 0
    elif contract_type is _O.ContractType.PUT:
        assert len(puts) > 0 and len(calls) == 0
    else:
        assert len(calls) > 0 and len(puts) > 0
    for side, contract in _all_contracts(data):
        assert contract['putCall'] == side


################################################################################
# Strike filters

def test_strike_count(live_client):
    '''strikeCount bounds strikes per expiration, not globally:
    every bucket holds at most N strikes and at least one bucket
    reaches exactly N.'''
    data = _chain(live_client, strike_count=3)
    sizes = [len(strikes)
             for strikes in data['callExpDateMap'].values()]
    assert len(sizes) > 0
    assert all(size <= 3 for size in sizes)
    assert any(size == 3 for size in sizes)


def test_strike_count_bounds(live_client):
    '''strikeCount is silently clamped at both ends: 0 empties the
    chain entirely while 999 returns the full unbounded grid —
    neither is an error.'''
    empty = _chain(live_client, strike_count=0)
    assert len(empty['callExpDateMap']) == 0
    assert len(empty['putExpDateMap']) == 0
    assert empty['numberOfContracts'] == 0

    full = _chain(live_client, strike_count=999)
    default = _chain(live_client)
    assert sum(len(s) for s in full['callExpDateMap'].values()) \
            == sum(len(s) for s in default['callExpDateMap'].values())


def test_strike_exact(live_client):
    '''An exact strike filter returns only that strike, and only
    for expirations that actually list it — a sparse filter over
    the expiration dimension.'''
    strike = _live_strike(live_client)
    data = _chain(live_client, strike=strike)
    for key in ('callExpDateMap', 'putExpDateMap'):
        assert len(data[key]) > 0
        for strikes in data[key].values():
            assert set(strikes) == {str(strike)}


def test_strike_no_match(live_client):
    '''A strike outside the listed range is not an error: 200 with
    both maps empty.'''
    data = _chain(live_client, strike=-50)
    assert len(data['callExpDateMap']) == 0
    assert len(data['putExpDateMap']) == 0


@pytest.mark.parametrize('strike_range', [
        _O.StrikeRange.IN_THE_MONEY, _O.StrikeRange.NEAR_THE_MONEY,
        _O.StrikeRange.OUT_OF_THE_MONEY])
def test_strike_range_moneyness(live_client, strike_range):
    '''Moneyness ranges filter on the inTheMoney flag: ITM returns
    only in-the-money contracts, OTM only out-of-the-money, and
    NTM a non-empty window strictly smaller than the full chain.'''
    data = _chain(live_client, strike_range=strike_range)
    contracts = list(_all_contracts(data))
    assert len(contracts) > 0
    if strike_range is _O.StrikeRange.IN_THE_MONEY:
        assert all(c['inTheMoney'] for _, c in contracts)
    elif strike_range is _O.StrikeRange.OUT_OF_THE_MONEY:
        assert not any(c['inTheMoney'] for _, c in contracts)
    else:
        full = _chain(live_client)
        assert len(contracts) < sum(
                1 for _ in _all_contracts(full))


@pytest.mark.parametrize('strike_range', [
        _O.StrikeRange.STRIKES_ABOVE_MARKET,
        _O.StrikeRange.STRIKES_BELOW_MARKET,
        _O.StrikeRange.STRIKES_NEAR_MARKET,
        _O.StrikeRange.ALL])
def test_strike_range_unfiltered_variants(live_client, strike_range):
    '''The SAK/SBK/SNK/ALL range values return the full chain
    unchanged — observed as no-ops on SINGLE-strategy requests,
    enshrined so a future behavioral change is caught.'''
    data = _chain(live_client, strike_range=strike_range)
    full = _chain(live_client)
    assert sum(len(s) for s in data['callExpDateMap'].values()) \
            == sum(len(s) for s in full['callExpDateMap'].values())


################################################################################
# Date and month filters

def test_date_range(live_client):
    '''fromDate/toDate bound the expiration dimension: every
    returned expiry key falls inside the window, and a degenerate
    window (from == to) yields exactly one expiration.'''
    full = _chain(live_client, strike_count=1)
    exp_dates = sorted(
            datetime.date.fromisoformat(_exp_key_date(k))
            for k in full['callExpDateMap'])
    assert len(exp_dates) >= 2
    first, second = exp_dates[0], exp_dates[1]

    window = _chain(live_client, strike_count=1,
                    from_date=first, to_date=second)
    keys = list(window['callExpDateMap'])
    assert len(keys) == 2
    for key in keys:
        d = datetime.date.fromisoformat(_exp_key_date(key))
        assert first <= d <= second

    single = _chain(live_client, strike_count=1,
                    from_date=first, to_date=first)
    assert list(single['callExpDateMap']) == [f'{first}:1'] \
            or len(single['callExpDateMap']) == 1


def test_exp_month(live_client):
    '''expMonth restricts expirations to a calendar month across
    all years: every expiry key's date has month == 12 for DEC.'''
    data = _chain(live_client, exp_month=_O.ExpirationMonth.DECEMBER)
    assert len(data['callExpDateMap']) > 0
    for key in data['callExpDateMap']:
        assert datetime.date.fromisoformat(
                _exp_key_date(key)).month == 12


################################################################################
# option_type

@pytest.mark.parametrize('option_type', list(_O.Type))
def test_option_type(live_client, option_type):
    '''optionType splits standard from adjusted contracts on the
    contract-level 'nonStandard' flag — orthogonal to
    expirationType, which stays S/M/W under the standard filter.
    S is populated and ALL is a superset of it; NS is well-formed
    but empty today, and any contract it returns must be flagged
    nonStandard.'''
    data = _chain(live_client, option_type=option_type,
                  strike_count=1)
    contracts = list(_all_contracts(data))
    if option_type is _O.Type.NON_STANDARD:
        for _, contract in contracts:
            assert contract['nonStandard'] is True
    elif option_type is _O.Type.STANDARD:
        assert len(contracts) > 0
        for _, contract in contracts:
            assert contract['nonStandard'] is False
    else:
        standard = _chain(live_client, option_type=_O.Type.STANDARD,
                          strike_count=1)
        assert len(contracts) >= len(list(_all_contracts(standard)))


################################################################################
# include_underlying_quote

def test_include_underlying_quote(live_client):
    '''includeUnderlyingQuote swaps the null underlying slot for a
    quote record on the underlier — symbol, description, and the
    usual price/volume fields.'''
    without = _chain(live_client, strike_count=1)
    assert without['underlying'] is None

    with_quote = _chain(
            live_client, strike_count=1, include_underlying_quote=True)
    underlying = with_quote['underlying']
    assert underlying['symbol'] == 'AAPL'
    assert isinstance(underlying['description'], str)
    for field in ('mark', 'last', 'bid', 'ask', 'close',
                  'totalVolume'):
        assert field in underlying


################################################################################
# Strategy chains

_SUPPORTED_STRATEGIES = [
        _O.Strategy.VERTICAL, _O.Strategy.STRADDLE,
        _O.Strategy.STRANGLE, _O.Strategy.CALENDAR,
        _O.Strategy.DIAGONAL, _O.Strategy.COVERED]

# Strategies whose legs are defined by a strike width populate the
# intervals field; straddles, calendars and covered calls have no
# strike spacing to offer, so theirs is empty.
_WIDTH_STRATEGIES = {
        _O.Strategy.VERTICAL, _O.Strategy.STRANGLE,
        _O.Strategy.DIAGONAL}

_UNSUPPORTED_STRATEGIES = [
        _O.Strategy.BUTTERFLY, _O.Strategy.CONDOR,
        _O.Strategy.COLLAR, _O.Strategy.ROLL]


def test_strategy_single(live_client):
    '''strategy=SINGLE is the default grid shape explicitly:
    populated expiration maps, no monthlyStrategyList.'''
    data = _chain(live_client, strategy=_O.Strategy.SINGLE,
                  strike_count=1)
    assert data['strategy'] == 'SINGLE'
    assert len(data['callExpDateMap']) > 0
    assert 'monthlyStrategyList' not in data


@pytest.mark.parametrize('strategy', _SUPPORTED_STRATEGIES)
def test_strategy_chains_format(live_client, strategy):
    '''Multi-leg strategies replace the grid with a strategy list:
    monthlyStrategyList entries pair expiration metadata with
    optionStrategyList records carrying primaryLeg/secondaryLeg
    and strategy-level prices and greeks, plus an intervals list
    of available strike widths.'''
    data = _chain(live_client, strategy=strategy, strike_count=3)
    assert data['status'] == 'SUCCESS'
    assert data['strategy'] == strategy.value
    assert data['callExpDateMap'] == {}
    assert data['putExpDateMap'] == {}
    assert isinstance(data['intervals'], list)
    if strategy in _WIDTH_STRATEGIES:
        assert len(data['intervals']) > 0
    else:
        assert len(data['intervals']) == 0
    monthlies = data['monthlyStrategyList']
    assert len(monthlies) > 0
    for monthly in monthlies:
        for strat in monthly['optionStrategyList']:
            leg = strat['primaryLeg']
            assert leg['symbol'] != ''
            assert leg['putCallInd'] in ('C', 'P')
            assert isinstance(leg['strikePrice'], float)
            # COVERED's stock leg is implicit: secondaryLeg is
            # null for every strategy; the option-pair strategies
            # populate it
            secondary = strat['secondaryLeg']
            if strategy is _O.Strategy.COVERED:
                assert secondary is None
            else:
                assert secondary['symbol'] != ''
                assert secondary['putCallInd'] in ('C', 'P')
            for field in ('strategyBid', 'strategyAsk',
                          'strategyMark'):
                assert field in strat


def test_strategy_interval(live_client):
    '''interval fixes the strike spacing of VERTICAL spreads:
    requesting 5 returns strategies whose two legs' strikes differ
    by exactly 5.'''
    data = _chain(live_client, strategy=_O.Strategy.VERTICAL,
                  interval=5)
    saw_spread = False
    for monthly in data['monthlyStrategyList']:
        for strat in monthly['optionStrategyList']:
            width = abs(strat['secondaryLeg']['strikePrice']
                        - strat['primaryLeg']['strikePrice'])
            assert width == 5
            saw_spread = True
    assert saw_spread


@pytest.mark.parametrize('strategy', _UNSUPPORTED_STRATEGIES)
def test_unsupported_strategies(live_client, strategy):
    '''Half the Strategy enum is dead: BUTTERFLY, CONDOR, COLLAR
    and ROLL are rejected with HTTP 400 whose body reports status
    '404' — enshrined so a future fix is noticed.'''
    resp = live_client.get_option_chain('AAPL', strategy=strategy)
    assert resp.status_code == 400
    assert resp.json()['errors'][0]['status'] == '404'


################################################################################
# ANALYTICAL

def test_analytical_format(live_client):
    '''ANALYTICAL returns the ordinary grid shape — populated
    expiration maps, no monthlyStrategyList — since it recomputes
    per-contract values rather than synthesizing strategy legs.'''
    data = _chain(live_client, strategy=_O.Strategy.ANALYTICAL,
                  strike_count=1)
    assert data['strategy'] == 'ANALYTICAL'
    assert len(data['callExpDateMap']) > 0
    assert 'monthlyStrategyList' not in data


def test_analytical_parameters_affect_greeks(live_client):
    '''The four ANALYTICAL inputs (volatility, underlyingPrice,
    interestRate, daysToExpiration) are documented as scenario
    overrides: extreme values should visibly move a contract's
    greeks versus a bare request. Skips on a closed market, where
    the pricing engine may be idle — the params were observed
    ignored out of hours; if this fails while the market is OPEN,
    the overrides are genuinely dead and warrant investigation.'''
    if not conftest.market_is_open(
            live_client, schwab.client.Client.MarketHours.Market.EQUITY):
        pytest.skip('equity market closed — ANALYTICAL inputs '
                    'appear ignored out of hours; rerun during a '
                    'session to verify')

    def first_contract(data):
        strikes = next(iter(data['callExpDateMap'].values()))
        return next(iter(strikes.values()))[0]

    bare = _chain(live_client, strategy=_O.Strategy.ANALYTICAL,
                  strike_count=1)
    scenario = _chain(live_client, strategy=_O.Strategy.ANALYTICAL,
                      strike_count=1, volatility=99.0,
                      underlying_price=100.0, interest_rate=20.0,
                      days_to_expiration=365)
    c_bare = first_contract(bare)
    c_scenario = first_contract(scenario)
    assert c_bare['symbol'] == c_scenario['symbol']
    differs = any(
            c_bare[g] != c_scenario[g]
            for g in ('delta', 'gamma', 'theta', 'vega', 'mark',
                      'volatility'))
    assert differs, ('ANALYTICAL inputs had no effect on contract '
                     'greeks with the market open — the scenario '
                     'parameters appear to be ignored')


################################################################################
# Errors and edges

def test_invalid_symbol(live_client):
    '''A bogus symbol is a real 400 'Check Param Values' error,
    unlike the empty-chain response for valid non-optionable
    symbols.'''
    resp = live_client.get_option_chain('NOT_A_SYMBOL')
    assert resp.status_code == 400
    assert resp.json()['errors'][0]['title'] == 'Bad Request'


def test_non_optionable_symbol(live_client):
    '''A valid but non-optionable symbol (SWPPX mutual fund) is
    success-with-nothing: 200, status SUCCESS, both maps empty,
    numberOfContracts 0.'''
    data = _chain(live_client, symbol='SWPPX')
    assert data['status'] == 'SUCCESS'
    assert data['callExpDateMap'] == {}
    assert data['putExpDateMap'] == {}
    assert data['numberOfContracts'] == 0


def test_from_after_to(live_client):
    '''An inverted date window is rejected: fromDate after toDate
    yields 400 'Check Param Values'.'''
    resp = live_client.get_option_chain(
            'AAPL', from_date=datetime.date(2026, 12, 1),
            to_date=datetime.date(2026, 1, 1))
    assert resp.status_code == 400


@pytest.mark.parametrize('entitlement', list(_O.Entitlement))
def test_entitlement(live_client, entitlement):
    '''Every entitlement declaration is accepted without changing
    the response shape — the parameter is a client-side
    entitlement claim, not a filter.'''
    data = _chain(live_client, strike_count=1,
                  entitlement=entitlement)
    assert data['status'] == 'SUCCESS'
    assert len(data['callExpDateMap']) > 0
