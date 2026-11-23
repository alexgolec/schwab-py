'''Live tests for schwab.streaming.StreamClient.

Most of the market-data tests enshrine the wire behavior observed
while the relevant market is closed: subscription handshake
semantics, snapshot shapes, and which services do and do not send
data on a closed book. Tests gated on market status skip when that
market is open; protocol-level tests (login/logout, error paths,
heartbeats) run unconditionally. The NEWS_HEADLINE section is the
exception: news is not session-dependent, so most of its tests run
in either state and one is gated on the equity market being open.

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


def _skip_if_closed(live_client, market, name):
    '''Skips the calling test when the named market is closed: used
    by the news-headline live-stream enshrinement, which needs the
    headline feed to be actively publishing.'''
    if not conftest.market_is_open(live_client, market):
        pytest.skip(f'{name} market is closed; this test enshrines '
                    'open-market streaming behavior')


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


################################################################################
# News headlines
#
# NEWS_HEADLINE follows the field map TDA documented for its service of
# the same name, verified against the live stream; Schwab dropped TDA's
# Error Code field (shifting the rest down one position) and added
# STORY_TEXT and LANGUAGE. TDA's sister services NEWS_HEADLINELIST and
# NEWS_STORY are still recognized but report code 11 'not available';
# an unrecognized name returns code 21 and the server closes the
# socket. Unlike the market-data services it is not session-dependent:
# subscribing replays a snapshot of recent headlines for each key
# regardless of market state.

_NHF = StreamClient.NewsHeadlineFields


def test_news_headline_snapshot_replay(
        live_client, stream_client, stream_loop):
    '''NEWS_HEADLINE SUBS replays a snapshot of recent headlines for
    each key — items days old arrive immediately, before any live
    updates. All data, replayed and live, arrives under command
    'SUBS'. The relabeled item carries the symbol as 'key', a
    per-key 'seq' counter of the rolling buffer, and the
    TDA-documented field set. Stories are delivered once per related
    subscribed key and may also repeat on the same key — identical
    HEADLINE_ID, distinct seq.'''
    captured, handler = _capture()
    stream_client.add_news_headline_handler(handler)
    try:
        stream_loop.run_until_complete(
                stream_client.news_headline_subs(['AAPL']))
        msg = stream_loop.run_until_complete(
                _drive(stream_client, captured))
        assert msg is not None, 'no headline replay within timeout'
        assert msg['service'] == 'NEWS_HEADLINE'
        assert msg['command'] == 'SUBS'
        item = _item(msg)
        assert item['key'] == 'AAPL'
        assert isinstance(item['seq'], int)
        assert item['STORY_DATETIME'] > 0
        assert item['HEADLINE_ID']
        assert item['STATUS'] in ('A', 'D')
        assert item['HEADLINE']
        assert item['STORY_ID'] == item['HEADLINE_ID']
        assert isinstance(item['KEYWORD_ARRAY'], list)
        assert isinstance(item['RELATED_SYMBOLS'], list)
        assert isinstance(item['IS_HOT'], bool)
        assert item['STORY_SOURCE']
        assert 'STORY_TEXT' in item
    finally:
        stream_loop.run_until_complete(
                stream_client.news_headline_unsubs(['AAPL']))


def test_news_headline_fields_required(
        live_client, stream_client, stream_loop):
    '''A NEWS_HEADLINE SUBS with no fields parameter is rejected
    with code 22 'SUBS command failed' — unlike other services the
    field list is mandatory.'''
    with pytest.raises(UnexpectedResponseCode) as exc_info:
        stream_loop.run_until_complete(
                stream_client._service_op(
                        ['AAPL'], 'NEWS_HEADLINE', 'SUBS'))
    resp = exc_info.value.response
    assert resp['response'][0]['content']['code'] == 22


def test_news_headline_field_zero_required(
        live_client, stream_client, stream_loop):
    '''A field subset that omits field 0 (the key) is rejected with
    code 22; requesting field 0 alone succeeds, so the key field is
    the mandatory element of the field list.'''
    with pytest.raises(UnexpectedResponseCode) as exc_info:
        stream_loop.run_until_complete(
                stream_client._service_op(
                        ['AAPL'], 'NEWS_HEADLINE', 'SUBS',
                        _NHF, fields=[
                                _NHF.STORY_DATETIME, _NHF.HEADLINE,
                                _NHF.STORY_SOURCE]))
    resp = exc_info.value.response
    assert resp['response'][0]['content']['code'] == 22
    try:
        stream_loop.run_until_complete(
                stream_client._service_op(
                        ['AAPL'], 'NEWS_HEADLINE', 'SUBS',
                        _NHF, fields=[_NHF.SYMBOL]))
    finally:
        stream_loop.run_until_complete(
                stream_client.news_headline_unsubs(['AAPL']))


def test_news_headline_unsubs(
        live_client, stream_client, stream_loop):
    '''UNSUBS on an active NEWS_HEADLINE subscription is acked with
    code 0 and no further headlines arrive for the key.'''
    captured, handler = _capture()
    stream_client.add_news_headline_handler(handler)
    stream_loop.run_until_complete(
            stream_client.news_headline_subs(['MSFT']))
    stream_loop.run_until_complete(
            _drive(stream_client, captured))
    stream_loop.run_until_complete(
            stream_client.news_headline_unsubs(['MSFT']))
    captured.clear()
    stream_loop.run_until_complete(_collect_silence(stream_client, 4))
    assert captured == []


def test_news_headlinelist_recognized_but_unavailable(
        live_client, stream_client, stream_loop):
    '''TDA's historical NEWS_HEADLINELIST service is still recognized
    by the gateway — a SUBS returns code 11 'Service not available or
    temporary down', distinct from the code 21 'Bad command
    formatting' that invalid service names produce.'''
    with pytest.raises(UnexpectedResponseCode) as exc_info:
        stream_loop.run_until_complete(
                stream_client._service_op(
                        ['AAPL'], 'NEWS_HEADLINELIST', 'SUBS',
                        _NHF, fields=_NHF.all_fields()))
    resp = exc_info.value.response
    content = resp['response'][0]['content']
    assert content['code'] == 11
    assert 'not available' in content['msg']


