import pytest

import schwab
from schwab.orders import equities, options
from schwab.orders.common import (
        Duration, OrderStrategyType, Session, SpecialInstruction)


_S = schwab.client.Client


@pytest.fixture(scope='module')
def account_hash(live_client):
    resp = live_client.get_account_numbers()
    assert resp.status_code == 200
    return resp.json()[0]['hashValue']


@pytest.fixture(scope='module')
def option_symbols(live_client):
    '''Two calls and two puts at AAPL's first listed expiration,
    pulled live so the legs never expire under the tests.'''
    resp = live_client.get_option_chain(
            'AAPL', strike_count=3)
    assert resp.status_code == 200
    chain = resp.json()
    expiry = sorted(chain['callExpDateMap'])[0]
    calls = [c['symbol'] for strike in sorted(
        chain['callExpDateMap'][expiry], key=float)
        for c in chain['callExpDateMap'][expiry][strike]]
    puts = [c['symbol'] for strike in sorted(
        chain['putExpDateMap'][expiry], key=float)
        for c in chain['putExpDateMap'][expiry][strike]]
    assert len(calls) >= 2 and len(puts) >= 2
    return {'call_lo': calls[0], 'call_hi': calls[-1],
            'put_lo': puts[0], 'put_hi': puts[-1]}


def _preview(live_client, account_hash, builder):
    '''POSTs the built spec to previewOrder and returns the parsed
    response, asserting the shared envelope: 200, orderId, a
    structured orderValidationResult, and the three-part
    commissionAndFee block.'''
    resp = live_client.preview_order(account_hash, builder)
    assert resp.status_code == 200, resp.text[:300]
    data = resp.json()
    assert data['orderId'] == 0

    validation = data['orderValidationResult']
    for reject in validation.get('rejects', []):
        assert isinstance(reject['activityMessage'], str)
        assert reject['originalSeverity'] in (
                'REJECT', 'REVIEW', 'WARN', 'INFO', 'NONE')

    fees = data['commissionAndFee']
    for block, legs_key in (
            ('commission', 'commissionLegs'), ('fee', 'feeLegs'),
            ('trueCommission', 'commissionLegs')):
        legs = fees[block][legs_key]
        assert isinstance(legs, list)
    return data


def _check_legs(strategy, expected_legs, symbols):
    '''Verifies every leg of the echoed strategy against the
    template inputs: instruction, resolved symbol, asset type and
    derived positionEffect, plus the market-data fields the echo
    attaches.'''
    legs = strategy['orderLegs']
    assert len(legs) == len(expected_legs)
    for leg, (instr, sym_key, asset, effect) in zip(
            legs, expected_legs):
        symbol = symbols.get(sym_key, sym_key)
        assert leg['instruction'] == instr
        assert leg['instrument']['symbol'] == symbol
        assert leg['instrument']['assetType'] == asset
        assert leg['finalSymbol'] == symbol
        assert leg['assetType'] == asset
        assert leg['positionEffect'] == effect
        assert isinstance(leg['legId'], int)
        for field in ('askPrice', 'bidPrice', 'lastPrice',
                      'markPrice'):
            assert isinstance(leg[field], (int, float))


def _check_strategy(data, symbols, *, order_type, quantity,
                    strategy='NONE', session='NORMAL',
                    duration='DAY', price=None, legs=()):
    '''Verifies the normalized orderStrategy echo against the
    template inputs: order type and strategy, session, duration,
    quantity, price (absent on market orders), and order value
    arithmetic.'''
    strategy_data = data['orderStrategy']
    assert strategy_data['orderType'] == order_type
    assert strategy_data['strategy'] == strategy
    assert strategy_data['orderStrategyType'] == 'SINGLE'
    assert strategy_data['advancedOrderType'] == 'NONE'
    assert strategy_data['session'] == session
    assert strategy_data['duration'] == duration
    assert strategy_data['quantity'] == quantity
    assert strategy_data['amountIndicator'] == 'SHARES'

    if price is None:
        assert strategy_data.get('price') in (None, 0.0)
    else:
        assert strategy_data['price'] == price
        multiplier = 100.0 if any(
                leg[2] == 'OPTION' for leg in legs) else 1.0
        assert strategy_data['orderValue'] == pytest.approx(
                price * quantity * multiplier)
    _check_legs(strategy_data, legs, symbols)


################################################################################
# Equity templates

