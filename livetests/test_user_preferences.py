import schwab


def test_get_user_preferences(live_client):
    resp = live_client.get_user_preferences()

    assert resp.status_code == 200
    prefs = resp.json()

    accounts = prefs['accounts']
    assert isinstance(accounts, list)
    assert len(accounts) > 0
    for account in accounts:
        assert account['accountNumber']
        assert account['displayAcctId']
        assert 'primaryAccount' in account

    streamer_info = prefs['streamerInfo']
    assert isinstance(streamer_info, list)
    assert len(streamer_info) > 0
    for info in streamer_info:
        assert info['streamerSocketUrl']
        assert info['schwabClientCustomerId']
        assert info['schwabClientCorrelId']

    assert isinstance(prefs['offers'], list)


def test_user_preferences_accounts_match(live_client):
    prefs_accounts = {
            a['accountNumber']
            for a in live_client.get_user_preferences()
                    .json()['accounts']}
    numbers_accounts = {
            entry['accountNumber']
            for entry in live_client.get_account_numbers().json()}

    assert prefs_accounts == numbers_accounts
