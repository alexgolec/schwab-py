import datetime

import pytest


def _chain(live_client, symbol):
    resp = live_client.get_option_expiration_chain(symbol)
    assert resp.status_code == 200
    return resp.json()


def _check_expiration(entry):
    '''Format contract for one expirationList entry: an ISO date,
    nonnegative day count, a known type code, and the remaining
    fields present with the right types.'''
    datetime.date.fromisoformat(entry['expirationDate'])
    assert isinstance(entry['daysToExpiration'], int)
    assert entry['daysToExpiration'] >= 0
    assert entry['expirationType'] in ('M', 'W', 'S', 'Q')
    assert isinstance(entry['settlementType'], str)
    assert entry['settlementType'] in ('P', 'A')
    assert isinstance(entry['optionRoots'], str)
    assert entry['optionRoots'] != ''
    assert isinstance(entry['standard'], bool)


@pytest.mark.parametrize('symbol', ['AAPL', 'SPY'])
def test_expiration_chain_format(live_client, symbol):
    '''An optionable symbol returns a non-empty list of well-formed
    expiration entries. The response's status field is present but
    observed null even on success — unlike get_option_chain, which
    returns 'SUCCESS' — so a non-empty expirationList is the only
    success signal this endpoint offers.'''
    data = _chain(live_client, symbol)
    assert data['status'] is None
    expirations = data['expirationList']
    assert len(expirations) > 0
    for entry in expirations:
        _check_expiration(entry)


def test_expiration_dates_sorted_and_not_past(live_client):
    '''Expiration dates are returned in strictly ascending order and
    none is earlier than today.'''
    expirations = _chain(live_client, 'AAPL')['expirationList']
    dates = [datetime.date.fromisoformat(e['expirationDate'])
             for e in expirations]
    assert dates == sorted(dates)
    for i in range(1, len(dates)):
        assert dates[i] > dates[i - 1]
    assert dates[0] >= datetime.date.today()


def test_days_to_expiration_matches_date(live_client):
    '''daysToExpiration agrees with expirationDate: each entry's
    date minus today equals its reported day count, allowing a
    one-day tolerance for the date boundary the field is computed
    against.'''
    today = datetime.date.today()
    for entry in _chain(live_client, 'AAPL')['expirationList']:
        expiry = datetime.date.fromisoformat(entry['expirationDate'])
        assert abs((expiry - today).days
                   - entry['daysToExpiration']) <= 1


def test_standard_expirations_fall_on_third_friday(live_client):
    '''Entries with expirationType 'S' are the standard monthlies:
    AAPL always has at least one, and each lands on the third
    Friday of its month — or the preceding Thursday when the
    Friday is a market holiday (e.g. 2027-06-17, Thursday, for the
    Juneteenth-observed Friday).'''
    expirations = _chain(live_client, 'AAPL')['expirationList']
    monthlies = [datetime.date.fromisoformat(e['expirationDate'])
                 for e in expirations if e['expirationType'] == 'S']
    assert len(monthlies) > 0
    for d in monthlies:
        # Third week of the month: day-of-month in [15, 21]
        assert 15 <= d.day <= 21
        # Friday, or Thursday when the Friday is a market holiday
        assert d.weekday() in (3, 4)


def test_month_end_expirations_land_on_last_day(live_client):
    '''Entries with expirationType 'M' are month-end expirations:
    each observed one lands on the last calendar day of its month
    (e.g. 2026-11-30, a Monday). Month-end expirations are not
    always listed, so this only checks dates when any appear.'''
    expirations = _chain(live_client, 'AAPL')['expirationList']
    for e in expirations:
        if e['expirationType'] != 'M':
            continue
        d = datetime.date.fromisoformat(e['expirationDate'])
        # Last calendar day of the month: adding a day rolls over
        assert (d + datetime.timedelta(days=1)).month != d.month


@pytest.mark.parametrize('symbol', ['NOT_A_SYMBOL', 'SWPPX'])
def test_expiration_chain_unsupported_symbols(live_client, symbol):
    '''Invalid or non-optionable symbols do not error: the response
    is 200 with an empty expirationList. status is null here too —
    but it is null on success as well, so the empty list is the
    only discriminator.'''
    data = _chain(live_client, symbol)
    assert data['expirationList'] == []
    assert data['status'] is None


def test_expiration_dates_usable_with_option_chain(live_client):
    '''The expiration chain enumerates dates that get_option_chain
    accepts: feeding the first entry's expirationDate back as both
    fromDate and toDate returns a callExpDateMap keyed by that
    date.'''
    expiry = datetime.date.fromisoformat(
            _chain(live_client, 'AAPL')
            ['expirationList'][0]['expirationDate'])

    resp = live_client.get_option_chain(
            'AAPL', from_date=expiry, to_date=expiry)
    assert resp.status_code == 200
    data = resp.json()
    assert data['status'] == 'SUCCESS'
    keys = list(data['callExpDateMap'].keys())
    assert len(keys) > 0
    # Keys are '<ISO-date>:<days-to-expiration>'; the date part must
    # be the expiration we asked for
    assert any(k.split(':')[0] == expiry.isoformat() for k in keys)
