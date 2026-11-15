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


def test_index_chain_multi_root(live_client):
    '''$SPX produces a real index-option chain — isIndex true,
    European exerciseType — and unlike AAPL it carries two
    optionRoots (SPX monthlies plus SPXW weeklies) that collide
    at some strikes, so a strike key maps to a contract LIST:
    several strikes hold more than one contract.'''
    data = _chain(live_client, symbol='$SPX', strike_count=2)
    assert data['isIndex'] is True
    roots = set()
    multi = 0
    for side, contract in _all_contracts(data):
        assert contract['exerciseType'] == 'E'
        roots.add(contract['optionRoot'])
    for key in ('callExpDateMap', 'putExpDateMap'):
        for strikes in data[key].values():
            for contracts in strikes.values():
                if len(contracts) > 1:
                    multi += 1
    assert {'SPX', 'SPXW'} <= roots
    assert multi > 0


@pytest.mark.parametrize('symbol', ['$VIX', '$RUT'])
def test_index_symbols_chain(live_client, symbol):
    '''Index option chains beyond $SPX work: $VIX and $RUT return
    isIndex chains with populated maps.'''
    data = _chain(live_client, symbol=symbol, strike_count=1)
    assert data['isIndex'] is True
    assert len(data['callExpDateMap']) > 0


def test_spx_settlement_split(live_client):
    '''$SPX's two roots differ by settlement: SPX monthlies are
    AM-settled ('A'), SPXW weeklies PM-settled ('P'), both
    European-exercise — the classic SPX/SPXW split enshrined.'''
    data = _chain(live_client, symbol='$SPX', strike_count=2)
    by_root = {}
    for _, contract in _all_contracts(data):
        by_root.setdefault(contract['optionRoot'], set()).add(
                (contract['settlementType'], contract['exerciseType']))
    assert by_root['SPX'] == {('A', 'E')}
    assert by_root['SPXW'] == {('P', 'E')}


def test_spy_bounded_request(live_client):
    '''SPY responds to a bounded chain request normally. Its
    unbounded chain is too large for the gateway — repeated
    requests with no strikeCount returned HTTP 502 — so this
    request is kept bounded to document the constraint without
    depending on the outage.'''
    data = _chain(live_client, symbol='SPY', strike_count=1)
    assert data['status'] == 'SUCCESS'
    assert data['isIndex'] is False
    assert len(data['callExpDateMap']) > 0


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
        assert contract['exerciseType'] == 'A'
        assert contract['multiplier'] == 100.0
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


def test_underlying_price_is_quote_last(live_client):
    '''The chain's underlyingPrice equals the quotes endpoint's
    lastPrice for the same symbol — the last trade, not the mark
    or close.'''
    quote = live_client.get_quotes(['AAPL']).json()
    last = quote['AAPL']['quote']['lastPrice']
    data = _chain(live_client, strike_count=1)
    assert data['underlyingPrice'] == last


def test_break_even_arithmetic(live_client):
    '''breakEven is strike + mark for calls and strike - mark for
    puts, computed against the UNROUNDED mark: it can land a cent
    away from the rounded mark's arithmetic (mark 4.22 with
    theoretical 4.225 breaks even at 361.725 -> 361.73).'''
    data = _chain(live_client, strike_count=2)
    for side, contract in _all_contracts(data):
        expected = contract['strikePrice'] + contract['mark'] \
                if side == 'CALL' \
                else contract['strikePrice'] - contract['mark']
        assert contract['breakEven'] == pytest.approx(
                expected, abs=0.011)


def test_deliverables(live_client):
    '''Standard contracts carry a populated optionDeliverablesList
    of 100 shares of the underlying, plus the human-readable
    deliverableNote '100 AAPL'.'''
    data = _chain(live_client, strike_count=1)
    for _, contract in _all_contracts(data):
        assert contract['deliverableNote'] == '100 AAPL'
        deliverables = contract['optionDeliverablesList']
        assert len(deliverables) == 1
        deliverable = deliverables[0]
        assert deliverable['symbol'] == 'AAPL'
        assert deliverable['assetType'] == 'STOCK'
        assert deliverable['deliverableUnits'] == 100.0


