'''Live tests for schwab.streaming.StreamClient.

These tests enshrine the wire behavior observed while the relevant
market is closed: subscription handshake semantics, snapshot shapes,
and which services do and do not send data on a closed book. Tests
gated on market status skip when that market is open; protocol-level
tests (login/logout, error paths, heartbeats) run unconditionally.

The whole module shares one event loop and one logged-in stream:
websockets bind to the loop that opened them, so a per-test loop or
per-test login would either break the socket or multiply logins.'''
import asyncio
import time

import conftest
import pytest
import websockets

import schwab
from schwab.streaming import StreamClient, UnexpectedResponseCode


_Market = schwab.client.Client.MarketHours.Market
_L1E = StreamClient.LevelOneEquityFields

# Subscription snapshots arrive within ~100ms of the ack; data waits
# use a generous bound and silence windows comfortably cover it.
_DATA_TIMEOUT = 15
_SILENCE_WINDOW = 8


@pytest.fixture(scope='module')
def stream_loop():
    '''One event loop for the whole module: the stream's socket is
    bound to the loop that opened it.'''
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


@pytest.fixture(scope='module')
def stream_client(live_client, stream_loop):
    '''A logged-in StreamClient shared by the module.'''
    stream = StreamClient(live_client)
    stream_loop.run_until_complete(stream.login())
    yield stream
    stream_loop.run_until_complete(stream.logout())
    # Cancel the pending receive task stashed by _pump_once, if any,
    # and let orphaned close tasks from re-logins (double-login and
    # the logout test's reconnect) finish before the loop closes.
    global _PENDING_MSG_TASK
    if _PENDING_MSG_TASK is not None:
        _PENDING_MSG_TASK.cancel()
        _PENDING_MSG_TASK = None
    stream_loop.run_until_complete(asyncio.sleep(0.2))


@pytest.fixture(scope='module')
def option_symbol(live_client):
    '''A live AAPL call symbol, pulled from the option chain so it
    never expires under the tests.'''
    resp = live_client.get_option_chain('AAPL', strike_count=1)
    assert resp.status_code == 200
    expiry = sorted(resp.json()['callExpDateMap'])[0]
    strike = sorted(resp.json()['callExpDateMap'][expiry], key=float)[0]
    return resp.json()['callExpDateMap'][expiry][strike][0]['symbol']


def _capture():
    '''Returns (list, handler): a message sink and a handler function
    that appends each dispatched message to it.'''
    msgs = []
    return msgs, msgs.append


# The one handle_message() task that is currently awaiting a socket
# receive. It is NEVER cancelled: cancelling a websockets recv()
# mid-flight can silently drop the message being delivered, which
# would then never reach the dispatch path. Callers time out by
# abandoning the wait, not the task — the pending task is adopted by
# the next caller and completes whenever the next envelope arrives.
_PENDING_MSG_TASK = None


async def _pump_once(stream, deadline):
    '''Waits until `deadline` for a single envelope to be received
    and dispatched by handle_message(). Returns True if one was
    handled, False on timeout. Exceptions raised by dispatch (e.g.
    UnexpectedResponse) propagate to the caller.'''
    global _PENDING_MSG_TASK
    if _PENDING_MSG_TASK is None:
        _PENDING_MSG_TASK = asyncio.ensure_future(
                stream.handle_message())
    task = _PENDING_MSG_TASK
    await asyncio.wait({task}, timeout=deadline - time.monotonic())
    if task.done():
        _PENDING_MSG_TASK = None
        task.result()  # propagate dispatch errors
        return True
    return False


async def _drive(stream, captured, timeout=_DATA_TIMEOUT, *, count=1):
    '''Pumps envelopes until `captured` holds `count` messages or the
    timeout expires. Returns the `count`-th captured message (the one
    the caller waited for — later traffic may have appended more) or
    None.'''
    deadline = time.monotonic() + timeout
    while len(captured) < count:
        if not await _pump_once(stream, deadline):
            break
    return captured[count - 1] if len(captured) >= count else None


async def _collect_silence(stream, seconds=_SILENCE_WINDOW):
    '''Pumps envelopes for `seconds`, returning once it elapses. Used
    to prove a service sends no data: the SUBS ack has already
    returned, so any snapshot would have arrived immediately.'''
    deadline = time.monotonic() + seconds
    while await _pump_once(stream, deadline):
        pass


