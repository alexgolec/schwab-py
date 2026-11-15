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


def _check_echo_common(strategy_data, session, duration,
                       quantity):
    '''The fields every single-order echo carries unchanged:
    SINGLE strategy type, no advanced order type, and the
    request's session, duration and (leg-derived) quantity.'''
    assert strategy_data['orderStrategyType'] == 'SINGLE'
    assert strategy_data['advancedOrderType'] == 'NONE'
    assert strategy_data['session'] == session
    assert strategy_data['duration'] == duration
    assert strategy_data['quantity'] == quantity
    assert strategy_data['amountIndicator'] == 'SHARES'


def _check_price(strategy_data, legs, price, quantity):
    '''Market orders echo no price; limit orders echo the price
    and orderValue = price x quantity x multiplier (100 for
    options, 1 for equities).'''
    if price is None:
        assert strategy_data.get('price') in (None, 0.0)
    else:
        assert strategy_data['price'] == price
        multiplier = 100.0 if any(
                leg[2] == 'OPTION' for leg in legs) else 1.0
        assert strategy_data['orderValue'] == pytest.approx(
                price * quantity * multiplier)


def _check_single(data, symbols, *, order_type, quantity,
                  session='NORMAL', duration='DAY', price=None,
                  legs=()):
    '''Verifies a single-leg template's echo: the order type
    round-trips under strategy 'NONE', session/duration/quantity
    carry through, price and orderValue arithmetic hold, and every
    leg matches its inputs.'''
    strategy_data = data['orderStrategy']
    assert strategy_data['orderType'] == order_type
    assert strategy_data['strategy'] == 'NONE'
    _check_echo_common(strategy_data, session, duration, quantity)
    _check_price(strategy_data, legs, price, quantity)
    _check_legs(strategy_data, legs, symbols)


def _check_vertical(data, symbols, *, quantity, price, legs):
    '''Verifies a vertical template's echo: NET_DEBIT and
    NET_CREDIT normalize to orderType 'LIMIT' while the complex
    strategy survives under strategy 'VERTICAL', with both legs
    matching the template's inputs.'''
    strategy_data = data['orderStrategy']
    assert strategy_data['orderType'] == 'LIMIT'
    assert strategy_data['strategy'] == 'VERTICAL'
    _check_echo_common(
            strategy_data, 'NORMAL', 'DAY', quantity)
    _check_price(strategy_data, legs, price, quantity)
    _check_legs(strategy_data, legs, symbols)


################################################################################
# Equity templates

def test_equity_buy_market(live_client, account_hash):
    '''equity_buy_market produces a MARKET BUY leg echoed with
    positionEffect OPENING, no price, and a market orderValue.'''
    data = _preview(live_client, account_hash,
                    equities.equity_buy_market('AAPL', 3))
    _check_single(data, {}, order_type='MARKET', quantity=3.0,
                    legs=[('BUY', 'AAPL', 'EQUITY', 'OPENING')])


def test_equity_buy_limit(live_client, account_hash):
    '''equity_buy_limit echoes LIMIT BUY with the price and
    orderValue = price x quantity.'''
    data = _preview(live_client, account_hash,
                    equities.equity_buy_limit('AAPL', 3, '350.00'))
    _check_single(data, {}, order_type='LIMIT', quantity=3.0,
                    price=350.0,
                    legs=[('BUY', 'AAPL', 'EQUITY', 'OPENING')])


def test_equity_sell_market(live_client, account_hash):
    '''equity_sell_market produces a MARKET SELL leg echoed with
    positionEffect CLOSING.'''
    data = _preview(live_client, account_hash,
                    equities.equity_sell_market('AAPL', 3))
    _check_single(data, {}, order_type='MARKET', quantity=3.0,
                    legs=[('SELL', 'AAPL', 'EQUITY', 'CLOSING')])


def test_equity_sell_limit(live_client, account_hash):
    '''equity_sell_limit echoes LIMIT SELL with the price,
    positionEffect CLOSING.'''
    data = _preview(live_client, account_hash,
                    equities.equity_sell_limit('AAPL', 3, '400.00'))
    _check_single(data, {}, order_type='LIMIT', quantity=3.0,
                    price=400.0,
                    legs=[('SELL', 'AAPL', 'EQUITY', 'CLOSING')])


