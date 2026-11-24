import datetime

import pytest

import schwab
from schwab.orders import equities, options
from schwab.orders.common import (
        Duration, EquityInstruction, OrderStrategyType, OrderType,
        PriceLinkBasis, PriceLinkType, Session, SpecialInstruction,
        StopPriceLinkBasis, StopPriceLinkType, StopType)
from schwab.orders.generic import OrderBuilder


_S = schwab.client.Client


@pytest.fixture(scope='module')
def account_hash(live_client):
    resp = live_client.get_account_numbers()
    assert resp.status_code == 200
    return resp.json()[0]['hashValue']


@pytest.fixture(scope='module')
def option_symbols(live_client):
    '''Two calls and two puts at AAPL's first expiration at least one
    day out, pulled live so the legs never expire under the tests.

    Skips same-day (0DTE) expirations: previewOrder rejects contracts
    expiring today with 400 "Symbol is expired."'''
    resp = live_client.get_option_chain(
            'AAPL', strike_count=3)
    assert resp.status_code == 200
    chain = resp.json()
    expiry = next(e for e in sorted(chain['callExpDateMap'])
                  if int(e.rsplit(':', 1)[1]) >= 1)
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


@pytest.mark.parametrize('duration', [
        Duration.IMMEDIATE_OR_CANCEL, Duration.END_OF_WEEK,
        Duration.END_OF_MONTH, Duration.NEXT_END_OF_MONTH])
def test_rejected_durations(live_client, account_hash, duration):
    '''Four Duration values are rejected at validation with HTTP 400
    ``Invalid value '<NAME>'``. Probed identically across equity,
    single-leg option, multi-leg option, and stop orders — the
    rejection is universal, not equity-specific.'''
    builder = equities.equity_buy_limit(
            'AAPL', 1, '350.00').set_duration(duration)
    resp = live_client.preview_order(account_hash, builder)
    assert resp.status_code == 400, resp.text[:300]
    assert "Invalid value '{}'".format(duration.value) in resp.text


def test_fok_rejected_on_stop_order(live_client, account_hash):
    '''FILL_OR_KILL is accepted on LIMIT orders but produces a
    structured validation reject on STOP orders — a narrower
    acceptance than the docstring implies.'''
    builder = (OrderBuilder()
            .set_order_type(OrderType.STOP)
            .set_stop_price('350.00')
            .set_session(Session.NORMAL)
            .set_duration(Duration.FILL_OR_KILL)
            .set_order_strategy_type(OrderStrategyType.SINGLE)
            .add_equity_leg(EquityInstruction.SELL, 'AAPL', 1))
    data = _preview(live_client, account_hash, builder)
    rejects = [r['activityMessage'] for r in
               data['orderValidationResult'].get('rejects', [])]
    assert 'Fill-or-kill (FOK) orders are not available for this ' \
            'order type.' in rejects


################################################################################
# cancelTime

def test_cancel_time_accepted_not_echoed(live_client, account_hash):
    '''cancelTime on a GTC order validates cleanly but is NOT echoed
    back in orderStrategy — the preview response gives no way to
    confirm the value round-tripped.'''
    cancel = (datetime.datetime.now(datetime.timezone.utc)
            + datetime.timedelta(days=90))
    builder = (equities.equity_buy_limit('AAPL', 1, '350.00')
            .set_duration(Duration.GOOD_TILL_CANCEL)
            .set_cancel_time(cancel))
    data = _preview(live_client, account_hash, builder)
    strategy = data['orderStrategy']
    assert strategy['duration'] == 'GOOD_TILL_CANCEL'
    assert 'cancelTime' not in strategy


def test_cancel_time_ignored_on_non_gtc(live_client, account_hash):
    '''cancelTime on a DAY order is silently dropped — no error, no
    echo. The builder sets it unconditionally and lets the API sort
    it out.'''
    cancel = (datetime.datetime.now(datetime.timezone.utc)
            + datetime.timedelta(days=30))
    builder = (equities.equity_buy_limit('AAPL', 1, '350.00')
            .set_duration(Duration.DAY)
            .set_cancel_time(cancel))
    data = _preview(live_client, account_hash, builder)
    strategy = data['orderStrategy']
    assert strategy['duration'] == 'DAY'
    assert 'cancelTime' not in strategy