_EQUITY_CASES = [
    ('buy_market',
     lambda: equities.equity_buy_market('AAPL', 3),
     'MARKET', None,
     [('BUY', 'AAPL', 'EQUITY', 'OPENING')]),
    ('buy_limit',
     lambda: equities.equity_buy_limit('AAPL', 3, '350.00'),
     'LIMIT', 350.0,
     [('BUY', 'AAPL', 'EQUITY', 'OPENING')]),
    ('sell_market',
     lambda: equities.equity_sell_market('AAPL', 3),
     'MARKET', None,
     [('SELL', 'AAPL', 'EQUITY', 'CLOSING')]),
    ('sell_limit',
     lambda: equities.equity_sell_limit('AAPL', 3, '400.00'),
     'LIMIT', 400.0,
     [('SELL', 'AAPL', 'EQUITY', 'CLOSING')]),
    ('sell_short_market',
     lambda: equities.equity_sell_short_market('AAPL', 3),
     'MARKET', None,
     [('SELL_SHORT', 'AAPL', 'EQUITY', 'OPENING')]),
    ('sell_short_limit',
     lambda: equities.equity_sell_short_limit('AAPL', 3, '400.00'),
     'LIMIT', 400.0,
     [('SELL_SHORT', 'AAPL', 'EQUITY', 'OPENING')]),
    ('buy_to_cover_market',
     lambda: equities.equity_buy_to_cover_market('AAPL', 3),
     'MARKET', None,
     [('BUY_TO_COVER', 'AAPL', 'EQUITY', 'CLOSING')]),
    ('buy_to_cover_limit',
     lambda: equities.equity_buy_to_cover_limit('AAPL', 3, '350.00'),
     'LIMIT', 350.0,
     [('BUY_TO_COVER', 'AAPL', 'EQUITY', 'CLOSING')]),
]


@pytest.mark.parametrize('case', _EQUITY_CASES,
        ids=[c[0] for c in _EQUITY_CASES])
def test_equity_template(
        live_client, account_hash, case):
    '''Every equity template previews to an echo matching its
    inputs: order type, price, quantity, instruction, symbol, and
    the positionEffect the server derives from the instruction.'''
    _, make, order_type, price, legs = case
    data = _preview(live_client, account_hash, make())
    _check_strategy(
            data, {}, order_type=order_type, quantity=3.0,
            price=price, legs=legs)


################################################################################
# Single-option templates

_OPTION_CASES = [
    ('buy_to_open_market',
     lambda s: options.option_buy_to_open_market(s['call_lo'], 2),
     'MARKET', None,
     [('BUY_TO_OPEN', 'call_lo', 'OPTION', 'OPENING')]),
    ('buy_to_open_limit',
     lambda s: options.option_buy_to_open_limit(s['call_lo'], 2, '5.00'),
     'LIMIT', 5.0,
     [('BUY_TO_OPEN', 'call_lo', 'OPTION', 'OPENING')]),
    ('sell_to_open_market',
     lambda s: options.option_sell_to_open_market(s['call_lo'], 2),
     'MARKET', None,
     [('SELL_TO_OPEN', 'call_lo', 'OPTION', 'OPENING')]),
    ('sell_to_open_limit',
     lambda s: options.option_sell_to_open_limit(s['call_lo'], 2, '5.00'),
     'LIMIT', 5.0,
     [('SELL_TO_OPEN', 'call_lo', 'OPTION', 'OPENING')]),
    ('buy_to_close_market',
     lambda s: options.option_buy_to_close_market(s['call_lo'], 2),
     'MARKET', None,
     [('BUY_TO_CLOSE', 'call_lo', 'OPTION', 'CLOSING')]),
    ('buy_to_close_limit',
     lambda s: options.option_buy_to_close_limit(s['call_lo'], 2, '5.00'),
     'LIMIT', 5.0,
     [('BUY_TO_CLOSE', 'call_lo', 'OPTION', 'CLOSING')]),
    ('sell_to_close_market',
     lambda s: options.option_sell_to_close_market(s['call_lo'], 2),
     'MARKET', None,
     [('SELL_TO_CLOSE', 'call_lo', 'OPTION', 'CLOSING')]),
    ('sell_to_close_limit',
     lambda s: options.option_sell_to_close_limit(s['call_lo'], 2, '5.00'),
     'LIMIT', 5.0,
     [('SELL_TO_CLOSE', 'call_lo', 'OPTION', 'CLOSING')]),
]


@pytest.mark.parametrize('case', _OPTION_CASES,
        ids=[c[0] for c in _OPTION_CASES])