def test_equity_sell_short_market(live_client, account_hash):
    '''equity_sell_short_market produces a MARKET SELL_SHORT
    leg echoed with positionEffect OPENING — the server treats a
    short sale as an opening trade.'''
    data = _preview(live_client, account_hash,
                    equities.equity_sell_short_market('AAPL', 3))
    _check_single(data, {}, order_type='MARKET', quantity=3.0,
                    legs=[('SELL_SHORT', 'AAPL', 'EQUITY',
                           'OPENING')])


def test_equity_sell_short_limit(live_client, account_hash):
    '''equity_sell_short_limit echoes LIMIT SELL_SHORT with
    positionEffect OPENING.'''
    data = _preview(live_client, account_hash,
                    equities.equity_sell_short_limit(
                        'AAPL', 3, '400.00'))
    _check_single(data, {}, order_type='LIMIT', quantity=3.0,
                    price=400.0,
                    legs=[('SELL_SHORT', 'AAPL', 'EQUITY',
                           'OPENING')])


def test_equity_buy_to_cover_market(live_client, account_hash):
    '''equity_buy_to_cover_market produces a MARKET
    BUY_TO_COVER leg echoed with positionEffect CLOSING.'''
    data = _preview(live_client, account_hash,
                    equities.equity_buy_to_cover_market('AAPL', 3))
    _check_single(data, {}, order_type='MARKET', quantity=3.0,
                    legs=[('BUY_TO_COVER', 'AAPL', 'EQUITY',
                           'CLOSING')])


def test_equity_buy_to_cover_limit(live_client, account_hash):
    '''equity_buy_to_cover_limit echoes LIMIT BUY_TO_COVER
    with the price and positionEffect CLOSING.'''
    data = _preview(live_client, account_hash,
                    equities.equity_buy_to_cover_limit(
                        'AAPL', 3, '350.00'))
    _check_single(data, {}, order_type='LIMIT', quantity=3.0,
                    price=350.0,
                    legs=[('BUY_TO_COVER', 'AAPL', 'EQUITY',
                           'CLOSING')])


################################################################################
# Single-option templates

def test_option_buy_to_open_market(
        live_client, account_hash, option_symbols):
    '''option_buy_to_open_market produces a MARKET BUY_TO_OPEN
    leg echoed with positionEffect OPENING against the live option
    symbol.'''
    data = _preview(live_client, account_hash,
                    options.option_buy_to_open_market(
                        option_symbols['call_lo'], 2))
    _check_single(data, option_symbols, order_type='MARKET',
                    quantity=2.0,
                    legs=[('BUY_TO_OPEN', 'call_lo', 'OPTION',
                           'OPENING')])


def test_option_buy_to_open_limit(
        live_client, account_hash, option_symbols):
    '''option_buy_to_open_limit echoes LIMIT BUY_TO_OPEN with
    the price and orderValue = price x quantity x 100.'''
    data = _preview(live_client, account_hash,
                    options.option_buy_to_open_limit(
                        option_symbols['call_lo'], 2, '5.00'))
    _check_single(data, option_symbols, order_type='LIMIT',
                    quantity=2.0, price=5.0,
                    legs=[('BUY_TO_OPEN', 'call_lo', 'OPTION',
                           'OPENING')])


def test_option_sell_to_open_market(
        live_client, account_hash, option_symbols):
    '''option_sell_to_open_market produces a MARKET
    SELL_TO_OPEN leg echoed with positionEffect OPENING.'''
    data = _preview(live_client, account_hash,
                    options.option_sell_to_open_market(
                        option_symbols['call_lo'], 2))
    _check_single(data, option_symbols, order_type='MARKET',
                    quantity=2.0,
                    legs=[('SELL_TO_OPEN', 'call_lo', 'OPTION',
                           'OPENING')])


def test_option_sell_to_open_limit(
        live_client, account_hash, option_symbols):
    '''option_sell_to_open_limit echoes LIMIT SELL_TO_OPEN
    with the price and positionEffect OPENING.'''
    data = _preview(live_client, account_hash,
                    options.option_sell_to_open_limit(
                        option_symbols['call_lo'], 2, '5.00'))
    _check_single(data, option_symbols, order_type='LIMIT',
                    quantity=2.0, price=5.0,
                    legs=[('SELL_TO_OPEN', 'call_lo', 'OPTION',
                           'OPENING')])


