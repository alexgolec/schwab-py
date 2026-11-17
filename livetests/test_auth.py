import time

import pytest


@pytest.fixture(scope='session')
def freshly_authenticated_client(live_login):
    '''The session client, but only when it came from a fresh in-process
    login — the code path affected by the token_endpoint bug.'''
    if not live_login['fresh_login']:
        pytest.skip(
                'the session client was authenticated from a retained '
                'token file rather than a fresh in-process login, so the '
                'code path this test exercises was never run. To validate '
                'this behavior, unset RETAINED_TOKEN_PATH (environment '
                'variable or schwab-credentials.env) so the run performs '
                'a fresh browser login, then rerun.')
    return live_login['client']


def test_fresh_login_session_can_refresh_access_token(
        freshly_authenticated_client):
    '''Regression test for
    https://github.com/alexgolec/schwab-py/issues/222

    client_from_received_url constructs its OAuth2 session without
    token_endpoint, so a client created through a fresh in-process login
    (client_from_login_flow, client_from_manual_flow) cannot refresh its
    access token: once it expires, every request raises InvalidTokenError
    even though the refresh token is still valid. A client loaded from a
    token file is unaffected, which is why this only runs after a fresh
    login.

    Backdates the session token's expires_at past the client's refresh
    leeway to force the refresh path without waiting for the access
    token's natural ~30-minute expiry.'''
    client = freshly_authenticated_client
    client.session.token['expires_at'] = time.time() - 3600

    resp = client.get_account_numbers()
    assert resp.status_code == 200, resp.status_code
