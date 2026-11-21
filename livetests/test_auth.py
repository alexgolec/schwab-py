import json
import os
import time

import pytest
from authlib.integrations.base_client.errors import InvalidTokenError
from authlib.integrations.httpx_client import OAuth2Client

import schwab.auth
from schwab.client.synchronous import Client
from schwab.utils import TokenRevokedError


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
    # expires_at must be an int — OAuth2Token.is_expired ignores
    # non-integer values and treats them as never expiring
    session.token['expires_at'] = int(time.time() - 3600)

    client = Client(schwab_credentials['api_key'], session)
    with pytest.raises(InvalidTokenError):
        client.get_account_numbers()

    live_client.session.token['expires_at'] = int(time.time() - 3600)
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
    client.session.token['expires_at'] = int(time.time() - 3600)

    resp = client.get_account_numbers()
    assert resp.status_code == 200, resp.status_code


def test_revoke_refresh_token(live_client, schwab_credentials):
    '''DESTRUCTIVE: revokes the session client's refresh token at
    Schwab via ``client.revoke()`` (RFC 7009). Only runs when the
    environment contains ``SCHWAB_LIVE_TOKEN_REVOCATION=1`` *and*
    ``RETAINED_TOKEN_PATH`` points at the token to destroy — the
    tombstone must land in a file we can inspect.

    Afterwards the retained token file contains a secretless revoked
    marker, direct loads refuse it, and the next ``make test-live``
    run performs a fresh browser login. Every other test in the same
    run will fail with auth errors once the access token dies, so run
    this test standalone:

        SCHWAB_LIVE_TOKEN_REVOCATION=1 \\
            uv run pytest livetests/test_auth.py::test_revoke_refresh_token -sv
    '''
    if os.environ.get('SCHWAB_LIVE_TOKEN_REVOCATION') != '1':
        pytest.skip(
                'destructive test: set SCHWAB_LIVE_TOKEN_REVOCATION=1 '
                'to revoke the retained refresh token at Schwab')
    token_path = schwab_credentials['retained_token_path']
    if not token_path:
        pytest.skip(
                'this test inspects the on-disk tombstone; set '
                'RETAINED_TOKEN_PATH (environment variable or '
                'schwab-credentials.env) so the token lives in a '
                'known file')

    assert live_client.revoke() is None
    assert live_client.token_metadata.revoked
    assert live_client.token_metadata.token is None

    # The on-disk marker is secretless: no token material survives.
    with open(token_path) as f:
        stored = json.load(f)
    assert stored['revoked'] is True
    assert 'token' not in stored

    with pytest.raises(TokenRevokedError):
        schwab.auth.client_from_token_file(
                token_path, schwab_credentials['api_key'],
                schwab_credentials['app_secret'])