def _skip_if_open(live_client, market, name):
    '''Skips the calling test when the named market is open: these
    tests enshrine closed-book behavior only.'''
    if conftest.market_is_open(live_client, market):
        pytest.skip(f'{name} market is open; this test enshrines '
                    'closed-market streaming behavior')


def _item(msg):
    return msg['content'][0]


################################################################################
# Protocol and lifecycle (market-independent)


def test_heartbeat_envelope(live_client, stream_client, stream_loop):
    '''The server emits heartbeats as {"notify": [{"heartbeat":
    "<millis>"}]} envelopes roughly every ten seconds, even with no
    active subscriptions. Verified by reading raw envelopes before
    handle_message consumes them: heartbeats are swallowed by the
    dispatcher. Runs before any subscription exists, so a cancelled
    receive can drop nothing but another heartbeat.'''
    global _PENDING_MSG_TASK
    if _PENDING_MSG_TASK is not None:
        # A stashed handle_message task would race this test's raw
        # receives (concurrent recv() is forbidden). Nothing is
        # subscribed yet, so cancelling it can only lose a heartbeat.
        _PENDING_MSG_TASK.cancel()
        _PENDING_MSG_TASK = None

    async def _run():
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            msg = await asyncio.wait_for(
                    stream_client._receive(),
                    deadline - time.monotonic())
            for note in msg.get('notify', []):
                if 'heartbeat' in note:
                    return note['heartbeat']
        return None

    heartbeat = stream_loop.run_until_complete(_run())
    assert heartbeat is not None, 'no heartbeat within 30s'
    assert int(heartbeat) > 0  # epoch millis, delivered as a string


def test_double_login(live_client, stream_client, stream_loop):
    '''A second login() on an already-connected client succeeds
    silently: the server accepts a fresh ADMIN/LOGIN and the client
    rebuilds its socket without complaint.'''
    stream_loop.run_until_complete(stream_client.login())


def test_logout_closes_session(live_client, stream_client,
                               stream_loop):
    '''After logout() the server closes the socket and further
    stream operations fail: subscribing raises websockets'
    ConnectionClosed. The server-side session is keyed on the
    streamerInfo customer/correl IDs — logging out ANY client with
    this identity kills the shared session — so this test uses the
    module client and re-logs-in to restore it for later tests.'''
    stream_loop.run_until_complete(stream_client.logout())
    with pytest.raises(websockets.exceptions.ConnectionClosed):
        stream_loop.run_until_complete(
                stream_client.level_one_equity_subs(['AAPL']))
    stream_loop.run_until_complete(stream_client.login())


def test_subs_empty_symbol_list_rejected(
        live_client, stream_client, stream_loop):
    '''An empty symbol list is the one observed protocol-level
    rejection: the SUBS response carries code 22 'SUBS command
    failed', surfacing as UnexpectedResponseCode.'''
    with pytest.raises(UnexpectedResponseCode) as exc_info:
        stream_loop.run_until_complete(
                stream_client.level_one_equity_subs([]))
    resp = exc_info.value.response
    assert resp['response'][0]['content']['code'] == 22


def test_unsubs_never_subscribed_is_silent(
        live_client, stream_client, stream_loop):
    '''UNSUBS on a never-subscribed symbol is not an error: the ack
    returns code 0 and no data message follows.'''
    captured, handler = _capture()
    stream_client.add_level_one_equity_handler(handler)
    stream_loop.run_until_complete(
            stream_client.level_one_equity_unsubs(
                    ['ZZZNEVERTRADEDZZZ']))
    stream_loop.run_until_complete(_collect_silence(stream_client, 4))
    assert captured == []


def test_acct_activity_handshake(live_client, stream_client,
                                 stream_loop):
    '''ACCT_ACTIVITY SUBS produces a handshake snapshot carrying a
    per-subscription UUID key and MESSAGE_TYPE 'SUBSCRIBED'. This is
    a session-level service, not market data, so it works in any
    session state.'''
    captured, handler = _capture()
    stream_client.add_account_activity_handler(handler)
    try:
        stream_loop.run_until_complete(
                stream_client.account_activity_sub())
        msg = stream_loop.run_until_complete(
                _drive(stream_client, captured))
        assert msg is not None
        assert msg['service'] == 'ACCT_ACTIVITY'
        item = _item(msg)
        assert item['MESSAGE_TYPE'] == 'SUBSCRIBED'
        assert item['key']  # subscription UUID
    finally:
        stream_loop.run_until_complete(
                stream_client.account_activity_unsubs())