def test_option_buy_to_close_market(
        live_client, account_hash, option_symbols):
    '''option_buy_to_close_market produces a MARKET
    BUY_TO_CLOSE leg echoed with positionEffect CLOSING.'''
    data = _preview(live_client, account_hash,
                    options.option_buy_to_close_market(
                        option_symbols['call_lo'], 2))
    _check_single(data, option_symbols, order_type='MARKET',
                    quantity=2.0,
                    legs=[('BUY_TO_CLOSE', 'call_lo', 'OPTION',
                           'CLOSING')])


def test_option_buy_to_close_limit(
        live_client, account_hash, option_symbols):
    '''option_buy_to_close_limit echoes LIMIT BUY_TO_CLOSE
    with the price and positionEffect CLOSING.'''
    data = _preview(live_client, account_hash,
                    options.option_buy_to_close_limit(
                        option_symbols['call_lo'], 2, '5.00'))
    _check_single(data, option_symbols, order_type='LIMIT',
                    quantity=2.0, price=5.0,
                    legs=[('BUY_TO_CLOSE', 'call_lo', 'OPTION',
                           'CLOSING')])


def test_option_sell_to_close_market(
        live_client, account_hash, option_symbols):
    '''option_sell_to_close_market produces a MARKET
    SELL_TO_CLOSE leg echoed with positionEffect CLOSING.'''
    data = _preview(live_client, account_hash,
                    options.option_sell_to_close_market(
                        option_symbols['call_lo'], 2))
    _check_single(data, option_symbols, order_type='MARKET',
                    quantity=2.0,
                    legs=[('SELL_TO_CLOSE', 'call_lo', 'OPTION',
                           'CLOSING')])


def test_option_sell_to_close_limit(
        live_client, account_hash, option_symbols):
    '''option_sell_to_close_limit echoes LIMIT SELL_TO_CLOSE
    with the price and positionEffect CLOSING.'''
    data = _preview(live_client, account_hash,
                    options.option_sell_to_close_limit(
                        option_symbols['call_lo'], 2, '5.00'))
    _check_single(data, option_symbols, order_type='LIMIT',
                    quantity=2.0, price=5.0,
                    legs=[('SELL_TO_CLOSE', 'call_lo', 'OPTION',
                           'CLOSING')])


################################################################################
# Vertical templates

def test_bull_call_vertical_open(
        live_client, account_hash, option_symbols):
    '''bull_call_vertical_open previews as a LIMIT order under
    strategy VERTICAL — NET_DEBIT normalizes to LIMIT — buying the
    lower call and selling the higher, both legs OPENING.'''
    data = _preview(live_client, account_hash,
                    options.bull_call_vertical_open(
                        option_symbols['call_lo'],
                        option_symbols['call_hi'], 2, '1.50'))
    _check_vertical(data, option_symbols,
                    quantity=2.0, price=1.5,
                    legs=[('BUY_TO_OPEN', 'call_lo', 'OPTION',
                           'OPENING'),
                          ('SELL_TO_OPEN', 'call_hi', 'OPTION',
                           'OPENING')])


def test_bull_call_vertical_close(
        live_client, account_hash, option_symbols):
    '''bull_call_vertical_close previews as LIMIT/VERTICAL —
    NET_CREDIT normalizes too — selling the long call and buying
    back the short, both legs CLOSING.'''
    data = _preview(live_client, account_hash,
                    options.bull_call_vertical_close(
                        option_symbols['call_lo'],
                        option_symbols['call_hi'], 2, '1.50'))
    _check_vertical(data, option_symbols,
                    quantity=2.0, price=1.5,
                    legs=[('SELL_TO_CLOSE', 'call_lo', 'OPTION',
                           'CLOSING'),
                          ('BUY_TO_CLOSE', 'call_hi', 'OPTION',
                           'CLOSING')])


def test_bear_call_vertical_open(
        live_client, account_hash, option_symbols):
    '''bear_call_vertical_open previews as LIMIT/VERTICAL,
    selling the lower call and buying the higher for protection,
    both legs OPENING.'''
    data = _preview(live_client, account_hash,
                    options.bear_call_vertical_open(
                        option_symbols['call_lo'],
                        option_symbols['call_hi'], 2, '1.50'))
    _check_vertical(data, option_symbols,
                    quantity=2.0, price=1.5,
                    legs=[('SELL_TO_OPEN', 'call_lo', 'OPTION',
                           'OPENING'),
                          ('BUY_TO_OPEN', 'call_hi', 'OPTION',
                           'OPENING')])


