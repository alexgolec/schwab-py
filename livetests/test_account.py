import schwab


def test_get_account_numbers(live_client):
    resp = live_client.get_account_numbers()

    assert resp.status_code == 200
    numbers = resp.json()
    assert isinstance(numbers, list)
    assert len(numbers) > 0
    for entry in numbers:
        assert entry['accountNumber']
        assert entry['hashValue']


def test_get_accounts(live_client):
    resp = live_client.get_accounts()

    assert resp.status_code == 200
    accounts = resp.json()
    assert isinstance(accounts, list)
    assert len(accounts) > 0
    for account in accounts:
        sa = account['securitiesAccount']
        assert sa['type'] in ('CASH', 'MARGIN')
        assert sa['accountNumber']


def test_get_account_by_hash(live_client):
    numbers = live_client.get_account_numbers().json()
    entry = numbers[0]

    resp = live_client.get_account(entry['hashValue'])

    assert resp.status_code == 200
    sa = resp.json()['securitiesAccount']
    assert sa['accountNumber'] == entry['accountNumber']
    assert sa['type'] in ('CASH', 'MARGIN')


def test_get_accounts_with_fields(live_client):
    resp = live_client.get_accounts(
            fields=[schwab.client.Client.Account.Fields.POSITIONS])

    assert resp.status_code == 200
    accounts = resp.json()
    assert isinstance(accounts, list)
    assert len(accounts) > 0
    for account in accounts:
        assert 'securitiesAccount' in account