def test_cancel_time_beyond_six_months_rejected(
        live_client, account_hash):
    '''Schwab enforces the six-month GTC window documented on
    Duration.GOOD_TILL_CANCEL.'''
    cancel = (datetime.datetime.now(datetime.timezone.utc)
            + datetime.timedelta(days=200))
    builder = (equities.equity_buy_limit('AAPL', 1, '350.00')
            .set_duration(Duration.GOOD_TILL_CANCEL)
            .set_cancel_time(cancel))
    resp = live_client.preview_order(account_hash, builder)
    assert resp.status_code == 400, resp.text[:300]
    assert 'Cancel time must be within next six months' in resp.text


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


################################################################################
# Price value handling — discoveries from probing the preview endpoint
#
# These tests pin observed Schwab behavior for the price and stopPrice
# fields. copy_price/copy_stop_price are used deliberately: they bypass
# the builder's validation so we can observe the API's own handling.
# NOTE: several tests enshrine behavior we do NOT endorse (e.g. silent
# sign stripping); if Schwab changes it, the failure is the signal.

def _preview_price(live_client, account_hash, price):
    '''Sends an equity_buy_limit with the given raw price string via
    copy_price (bypassing builder validation) and returns the
    response.'''
    builder = equities.equity_buy_limit('AAPL', 1, '1.00')
    builder.copy_price(price)
    return live_client.preview_order(account_hash, builder)


def test_price_format_normalization(live_client, account_hash):
    '''Schwab's price parser is liberal: whitespace, leading +,
    leading zeros, trailing zeros, and scientific notation are all
    accepted and normalized to a JSON number in the echo.'''
    for raw, expected in (
            ('350.00', 350.0), ('350', 350.0), ('350.0', 350.0),
            ('350.00000', 350.0), (' 350.00 ', 350.0),
            ('+350.00', 350.0), ('0350.00', 350.0), ('1e3', 1000.0)):
        resp = _preview_price(live_client, account_hash, raw)
        assert resp.status_code == 200, (raw, resp.text[:200])
        assert resp.json()['orderStrategy']['price'] == expected, raw


def test_price_invalid_strings_rejected(live_client, account_hash):
    '''Non-numeric strings are rejected outright with HTTP 400 —
    confirming that pass-through-unvalidated strings are handled by
    Schwab, not silently accepted.'''
    for raw in ('abc', '$350.00', '350,00', '--350.00'):
        resp = _preview_price(live_client, account_hash, raw)
        assert resp.status_code == 400, (raw, resp.status_code)
        assert 'Invalid value' in resp.json()['message']


def test_price_non_finite_rejected(live_client, account_hash):
    '''Schwab rejects non-finite prices with HTTP 400, matching the
    builder's own earlier ValueError — the two layers agree.'''
    for raw in ('nan', 'inf'):
        resp = _preview_price(live_client, account_hash, raw)
        assert resp.status_code == 400, (raw, resp.status_code)


def test_price_precision_rule_flagged(live_client, account_hash):
    '''Prices with more than two decimals above $1 (or four below)
    still echo but carry Schwab's own validation message stating the
    rule.'''
    for raw in ('350.999', '350.005', '0.00001'):
        resp = _preview_price(live_client, account_hash, raw)
        assert resp.status_code == 200, (raw, resp.text[:200])
        messages = ' '.join(
                x['activityMessage'] for x in
                resp.json()['orderValidationResult'].get('rejects', []))
        assert 'no more than two decimals' in messages, (raw, messages)


def test_negative_price_silently_stripped(live_client, account_hash):
    '''DOCUMENTING, NOT ENDORSING: Schwab silently strips the sign from
    the price field — '-350.00' echoes as 350.0 with no error. This is
    why the builder now refuses negative price strings with
    ValueError. If this test fails, Schwab changed the behavior —
    investigate before updating.'''
    resp = _preview_price(live_client, account_hash, '-350.00')
    assert resp.status_code == 200, resp.text[:200]
    assert resp.json()['orderStrategy']['price'] == 350.0