def test_option_template(
        live_client, account_hash, option_symbols, case):
    '''Every single-option template previews to an echo matching
    its inputs — including the orderValue arithmetic of
    price x quantity x 100.'''
    _, make, order_type, price, legs = case
    data = _preview(live_client, account_hash, make(option_symbols))
    _check_strategy(
            data, option_symbols, order_type=order_type,
            quantity=2.0, price=price, legs=legs)


################################################################################
# Vertical templates

_VERTICAL_CASES = [
    ('bull_call_open',
     lambda s: options.bull_call_vertical_open(
         s['call_lo'], s['call_hi'], 2, '1.50'),
     [('BUY_TO_OPEN', 'call_lo', 'OPTION', 'OPENING'),
      ('SELL_TO_OPEN', 'call_hi', 'OPTION', 'OPENING')],
     1.50),
    ('bull_call_close',
     lambda s: options.bull_call_vertical_close(
         s['call_lo'], s['call_hi'], 2, '1.50'),
     [('SELL_TO_CLOSE', 'call_lo', 'OPTION', 'CLOSING'),
      ('BUY_TO_CLOSE', 'call_hi', 'OPTION', 'CLOSING')],
     1.50),
    ('bear_call_open',
     lambda s: options.bear_call_vertical_open(
         s['call_lo'], s['call_hi'], 2, '1.50'),
     [('SELL_TO_OPEN', 'call_lo', 'OPTION', 'OPENING'),
      ('BUY_TO_OPEN', 'call_hi', 'OPTION', 'OPENING')],
     1.50),
    ('bear_call_close',
     lambda s: options.bear_call_vertical_close(
         s['call_lo'], s['call_hi'], 2, '1.50'),
     [('BUY_TO_CLOSE', 'call_lo', 'OPTION', 'CLOSING'),
      ('SELL_TO_CLOSE', 'call_hi', 'OPTION', 'CLOSING')],
     1.50),
    ('bull_put_open',
     lambda s: options.bull_put_vertical_open(
         s['put_lo'], s['put_hi'], 2, '1.50'),
     [('BUY_TO_OPEN', 'put_lo', 'OPTION', 'OPENING'),
      ('SELL_TO_OPEN', 'put_hi', 'OPTION', 'OPENING')],
     1.50),
    ('bull_put_close',
     lambda s: options.bull_put_vertical_close(
         s['put_lo'], s['put_hi'], 2, '1.50'),
     [('SELL_TO_CLOSE', 'put_lo', 'OPTION', 'CLOSING'),
      ('BUY_TO_CLOSE', 'put_hi', 'OPTION', 'CLOSING')],
     1.50),
    ('bear_put_open',
     lambda s: options.bear_put_vertical_open(
         s['put_lo'], s['put_hi'], 2, '1.50'),
     [('SELL_TO_OPEN', 'put_lo', 'OPTION', 'OPENING'),
      ('BUY_TO_OPEN', 'put_hi', 'OPTION', 'OPENING')],
     1.50),
    ('bear_put_close',
     lambda s: options.bear_put_vertical_close(
         s['put_lo'], s['put_hi'], 2, '1.50'),
     [('BUY_TO_CLOSE', 'put_lo', 'OPTION', 'CLOSING'),
      ('SELL_TO_CLOSE', 'put_hi', 'OPTION', 'CLOSING')],
     1.50),
]


@pytest.mark.parametrize('case', _VERTICAL_CASES,
        ids=[c[0] for c in _VERTICAL_CASES])
def test_vertical_template(
        live_client, account_hash, option_symbols, case):
    '''Every vertical template previews to a LIMIT echo under
    strategy 'VERTICAL' — NET_DEBIT and NET_CREDIT both normalize
    to LIMIT — with both legs' instructions, symbols and derived
    positionEffects matching the template's construction.'''
    _, make, legs, price = case
    data = _preview(live_client, account_hash, make(option_symbols))
    _check_strategy(
            data, option_symbols, order_type='LIMIT', quantity=2.0,
            strategy='VERTICAL', price=price, legs=legs)


################################################################################
# Builder variants on templates

@pytest.mark.parametrize('session', list(Session))
def test_variant_session(live_client, account_hash, session):
    '''set_session on a template carries through to the echo: every
    Session value round-trips into orderStrategy.session.'''
    builder = equities.equity_buy_limit(
            'AAPL', 1, '350.00').set_session(session)
    data = _preview(live_client, account_hash, builder)
    _check_strategy(
            data, {}, order_type='LIMIT', quantity=1.0,
            session=session.value, price=350.0,
            legs=[('BUY', 'AAPL', 'EQUITY', 'OPENING')])