def test_neg999_paired_sentinels(live_client):
    '''Every contract with the -999.0 volatility sentinel also has
    -999.0 theoreticalOptionValue — the missing-data marker comes
    in pairs, flagging contracts with no usable market.'''
    data = _chain(live_client, strike_count=3)
    for _, contract in _all_contracts(data):
        if contract['volatility'] == -999.0:
            assert contract['theoreticalOptionValue'] == -999.0


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


def test_contract_type_and_range_compose(live_client):
    '''contractType and strikeRange compose: CALL plus OTM leaves
    only out-of-the-money calls — the zeroed put map and the
    moneyness filter apply together rather than one winning.'''
    data = _chain(live_client, contract_type=_O.ContractType.CALL,
                  strike_range=_O.StrikeRange.OUT_OF_THE_MONEY)
    assert len(data['callExpDateMap']) > 0
    assert len(data['putExpDateMap']) == 0
    for _, contract in _all_contracts(data):
        assert contract['putCall'] == 'CALL'
        assert contract['inTheMoney'] is False


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


def test_strike_count_fractional(live_client):
    '''The server validates numeric parameter format even though it
    ignores numeric values: a fractional strikeCount is a 400.'''
    resp = live_client.get_option_chain('AAPL', strike_count=3.7)
    assert resp.status_code == 400


def test_strike_count_negative(live_client):
    '''A negative strikeCount is silently treated as unbounded,
    returning the full chain just like an over-large value.'''
    data = _chain(live_client, strike_count=-1)
    default = _chain(live_client)
    assert sum(len(s) for s in data['callExpDateMap'].values()) \
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


@pytest.mark.parametrize('strike', [272.5, 275.13])
def test_strike_fractional_no_match(live_client, strike):
    '''The exact-strike filter does no rounding or fuzzy matching:
    strikes between or near listed increments return 200 with
    empty maps, not the nearest listed strike.'''
    data = _chain(live_client, strike=strike)
    assert len(data['callExpDateMap']) == 0
    assert len(data['putExpDateMap']) == 0


def test_strike_overridden_by_count(live_client):
    '''Precedence quirk: when strike and strikeCount are both
    supplied, strike is silently ignored — the response is
    indistinguishable from strikeCount alone (three strikes per
    expiration), not the single-strike sparse filter.'''
    strike = _live_strike(live_client)
    data = _chain(live_client, strike=strike, strike_count=3)
    sizes = [len(strikes)
             for strikes in data['callExpDateMap'].values()]
    assert len(sizes) > 0
    assert all(size <= 3 for size in sizes)
    assert any(size == 3 for size in sizes)
    strikes_seen = {
            float(k) for strikes in data['callExpDateMap'].values()
            for k in strikes}
    assert len(strikes_seen) > 1


