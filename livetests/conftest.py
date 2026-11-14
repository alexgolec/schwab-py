import os
import pathlib

import pytest

import schwab


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
        pytest.skip(
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
def live_client(schwab_credentials, tmp_path_factory):
    '''Performs one real Schwab login for the entire test run. Requires
    interactive browser access.

    When the RETAINED_TOKEN_PATH environment variable (or the same key in
    schwab-credentials.env) points at a filename, the token is loaded from
    and written to that file so it can be reused across runs; it is not
    deleted at teardown. Otherwise a temporary token is used and deleted.'''
    retained_path = schwab_credentials['retained_token_path']
    if retained_path:
        token_path = pathlib.Path(retained_path).expanduser()
        token_path.parent.mkdir(parents=True, exist_ok=True)
    else:
        token_path = tmp_path_factory.mktemp('schwab-live') / 'token.json'

    client = schwab.auth.easy_client(
            schwab_credentials['api_key'],
            schwab_credentials['app_secret'],
            schwab_credentials['callback_url'],
            str(token_path),
            callback_timeout=schwab_credentials['callback_timeout'],
            requested_browser=schwab_credentials['requested_browser'])

    yield client

    if not retained_path:
        token_path.unlink(missing_ok=True)