@pytest.mark.parametrize('duration', [
        Duration.GOOD_TILL_CANCEL, Duration.FILL_OR_KILL])
def test_variant_duration(live_client, account_hash, duration):
    '''set_duration carries through to the echo for the durations
    the API actually accepts.'''
    builder = equities.equity_buy_limit(
            'AAPL', 1, '350.00').set_duration(duration)
    data = _preview(live_client, account_hash, builder)
    _check_strategy(
            data, {}, order_type='LIMIT', quantity=1.0,
            duration=duration.value, price=350.0,
            legs=[('BUY', 'AAPL', 'EQUITY', 'OPENING')])


def test_variant_special_instruction(live_client, account_hash):
    '''set_special_instruction lands on the built spec but is
    silently dropped by the echo: orderStrategy carries no
    special-instruction field.'''
    builder = equities.equity_buy_limit(
            'AAPL', 1, '350.00').set_special_instruction(
            SpecialInstruction.ALL_OR_NONE)
    assert builder.build()['specialInstruction'] == 'ALL_OR_NONE'
    data = _preview(live_client, account_hash, builder)
    strategy = data['orderStrategy']
    assert 'specialInstruction' not in strategy
    assert 'specialInstructions' not in strategy


def test_variant_quantity(live_client, account_hash):
    '''set_quantity writes the order-level quantity field, but the
    echo derives quantity from the LEGS — a top-level quantity of
    7 over a 1-share leg still echoes quantity 1.0. The orderValue
    follows the leg too.'''
    builder = equities.equity_buy_limit(
            'AAPL', 1, '350.00').set_quantity(7)
    assert builder.build()['quantity'] == 7
    data = _preview(live_client, account_hash, builder)
    _check_strategy(
            data, {}, order_type='LIMIT', quantity=1.0,
            price=350.0,
            legs=[('BUY', 'AAPL', 'EQUITY', 'OPENING')])


def test_variant_trigger_child(live_client, account_hash):
    '''Adding a child order strategy turns a template into a
    composite: the echo reports advancedOrderType OTO —
    one-triggers-other — while the child spec serializes into the
    request.'''
    child = equities.equity_sell_limit('AAPL', 1, '400.00')
    builder = (equities.equity_buy_limit('AAPL', 1, '350.00')
               .set_order_strategy_type(OrderStrategyType.TRIGGER)
               .add_child_order_strategy(child))
    spec = builder.build()
    assert spec['orderStrategyType'] == 'TRIGGER'
    assert len(spec['childOrderStrategies']) == 1
    assert spec['childOrderStrategies'][0]['orderType'] == 'LIMIT'

    data = _preview(live_client, account_hash, builder)
    strategy = data['orderStrategy']
    assert strategy['orderStrategyType'] == 'TRIGGER'
    assert strategy['advancedOrderType'] == 'OTO'


def test_variant_oco(live_client, account_hash):
    '''An OCO parent with two child orders previews with NO
    orderStrategy at all — composite wrappers get only validation
    and fee structure, not a normalized echo.'''
    child1 = equities.equity_sell_limit('AAPL', 1, '400.00')
    child2 = equities.equity_sell_limit('AAPL', 1, '300.00')
    builder = (equities.equity_sell_limit('AAPL', 1, '400.00')
               .set_order_strategy_type(OrderStrategyType.OCO)
               .add_child_order_strategy(child1)
               .add_child_order_strategy(child2))
    data = _preview(live_client, account_hash, builder)
    assert 'orderStrategy' not in data
    assert 'orderValidationResult' in data
    assert 'commissionAndFee' in data


def test_preview_order_builder_and_dict_equivalent(
        live_client, account_hash):
    '''Passing the OrderBuilder and passing its built dict are
    equivalent: both paths produce the same preview response.'''
    builder = equities.equity_buy_limit('AAPL', 1, '350.00')
    from_builder = _preview(live_client, account_hash, builder)
    from_dict = _preview(live_client, account_hash, builder.build())
    b_strat = from_builder['orderStrategy']
    d_strat = from_dict['orderStrategy']
    for key in ('orderType', 'session', 'duration', 'price',
                'quantity', 'strategy'):
        assert b_strat[key] == d_strat[key]