################################################################################
# Level-one equities


def test_level_one_equity_snapshot_market_closed(
        live_client, stream_client, stream_loop):
    '''On a closed book, SUBS still returns an immediate snapshot: a
    data message with command 'SUBS' whose content item echoes the
    symbol key, delayed=False, assetMainType EQUITY, and the full
    relabeled field set including the last session's bid/ask/last.'''
    _skip_if_open(live_client, _Market.EQUITY, 'equity')
    captured, handler = _capture()
    stream_client.add_level_one_equity_handler(handler)
    try:
        stream_loop.run_until_complete(
                stream_client.level_one_equity_subs(['AAPL']))
        msg = stream_loop.run_until_complete(
                _drive(stream_client, captured))
        assert msg is not None
        assert msg['service'] == 'LEVELONE_EQUITIES'
        assert msg['command'] == 'SUBS'
        item = _item(msg)
        assert item['key'] == 'AAPL'
        assert item['delayed'] is False
        assert item['assetMainType'] == 'EQUITY'
        assert item['assetSubType'] == 'COE'
        assert item['DESCRIPTION'] == 'APPLE INC'
        assert item['BID_PRICE'] > 0
        assert item['ASK_PRICE'] > 0
        assert item['LAST_PRICE'] > 0
        assert item['SECURITY_STATUS'] == 'Closed'
    finally:
        stream_loop.run_until_complete(
                stream_client.level_one_equity_unsubs(['AAPL']))


def test_level_one_equity_field_subset_market_closed(
        live_client, stream_client, stream_loop):
    '''The fields= parameter narrows the snapshot: requesting only
    BID_PRICE and ASK_PRICE yields exactly those fields plus the
    envelope metadata (key, delayed, assetMainType, cusip). SYMBOL
    is auto-appended to any subset so the key is always present.'''
    _skip_if_open(live_client, _Market.EQUITY, 'equity')
    captured, handler = _capture()
    stream_client.add_level_one_equity_handler(handler)
    try:
        stream_loop.run_until_complete(
                stream_client.level_one_equity_subs(
                        ['MSFT'], fields=[
                                _L1E.BID_PRICE, _L1E.ASK_PRICE]))
        msg = stream_loop.run_until_complete(
                _drive(stream_client, captured))
        item = _item(msg)
        assert item['key'] == 'MSFT'
        assert item['BID_PRICE'] > 0
        assert item['ASK_PRICE'] > 0
        for absent in ('LAST_PRICE', 'DESCRIPTION', 'TOTAL_VOLUME'):
            assert absent not in item
    finally:
        stream_loop.run_until_complete(
                stream_client.level_one_equity_unsubs(['MSFT']))


def test_level_one_equity_add_symbol_market_closed(
        live_client, stream_client, stream_loop):
    '''ADD extends an active subscription: after SUBS on AAPL, ADD
    on MSFT produces a second command 'SUBS' snapshot for MSFT only
    — added symbols snapshot immediately, existing ones are not
    resent.'''
    _skip_if_open(live_client, _Market.EQUITY, 'equity')
    captured, handler = _capture()
    stream_client.add_level_one_equity_handler(handler)
    try:
        stream_loop.run_until_complete(
                stream_client.level_one_equity_subs(['AAPL']))
        first = stream_loop.run_until_complete(
                _drive(stream_client, captured))
        assert _item(first)['key'] == 'AAPL'

        stream_loop.run_until_complete(
                stream_client.level_one_equity_add(['MSFT']))
        second = stream_loop.run_until_complete(
                _drive(stream_client, captured, count=2))
        assert second is not None
        assert second['command'] == 'SUBS'
        assert _item(second)['key'] == 'MSFT'
    finally:
        stream_loop.run_until_complete(
                stream_client.level_one_equity_unsubs(
                        ['AAPL', 'MSFT']))


def test_level_one_equity_multi_symbol_market_closed(
        live_client, stream_client, stream_loop):
    '''A multi-symbol SUBS snapshots every requested key: the
    content list carries one item per symbol in the same data
    message.'''
    _skip_if_open(live_client, _Market.EQUITY, 'equity')
    captured, handler = _capture()
    stream_client.add_level_one_equity_handler(handler)
    try:
        stream_loop.run_until_complete(
                stream_client.level_one_equity_subs(
                        ['AAPL', 'MSFT']))
        deadline = time.monotonic() + _DATA_TIMEOUT
        seen = set()
        while seen != {'AAPL', 'MSFT'} and time.monotonic() < deadline:
            stream_loop.run_until_complete(
                    _drive(stream_client, captured,
                           deadline - time.monotonic(),
                           count=len(captured) + 1))
            seen = {i['key'] for m in captured for i in m['content']}
        assert seen == {'AAPL', 'MSFT'}
    finally:
        stream_loop.run_until_complete(
                stream_client.level_one_equity_unsubs(
                        ['AAPL', 'MSFT']))