def test_negative_net_debit_silently_stripped(
        live_client, account_hash, option_symbols):
    '''DOCUMENTING, NOT ENDORSING: the sign strip applies to vertical
    net_debit too, where negative semantically means credit —
    '-1.50' echoes as a 1.5 debit, inverting the order.'''
    builder = options.bull_call_vertical_open(
            option_symbols['call_lo'], option_symbols['call_hi'],
            1, '1.00')
    builder.copy_price('-1.50')
    resp = live_client.preview_order(account_hash, builder)
    assert resp.status_code == 200, resp.text[:200]
    assert resp.json()['orderStrategy']['price'] == 1.5


def test_stop_price_echo_absent(live_client, account_hash):
    '''stopPrice does not surface anywhere in the preview echo; the
    orderValue derived from it is the observable. '-350.00' and
    '350.00' both derive orderValue 350.0, confirming the sign strip
    applies to stopPrice as well.'''
    for raw in ('-350.00', '350.00'):
        builder = (equities.equity_buy_market('AAPL', 1)
                .set_order_type(OrderType.STOP)
                .copy_stop_price(raw))
        resp = live_client.preview_order(account_hash, builder)
        assert resp.status_code == 200, resp.text[:200]
        strategy = resp.json()['orderStrategy']
        assert 'stopPrice' not in strategy
        assert strategy['orderValue'] == 350.0, raw


def _trailing_stop(builder_fn, basis, offset):
    return (builder_fn('AAPL', 1)
            .set_order_type(OrderType.TRAILING_STOP)
            .set_stop_type(StopType.STANDARD)
            .set_stop_price_link_type(StopPriceLinkType.VALUE)
            .set_stop_price_link_basis(basis)
            .set_stop_price_offset(offset))


def test_trailing_stop_offset_sign_rule(live_client, account_hash):
    '''stopPriceOffset is validated directionally, NOT stripped: SELL
    trailing stops require a positive offset, while BUY stops accept
    negative values. Confirms price/stopPrice are the only numeric
    fields where the sign is silently discarded. Also enshrines that
    previewable trailing stops require stopType and a valid
    stopPriceLinkBasis — without them the endpoint returns 500.'''
    for off in (-5.0, 0.0):
        resp = live_client.preview_order(account_hash, _trailing_stop(
            equities.equity_sell_market, StopPriceLinkBasis.BID, off))
        assert resp.status_code == 400, (off, resp.status_code)
        assert 'stopPriceOffset' in resp.text

    resp = live_client.preview_order(account_hash, _trailing_stop(
        equities.equity_sell_market, StopPriceLinkBasis.BID, 5.0))
    assert resp.status_code == 200, resp.text[:200]

    resp = live_client.preview_order(account_hash, _trailing_stop(
        equities.equity_buy_market, StopPriceLinkBasis.ASK, -5.0))
    assert resp.status_code == 200, resp.text[:200]


################################################################################
# priceOffset / priceLinkBasis / priceLinkType — limit-price derivation
#
# TRAILING_STOP_LIMIT derives its limit price from a market feed via the
# priceLink trio, paralleling how the stopPrice trio derives the trigger.
# These tests enshrine the field's contract, probed directly since the
# builder's set_price_offset is a thin pass-through.

def _tsl_sell(link_basis=None, link_type=None, offset='UNSET', price=None):
    '''A minimal TRAILING_STOP_LIMIT sell with parametric price-link
    fields. ``offset`` is injected directly to match what
    ``builder._priceOffset`` produces; ``'UNSET'`` omits it.'''
    builder = (equities.equity_sell_market('AAPL', 1)
            .set_order_type(OrderType.TRAILING_STOP_LIMIT)
            .set_stop_type(StopType.STANDARD)
            .set_stop_price_link_basis(StopPriceLinkBasis.BID)
            .set_stop_price_link_type(StopPriceLinkType.VALUE)
            .set_stop_price_offset(5.0))
    if link_basis is not None:
        builder.set_price_link_basis(link_basis)
    if link_type is not None:
        builder.set_price_link_type(link_type)
    if offset != 'UNSET':
        builder._priceOffset = offset
    if price is not None:
        builder.copy_price(price)
    return builder