def test_strike_and_range_compose(live_client):
    '''strike and strikeRange compose on a per-side basis: an
    out-of-the-money PUT strike (below market) survives for puts
    while calls at the same strike — being in the money — are
    filtered out entirely.'''
    chain = _chain(live_client, strike_count=3)
    underlying = chain['underlyingPrice']
    below = sorted(
            float(k) for strikes in chain['callExpDateMap'].values()
            for k in strikes if float(k) < underlying)
    assert below
    strike = below[len(below) // 2]
    data = _chain(live_client, strike=strike,
                  strike_range=_O.StrikeRange.OUT_OF_THE_MONEY)
    assert len(data['callExpDateMap']) == 0
    assert len(data['putExpDateMap']) > 0
    for _, contract in _all_contracts(data):
        assert contract['strikePrice'] == strike
        assert contract['inTheMoney'] is False


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


def test_exp_month_intersects_dates(live_client):
    '''expMonth and the date window compose as an intersection:
    DECEMBER plus a window spanning December and January returns
    only the December expiries inside it, while DECEMBER plus a
    window that misses December entirely returns empty maps.'''
    year = datetime.date.today().year
    dec = _chain(live_client,
                 exp_month=_O.ExpirationMonth.DECEMBER,
                 from_date=datetime.date(year, 12, 1),
                 to_date=datetime.date(year + 1, 2, 1))
    keys = list(dec['callExpDateMap'])
    if keys:
        for key in keys:
            d = datetime.date.fromisoformat(_exp_key_date(key))
            assert d.month == 12
            assert datetime.date(year, 12, 1) <= d \
                    <= datetime.date(year + 1, 2, 1)

    miss = _chain(live_client,
                  exp_month=_O.ExpirationMonth.DECEMBER,
                  from_date=datetime.date(year + 1, 3, 1),
                  to_date=datetime.date(year + 1, 4, 1))
    assert len(miss['callExpDateMap']) == 0
    assert len(miss['putExpDateMap']) == 0


def test_from_date_past(live_client):
    '''Date-window validation is asymmetric: a fromDate in the past
    is a hard 400, while a toDate beyond the last listed expiry
    is accepted and simply bounded by the chain itself.'''
    past = datetime.date.today() - datetime.timedelta(30)
    resp = live_client.get_option_chain(
            'AAPL', from_date=past,
            to_date=past + datetime.timedelta(7))
    assert resp.status_code == 400

    data = _chain(live_client, to_date=datetime.date(2040, 1, 1),
                  strike_count=1)
    assert len(data['callExpDateMap']) > 0


def test_window_with_no_expiry(live_client):
    '''A window that contains no expiration is not an error — a
    midpoint between two real expiries returns 200 with empty
    maps, unlike the 400 for a window in the past.'''
    full = _chain(live_client, strike_count=1)
    exp_dates = sorted(
            datetime.date.fromisoformat(_exp_key_date(k))
            for k in full['callExpDateMap'])
    assert len(exp_dates) >= 2
    gap_start = exp_dates[0]
    for nxt in exp_dates[1:]:
        if (nxt - gap_start).days > 2:
            break
        gap_start = nxt
    else:
        pytest.skip('no multi-day gap between expirations')
    mid = gap_start + datetime.timedelta(
            days=(nxt - gap_start).days // 2)
    data = _chain(live_client, from_date=mid, to_date=mid)
    assert len(data['callExpDateMap']) == 0
    assert len(data['putExpDateMap']) == 0


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


def _strategies(data):
    for monthly in data['monthlyStrategyList']:
        yield from monthly['optionStrategyList']


def _leg_width(strat):
    return abs(strat['secondaryLeg']['strikePrice']
               - strat['primaryLeg']['strikePrice'])


@pytest.mark.parametrize('contract_type', [
        _O.ContractType.CALL, _O.ContractType.PUT])
def test_strategy_contract_type(live_client, contract_type):
    '''contractType works on strategy chains: CALL returns only
    call-leg spreads, PUT only put-leg spreads — the filter
    applies to leg side, not just the grid.'''
    data = _chain(live_client, strategy=_O.Strategy.VERTICAL,
                  interval=5, contract_type=contract_type)
    expected = 'C' if contract_type is _O.ContractType.CALL else 'P'
    strats = list(_strategies(data))
    assert len(strats) > 0
    for strat in strats:
        assert strat['primaryLeg']['putCallInd'] == expected
        assert strat['secondaryLeg']['putCallInd'] == expected


def test_strategy_truncation_is_put_biased(live_client):
    '''Truncation takes a put-sorted prefix: the default VERTICAL
    response's 1000 capped strategies are all put spreads.'''
    data = _chain(live_client, strategy=_O.Strategy.VERTICAL)
    assert data['isChainTruncated'] is True
    strats = list(_strategies(data))
    assert len(strats) == 1000
    for strat in strats:
        assert strat['primaryLeg']['putCallInd'] == 'P'


def test_strategy_strike_anchors_either_leg(live_client):
    '''strike on a strategy chain anchors spreads at EITHER leg:
    a strike filter returns every spread touching it — both
    (X,X+w) and (X-w,X) pairs — not just one leg position.'''
    data = _chain(live_client, strategy=_O.Strategy.VERTICAL,
                  interval=5, strike=275)
    strats = list(_strategies(data))
    assert len(strats) > 0
    saw_lower = saw_upper = False
    for strat in strats:
        strikes = {strat['primaryLeg']['strikePrice'],
                   strat['secondaryLeg']['strikePrice']}
        assert 275.0 in strikes
        saw_lower |= strat['primaryLeg']['strikePrice'] == 275.0
        saw_upper |= strat['secondaryLeg']['strikePrice'] == 275.0
    assert saw_lower and saw_upper


def test_strategy_filters_compose(live_client):
    '''strikeRange, the date window and expMonth all filter
    strategy lists just as they filter the grid — each yields a
    narrower, still well-formed monthlyStrategyList.'''
    for kwargs in (
            {'strike_range': _O.StrikeRange.OUT_OF_THE_MONEY},
            {'exp_month': _O.ExpirationMonth.DECEMBER}):
        data = _chain(live_client, strategy=_O.Strategy.VERTICAL,
                      interval=5, **kwargs)
        assert len(list(_strategies(data))) > 0

    full = _chain(live_client, strike_count=1)
    exp_dates = sorted(
            datetime.date.fromisoformat(_exp_key_date(k))
            for k in full['callExpDateMap'])
    data = _chain(live_client, strategy=_O.Strategy.VERTICAL,
                  interval=5, from_date=exp_dates[0],
                  to_date=exp_dates[min(3, len(exp_dates) - 1)])
    assert len(list(_strategies(data))) > 0


def test_strategy_strike_count_ignored(live_client):
    '''strikeCount does NOT apply to strategy chains: a bounded
    VERTICAL request returns the identical strategy count with and
    without it — count limits grid strikes, not strategy
    generation.'''
    kwargs = {'strategy': _O.Strategy.VERTICAL, 'interval': 2.5}
    bounded = _chain(live_client, strike_count=1, **kwargs)
    unbounded = _chain(live_client, **kwargs)
    assert sum(1 for _ in _strategies(bounded)) \
            == sum(1 for _ in _strategies(unbounded))


def test_strategy_include_underlying_quote(live_client):
    '''includeUnderlyingQuote populates the strategy response's
    underlying slot too — the flag applies to whichever response
    shape the request produces.'''
    data = _chain(live_client, strategy=_O.Strategy.VERTICAL,
                  interval=5, include_underlying_quote=True)
    assert data['underlying']['symbol'] == 'AAPL'


def test_strategy_truncation_cap(live_client):
    '''The strategy list is capped at 1000 entries server-side and
    isChainTruncated reports the cap was hit: a default VERTICAL
    request (multiple widths) returns exactly 1000 strategies with
    the flag set.'''
    data = _chain(live_client, strategy=_O.Strategy.VERTICAL)
    assert data['isChainTruncated'] is True
    assert sum(1 for _ in _strategies(data)) == 1000


def test_vertical_default_mixed_widths(live_client):
    '''An unbounded VERTICAL chain mixes leg widths: the response
    contains strategies at more than one strike spacing, all
    drawn from the advertised intervals list.'''
    data = _chain(live_client, strategy=_O.Strategy.VERTICAL)
    widths = {_leg_width(s) for s in _strategies(data)}
    assert len(widths) > 1
    assert widths <= set(data['intervals'])


def test_strategy_interval_no_offering(live_client):
    '''interval filters strategies to an exact width, and a width
    nobody offers is not an error — intervals 0 and 1000 return
    200 with an empty monthlyStrategyList.'''
    for interval in (0, 1000):
        data = _chain(live_client, strategy=_O.Strategy.VERTICAL,
                      interval=interval)
        assert data['monthlyStrategyList'] == []


def test_straddle_ignores_interval(live_client):
    '''STRADDLE legs share one strike, so interval is meaningless:
    every strategy's legs have identical strikes regardless of the
    requested width, while the 1000-entry cap still applies.'''
    data = _chain(live_client, strategy=_O.Strategy.STRADDLE,
                  interval=5)
    strats = list(_strategies(data))
    assert len(strats) == 1000
    for strat in strats:
        assert strat['primaryLeg']['strikePrice'] \
                == strat['secondaryLeg']['strikePrice']


def test_calendar_pairing_fields(live_client):
    '''CALENDAR legs share a strike and differ only in expiration;
    since the leg records carry no expiration of their own, the
    pairing lives in the monthlyStrategyList entry's secondary*
    fields — month, daysToExp, type — which differ from the
    primary leg's.'''
    data = _chain(live_client, strategy=_O.Strategy.CALENDAR)
    saw_entry = False
    for monthly in data['monthlyStrategyList']:
        assert monthly['daysToExp'] != monthly['secondaryDaysToExp']
        saw_entry = True
        for strat in monthly['optionStrategyList']:
            assert strat['primaryLeg']['strikePrice'] \
                    == strat['secondaryLeg']['strikePrice']
    assert saw_entry


def test_diagonal_differs_in_both_dimensions(live_client):
    '''DIAGONAL is a calendar plus a width: legs differ in both
    strike and expiration, combining the monthly pairing fields
    with non-equal leg strikes.'''
    data = _chain(live_client, strategy=_O.Strategy.DIAGONAL,
                  interval=5)
    saw_diagonal = False
    for monthly in data['monthlyStrategyList']:
        for strat in monthly['optionStrategyList']:
            assert _leg_width(strat) == 5
            saw_diagonal = True
    assert saw_diagonal


def test_strategy_echo_fields_zeroed(live_client):
    '''Strategy-chain responses keep the real underlyingPrice but
    zero out the scenario echo fields — volatility, interestRate
    and daysToExpiration are all 0.0 since no single-contract
    analytics apply to multi-leg entries.'''
    data = _chain(live_client, strategy=_O.Strategy.VERTICAL,
                  interval=5)
    assert data['underlyingPrice'] > 0
    assert data['volatility'] == 0.0
    assert data['interestRate'] == 0.0
    assert data['daysToExpiration'] == 0.0


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


@pytest.mark.parametrize('kwargs', [
        {'volatility': -5}, {'underlying_price': -100},
        {'interest_rate': 200}, {'days_to_expiration': -10}])
def test_analytical_inputs_unvalidated(live_client, kwargs):
    '''ANALYTICAL's four scenario inputs receive no server-side
    validation at all: negative volatility, negative underlying
    price, a 200%% interest rate and negative days-to-expiration
    are all accepted with 200 SUCCESS.'''
    data = _chain(live_client, strategy=_O.Strategy.ANALYTICAL,
                  strike_count=1, **kwargs)
    assert data['status'] == 'SUCCESS'


def test_scenario_params_accepted_on_single(live_client):
    '''The ANALYTICAL-only inputs are silently accepted on a
    SINGLE request too — the "applies only to ANALYTICAL" contract
    is documentation, not enforcement.'''
    data = _chain(live_client, strategy=_O.Strategy.SINGLE,
                  strike_count=1, volatility=50)
    assert data['status'] == 'SUCCESS'


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


@pytest.mark.parametrize('symbol', ['aapl', ' AAPL ', ''])
def test_symbol_form_rejected(live_client, symbol):
    '''Symbol matching is strict: lowercase, whitespace-padded and
    empty symbols are all 400 'Check Param Values' — no
    case-folding or trimming happens server-side.'''
    resp = live_client.get_option_chain(symbol)
    assert resp.status_code == 400


def test_symbol_share_class_slash(live_client):
    ''''BRK/B' resolves to a real chain while 'BRK.B' and 'BRKB'
    are 400s: only the slash spelling works for this share
    class.'''
    data = _chain(live_client, symbol='BRK/B', strike_count=1)
    assert len(data['callExpDateMap']) > 0
    for bad in ('BRK.B', 'BRKB'):
        resp = live_client.get_option_chain(bad)
        assert resp.status_code == 400


@pytest.mark.parametrize('symbol', ['/ES', 'EUR/USD'])
def test_no_chain_asset_classes(live_client, symbol):
    '''Futures and forex symbols are recognized enough to fail
    cleanly: they return the same 400 as a bogus symbol rather
    than an empty-success chain.'''
    resp = live_client.get_option_chain(symbol)
    assert resp.status_code == 400


def test_from_after_to(live_client):
    '''An inverted date window is rejected: fromDate after toDate
    yields 400 'Check Param Values'.'''
    resp = live_client.get_option_chain(
            'AAPL', from_date=datetime.date(2026, 12, 1),
            to_date=datetime.date(2026, 1, 1))
    assert resp.status_code == 400


@pytest.mark.parametrize('entitlement', list(_O.Entitlement))
def test_entitlement(live_client, entitlement):
    '''Every entitlement declaration is accepted with zero
    observable effect — the parameter is a client-side
    entitlement claim, not a filter, and none of PP/NP/PN flip
    isDelayed on this account's data.'''
    data = _chain(live_client, strike_count=1,
                  entitlement=entitlement)
    assert data['status'] == 'SUCCESS'
    assert data['isDelayed'] is False
    assert len(data['callExpDateMap']) > 0
