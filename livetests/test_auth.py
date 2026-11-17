import time

import pytest
from authlib.integrations.httpx_client import OAuth2Client
from authlib.oauth2.rfc6750 import InvalidTokenError

from schwab.client.synchronous import Client


def test_session_without_token_endpoint_cannot_refresh(
        live_client, schwab_credentials):
    '''Demonstrates the mechanism of
    https://github.com/alexgolec/schwab-py/issues/222

    Rebuilds the OAuth2 session exactly the way client_from_received_url
    constructed it before the fix — token, update_token, and leeway but
    no token_endpoint — around the session's live token. With the expiry
    backdated, authlib holds a valid refresh token but has no endpoint to
    send it to, so the request raises InvalidTokenError without making a
    single HTTP call.

    Then performs the same expired-token request through the real
    session client, which does have token_endpoint: it refreshes and the
    request succeeds. Note this second half fails on unfixed code when
    the session client itself came from a fresh in-process login — that
    failure is the bug, demonstrated end-to-end.'''
    session = OAuth2Client(
            schwab_credentials['api_key'],
            client_secret=schwab_credentials['app_secret'],
            token=dict(live_client.session.token),
            update_token=lambda *args, **kwargs: None,
            leeway=300)
    session.token['expires_at'] = time.time() - 3600

    client = Client(schwab_credentials['api_key'], session)
    with pytest.raises(InvalidTokenError):
        client.get_account_numbers()

    live_client.session.token['expires_at'] = time.time() - 3600
    resp = live_client.get_account_numbers()
    assert resp.status_code == 200, resp.status_code


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