def test_fixed_price_requires_a_basis(live_client, account_hash):
    '''A fixed price alone is not a valid limit for a TSL order — the
    API demands a priceLinkBasis to say how the limit derives, and the
    error names the field.'''
    resp = live_client.preview_order(
            account_hash, _tsl_sell(price='300.00'))
    assert resp.status_code == 400
    assert 'Price link basis must be populated for trailing ' \
            'stop limit orders' in resp.text


def test_no_basis_no_price_is_generic_limit_error(live_client,
                                                  account_hash):
    '''With neither a basis nor a price the API checks the derived
    limit first: both a bare TSL and link fields without a basis hit
    the generic 'limit price cannot be zero' rejection instead of the
    basis-specific error.'''
    for builder in (
            _tsl_sell(),
            _tsl_sell(link_type=PriceLinkType.VALUE, offset=0.10)):
        resp = live_client.preview_order(account_hash, builder)
        assert resp.status_code == 400
        assert 'Limit price cannot be zero' in resp.text


def test_market_data_bases_accepted(live_client, account_hash):
    '''Every market-data basis derives the limit price: the trio of
    basis + type + offset yields a 200. Note the echo strips all three
    link fields — orderStrategy reports them as null.'''
    for basis in (PriceLinkBasis.LAST, PriceLinkBasis.BID,
                  PriceLinkBasis.ASK, PriceLinkBasis.ASK_BID,
                  PriceLinkBasis.MARK, PriceLinkBasis.AVERAGE):
        resp = live_client.preview_order(account_hash, _tsl_sell(
                link_basis=basis, link_type=PriceLinkType.VALUE,
                offset=0.10))
        assert resp.status_code == 200, (basis, resp.text[:200])
        strategy = resp.json()['orderStrategy']
        for field in ('priceOffset', 'priceLinkBasis', 'priceLinkType'):
            assert strategy.get(field) is None


def test_trigger_basis_is_child_only(live_client, account_hash):
    '''TRIGGER is not usable on a standalone order — the API reserves
    it for child orders of trigger strategies.'''
    resp = live_client.preview_order(account_hash, _tsl_sell(
            link_basis=PriceLinkBasis.TRIGGER,
            link_type=PriceLinkType.VALUE, offset=0.10))
    assert resp.status_code == 400
    assert 'Price link trigger only allowed on children of ' \
            'trigger orders' in resp.text


def test_manual_is_the_fixed_price_path(live_client, account_hash):
    '''basis=MANUAL switches the order to a fixed limit price: with a
    price the order previews (price echoed), and link type/offset are
    then *rejected* as misplaced fields.'''
    resp = live_client.preview_order(account_hash, _tsl_sell(
            link_basis=PriceLinkBasis.MANUAL, price='300.00'))
    assert resp.status_code == 200, resp.text[:200]
    strategy = resp.json()['orderStrategy']
    assert strategy['price'] == 300.0

    # MANUAL + link type or offset: treated as non-link order, fields
    # rejected outright
    resp = live_client.preview_order(account_hash, _tsl_sell(
            link_basis=PriceLinkBasis.MANUAL,
            link_type=PriceLinkType.VALUE, price='300.00'))
    assert resp.status_code == 400
    assert 'Price link type must be populated only' in resp.text

    resp = live_client.preview_order(account_hash, _tsl_sell(
            link_basis=PriceLinkBasis.MANUAL, price='300.00',
            offset=0.10))
    assert resp.status_code == 400
    assert 'Price offset must be populated only' in resp.text


def test_base_behaves_like_no_basis(live_client, account_hash):
    '''basis=BASE does not derive a limit price — the order falls
    through to the generic 'limit price cannot be zero' rejection,
    same as supplying no basis at all.'''
    resp = live_client.preview_order(account_hash, _tsl_sell(
            link_basis=PriceLinkBasis.BASE,
            link_type=PriceLinkType.VALUE, offset=0.10))
    assert resp.status_code == 400
    assert 'Limit price cannot be zero' in resp.text