def test_level_one_equity_unknown_symbol_market_closed(
        live_client, stream_client, stream_loop):
    '''An unknown symbol is a data-level result, not a protocol
    error: SUBS still acks and snapshots, but the item's DESCRIPTION
    is 'Symbol not found', EXCHANGE_NAME 'unavailable', and every
    price field is zero.'''
    _skip_if_open(live_client, _Market.EQUITY, 'equity')
    captured, handler = _capture()
    stream_client.add_level_one_equity_handler(handler)
    try:
        stream_loop.run_until_complete(
                stream_client.level_one_equity_subs(
                        ['ZZZNOSUCHSYMBOLZZZ']))
        msg = stream_loop.run_until_complete(
                _drive(stream_client, captured))
        item = _item(msg)
        assert item['key'] == 'ZZZNOSUCHSYMBOLZZZ'
        assert item['DESCRIPTION'] == 'Symbol not found'
        assert item['EXCHANGE_NAME'] == 'unavailable'
        assert item['LAST_PRICE'] == 0
    finally:
        stream_loop.run_until_complete(
                stream_client.level_one_equity_unsubs(
                        ['ZZZNOSUCHSYMBOLZZZ']))


################################################################################
# Level-one options, futures, forex


def test_level_one_option_snapshot_market_closed(
        live_client, stream_client, stream_loop, option_symbol):
    '''Option subscriptions snapshot on a closed book with
    assetMainType OPTION, a human-readable DESCRIPTION ('AAPL
    MM/DD/YYYY strike C'), quote fields, and greek/volatility
    fields.'''
    _skip_if_open(live_client, _Market.OPTION, 'option')
    captured, handler = _capture()
    stream_client.add_level_one_option_handler(handler)
    try:
        stream_loop.run_until_complete(
                stream_client.level_one_option_subs([option_symbol]))
        msg = stream_loop.run_until_complete(
                _drive(stream_client, captured))
        assert msg['service'] == 'LEVELONE_OPTIONS'
        item = _item(msg)
        assert item['key'] == option_symbol
        assert item['assetMainType'] == 'OPTION'
        assert isinstance(item['DESCRIPTION'], str)
        assert 'AAPL' in item['DESCRIPTION']
        assert item['BID_PRICE'] >= 0
        assert item['ASK_PRICE'] >= 0
        assert 'VOLATILITY' in item
    finally:
        stream_loop.run_until_complete(
                stream_client.level_one_option_unsubs([option_symbol]))


def test_level_one_futures_snapshot_market_closed(
        live_client, stream_client, stream_loop):
    '''/ES subscriptions snapshot on a closed book with
    assetMainType FUTURE and a populated quote field set.'''
    _skip_if_open(live_client, _Market.FUTURE, 'future')
    captured, handler = _capture()
    stream_client.add_level_one_futures_handler(handler)
    try:
        stream_loop.run_until_complete(
                stream_client.level_one_futures_subs(['/ES']))
        msg = stream_loop.run_until_complete(
                _drive(stream_client, captured))
        assert msg['service'] == 'LEVELONE_FUTURES'
        item = _item(msg)
        assert item['key'] == '/ES'
        assert item['assetMainType'] == 'FUTURE'
        assert item['BID_PRICE'] >= 0
        assert item['ASK_PRICE'] >= 0
        assert item['LAST_PRICE'] > 0
    finally:
        stream_loop.run_until_complete(
                stream_client.level_one_futures_unsubs(['/ES']))


