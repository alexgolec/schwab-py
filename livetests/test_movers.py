import conftest
import pytest

import schwab


def _equity_market_is_open(live_client):
    return conftest.market_is_open(
            live_client, live_client.MarketHours.Market.EQUITY)


@pytest.mark.parametrize(
        'index', list(schwab.client.Client.Movers.Index))
def test_movers_market_closed(live_client, index):
    '''Out of session the movers endpoint returns an explicit empty
    result rather than stale data: HTTP 200 with screeners == [] for
    every index enum value. Skips while the equity market is open,
    where test_movers_market_open_format applies instead.'''
    if _equity_market_is_open(live_client):
        pytest.skip('equity market is open; the populated-screeners '
                    'contract is covered by '
                    'test_movers_market_open_format')

    resp = live_client.get_movers(index)
    assert resp.status_code == 200
    assert resp.json() == {'screeners': []}


def test_movers_market_open_format(live_client):
    '''During the session get_movers returns a non-empty screeners
    list whose entries carry a symbol, description, last price,
    change, direction, and volume. Skips while the market is
    closed, where test_movers_market_closed applies instead.'''
    if not _equity_market_is_open(live_client):
        pytest.skip('equity market is closed; the empty-screeners '
                    'contract is covered by test_movers_market_closed')

    M = live_client.Movers
    resp = live_client.get_movers(M.Index.SPX)
    assert resp.status_code == 200
    screeners = resp.json()['screeners']
    assert len(screeners) > 0
    for entry in screeners:
        assert isinstance(entry['symbol'], str)
        assert entry['symbol'] != ''
        assert isinstance(entry['description'], str)
        assert isinstance(entry['last'], (int, float))
        assert entry['last'] > 0
        assert isinstance(entry['change'], (int, float))
        assert entry['direction'] in ('up', 'down')
        assert isinstance(entry['totalVolume'], int)
        assert entry['totalVolume'] >= 0


def test_movers_sort_direction_matches(live_client):
    '''The sort param selects the side of the book: sorting by
    PERCENT_CHANGE_UP returns only upward movers and
    PERCENT_CHANGE_DOWN only downward ones. Open-session only.'''
    if not _equity_market_is_open(live_client):
        pytest.skip('equity market is closed; movers data only '
                    'exists in session')

    M = live_client.Movers
    for sort_order, direction in [
            (M.SortOrder.PERCENT_CHANGE_UP, 'up'),
            (M.SortOrder.PERCENT_CHANGE_DOWN, 'down')]:
        resp = live_client.get_movers(
                M.Index.SPX, sort_order=sort_order)
        assert resp.status_code == 200
        screeners = resp.json()['screeners']
        for entry in screeners:
            assert entry['direction'] == direction


def test_movers_sort_and_frequency_params(live_client):
    '''sort_order and frequency serialize through to the API:
    a VOLUME-sorted, zero-frequency request on SPX returns 200
    with a well-formed screeners list. Open-session only.'''
    if not _equity_market_is_open(live_client):
        pytest.skip('equity market is closed; movers data only '
                    'exists in session')

    M = live_client.Movers
    resp = live_client.get_movers(
            M.Index.SPX, sort_order=M.SortOrder.VOLUME,
            frequency=M.Frequency.ZERO)
    assert resp.status_code == 200
    assert isinstance(resp.json()['screeners'], list)


def test_movers_invalid_index_client_side(live_client):
    '''A non-enum index is rejected client-side with ValueError by
    enforce_enums; the request never reaches the API, so this
    holds in any session.'''
    with pytest.raises(ValueError):
        live_client.get_movers('NOT_AN_INDEX')
