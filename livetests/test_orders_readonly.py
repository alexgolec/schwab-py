import datetime

import pytest

import schwab


_ORDER_STATUSES = {s.value for s in schwab.client.Client.Order.Status}


def _check_order_list(orders):
    assert isinstance(orders, list)
    for order in orders:
        assert order['orderId']
        assert order['status'] in _ORDER_STATUSES
        assert order['accountNumber']


def test_get_orders_for_all_linked_accounts(live_client):
    resp = live_client.get_orders_for_all_linked_accounts()

    assert resp.status_code == 200
    _check_order_list(resp.json())


def test_get_orders_for_account(live_client):
    account_hash = live_client.get_account_numbers().json()[0]['hashValue']

    resp = live_client.get_orders_for_account(account_hash)

    assert resp.status_code == 200
    _check_order_list(resp.json())


def test_get_order_by_id(live_client):
    orders = live_client.get_orders_for_all_linked_accounts().json()
    if not orders:
        pytest.skip(
                'no orders returned by get_orders_for_all_linked_accounts '
                '— cannot exercise get_order by ID')
    order = orders[0]

    mappings = {entry['accountNumber']: entry['hashValue']
                for entry in live_client.get_account_numbers().json()}
    account_hash = mappings[order['accountNumber']]

    resp = live_client.get_order(order['orderId'], account_hash)

    assert resp.status_code == 200
    assert resp.json()['orderId'] == order['orderId']


def test_get_orders_with_filters(live_client):
    now = datetime.datetime.now(datetime.timezone.utc)
    resp = live_client.get_orders_for_all_linked_accounts(
            max_results=1,
            from_entered_datetime=now - datetime.timedelta(days=59),
            to_entered_datetime=now,
            status=schwab.client.Client.Order.Status.FILLED)

    assert resp.status_code == 200
    assert isinstance(resp.json(), list)