def test_level_one_forex_snapshot_market_closed(
        live_client, stream_client, stream_loop):
    '''EUR/USD subscriptions snapshot on a closed book with
    assetMainType FOREX and the level-one quote fields. Forex
    reopens Sunday evening, so this skips whenever that book is
    live.'''
    _skip_if_open(live_client, _Market.FOREX, 'forex')
    captured, handler = _capture()
    stream_client.add_level_one_forex_handler(handler)
    try:
        stream_loop.run_until_complete(
                stream_client.level_one_forex_subs(['EUR/USD']))
        msg = stream_loop.run_until_complete(
                _drive(stream_client, captured))
        assert msg['service'] == 'LEVELONE_FOREX'
        item = _item(msg)
        assert item['key'] == 'EUR/USD'
        assert item['assetMainType'] == 'FOREX'
        # Quote values are NOT asserted: the forex book zeroes its
        # fields as the next session approaches, so a closed-but-
        # nearly-open snapshot can carry all-zero prices.
        assert isinstance(item['BID_PRICE'], (int, float))
        assert isinstance(item['ASK_PRICE'], (int, float))
        assert isinstance(item['LAST_PRICE'], (int, float))
    finally:
        stream_loop.run_until_complete(
                stream_client.level_one_forex_unsubs(['EUR/USD']))


def test_level_one_futures_options_silent_market_closed(
        live_client, stream_client, stream_loop):
    '''LEVELONE_FUTURES_OPTIONS accepts a SUBS (code 0) but observed
    behavior on a closed book is total silence: no snapshot arrives
    even for plausible symbols, unlike every other level-one
    service.'''
    _skip_if_open(live_client, _Market.FUTURE, 'future')
    captured, handler = _capture()
    stream_client.add_level_one_futures_options_handler(handler)
    try:
        stream_loop.run_until_complete(
                stream_client.level_one_futures_options_subs(
                        ['./ESZ6 C7000']))
        stream_loop.run_until_complete(
                _collect_silence(stream_client))
        assert captured == [], \
                f'expected no snapshot, got: {captured}'
    finally:
        stream_loop.run_until_complete(
                stream_client.level_one_futures_options_unsubs(
                        ['./ESZ6 C7000']))


################################################################################
# Chart services


def test_chart_equity_snapshot_market_closed(
        live_client, stream_client, stream_loop):
    '''CHART_EQUITY SUBS snapshots the last minute bar: a content
    item with a sequence number and the relabeled OHLC/volume/time
    fields.'''
    _skip_if_open(live_client, _Market.EQUITY, 'equity')
    captured, handler = _capture()
    stream_client.add_chart_equity_handler(handler)
    try:
        stream_loop.run_until_complete(
                stream_client.chart_equity_subs(['AAPL']))
        msg = stream_loop.run_until_complete(
                _drive(stream_client, captured))
        assert msg['service'] == 'CHART_EQUITY'
        item = _item(msg)
        assert item['key'] == 'AAPL'
        assert item['SEQUENCE'] > 0
        assert item['OPEN_PRICE'] > 0
        assert item['HIGH_PRICE'] > 0
        assert item['LOW_PRICE'] > 0
        assert item['CLOSE_PRICE'] > 0
        assert item['VOLUME'] >= 0
        assert item['CHART_TIME_MILLIS'] > 0
    finally:
        stream_loop.run_until_complete(
                stream_client.chart_equity_unsubs(['AAPL']))


def test_chart_futures_snapshot_market_closed(
        live_client, stream_client, stream_loop):
    '''CHART_FUTURES /ES SUBS snapshots with the same seq + OHLC
    shape as the equity chart service.'''
    _skip_if_open(live_client, _Market.FUTURE, 'future')
    captured, handler = _capture()
    stream_client.add_chart_futures_handler(handler)
    try:
        stream_loop.run_until_complete(
                stream_client.chart_futures_subs(['/ES']))
        msg = stream_loop.run_until_complete(
                _drive(stream_client, captured))
        assert msg['service'] == 'CHART_FUTURES'
        item = _item(msg)
        assert item['key'] == '/ES'
        assert item['OPEN_PRICE'] > 0
        assert item['CLOSE_PRICE'] > 0
        assert item['CHART_TIME_MILLIS'] > 0
    finally:
        stream_loop.run_until_complete(
                stream_client.chart_futures_unsubs(['/ES']))


################################################################################
# Books


def test_nasdaq_book_empty_snapshot_market_closed(
        live_client, stream_client, stream_loop):
    '''NASDAQ_BOOK SUBS snapshots on a closed book with empty depth:
    the content item carries a book timestamp and empty BIDS and
    ASKS lists.'''
    _skip_if_open(live_client, _Market.EQUITY, 'equity')
    captured, handler = _capture()
    stream_client.add_nasdaq_book_handler(handler)
    try:
        stream_loop.run_until_complete(
                stream_client.nasdaq_book_subs(['AAPL']))
        msg = stream_loop.run_until_complete(
                _drive(stream_client, captured))
        assert msg['service'] == 'NASDAQ_BOOK'
        item = _item(msg)
        assert item['key'] == 'AAPL'
        assert item['BOOK_TIME'] > 0
        assert item['BIDS'] == []
        assert item['ASKS'] == []
    finally:
        stream_loop.run_until_complete(
                stream_client.nasdaq_book_unsubs(['AAPL']))