def test_bear_call_vertical_close(
        live_client, account_hash, option_symbols):
    '''bear_call_vertical_close previews as LIMIT/VERTICAL,
    buying back the short call and selling the long, both legs
    CLOSING.'''
    data = _preview(live_client, account_hash,
                    options.bear_call_vertical_close(
                        option_symbols['call_lo'],
                        option_symbols['call_hi'], 2, '1.50'))
    _check_vertical(data, option_symbols,
                    quantity=2.0, price=1.5,
                    legs=[('BUY_TO_CLOSE', 'call_lo', 'OPTION',
                           'CLOSING'),
                          ('SELL_TO_CLOSE', 'call_hi', 'OPTION',
                           'CLOSING')])


def test_bull_put_vertical_open(
        live_client, account_hash, option_symbols):
    '''bull_put_vertical_open previews as LIMIT/VERTICAL,
    buying the lower put and selling the higher — the put mirror
    of the bull call, both legs OPENING.'''
    data = _preview(live_client, account_hash,
                    options.bull_put_vertical_open(
                        option_symbols['put_lo'],
                        option_symbols['put_hi'], 2, '1.50'))
    _check_vertical(data, option_symbols,
                    quantity=2.0, price=1.5,
                    legs=[('BUY_TO_OPEN', 'put_lo', 'OPTION',
                           'OPENING'),
                          ('SELL_TO_OPEN', 'put_hi', 'OPTION',
                           'OPENING')])


def test_bull_put_vertical_close(
        live_client, account_hash, option_symbols):
    '''bull_put_vertical_close previews as LIMIT/VERTICAL,
    selling the long put and buying back the short, both legs
    CLOSING.'''
    data = _preview(live_client, account_hash,
                    options.bull_put_vertical_close(
                        option_symbols['put_lo'],
                        option_symbols['put_hi'], 2, '1.50'))
    _check_vertical(data, option_symbols,
                    quantity=2.0, price=1.5,
                    legs=[('SELL_TO_CLOSE', 'put_lo', 'OPTION',
                           'CLOSING'),
                          ('BUY_TO_CLOSE', 'put_hi', 'OPTION',
                           'CLOSING')])


def test_bear_put_vertical_open(
        live_client, account_hash, option_symbols):
    '''bear_put_vertical_open previews as LIMIT/VERTICAL,
    selling the lower put and buying the higher for protection,
    both legs OPENING.'''
    data = _preview(live_client, account_hash,
                    options.bear_put_vertical_open(
                        option_symbols['put_lo'],
                        option_symbols['put_hi'], 2, '1.50'))
    _check_vertical(data, option_symbols,
                    quantity=2.0, price=1.5,
                    legs=[('SELL_TO_OPEN', 'put_lo', 'OPTION',
                           'OPENING'),
                          ('BUY_TO_OPEN', 'put_hi', 'OPTION',
                           'OPENING')])


def test_bear_put_vertical_close(
        live_client, account_hash, option_symbols):
    '''bear_put_vertical_close previews as LIMIT/VERTICAL,
    buying back the short put and selling the long, both legs
    CLOSING.'''
    data = _preview(live_client, account_hash,
                    options.bear_put_vertical_close(
                        option_symbols['put_lo'],
                        option_symbols['put_hi'], 2, '1.50'))
    _check_vertical(data, option_symbols,
                    quantity=2.0, price=1.5,
                    legs=[('BUY_TO_CLOSE', 'put_lo', 'OPTION',
                           'CLOSING'),
                          ('SELL_TO_CLOSE', 'put_hi', 'OPTION',
                           'CLOSING')])


################################################################################
# Builder variants on templates

@pytest.mark.parametrize('session', list(Session))
def test_variant_session(live_client, account_hash, session):
    '''set_session on a template carries through to the echo: every
    Session value round-trips into orderStrategy.session.'''
    builder = equities.equity_buy_limit(
            'AAPL', 1, '350.00').set_session(session)
    data = _preview(live_client, account_hash, builder)
    _check_single(
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
    _check_single(
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
    _check_single(
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