def test_news_story_recognized_but_unavailable(
        live_client, stream_client, stream_loop):
    '''TDA's NEWS_STORY service is still recognized by the gateway:
    a SUBS on a story ID returns code 11 'Service not available or
    temporary down' rather than bad-format. Story text instead
    arrives inline as NEWS_HEADLINE's STORY_TEXT field.'''
    with pytest.raises(UnexpectedResponseCode) as exc_info:
        stream_loop.run_until_complete(
                stream_client._service_op(
                        ['tag_reuters_com_2026-01-01_newsml_XXX'],
                        'NEWS_STORY', 'SUBS',
                        _NHF, fields=_NHF.all_fields()))
    resp = exc_info.value.response
    content = resp['response'][0]['content']
    assert content['code'] == 11
    assert 'not available' in content['msg']


def test_unrecognized_service_closes_socket(
        live_client, stream_client, stream_loop):
    '''A service name the gateway does not recognize is fatal to the
    session: the SUBS returns code 21 'Bad command formatting' and
    the server then closes the websocket. Re-login restores the
    shared session for later tests.'''
    global _PENDING_MSG_TASK
    if _PENDING_MSG_TASK is not None:
        # A stashed handle_message task dies with the socket; drop it
        # so the next _pump_once doesn't re-raise the stale close.
        _PENDING_MSG_TASK.cancel()
        _PENDING_MSG_TASK = None
    with pytest.raises(UnexpectedResponseCode) as exc_info:
        stream_loop.run_until_complete(
                stream_client._service_op(
                        ['AAPL'], 'NOT_A_SERVICE', 'SUBS',
                        _NHF, fields=_NHF.all_fields()))
    resp = exc_info.value.response
    assert resp['response'][0]['content']['code'] == 21

    async def _await_close():
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline:
            await asyncio.wait_for(
                    stream_client._receive(),
                    deadline - time.monotonic())
    with pytest.raises(websockets.exceptions.ConnectionClosed):
        stream_loop.run_until_complete(_await_close())
    stream_loop.run_until_complete(stream_client.login())


def test_news_headline_live_items_market_open(
        live_client, stream_client, stream_loop):
    '''While the equity market is open the feed actively publishes:
    within a broad basket of symbols at least one headline arrives
    whose STORY_DATETIME is at or after the subscription, mixed in
    with older replay items under the same command 'SUBS'.'''
    _skip_if_closed(live_client, _Market.EQUITY, 'equity')
    basket = ['AAPL', 'MSFT', 'TSLA', 'SPY', 'QQQ', 'NVDA', 'AMD',
              'META', 'JPM', 'WMT']
    captured, handler = _capture()
    stream_client.add_news_headline_handler(handler)
    try:
        stream_loop.run_until_complete(
                stream_client.news_headline_subs(basket))
        deadline = time.monotonic() + 90
        sub_time_ms = int(time.time() * 1000)
        fresh = None
        while fresh is None and time.monotonic() < deadline:
            if not stream_loop.run_until_complete(
                    _pump_once(stream_client, deadline)):
                break
            for msg in captured:
                for item in msg.get('content', []):
                    # Allow ~10min of feed-side timestamp slack;
                    # observed live items post within seconds.
                    if item.get('STORY_DATETIME', 0) >= \
                            sub_time_ms - 600000:
                        fresh = item
                        break
                if fresh is not None:
                    break
        assert fresh is not None, \
                'no live headline within 90s on an open market'
        assert fresh['key'] in basket
        assert fresh['STATUS'] in ('A', 'D')
    finally:
        stream_loop.run_until_complete(
                stream_client.news_headline_unsubs(basket))