def test_nyse_book_silent_market_closed(
        live_client, stream_client, stream_loop):
    '''NYSE_BOOK accepts a SUBS but observed closed-book behavior is
    silence: no snapshot at all, an asymmetry with NASDAQ_BOOK
    which does snapshot empty depth.'''
    _skip_if_open(live_client, _Market.EQUITY, 'equity')
    captured, handler = _capture()
    stream_client.add_nyse_book_handler(handler)
    try:
        stream_loop.run_until_complete(
                stream_client.nyse_book_subs(['IBM']))
        stream_loop.run_until_complete(
                _collect_silence(stream_client))
        assert captured == [], \
                f'expected no snapshot, got: {captured}'
    finally:
        stream_loop.run_until_complete(
                stream_client.nyse_book_unsubs(['IBM']))


def test_options_book_silent_market_closed(
        live_client, stream_client, stream_loop, option_symbol):
    '''OPTIONS_BOOK behaves like NYSE_BOOK on a closed book: the
    SUBS ack succeeds but no snapshot follows within the window.'''
    _skip_if_open(live_client, _Market.OPTION, 'option')
    captured, handler = _capture()
    stream_client.add_options_book_handler(handler)
    try:
        stream_loop.run_until_complete(
                stream_client.options_book_subs([option_symbol]))
        stream_loop.run_until_complete(
                _collect_silence(stream_client))
        assert captured == [], \
                f'expected no snapshot, got: {captured}'
    finally:
        stream_loop.run_until_complete(
                stream_client.options_book_unsubs([option_symbol]))


################################################################################
# Screeners


def test_screener_equity_na_items_market_closed(
        live_client, stream_client, stream_loop):
    '''Screener keys are query strings PREFIX_SORTFIELD_FREQUENCY:
    '$COMPX_VOLUME_0' echoes back as the content key with
    SORT_FIELD/FREQUENCY parsed out, and the ITEMS list is present
    but every entry is 'N/A' zeroed data while the book is
    closed.'''
    _skip_if_open(live_client, _Market.EQUITY, 'equity')
    captured, handler = _capture()
    stream_client.add_screener_equity_handler(handler)
    try:
        stream_loop.run_until_complete(
                stream_client.screener_equity_subs(['$COMPX_VOLUME_0']))
        msg = stream_loop.run_until_complete(
                _drive(stream_client, captured))
        assert msg['service'] == 'SCREENER_EQUITY'
        item = _item(msg)
        assert item['key'] == '$COMPX_VOLUME_0'
        assert item['SORT_FIELD'] == 'VOLUME'
        assert item['FREQUENCY'] == 0
        assert isinstance(item['ITEMS'], list) and item['ITEMS']
        assert all(i['symbol'] == 'N/A' for i in item['ITEMS'])
    finally:
        stream_loop.run_until_complete(
                stream_client.screener_equity_unsubs(
                        ['$COMPX_VOLUME_0']))


def test_screener_option_na_items_market_closed(
        live_client, stream_client, stream_loop):
    '''SCREENER_OPTION behaves identically: 'OPTION_CALL_VOLUME_0'
    echoes the key and returns an ITEMS list of 'N/A' entries on a
    closed book.'''
    _skip_if_open(live_client, _Market.OPTION, 'option')
    captured, handler = _capture()
    stream_client.add_screener_option_handler(handler)
    try:
        stream_loop.run_until_complete(
                stream_client.screener_option_subs(
                        ['OPTION_CALL_VOLUME_0']))
        msg = stream_loop.run_until_complete(
                _drive(stream_client, captured))
        assert msg['service'] == 'SCREENER_OPTION'
        item = _item(msg)
        assert item['key'] == 'OPTION_CALL_VOLUME_0'
        assert item['SORT_FIELD'] == 'VOLUME'
        assert all(i['symbol'] == 'N/A' for i in item['ITEMS'])
    finally:
        stream_loop.run_until_complete(
                stream_client.screener_option_unsubs(
                        ['OPTION_CALL_VOLUME_0']))
