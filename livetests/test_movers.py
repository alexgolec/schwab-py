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
    list whose entries carry the quote-style schema Schwab migrated
    movers to: lastPrice/netChange/netPercentChange plus volume,
    marketShare, totalVolume, and trades. The legacy fields (last,
    change, direction) are gone; asserting their absence pins the
    removal so a restoration fails loudly. Skips while the market is
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
        assert isinstance(entry['lastPrice'], (int, float))
        assert entry['lastPrice'] > 0
        assert isinstance(entry['netChange'], (int, float))
        assert isinstance(entry['netPercentChange'], (int, float))
        assert isinstance(entry['marketShare'], (int, float))
        assert isinstance(entry['volume'], int)
        assert isinstance(entry['totalVolume'], int)
        assert isinstance(entry['trades'], int)
        for gone in ('last', 'change', 'direction'):
            assert gone not in entry


def test_movers_sort_order_ignored(live_client):
    '''DOCUMENTING, NOT ENDORSING: sort_order is currently ignored —
    all four values return identical lists. If this test fails,
    Schwab restored sort semantics; investigate which values took
    effect and re-enshrine. Open-session only.'''
    if not _equity_market_is_open(live_client):
        pytest.skip('equity market is closed; movers data only '
                    'exists in session')

    M = live_client.Movers
    results = {}
    for sort_order in M.SortOrder:
        resp = live_client.get_movers(
                M.Index.SPX, sort_order=sort_order)
        assert resp.status_code == 200
        results[sort_order] = resp.json()['screeners']
    assert all(s == results[M.SortOrder.VOLUME]
               for s in results.values())


def test_movers_frequency_ignored(live_client):
    '''DOCUMENTING, NOT ENDORSING: frequency is currently ignored —
    a sixty-minute window returns the same screeners list as the
    default. If this test fails, Schwab restored frequency
    semantics; investigate and re-enshrine. Open-session only.'''
    if not _equity_market_is_open(live_client):
        pytest.skip('equity market is closed; movers data only '
                    'exists in session')

    M = live_client.Movers
    base = live_client.get_movers(
            M.Index.SPX, frequency=M.Frequency.ZERO)
    windowed = live_client.get_movers(
            M.Index.SPX, frequency=M.Frequency.SIXTY)
    assert base.status_code == 200
    assert windowed.status_code == 200
    assert base.json()['screeners'] == windowed.json()['screeners']


def test_movers_volume_ordered(live_client):
    '''With all sort parameters ignored, the current response is
    ordered by volume descending. Enshrines the effective ordering
    so an ordering change fails loudly. Open-session only.'''
    if not _equity_market_is_open(live_client):
        pytest.skip('equity market is closed; movers data only '
                    'exists in session')

    M = live_client.Movers
    resp = live_client.get_movers(M.Index.SPX)
    assert resp.status_code == 200
    volumes = [e['volume'] for e in resp.json()['screeners']]
    assert volumes == sorted(volumes, reverse=True)


def test_movers_invalid_index_client_side(live_client):
    '''A non-enum index is rejected client-side with ValueError by
    enforce_enums; the request never reaches the API, so this
    holds in any session.'''
    with pytest.raises(ValueError):
        live_client.get_movers('NOT_AN_INDEX')