def test_link_trio_is_all_or_nothing(live_client, account_hash):
    '''With a non-MANUAL basis, type and offset are independently
    required — each missing field is named in its own error.'''
    resp = live_client.preview_order(account_hash, _tsl_sell(
            link_basis=PriceLinkBasis.LAST,
            link_type=PriceLinkType.VALUE))
    assert resp.status_code == 400
    assert 'Price offset must be populated' in resp.text

    resp = live_client.preview_order(account_hash, _tsl_sell(
            link_basis=PriceLinkBasis.LAST, offset=0.10))
    assert resp.status_code == 400
    assert 'Price link type must be populated' in resp.text


def test_price_offset_types_and_sign(live_client, account_hash):
    '''The offset accepts floats, ints, numeric strings, and zero —
    and unlike stopPriceOffset there is no directional sign check on
    either side. Non-numeric values are rejected.'''
    for offset in (0.10, -0.10, 0.0, 2, '0.10'):
        resp = live_client.preview_order(account_hash, _tsl_sell(
                link_basis=PriceLinkBasis.LAST,
                link_type=PriceLinkType.VALUE, offset=offset))
        assert resp.status_code == 200, (offset, resp.text[:200])

    for offset in ('abc', 'nan'):
        resp = live_client.preview_order(account_hash, _tsl_sell(
                link_basis=PriceLinkBasis.LAST,
                link_type=PriceLinkType.VALUE, offset=offset))
        assert resp.status_code == 400, offset
        assert 'Invalid value' in resp.text


def test_price_link_fields_rejected_on_other_order_types(
        live_client, account_hash):
    '''priceOffset, priceLinkBasis and priceLinkType are all rejected
    on MARKET, LIMIT and TRAILING_STOP orders — despite an error
    message that claims stop-limit and limit-on-close orders accept
    them. STOP_LIMIT rejects them too.'''
    specs = []

    b = equities.equity_sell_market('AAPL', 1)
    b._priceOffset = 0.10
    specs.append(b)

    b = equities.equity_sell_limit('AAPL', 1, '400.00')
    b._priceOffset = 0.10
    specs.append(b)

    b = (equities.equity_sell_market('AAPL', 1)
            .set_order_type(OrderType.TRAILING_STOP)
            .set_stop_type(StopType.STANDARD)
            .set_stop_price_link_basis(StopPriceLinkBasis.BID)
            .set_stop_price_link_type(StopPriceLinkType.VALUE)
            .set_stop_price_offset(5.0))
    b._priceOffset = 0.10
    specs.append(b)

    for builder in specs:
        resp = live_client.preview_order(account_hash, builder)
        assert resp.status_code == 400
        assert 'Price offset must be populated only' in resp.text

    # The message names "stop limit or trailing stop limit" as valid
    # recipients, but STOP_LIMIT rejects the link fields anyway.
    b = (equities.equity_sell_limit('AAPL', 1, '300.00')
            .set_order_type(OrderType.STOP_LIMIT)
            .copy_stop_price('340.00')
            .set_price_link_basis(PriceLinkBasis.LAST)
            .set_price_link_type(PriceLinkType.VALUE))
    b._priceOffset = 0.10
    resp = live_client.preview_order(account_hash, b)
    assert resp.status_code == 400
    assert 'Price link type must be populated only' in resp.text


def test_price_offset_buy_side_matrix(live_client, account_hash):
    '''The buy side accepts the same link configurations, including
    PERCENT and TICK types and negative offsets — again with no
    directional sign enforcement.'''
    def buy_tsl(link_type, offset):
        b = (equities.equity_buy_market('AAPL', 1)
                .set_order_type(OrderType.TRAILING_STOP_LIMIT)
                .set_stop_type(StopType.STANDARD)
                .set_stop_price_link_basis(StopPriceLinkBasis.ASK)
                .set_stop_price_link_type(StopPriceLinkType.VALUE)
                .set_stop_price_offset(-5.0)
                .set_price_link_basis(PriceLinkBasis.LAST)
                .set_price_link_type(link_type))
        b._priceOffset = offset
        return b

    for link_type, offset in (
            (PriceLinkType.VALUE, -0.10),
            (PriceLinkType.VALUE, 0.10),
            (PriceLinkType.PERCENT, 0.5),
            (PriceLinkType.TICK, 2)):
        resp = live_client.preview_order(
                account_hash, buy_tsl(link_type, offset))
        assert resp.status_code == 200, (link_type, offset,
                                         resp.text[:200])
