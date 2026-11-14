import schwab


def test_easy_client_login(live_client):
    '''Completing the login flow in the browser should produce a usable
    client.'''
    assert isinstance(live_client, schwab.client.Client)
