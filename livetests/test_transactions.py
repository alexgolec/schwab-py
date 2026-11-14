import datetime

import pytest

import schwab


_TransactionType = schwab.client.Client.Transactions.TransactionType
_TRANSACTION_TYPES = {t.value for t in _TransactionType}


def _account_hash(live_client):
    return live_client.get_account_numbers().json()[0]['hashValue']


def test_get_transactions(live_client):
    resp = live_client.get_transactions(_account_hash(live_client))

    assert resp.status_code == 200
    transactions = resp.json()
    assert isinstance(transactions, list)
    for transaction in transactions:
        assert transaction['activityId']
        assert transaction['type'] in _TRANSACTION_TYPES
        assert transaction['accountNumber']


def test_get_transaction_by_id(live_client):
    account_hash = _account_hash(live_client)
    transactions = live_client.get_transactions(account_hash).json()
    if not transactions:
        pytest.skip(
                'no transactions returned by get_transactions — cannot '
                'exercise get_transaction by ID')

    resp = live_client.get_transaction(
            account_hash, transactions[0]['activityId'])

    assert resp.status_code == 200
    assert resp.json()['activityId'] == transactions[0]['activityId']


def test_get_transactions_date_range_as_date(live_client):
    today = datetime.date.today()
    resp = live_client.get_transactions(
            _account_hash(live_client),
            start_date=today - datetime.timedelta(days=59),
            end_date=today)

    assert resp.status_code == 200
    assert isinstance(resp.json(), list)


def test_get_transactions_date_range_as_datetime(live_client):
    now = datetime.datetime.now(datetime.timezone.utc)
    resp = live_client.get_transactions(
            _account_hash(live_client),
            start_date=now - datetime.timedelta(days=59),
            end_date=now)

    assert resp.status_code == 200
    assert isinstance(resp.json(), list)


def test_get_transactions_bare_transaction_type(live_client):
    resp = live_client.get_transactions(
            _account_hash(live_client),
            transaction_types=_TransactionType.TRADE)

    assert resp.status_code == 200
    transactions = resp.json()
    assert isinstance(transactions, list)
    for transaction in transactions:
        assert transaction['type'] == 'TRADE'


def test_get_transactions_single_transaction_type(live_client):
    resp = live_client.get_transactions(
            _account_hash(live_client),
            transaction_types=[_TransactionType.TRADE])

    assert resp.status_code == 200
    transactions = resp.json()
    assert isinstance(transactions, list)
    for transaction in transactions:
        assert transaction['type'] == 'TRADE'


def test_get_transactions_multiple_transaction_types(live_client):
    requested = {'TRADE', 'CASH_RECEIPT'}
    resp = live_client.get_transactions(
            _account_hash(live_client),
            transaction_types=[
                _TransactionType.TRADE, _TransactionType.CASH_RECEIPT])

    assert resp.status_code == 200
    transactions = resp.json()
    assert isinstance(transactions, list)
    for transaction in transactions:
        assert transaction['type'] in requested


def test_get_transactions_symbol_filter(live_client):
    resp = live_client.get_transactions(
            _account_hash(live_client), symbol='AAPL')

    assert resp.status_code == 200
    assert isinstance(resp.json(), list)


def test_get_transactions_max_span_boundary(live_client):
    now = datetime.datetime.now(datetime.timezone.utc)
    resp = live_client.get_transactions(
            _account_hash(live_client),
            start_date=now - datetime.timedelta(days=365),
            end_date=now)

    assert resp.status_code == 200
    assert isinstance(resp.json(), list)


def test_get_transactions_span_too_wide(live_client):
    now = datetime.datetime.now(datetime.timezone.utc)
    resp = live_client.get_transactions(
            _account_hash(live_client),
            start_date=now - datetime.timedelta(days=366),
            end_date=now)

    assert resp.status_code == 400
    assert 'more than a year' in resp.json()['message']


def test_get_transactions_old_window_accepted(live_client):
    now = datetime.datetime.now(datetime.timezone.utc)
    resp = live_client.get_transactions(
            _account_hash(live_client),
            start_date=now - datetime.timedelta(days=400),
            end_date=now - datetime.timedelta(days=40))

    assert resp.status_code == 200
    assert isinstance(resp.json(), list)


def test_get_transactions_inverted_range(live_client):
    now = datetime.datetime.now(datetime.timezone.utc)
    resp = live_client.get_transactions(
            _account_hash(live_client),
            start_date=now,
            end_date=now - datetime.timedelta(days=30))

    assert resp.status_code == 400
    assert 'startDate must not be after endDate' in resp.json()['message']


def test_get_transactions_future_end_date(live_client):
    now = datetime.datetime.now(datetime.timezone.utc)
    resp = live_client.get_transactions(
            _account_hash(live_client),
            start_date=now - datetime.timedelta(days=30),
            end_date=now + datetime.timedelta(days=10))

    assert resp.status_code == 200
    assert isinstance(resp.json(), list)
