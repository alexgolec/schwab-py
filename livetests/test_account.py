import schwab


def test_get_account_numbers(live_client):
    numbers = live_client.get_account_numbers()

    assert isinstance(numbers, list)
    assert len(numbers) > 0
    for entry in numbers:
        assert entry['accountNumber']
        assert entry['hashValue']


def test_get_accounts(live_client):
    accounts = live_client.get_accounts()

    assert isinstance(accounts, list)
    assert len(accounts) > 0
    for account in accounts:
        sa = account['securitiesAccount']
        assert sa['type'] in ('CASH', 'MARGIN')
        assert sa['accountNumber']


def test_get_account_by_hash(live_client):
    numbers = live_client.get_account_numbers()
    entry = numbers[0]

    account = live_client.get_account(entry['hashValue'])
    sa = account['securitiesAccount']

    assert sa['accountNumber'] == entry['accountNumber']
    assert sa['type'] in ('CASH', 'MARGIN')


def test_get_accounts_with_fields(live_client):
    accounts = live_client.get_accounts(
            fields=[schwab.client.Client.Account.Fields.POSITIONS])

    assert isinstance(accounts, list)
    assert len(accounts) > 0
    for account in accounts:
        assert 'securitiesAccount' in account