################################################################################
# Dead services
#
# TDA documented a wider constellation of streams than it ever
# shipped, and Schwab carries even fewer. Probing classifies every
# dead service into two failure modes, distinguished by whether the
# gateway still routes the service name:
#
#  - Recognized names reject with code 11 'Service not available or
#    temporary down' and the socket stays open.
#  - A smaller set of recognized names reject with code 21 'Bad
#    command formatting' — their commands were never implemented —
#    and the server may then close the socket.
#
# Truly unrecognized names also get code 21 with a socket close
# (enshrined in test_unrecognized_service_closes_socket above). These
# enshrinements will flag any service Schwab later provisions.


def _sub_dead(stream_loop, stream_client, service, keys, fields):
    '''SUBS a dead service, returning the response content dict.'''
    with pytest.raises(UnexpectedResponseCode) as exc_info:
        stream_loop.run_until_complete(
                stream_client._service_op(
                        keys, service, 'SUBS', _NHF, fields=fields))
    return exc_info.value.response['response'][0]['content']


# TDA-documented services that the gateway still routes but never
# provisioned. A key of None resolves to a live option symbol via the
# option_symbol fixture.
_DEAD_SERVICE_CODE_11 = [
    ('TIMESALE_EQUITY', 'AAPL'),
    ('TIMESALE_FUTURES', '/ES'),
    ('TIMESALE_OPTIONS', None),
    ('ACTIVES_NASDAQ', 'NASDAQ'),
    ('ACTIVES_NYSE', 'NYSE'),
    ('ACTIVES_OTCBB', 'OTCBB'),
    ('ACTIVES_OPTIONS', 'OPTIONS'),
    ('FOREX_BOOK', 'EUR/USD'),
    ('FUTURES_BOOK', '/ES'),
    ('LISTED_BOOK', 'AAPL'),
    ('CHART_OPTIONS', None),
    ('CHART_HISTORY_FUTURES', '/ES'),
]


@pytest.mark.parametrize('service,key', _DEAD_SERVICE_CODE_11,
                         ids=[svc for svc, _ in _DEAD_SERVICE_CODE_11])
def test_dead_service_code_11(
        live_client, stream_client, stream_loop, option_symbol,
        service, key):
    '''TDA-documented services the gateway routes but never
    provisioned reject SUBS with code 11 'Service not available or
    temporary down' and leave the socket alive. Covers the TIMESALE
    family that tda-api implemented, the never-shipped ACTIVES and
    extra BOOK services, and the chart-history services.'''
    content = _sub_dead(stream_loop, stream_client, service,
                        [key or option_symbol], _NHF.all_fields())
    assert content['code'] == 11, content
    assert 'not available' in content['msg']
    assert stream_client._socket.state.name == 'OPEN'


# Recognized service names whose commands were never implemented:
# code 21 'Bad command formatting'. The server may then close the
# socket — observed both killing and sparing the connection — so
# each test re-logs in to protect the shared session.
_DEAD_SERVICE_CODE_21 = [
    ('TIMESALE_FOREX', 'EUR/USD'),
    ('FUTURES_OPTIONS_BOOK', '/ES'),
    ('LEVELTWO_FUTURES', '/ES'),
]


def _relogin(stream_loop, stream_client):
    '''Restores the shared stream after a request that may have
    killed the socket: drops a stashed handle_message task so it
    can't re-raise a stale close, then re-logs in. login() is safe
    on a still-open socket too (see test_double_login).'''
    global _PENDING_MSG_TASK
    if _PENDING_MSG_TASK is not None:
        _PENDING_MSG_TASK.cancel()
        _PENDING_MSG_TASK = None
    stream_loop.run_until_complete(stream_client.login())


@pytest.mark.parametrize('service,key', _DEAD_SERVICE_CODE_21,
                         ids=[svc for svc, _ in _DEAD_SERVICE_CODE_21])
def test_dead_service_code_21(
        live_client, stream_client, stream_loop, service, key):
    '''A few recognized service names reject with code 21 'Bad
    command formatting' instead of 11 — registered in the routing
    table but their commands were never implemented. The server may
    also close the socket afterward, so the shared session is
    re-established.'''
    content = _sub_dead(stream_loop, stream_client, service,
                        [key], _NHF.all_fields())
    assert content['code'] == 21, content
    _relogin(stream_loop, stream_client)


def test_admin_qos_dead(live_client, stream_client, stream_loop):
    '''TDA's ADMIN/QOS command (quality-of-service throttling, which
    tda-api exposed as quality_of_service) is gone from the Schwab
    command table: the request rejects with code 21 'Bad command
    formatting'. The server may also close the socket afterward, so
    the shared session is re-established.'''
    request, request_id = stream_client._make_request(
            service='ADMIN', command='QOS',
            parameters={'qoslevel': '1'})
    with pytest.raises(UnexpectedResponseCode) as exc_info:
        async def _op():
            await stream_client._send({'requests': [request]})
            await stream_client._await_response(
                    request_id, 'ADMIN', 'QOS')
        stream_loop.run_until_complete(_op())
    content = exc_info.value.response['response'][0]['content']
    assert content['code'] == 21
    _relogin(stream_loop, stream_client)
