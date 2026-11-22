import os
import pathlib
import warnings

import pytest

import schwab


def pytest_collection_modifyitems(items):
    '''Runs ``@pytest.mark.run_last`` tests after all others. Destructive
    tests (e.g. token revocation, which invalidates the shared session
    credential) must not execute until every other test has finished
    with the token.'''
    last = [i for i in items if i.get_closest_marker('run_last')]
    if last:
        items[:] = [i for i in items if i not in last] + last


_CREDENTIALS_FILE = os.path.join(
        os.path.dirname(__file__), 'schwab-credentials.env')

_REQUIRED = ('SCHWAB_API_KEY', 'SCHWAB_APP_SECRET', 'SCHWAB_CALLBACK_URL')
_OPTIONAL = ('SCHWAB_BROWSER', 'SCHWAB_CALLBACK_TIMEOUT', 'RETAINED_TOKEN_PATH')


def _load_credentials():
    values = {}

    if os.path.exists(_CREDENTIALS_FILE):
        with open(_CREDENTIALS_FILE) as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith('#') or '=' not in line:
                    continue
                key, _, value = line.partition('=')
                values[key.strip()] = value.strip(' \t"\'')

    for key in _REQUIRED + _OPTIONAL:
        if os.environ.get(key):
            values[key] = os.environ[key]

    return values


@pytest.fixture(scope='session')
def schwab_credentials():
    values = _load_credentials()

    missing = [key for key in _REQUIRED if not values.get(key)]
    if missing:
        pytest.fail(
                'missing Schwab credentials ({}): copy '
                'livetests/schwab-credentials.env.template to '
                'livetests/schwab-credentials.env and fill it in, or set '
                'environment variables'.format(', '.join(missing)))

    browser = values.get('SCHWAB_BROWSER')
    return {
        'api_key': values['SCHWAB_API_KEY'],
        'app_secret': values['SCHWAB_APP_SECRET'],
        'callback_url': values['SCHWAB_CALLBACK_URL'],
        'requested_browser':
            None if browser in (None, '', 'None') else browser,
        'callback_timeout':
            float(values.get('SCHWAB_CALLBACK_TIMEOUT') or 300),
        'retained_token_path': values.get('RETAINED_TOKEN_PATH') or None,
    }


@pytest.fixture(scope='session')
def live_login(schwab_credentials, tmp_path_factory):
    '''Performs one real Schwab login for the entire test run. Requires
    interactive browser access.

    Returns a dict with 'client' (the authenticated client),
    'fresh_login' (True if a fresh in-process login flow was performed,
    False if an existing token file was loaded), and 'token_path' (the
    file backing the token).

    When the RETAINED_TOKEN_PATH environment variable (or the same key in
    schwab-credentials.env) points at a filename, the token is loaded from
    and written to that file so it can be reused across runs; it is not
    deleted at teardown. Otherwise a temporary token is used; it is
    revoked at Schwab and then deleted at teardown so no live credential
    is left behind.'''
    retained_path = schwab_credentials['retained_token_path']
    if retained_path:
        token_path = pathlib.Path(retained_path).expanduser()
        token_path.parent.mkdir(parents=True, exist_ok=True)
    else:
        token_path = tmp_path_factory.mktemp('schwab-live') / 'token.json'

    fresh_login = not token_path.exists()

    try:
        client = schwab.auth.easy_client(
                schwab_credentials['api_key'],
                schwab_credentials['app_secret'],
                schwab_credentials['callback_url'],
                str(token_path),
                callback_timeout=schwab_credentials['callback_timeout'],
                requested_browser=schwab_credentials['requested_browser'])
    except OSError as e:
        if 'stdin' in str(e):
            pytest.fail(
                    'the easy_client login flow requires interactive stdin; '
                    'rerun with -s (e.g. make test-live)')
        raise

    yield {'client': client, 'fresh_login': fresh_login,
           'token_path': str(token_path)}

    if not retained_path:
        # The token is disposable: revoke it at Schwab before deleting
        # the file so no live credential is left behind. A no-op if the
        # revocation test already ran; best-effort so teardown cannot
        # fail the suite.
        try:
            client.revoke()
        except Exception as e:
            warnings.warn(
                    'cleanup revocation of the disposable token failed; '
                    'the credential may still be live at Schwab: '
                    f'{e}')
        token_path.unlink(missing_ok=True)


@pytest.fixture(scope='session')
def live_client(live_login):
    '''The authenticated client from live_login; see that fixture for
    details on login and token retention.'''
    return live_login['client']


def market_is_open(live_client, market):
    '''Asks the market-hours API whether the given market is open.
    Fails the calling test if the status cannot be determined: an
    auth or transport failure must not silently masquerade as a
    session condition.'''
    resp = live_client.get_market_hours([market])
    if resp.status_code != 200:
        pytest.fail('could not determine market status from the '
                    f'market-hours API (status {resp.status_code})')
    products = resp.json()[market.value]
    return any(p['isOpen'] for p in products.values())
