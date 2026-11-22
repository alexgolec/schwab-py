from schwab import auth
from schwab.client import AsyncClient, Client
from schwab.utils import TokenRevocationError, TokenRevokedError
from .utils import (
        AnyStringWith,
        AsyncMagicMock,
        MockAsyncOAuthClient,
        MockOAuthClient,
        MockResponse,
        ResyncProxy,
        no_duplicates
)
from unittest.mock import patch, ANY, MagicMock
from unittest.mock import ANY as _

import httpx2
import json
import os
import requests
import tempfile
import unittest


API_KEY = 'APIKEY'
APP_SECRET = '0x5EC07'
TOKEN_CREATION_TIMESTAMP = 1613745000
MOCK_NOW = 1613745082
CALLBACK_URL = 'https://redirect.url.com'
REVOKE_URL = 'https://api.schwabapi.com/v1/oauth/revoke'
RAW_TOKEN = {
    'access_token': 'ACCESS_TOKEN',
    'refresh_token': 'REFRESH_TOKEN',
    'token_type': 'Bearer',
    'expires_in': 1800,
}
REVOKED_TOMBSTONE = {
    'creation_timestamp': TOKEN_CREATION_TIMESTAMP,
    'revoked': True,
}


class ClientFromLoginFlowTest(unittest.TestCase):

    def setUp(self):
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.token_path = os.path.join(self.tmp_dir.name, 'token.json')
        self.raw_token = {'token': 'yes'}
        self.token = {
                'token': self.raw_token,
                'creation_timestamp': TOKEN_CREATION_TIMESTAMP
        }

    @patch('schwab.auth.Client')
    @patch('schwab.auth.OAuth2Client', new_callable=MockOAuthClient)
    @patch('schwab.auth.AsyncOAuth2Client', new_callable=MockAsyncOAuthClient)
    @patch('schwab.auth.webbrowser.get', new_callable=MagicMock)
    @patch('schwab.auth.input', MagicMock(return_value=''))
    @patch('time.time', MagicMock(return_value=MOCK_NOW))
    def test_create_token_file(
            self, mock_webbrowser_get, async_session, sync_session, client):
        AUTH_URL = 'https://auth.url.com'

        sync_session.return_value = sync_session
        sync_session.create_authorization_url.return_value = AUTH_URL, None
        sync_session.fetch_token.return_value = self.raw_token

        callback_url = 'https://127.0.0.1:6969/callback'

        controller = MagicMock()
        mock_webbrowser_get.return_value = controller
        controller.open.side_effect = \
                lambda auth_url: requests.get(
                        'https://127.0.0.1:6969/callback', verify=False)

        client.return_value = 'returned client'

        auth.client_from_login_flow(
                API_KEY, APP_SECRET, callback_url, self.token_path)

        with open(self.token_path, 'r') as f:
            self.assertEqual({
                'creation_timestamp': MOCK_NOW,
                'token': self.raw_token
            }, json.load(f))


    @patch('schwab.auth.Client')
    @patch('schwab.auth.OAuth2Client', new_callable=MockOAuthClient)
    @patch('schwab.auth.AsyncOAuth2Client', new_callable=MockAsyncOAuthClient)
    @patch('schwab.auth.webbrowser.get', new_callable=MagicMock)
    @patch('schwab.auth.input', MagicMock(return_value=''))
    @patch('time.time', MagicMock(return_value=MOCK_NOW))
    def test_specify_web_browser(
            self, mock_webbrowser_get, async_session, sync_session, client):
        AUTH_URL = 'https://auth.url.com'

        sync_session.return_value = sync_session
        sync_session.create_authorization_url.return_value = AUTH_URL, None
        sync_session.fetch_token.return_value = self.raw_token

        callback_url = 'https://127.0.0.1:6969/callback'

        controller = MagicMock()
        mock_webbrowser_get.return_value = controller
        controller.open.side_effect = \
                lambda auth_url: requests.get(
                        'https://127.0.0.1:6969/callback', verify=False)

        auth.client_from_login_flow(
                API_KEY, APP_SECRET, callback_url, self.token_path,
                requested_browser='custom-browser')

        mock_webbrowser_get.assert_called_with('custom-browser')


    @patch('schwab.auth.Client')
    @patch('schwab.auth.OAuth2Client', new_callable=MockOAuthClient)
    @patch('schwab.auth.AsyncOAuth2Client', new_callable=MockAsyncOAuthClient)
    @patch('schwab.auth.webbrowser.get', new_callable=MagicMock)
    @patch('schwab.auth.input')
    @patch('time.time', MagicMock(return_value=MOCK_NOW))
    def test_create_token_file_not_interactive(
            self, mock_prompt,mock_webbrowser_get, async_session, sync_session,
            client):
        AUTH_URL = 'https://auth.url.com'

        sync_session.return_value = sync_session
        sync_session.create_authorization_url.return_value = AUTH_URL, None
        sync_session.fetch_token.return_value = self.raw_token

        callback_url = 'https://127.0.0.1:6969/callback'

        controller = MagicMock()
        mock_webbrowser_get.return_value = controller
        controller.open.side_effect = \
               lambda auth_url: requests.get(
                        'https://127.0.0.1:6969/callback', verify=False)

        client.return_value = 'returned client'

        auth.client_from_login_flow(
                API_KEY, APP_SECRET, callback_url, self.token_path, 
                interactive=False)

        with open(self.token_path, 'r') as f:
            self.assertEqual({
                'creation_timestamp': MOCK_NOW,
                'token': self.raw_token
            }, json.load(f))

        mock_prompt.assert_not_called()


    @patch('schwab.auth.Client')
    @patch('schwab.auth.OAuth2Client', new_callable=MockOAuthClient)
    @patch('schwab.auth.AsyncOAuth2Client', new_callable=MockAsyncOAuthClient)
    @patch('schwab.auth.webbrowser.get', new_callable=MagicMock)
    @patch('schwab.auth.input', MagicMock(return_value=''))
    @patch('time.time', MagicMock(return_value=MOCK_NOW))
    def test_create_token_file_root_callback_url(
            self, mock_webbrowser_get, async_session, sync_session, client):
        AUTH_URL = 'https://auth.url.com'

        sync_session.return_value = sync_session
        sync_session.create_authorization_url.return_value = AUTH_URL, None
        sync_session.fetch_token.return_value = self.raw_token

        callback_url = 'https://127.0.0.1:6969/'

        controller = MagicMock()
        mock_webbrowser_get.return_value = controller
        controller.open.side_effect = \
               lambda auth_url: requests.get(
                        'https://127.0.0.1:6969/', verify=False)

        client.return_value = 'returned client'

        auth.client_from_login_flow(
                API_KEY, APP_SECRET, callback_url, self.token_path)

        with open(self.token_path, 'r') as f:
            self.assertEqual({
                'creation_timestamp': MOCK_NOW,
                'token': self.raw_token
            }, json.load(f))


    @patch('schwab.auth.Client')
    @patch('schwab.auth.OAuth2Client', new_callable=MockOAuthClient)
    @patch('schwab.auth.AsyncOAuth2Client', new_callable=MockAsyncOAuthClient)
    @patch('schwab.auth.webbrowser.get', new_callable=MagicMock)
    @patch('time.time', MagicMock(return_value=MOCK_NOW))
    def test_disallowed_hostname(
            self, mock_webbrowser_get, async_session, sync_session, client):
        callback_url = 'https://example.com/callback'

        with self.assertRaisesRegex(
                ValueError, 'Disallowed hostname example.com'):
            auth.client_from_login_flow(
                    API_KEY, APP_SECRET, callback_url, self.token_path)


    @patch('schwab.auth.Client')
    @patch('schwab.auth.OAuth2Client', new_callable=MockOAuthClient)
    @patch('schwab.auth.AsyncOAuth2Client', new_callable=MockAsyncOAuthClient)
    @patch('schwab.auth.webbrowser.get', new_callable=MagicMock)
    @patch('time.time', MagicMock(return_value=MOCK_NOW))
    def test_negative_timeout(
            self, mock_webbrowser_get, async_session, sync_session, client):
        callback_url = 'https://example.com/callback'

        with self.assertRaisesRegex(
                ValueError, 'callback_timeout must be positive'):
            auth.client_from_login_flow(
                    API_KEY, APP_SECRET, callback_url, self.token_path,
                    callback_timeout=-1)


    @patch('schwab.auth.Client')
    @patch('schwab.auth.OAuth2Client', new_callable=MockOAuthClient)
    @patch('schwab.auth.AsyncOAuth2Client', new_callable=MockAsyncOAuthClient)
    @patch('schwab.auth.webbrowser.get', new_callable=MagicMock)
    @patch('time.time', MagicMock(return_value=MOCK_NOW))
    def test_disallowed_hostname_with_port(
            self, mock_webbrowser_get, async_session, sync_session, client):
        callback_url = 'https://example.com:8080/callback'

        with self.assertRaisesRegex(
                ValueError, 'Disallowed hostname example.com'):
            auth.client_from_login_flow(
                    API_KEY, APP_SECRET, callback_url, self.token_path)


    @patch('schwab.auth.Client')
    @patch('schwab.auth.OAuth2Client', new_callable=MockOAuthClient)
    @patch('schwab.auth.AsyncOAuth2Client', new_callable=MockAsyncOAuthClient)
    @patch('schwab.auth.webbrowser.get', new_callable=MagicMock)
    @patch('time.time', MagicMock(return_value=MOCK_NOW))
    def test_start_on_port_443(
            self, mock_webbrowser_get, async_session, sync_session, client):
        callback_url = 'https://127.0.0.1/callback'

        with self.assertRaisesRegex(auth.RedirectServerExitedError,
                                    'callback URL without a port number'):
            auth.client_from_login_flow(
                    API_KEY, APP_SECRET, callback_url, self.token_path)


    @patch('schwab.auth.Client')
    @patch('schwab.auth.OAuth2Client', new_callable=MockOAuthClient)
    @patch('schwab.auth.AsyncOAuth2Client', new_callable=MockAsyncOAuthClient)
    @patch('schwab.auth.webbrowser.get', new_callable=MagicMock)
    @patch('schwab.auth.input', MagicMock(return_value=''))
    @patch('time.time', MagicMock(return_value=MOCK_NOW))
    def test_time_out_waiting_for_request(
            self, mock_webbrowser_get, async_session, sync_session, client):
        AUTH_URL = 'https://auth.url.com'

        sync_session.return_value = sync_session
        sync_session.create_authorization_url.return_value = AUTH_URL, None
        sync_session.fetch_token.return_value = self.raw_token

        callback_url = 'https://127.0.0.1:6969/callback'

        with self.assertRaisesRegex(auth.RedirectTimeoutError,
                                    'Timed out waiting'):
            auth.client_from_login_flow(
                    API_KEY, APP_SECRET, callback_url, self.token_path,
                    callback_timeout=0.01)


    @patch('schwab.auth.Client')
    @patch('schwab.auth.OAuth2Client', new_callable=MockOAuthClient)
    @patch('schwab.auth.AsyncOAuth2Client', new_callable=MockAsyncOAuthClient)
    @patch('schwab.auth.webbrowser.get', new_callable=MagicMock)
    @patch('schwab.auth.input', MagicMock(return_value=''))
    @patch('time.time', MagicMock(return_value=MOCK_NOW))
    def test_wait_forever_callback_timeout_equals_none(
            self, mock_webbrowser_get, async_session, sync_session, client):
        AUTH_URL = 'https://auth.url.com'

        sync_session.return_value = sync_session
        sync_session.create_authorization_url.return_value = AUTH_URL, None
        sync_session.fetch_token.return_value = self.raw_token

        callback_url = 'https://127.0.0.1:6969/callback'

        with self.assertRaisesRegex(ValueError, 'endless wait requested'):
            auth.client_from_login_flow(
                    API_KEY, APP_SECRET, callback_url, self.token_path,
                    callback_timeout=None)


    @patch('schwab.auth.Client')
    @patch('schwab.auth.OAuth2Client', new_callable=MockOAuthClient)
    @patch('schwab.auth.AsyncOAuth2Client', new_callable=MockAsyncOAuthClient)
    @patch('schwab.auth.webbrowser.get', new_callable=MagicMock)
    @patch('schwab.auth.input', MagicMock(return_value=''))
    @patch('time.time', MagicMock(return_value=MOCK_NOW))
    def test_wait_forever_callback_timeout_equals_zero(
            self, mock_webbrowser_get, async_session, sync_session, client):
        AUTH_URL = 'https://auth.url.com'

        sync_session.return_value = sync_session
        sync_session.create_authorization_url.return_value = AUTH_URL, None
        sync_session.fetch_token.return_value = self.raw_token

        callback_url = 'https://127.0.0.1:6969/callback'

        with self.assertRaisesRegex(ValueError, 'endless wait requested'):
            auth.client_from_login_flow(
                    API_KEY, APP_SECRET, callback_url, self.token_path,
                    callback_timeout=0)


class ClientFromTokenFileTest(unittest.TestCase):

    def setUp(self):
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.token_path = os.path.join(self.tmp_dir.name, 'token.json')
        self.raw_token = {'token': 'yes'}
        self.token = {
                'token': self.raw_token,
                'creation_timestamp': TOKEN_CREATION_TIMESTAMP
        }

    def write_token(self):
        with open(self.token_path, 'w') as f:
            json.dump(self.token, f)

    @no_duplicates
    def test_no_such_file(self):
        with self.assertRaises(FileNotFoundError):
            auth.client_from_token_file(self.token_path, API_KEY, APP_SECRET)

    @no_duplicates
    def test_refuses_revoked_tombstone(self):
        with open(self.token_path, 'w') as f:
            json.dump(REVOKED_TOMBSTONE, f)
        with self.assertRaises(TokenRevokedError):
            auth.client_from_token_file(self.token_path, API_KEY, APP_SECRET)

    @no_duplicates
    @patch('schwab.auth.Client')
    @patch('schwab.auth.OAuth2Client', new_callable=MockOAuthClient)
    @patch('schwab.auth.AsyncOAuth2Client', new_callable=MockAsyncOAuthClient)
    def test_json_loads(self, async_session, sync_session, client):
        self.write_token()

        client.return_value = 'returned client'

        self.assertEqual('returned client',
                         auth.client_from_token_file(
                             self.token_path, API_KEY, APP_SECRET))
        client.assert_called_once_with(API_KEY, _, token_metadata=_,
                                       enforce_enums=_, base_url=auth.DEFAULT_BASE_URL)
        sync_session.assert_called_once_with(
            API_KEY,
            client_secret=APP_SECRET,
            token=self.raw_token,
            token_endpoint=_,
            update_token=_,
            leeway=_)

    @no_duplicates
    @patch('schwab.auth.Client')
    @patch('schwab.auth.OAuth2Client', new_callable=MockOAuthClient)
    @patch('schwab.auth.AsyncOAuth2Client', new_callable=MockAsyncOAuthClient)
    def test_update_token_updates_token(
            self, async_session, sync_session, client):
        self.write_token()

        auth.client_from_token_file(self.token_path, API_KEY, APP_SECRET)
        sync_session.assert_called_once()

        session_call = sync_session.mock_calls[0]
        update_token = session_call[2]['update_token']

        updated_token = {'updated': 'token'}
        update_token(updated_token)
        with open(self.token_path, 'r') as f:
            self.assertEqual(json.load(f), {
                'token': updated_token,
                'creation_timestamp': TOKEN_CREATION_TIMESTAMP
            })

    @no_duplicates
    @patch('schwab.auth.Client')
    @patch('schwab.auth.OAuth2Client', new_callable=MockOAuthClient)
    @patch('schwab.auth.AsyncOAuth2Client', new_callable=MockAsyncOAuthClient)
    def test_enforce_enums_being_disabled(self, async_session, sync_session, client):
        self.write_token()

        client.return_value = 'returned client'

        self.assertEqual('returned client',
                         auth.client_from_token_file(
                             self.token_path, API_KEY, APP_SECRET,
                             enforce_enums=False))
        client.assert_called_once_with(API_KEY, _, token_metadata=_,
                                       enforce_enums=False, base_url=auth.DEFAULT_BASE_URL)

    @no_duplicates
    @patch('schwab.auth.Client')
    @patch('schwab.auth.OAuth2Client', new_callable=MockOAuthClient)
    @patch('schwab.auth.AsyncOAuth2Client', new_callable=MockAsyncOAuthClient)
    def test_enforce_enums_being_enabled(self, async_session, sync_session, client):
        self.write_token()

        client.return_value = 'returned client'

        self.assertEqual('returned client',
                         auth.client_from_token_file(
                             self.token_path, API_KEY, APP_SECRET))
        client.assert_called_once_with(API_KEY, _, token_metadata=_,
                                       enforce_enums=True, base_url=auth.DEFAULT_BASE_URL)

    @no_duplicates
    @patch('schwab.auth.Client')
    @patch('schwab.auth.OAuth2Client', new_callable=MockOAuthClient)
    @patch('schwab.auth.AsyncOAuth2Client', new_callable=MockAsyncOAuthClient)
    def test_custom_base_url(self, async_session, sync_session, client):
        self.write_token()

        client.return_value = 'returned client'

        self.assertEqual('returned client',
                         auth.client_from_token_file(
                             self.token_path, API_KEY, APP_SECRET,
                             base_url='https://proxy.example.com/'))
        client.assert_called_once_with(
                API_KEY, _, token_metadata=_, enforce_enums=_,
                base_url='https://proxy.example.com')
        sync_session.assert_called_once_with(
            API_KEY,
            client_secret=APP_SECRET,
            token=self.raw_token,
            token_endpoint='https://proxy.example.com/v1/oauth/token',
            update_token=_,
            leeway=_)


class ClientFromAccessFunctionsTest(unittest.TestCase):


    def setUp(self):
        self.raw_token = {'token': 'yes'}
        self.token = {
                'token': self.raw_token,
                'creation_timestamp': TOKEN_CREATION_TIMESTAMP
        }


    @no_duplicates
    @patch('schwab.auth.Client')
    @patch('schwab.auth.OAuth2Client', new_callable=MockOAuthClient)
    @patch('schwab.auth.AsyncOAuth2Client', new_callable=MockAsyncOAuthClient)
    def test_success_with_write_func(
            self, async_session, sync_session, client):
        token_read_func = MagicMock()
        token_read_func.return_value = self.token

        token_writes = []

        def token_write_func(token):
            token_writes.append(token)

        client.return_value = 'returned client'
        self.assertEqual('returned client',
                         auth.client_from_access_functions(
                             API_KEY,
                             APP_SECRET,
                             token_read_func,
                             token_write_func))

        sync_session.assert_called_once_with(
            API_KEY,
            client_secret=APP_SECRET,
            token=self.raw_token,
            token_endpoint=_,
            update_token=_,
            leeway=_)
        token_read_func.assert_called_once()

        # Verify that the write function is called when the updater is called
        session_call = sync_session.mock_calls[0]
        update_token = session_call[2]['update_token']

        update_token(self.raw_token)
        self.assertEqual([{
            'creation_timestamp': TOKEN_CREATION_TIMESTAMP,
            'token': self.raw_token
        }], token_writes)

    @no_duplicates
    @patch('schwab.auth.Client')
    @patch('schwab.auth.OAuth2Client', new_callable=MockOAuthClient)
    @patch('schwab.auth.AsyncOAuth2Client', new_callable=MockAsyncOAuthClient)
    def test_success_with_write_func_metadata_aware_token(
            self, async_session, sync_session, client):
        token_read_func = MagicMock()
        token_read_func.return_value = self.token

        token_writes = []

        def token_write_func(token):
            token_writes.append(token)

        client.return_value = 'returned client'
        self.assertEqual('returned client',
                         auth.client_from_access_functions(
                             API_KEY,
                             APP_SECRET,
                             token_read_func,
                             token_write_func))

        sync_session.assert_called_once_with(
            API_KEY,
            client_secret=APP_SECRET,
            token=self.raw_token,
            token_endpoint=_,
            update_token=_,
            leeway=_)
        token_read_func.assert_called_once()

        # Verify that the write function is called when the updater is called
        session_call = sync_session.mock_calls[0]
        update_token = session_call[2]['update_token']

        update_token(self.raw_token)
        self.assertEqual([{
            'creation_timestamp': TOKEN_CREATION_TIMESTAMP,
            'token': self.raw_token
        }], token_writes)

    @no_duplicates
    @patch('schwab.auth.Client')
    @patch('schwab.auth.OAuth2Client', new_callable=MockOAuthClient)
    @patch('schwab.auth.AsyncOAuth2Client', new_callable=MockAsyncOAuthClient)
    def test_success_with_enforce_enums_disabled(
            self, async_session, sync_session, client):
        token_read_func = MagicMock()
        token_read_func.return_value = self.token

        token_writes = []

        def token_write_func(token):
            token_writes.append(token)

        client.return_value = 'returned client'
        self.assertEqual('returned client',
                         auth.client_from_access_functions(
                             API_KEY,
                             APP_SECRET,
                             token_read_func,
                             token_write_func, enforce_enums=False))

        client.assert_called_once_with(
                API_KEY, _, token_metadata=_, enforce_enums=False, base_url=auth.DEFAULT_BASE_URL)

    @no_duplicates
    @patch('schwab.auth.Client')
    @patch('schwab.auth.OAuth2Client', new_callable=MockOAuthClient)
    @patch('schwab.auth.AsyncOAuth2Client', new_callable=MockAsyncOAuthClient)
    def test_success_with_enforce_enums_enabled(
            self, async_session, sync_session, client):
        token_read_func = MagicMock()
        token_read_func.return_value = self.token

        token_writes = []

        def token_write_func(token):
            token_writes.append(token)

        client.return_value = 'returned client'
        self.assertEqual('returned client',
                         auth.client_from_access_functions(
                             API_KEY,
                             APP_SECRET,
                             token_read_func,
                             token_write_func))

        client.assert_called_once_with(
                API_KEY, _, token_metadata=_, enforce_enums=True, base_url=auth.DEFAULT_BASE_URL)

    @no_duplicates
    @patch('schwab.auth.Client')
    @patch('schwab.auth.OAuth2Client', new_callable=MockOAuthClient)
    @patch('schwab.auth.AsyncOAuth2Client', new_callable=MockAsyncOAuthClient)
    def test_custom_base_url(self, async_session, sync_session, client):
        token_read_func = MagicMock()
        token_read_func.return_value = self.token

        client.return_value = 'returned client'
        self.assertEqual('returned client',
                         auth.client_from_access_functions(
                             API_KEY,
                             APP_SECRET,
                             token_read_func,
                             MagicMock(),
                             base_url='https://proxy.example.com'))

        sync_session.assert_called_once_with(
            API_KEY,
            client_secret=APP_SECRET,
            token=self.raw_token,
            token_endpoint='https://proxy.example.com/v1/oauth/token',
            update_token=_,
            leeway=_)
        client.assert_called_once_with(
                API_KEY, _, token_metadata=_, enforce_enums=_,
                base_url='https://proxy.example.com')

    @no_duplicates
    def test_refuses_revoked_tombstone(self):
        token_read_func = MagicMock(return_value=dict(REVOKED_TOMBSTONE))
        with self.assertRaises(TokenRevokedError):
            auth.client_from_access_functions(
                    API_KEY, APP_SECRET, token_read_func, lambda t: None)

    @no_duplicates
    def test_rejects_awaitable_read_func(self):
        async def token_read_func():
            return self.token

        with self.assertRaisesRegex(
                TypeError, 'not an awaitable function'):
            auth.client_from_access_functions(
                    API_KEY, APP_SECRET, token_read_func, lambda t: None)

    @no_duplicates
    def test_rejects_awaitable_write_func_sync_client(self):
        token_read_func = MagicMock(return_value=self.token)

        async def token_write_func(token):
            pass

        with self.assertRaisesRegex(
                TypeError, 'not an awaitable function'):
            auth.client_from_access_functions(
                    API_KEY, APP_SECRET, token_read_func, token_write_func)

    @no_duplicates
    @patch('schwab.auth.Client')
    @patch('schwab.auth.AsyncClient')
    @patch('schwab.auth.OAuth2Client', new_callable=MockOAuthClient)
    @patch('schwab.auth.AsyncOAuth2Client', new_callable=MockAsyncOAuthClient)
    def test_awaitable_write_func_allowed_for_async_client(
            self, async_session, sync_session, async_client, client):
        token_read_func = MagicMock(return_value=self.token)

        async def token_write_func(token):
            pass

        async_client.return_value = 'returned client'
        self.assertEqual('returned client',
                         auth.client_from_access_functions(
                             API_KEY,
                             APP_SECRET,
                             token_read_func,
                             token_write_func,
                             asyncio=True))
        async_client.assert_called_once()
        client.assert_not_called()

    @no_duplicates
    @patch('schwab.auth.Client')
    @patch('schwab.auth.OAuth2Client', new_callable=MockOAuthClient)
    @patch('schwab.auth.AsyncOAuth2Client', new_callable=MockAsyncOAuthClient)
    def test_rejects_awaitable_returning_write_func_at_refresh(
            self, async_session, sync_session, client):
        # A synchronous write function that *returns* an awaitable slips
        # past the construction-time check but must still fail loudly at
        # refresh time rather than silently dropping the write.
        token_read_func = MagicMock(return_value=self.token)

        async def coro():
            pass

        def token_write_func(token):
            return coro()

        auth.client_from_access_functions(
                API_KEY, APP_SECRET, token_read_func, token_write_func)

        session_call = sync_session.mock_calls[0]
        update_token = session_call[2]['update_token']
        with self.assertRaisesRegex(
                TypeError, 'not an awaitable function'):
            update_token(self.raw_token)


# Note the client_from_received_url is called internally by the other client 
# generation functions, so testing here is kept light
class ClientFromReceivedUrl(unittest.TestCase):

    def setUp(self):
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.token_path = os.path.join(self.tmp_dir.name, 'token.json')
        self.raw_token = {'token': 'yes'}

    @no_duplicates
    @patch('schwab.auth.Client')
    @patch('schwab.auth.AsyncClient')
    @patch('schwab.auth.OAuth2Client', new_callable=MockOAuthClient)
    @patch('schwab.auth.AsyncOAuth2Client', new_callable=MockAsyncOAuthClient)
    @patch('time.time', MagicMock(return_value=MOCK_NOW))
    def test_success_sync(
            self, async_session, sync_session, async_client, client):
        AUTH_URL = 'https://auth.url.com'

        sync_session.return_value = sync_session
        sync_session.create_authorization_url.return_value = \
                AUTH_URL, 'oauth state'
        sync_session.fetch_token.return_value = self.raw_token

        auth_context = auth.get_auth_context(API_KEY, CALLBACK_URL)
        self.assertEqual(AUTH_URL, auth_context.authorization_url)
        self.assertEqual('oauth state', auth_context.state)

        client.return_value = 'returned client'
        token_capture = []
        auth.client_from_received_url(
                API_KEY, APP_SECRET, auth_context, 
                'http://redirect.url.com/?data',
                lambda token: token_capture.append(token))

        client.assert_called_once()
        async_client.assert_not_called()

        # Verify that the returned session can refresh itself when the access
        # token expires: without token_endpoint, authlib's ensure_active_token
        # cannot call refresh_token and every request raises InvalidTokenError
        # ~30 minutes after login.
        sync_session.assert_called_with(
                API_KEY,
                client_secret=APP_SECRET,
                token=self.raw_token,
                token_endpoint=_,
                update_token=_,
                leeway=_)

        # Verify that the oauth state is correctly passed along
        sync_session.fetch_token.assert_called_once_with(
                _,
                authorization_response=_,
                client_id=_,
                auth=_,
                state='oauth state')

        self.assertEqual([{
                'creation_timestamp': MOCK_NOW,
                'token': self.raw_token
            }], token_capture)


    @no_duplicates
    @patch('schwab.auth.Client')
    @patch('schwab.auth.AsyncClient')
    @patch('schwab.auth.OAuth2Client', new_callable=MockOAuthClient)
    @patch('schwab.auth.AsyncOAuth2Client', new_callable=MockAsyncOAuthClient)
    @patch('time.time', MagicMock(return_value=MOCK_NOW))
    def test_success_async(
            self, async_session, sync_session, async_client, client):
        AUTH_URL = 'https://auth.url.com'

        sync_session.return_value = sync_session
        sync_session.create_authorization_url.return_value = \
                AUTH_URL, 'oauth state'
        sync_session.fetch_token.return_value = self.raw_token

        auth_context = auth.get_auth_context(API_KEY, CALLBACK_URL)

        client.return_value = 'returned client'
        token_capture = []
        auth.client_from_received_url(
                API_KEY, APP_SECRET, auth_context, 
                'http://redirect.url.com/?data',
                lambda token: token_capture.append(token),
                asyncio=True)

        async_client.assert_called_once()
        client.assert_not_called()

        # Verify that the returned session can refresh itself when the access
        # token expires (see the sync variant above).
        async_session.assert_called_once_with(
                API_KEY,
                client_secret=APP_SECRET,
                token=self.raw_token,
                token_endpoint=_,
                update_token=_,
                leeway=_)

        # Verify that the oauth state is correctly passed along
        sync_session.fetch_token.assert_called_once_with(
                _,
                authorization_response=_,
                client_id=_,
                auth=_,
                state='oauth state')

        self.assertEqual([{
                'creation_timestamp': MOCK_NOW,
                'token': self.raw_token
            }], token_capture)

    @no_duplicates
    @patch('schwab.auth.Client')
    @patch('schwab.auth.AsyncClient')
    @patch('schwab.auth.OAuth2Client', new_callable=MockOAuthClient)
    @patch('schwab.auth.AsyncOAuth2Client', new_callable=MockAsyncOAuthClient)
    @patch('time.time', MagicMock(return_value=MOCK_NOW))
    def test_custom_base_url(
            self, async_session, sync_session, async_client, client):
        AUTH_URL = 'https://auth.url.com'

        sync_session.return_value = sync_session
        sync_session.create_authorization_url.return_value = \
                AUTH_URL, 'oauth state'
        sync_session.fetch_token.return_value = self.raw_token

        # The authorization URL is derived from the custom base URL
        auth_context = auth.get_auth_context(
                API_KEY, CALLBACK_URL,
                base_url='https://proxy.example.com')
        sync_session.create_authorization_url.assert_called_once_with(
                'https://proxy.example.com/v1/oauth/authorize', state=_)

        client.return_value = 'returned client'
        token_capture = []
        self.assertEqual('returned client',
                auth.client_from_received_url(
                        API_KEY, APP_SECRET, auth_context,
                        'http://redirect.url.com/?data',
                        lambda token: token_capture.append(token),
                        base_url='https://proxy.example.com'))

        # As is the token endpoint
        sync_session.fetch_token.assert_called_once_with(
                'https://proxy.example.com/v1/oauth/token',
                authorization_response=_,
                client_id=_,
                auth=_,
                state='oauth state')

        # And the constructed client receives the base URL
        client.assert_called_once_with(
                API_KEY, _, token_metadata=_, enforce_enums=_,
                base_url='https://proxy.example.com')

    @no_duplicates
    @patch('schwab.auth.OAuth2Client', new_callable=MockOAuthClient)
    def test_rejects_awaitable_write_func(self, sync_session):
        AUTH_URL = 'https://auth.url.com'

        sync_session.return_value = sync_session
        sync_session.create_authorization_url.return_value = \
                AUTH_URL, 'oauth state'
        sync_session.fetch_token.return_value = self.raw_token

        auth_context = auth.get_auth_context(API_KEY, CALLBACK_URL)

        async def token_write_func(token):
            pass

        with self.assertRaisesRegex(
                TypeError, 'not an awaitable function'):
            auth.client_from_received_url(
                    API_KEY, APP_SECRET, auth_context,
                    'http://redirect.url.com/?data', token_write_func)


class ClientFromManualFlow(unittest.TestCase):

    def setUp(self):
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.token_path = os.path.join(self.tmp_dir.name, 'token.json')
        self.raw_token = {'token': 'yes'}

    @no_duplicates
    @patch('schwab.auth.Client')
    @patch('schwab.auth.OAuth2Client', new_callable=MockOAuthClient)
    @patch('schwab.auth.AsyncOAuth2Client', new_callable=MockAsyncOAuthClient)
    @patch('schwab.auth.input')
    @patch('time.time', MagicMock(return_value=MOCK_NOW))
    def test_no_token_file(
            self, prompt_func, async_session, sync_session, client):
        AUTH_URL = 'https://auth.url.com'

        sync_session.return_value = sync_session
        sync_session.create_authorization_url.return_value = AUTH_URL, None
        sync_session.fetch_token.return_value = self.raw_token

        client.return_value = 'returned client'
        prompt_func.return_value = 'http://redirect.url.com/?data'

        self.assertEqual('returned client',
                         auth.client_from_manual_flow(
                             API_KEY, APP_SECRET, CALLBACK_URL, self.token_path))

        with open(self.token_path, 'r') as f:
            self.assertEqual({
                'creation_timestamp': MOCK_NOW,
                'token': self.raw_token
            }, json.load(f))

    @no_duplicates
    @patch('schwab.auth.Client')
    @patch('schwab.auth.OAuth2Client', new_callable=MockOAuthClient)
    @patch('schwab.auth.AsyncOAuth2Client', new_callable=MockAsyncOAuthClient)
    @patch('schwab.auth.input')
    @patch('time.time', MagicMock(return_value=MOCK_NOW))
    def test_custom_token_write_func(
            self, prompt_func, async_session, sync_session, client):
        AUTH_URL = 'https://auth.url.com'

        sync_session.return_value = sync_session
        sync_session.create_authorization_url.return_value = AUTH_URL, None
        sync_session.fetch_token.return_value = self.raw_token

        client.return_value = 'returned client'
        prompt_func.return_value = 'http://redirect.url.com/?data'

        token_writes = []

        def dummy_token_write_func(token):
            token_writes.append(token)

        self.assertEqual('returned client',
                         auth.client_from_manual_flow(
                             API_KEY, APP_SECRET, CALLBACK_URL,
                             self.token_path,
                             token_write_func=dummy_token_write_func))

        sync_session.assert_called_with(
                _, client_secret=APP_SECRET, token=_, token_endpoint=_,
                update_token=_, leeway=_)

        self.assertEqual([{
            'creation_timestamp': MOCK_NOW,
            'token': self.raw_token
        }], token_writes)

    @no_duplicates
    @patch('schwab.auth.Client')
    @patch('schwab.auth.OAuth2Client', new_callable=MockOAuthClient)
    @patch('schwab.auth.AsyncOAuth2Client', new_callable=MockAsyncOAuthClient)
    @patch('schwab.auth.input')
    @patch('builtins.print')
    @patch('time.time', MagicMock(return_value=MOCK_NOW))
    def test_print_warning_on_http_redirect_uri(
            self, print_func, prompt_func, async_session, sync_session, client):
        auth_url = 'https://auth.url.com'

        redirect_url = 'http://redirect.url.com'

        sync_session.return_value = sync_session
        sync_session.create_authorization_url.return_value = auth_url, None
        sync_session.fetch_token.return_value = self.raw_token

        client.return_value = 'returned client'
        prompt_func.return_value = 'http://redirect.url.com/?data'

        self.assertEqual('returned client',
                         auth.client_from_manual_flow(
                             API_KEY, APP_SECRET, redirect_url, self.token_path))

        with open(self.token_path, 'r') as f:
            self.assertEqual({
                'creation_timestamp': MOCK_NOW,
                'token': self.raw_token
            }, json.load(f))

        print_func.assert_any_call(AnyStringWith('will transmit data over HTTP'))

    @no_duplicates
    @patch('schwab.auth.Client')
    @patch('schwab.auth.OAuth2Client', new_callable=MockOAuthClient)
    @patch('schwab.auth.AsyncOAuth2Client', new_callable=MockAsyncOAuthClient)
    @patch('schwab.auth.input')
    @patch('time.time', MagicMock(return_value=MOCK_NOW))
    def test_enforce_enums_disabled(
            self, prompt_func, async_session, sync_session, client):
        auth_url = 'https://auth.url.com'

        sync_session.return_value = sync_session
        sync_session.create_authorization_url.return_value = auth_url, None
        sync_session.fetch_token.return_value = self.raw_token

        client.return_value = 'returned client'
        prompt_func.return_value = 'http://redirect.url.com/?data'

        self.assertEqual('returned client',
                         auth.client_from_manual_flow(
                             API_KEY, APP_SECRET, CALLBACK_URL, self.token_path,
                             enforce_enums=False))

        client.assert_called_once_with(API_KEY, _, token_metadata=_,
                                       enforce_enums=False, base_url=auth.DEFAULT_BASE_URL)

    @no_duplicates
    @patch('schwab.auth.Client')
    @patch('schwab.auth.OAuth2Client', new_callable=MockOAuthClient)
    @patch('schwab.auth.AsyncOAuth2Client', new_callable=MockAsyncOAuthClient)
    @patch('schwab.auth.input')
    @patch('time.time', MagicMock(return_value=MOCK_NOW))
    def test_enforce_enums_enabled(
            self, prompt_func, async_session, sync_session, client):
        auth_url = 'https://auth.url.com'

        sync_session.return_value = sync_session
        sync_session.create_authorization_url.return_value = auth_url, None
        sync_session.fetch_token.return_value = self.raw_token

        client.return_value = 'returned client'
        prompt_func.return_value = 'http://redirect.url.com/?data'

        self.assertEqual('returned client',
                         auth.client_from_manual_flow(
                             API_KEY, APP_SECRET, CALLBACK_URL, self.token_path))

        client.assert_called_once_with(API_KEY, _, token_metadata=_,
                                       enforce_enums=True, base_url=auth.DEFAULT_BASE_URL)


class TokenMetadataTest(unittest.TestCase):

    @no_duplicates
    def test_from_loaded_token(self):
        token = {'token': 'yes', 'creation_timestamp': TOKEN_CREATION_TIMESTAMP}

        metadata = auth.TokenMetadata.from_loaded_token(
                token, unwrapped_token_write_func=None)
        self.assertEqual(metadata.token, token['token'])


    @no_duplicates
    def test_wrapped_token_write_func_updates_stored_token(self):
        token = {'token': 'yes', 'creation_timestamp': TOKEN_CREATION_TIMESTAMP}

        updated = [False]
        def update_token(token):
            updated[0] = True

        metadata = auth.TokenMetadata.from_loaded_token(
                token, unwrapped_token_write_func=update_token)

        new_token = {'updated': 'yes'}
        metadata.wrapped_token_write_func()(new_token)

        self.assertTrue(updated[0])
        self.assertEqual(new_token, metadata.token)


    @no_duplicates
    def test_reject_tokens_without_creation_timestamp(self):
        with self.assertRaisesRegex(ValueError, 'token format has changed'):
            metadata = auth.TokenMetadata.from_loaded_token(
                    {'token': 'yes'}, lambda t: None)


    @no_duplicates
    @patch('time.time', MagicMock(return_value=MOCK_NOW))
    def test_token_age(self):
        token = {'token': 'yes', 'creation_timestamp': TOKEN_CREATION_TIMESTAMP}

        metadata = auth.TokenMetadata.from_loaded_token(
                token, unwrapped_token_write_func=None)
        self.assertEqual(metadata.token_age(),
                         MOCK_NOW - TOKEN_CREATION_TIMESTAMP)

    @no_duplicates
    def test_secretless_revoked_tombstone_loads_as_revoked(self):
        metadata = auth.TokenMetadata.from_loaded_token(
                dict(REVOKED_TOMBSTONE), unwrapped_token_write_func=None)
        self.assertTrue(metadata.revoked)
        self.assertIsNone(metadata.token)

    @no_duplicates
    def test_retained_revoked_tombstone_loads_as_revoked(self):
        # A tombstone written by a version that retained the credential
        # must still load as revoked — and drop the token.
        tombstone = dict(REVOKED_TOMBSTONE)
        tombstone['token'] = dict(RAW_TOKEN)
        metadata = auth.TokenMetadata.from_loaded_token(
                tombstone, unwrapped_token_write_func=None)
        self.assertTrue(metadata.revoked)
        self.assertIsNone(metadata.token)

    @no_duplicates
    def test_non_bool_revoked_marker_rejected(self):
        for bogus in ('true', 1, {'revoked': True}):
            tombstone = dict(REVOKED_TOMBSTONE)
            tombstone['revoked'] = bogus
            tombstone['token'] = dict(RAW_TOKEN)
            with self.assertRaises(ValueError):
                auth.TokenMetadata.from_loaded_token(
                        tombstone, unwrapped_token_write_func=None)


class EasyClientTest(unittest.TestCase):

    def setUp(self):
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.token_path = os.path.join(self.tmp_dir.name, 'token.json')
        self.raw_token = {'token': 'yes'}

    def put_token(self):
        with open(self.token_path, 'w') as f:
            f.write(json.dumps(self.raw_token))


    @no_duplicates
    @patch('schwab.auth.client_from_token_file')
    @patch('schwab.auth.client_from_login_flow', new_callable=MockOAuthClient)
    @patch('time.time', MagicMock(return_value=MOCK_NOW))
    def test_no_token(
            self, client_from_login_flow, client_from_token_file):
        mock_client = MagicMock()
        client_from_login_flow.return_value = mock_client

        c = auth.easy_client(API_KEY, APP_SECRET, CALLBACK_URL, self.token_path)

        self.assertIs(c, mock_client)


    @no_duplicates
    @patch('schwab.auth.client_from_token_file')
    @patch('schwab.auth.client_from_login_flow', new_callable=MockOAuthClient)
    @patch('schwab.auth.client_from_manual_flow', new_callable=MockOAuthClient)
    @patch('os.getenv', new_callable=MockOAuthClient)
    @patch('time.time', MagicMock(return_value=MOCK_NOW))
    def test_running_on_collab_environment(
            self, getenv, client_from_manual_flow, client_from_login_flow, 
            client_from_token_file):
        def do_getenv(flag):
            assert flag == 'COLAB_RELEASE_TAG'
            return 'yes'
        getenv.side_effect = do_getenv

        mock_client = MagicMock()
        client_from_manual_flow.return_value = mock_client

        c = auth.easy_client(API_KEY, APP_SECRET, CALLBACK_URL, self.token_path)
        self.assertIs(c, mock_client)


    @no_duplicates
    @patch('schwab.auth.client_from_token_file')
    @patch('schwab.auth.client_from_login_flow', new_callable=MockOAuthClient)
    @patch('schwab.auth.client_from_manual_flow', new_callable=MockOAuthClient)
    @patch('os.getenv', new_callable=MockOAuthClient)
    @patch('schwab.auth._get_ipython')
    @patch('time.time', MagicMock(return_value=MOCK_NOW))
    def test_running_on_ipython_in_notebook_mode(
            self, get_ipython, getenv, client_from_manual_flow, 
            client_from_login_flow, client_from_token_file):
        getenv.return_value = ''

        class ZMQInteractiveShell:
            pass
        get_ipython.return_value = ZMQInteractiveShell()

        mock_client = MagicMock()
        client_from_manual_flow.return_value = mock_client

        c = auth.easy_client(API_KEY, APP_SECRET, CALLBACK_URL, self.token_path)
        self.assertIs(c, mock_client)


    @no_duplicates
    @patch('schwab.auth.client_from_token_file')
    @patch('schwab.auth.client_from_login_flow', new_callable=MockOAuthClient)
    @patch('schwab.auth.client_from_manual_flow', new_callable=MockOAuthClient)
    @patch('os.getenv', new_callable=MockOAuthClient)
    @patch('schwab.auth._get_ipython')
    @patch('time.time', MagicMock(return_value=MOCK_NOW))
    def test_running_on_ipython_in_something_other_than_notebook_mode(
            self, get_ipython, getenv, client_from_manual_flow, 
            client_from_login_flow, client_from_token_file):
        getenv.return_value = ''

        class NotZMQInteractiveShell:
            pass
        get_ipython.return_value = NotZMQInteractiveShell()

        mock_client = MagicMock()
        client_from_login_flow.return_value = mock_client

        c = auth.easy_client(API_KEY, APP_SECRET, CALLBACK_URL, self.token_path)
        self.assertIs(c, mock_client)


    @no_duplicates
    @patch('schwab.auth.client_from_token_file')
    @patch('schwab.auth.client_from_login_flow', new_callable=MockOAuthClient)
    @patch('time.time', MagicMock(return_value=MOCK_NOW))
    def test_no_token_passing_parameters(
            self, client_from_login_flow, client_from_token_file):
        mock_client = MagicMock()
        client_from_login_flow.return_value = mock_client

        c = auth.easy_client(
                API_KEY, APP_SECRET, CALLBACK_URL, self.token_path, 
                asyncio='asyncio', enforce_enums='enforce_enums', 
                callback_timeout='callback_timeout', interactive='interactive',
                requested_browser='requested_browser')

        self.assertIs(c, mock_client)

        client_from_login_flow.assert_called_once_with(
                API_KEY, APP_SECRET, CALLBACK_URL, self.token_path,
                asyncio='asyncio', enforce_enums='enforce_enums',
                callback_timeout='callback_timeout', interactive='interactive',
                requested_browser='requested_browser', base_url=None)


    @no_duplicates
    @patch('schwab.auth.client_from_token_file')
    @patch('schwab.auth.client_from_login_flow', new_callable=MockOAuthClient)
    @patch('time.time', MagicMock(return_value=MOCK_NOW))
    def test_existing_token(
            self, client_from_login_flow, client_from_token_file):
        self.put_token()

        mock_client = MagicMock()
        client_from_token_file.return_value = mock_client
        mock_client.token_age.return_value = 1

        c = auth.easy_client(API_KEY, APP_SECRET, CALLBACK_URL, self.token_path)

        self.assertIs(c, mock_client)


    @no_duplicates
    @patch('schwab.auth.client_from_token_file')
    @patch('schwab.auth.client_from_login_flow', new_callable=MockOAuthClient)
    @patch('time.time', MagicMock(return_value=MOCK_NOW))
    def test_existing_token_passing_parameters(
            self, client_from_login_flow, client_from_token_file):
        self.put_token()

        mock_client = MagicMock()
        client_from_token_file.return_value = mock_client
        mock_client.token_age.return_value = 1

        c = auth.easy_client(API_KEY, APP_SECRET, CALLBACK_URL, self.token_path,
                             asyncio='asyncio', enforce_enums='enforce_enums')

        self.assertIs(c, mock_client)

        client_from_token_file.assert_called_once_with(
                self.token_path, API_KEY, APP_SECRET,
                asyncio='asyncio', enforce_enums='enforce_enums',
                base_url=None)


    @no_duplicates
    @patch('schwab.auth.client_from_token_file')
    @patch('schwab.auth.client_from_login_flow', new_callable=MockOAuthClient)
    @patch('time.time', MagicMock(return_value=MOCK_NOW))
    def test_token_too_old(
            self, client_from_login_flow, client_from_token_file):
        self.put_token()

        mock_file_client = MagicMock()
        client_from_token_file.return_value = mock_file_client
        mock_file_client.token_age.return_value = 9999999999

        mock_browser_client = MagicMock()
        client_from_login_flow.return_value = mock_browser_client
        mock_browser_client.token_age.return_value = 1

        c = auth.easy_client(API_KEY, APP_SECRET, CALLBACK_URL, self.token_path)

        self.assertIs(c, mock_browser_client)


    @no_duplicates
    @patch('schwab.auth.client_from_token_file')
    @patch('schwab.auth.client_from_login_flow', new_callable=MockOAuthClient)
    @patch('time.time', MagicMock(return_value=MOCK_NOW))
    def test_negative_max_token_age(
            self, client_from_login_flow, client_from_token_file):
        with self.assertRaisesRegex(
                ValueError, 'max_token_age must be positive, zero, or None'):
            c = auth.easy_client(API_KEY, APP_SECRET, CALLBACK_URL, 
                                 self.token_path, max_token_age=-1)


    @no_duplicates
    @patch('schwab.auth.client_from_token_file')
    @patch('schwab.auth.client_from_login_flow', new_callable=MockOAuthClient)
    @patch('time.time', MagicMock(return_value=MOCK_NOW))
    def test_none_max_token_age(
            self, client_from_login_flow, client_from_token_file):
        self.put_token()

        mock_client = MagicMock()
        client_from_token_file.return_value = mock_client
        mock_client.token_age.return_value = 9999999999

        c = auth.easy_client(API_KEY, APP_SECRET, CALLBACK_URL, self.token_path,
                             max_token_age=None)

        self.assertIs(c, mock_client)


    @no_duplicates
    @patch('schwab.auth.client_from_token_file')
    @patch('schwab.auth.client_from_login_flow', new_callable=MockOAuthClient)
    @patch('time.time', MagicMock(return_value=MOCK_NOW))
    def test_zero_max_token_age(
            self, client_from_login_flow, client_from_token_file):
        self.put_token()

        mock_client = MagicMock()
        client_from_token_file.return_value = mock_client
        mock_client.token_age.return_value = 9999999999

        c = auth.easy_client(API_KEY, APP_SECRET, CALLBACK_URL, self.token_path,
                             max_token_age=0)


    @no_duplicates
    @patch('schwab.auth.client_from_login_flow')
    def test_revoked_token_falls_through_to_login(
            self, client_from_login_flow):
        with open(self.token_path, 'w') as f:
            json.dump(REVOKED_TOMBSTONE, f)

        mock_client = MagicMock()
        client_from_login_flow.return_value = mock_client

        with self.assertLogs(auth.get_logger(), level='WARNING') as logs:
            c = auth.easy_client(
                    API_KEY, APP_SECRET, CALLBACK_URL, self.token_path)

        self.assertIs(c, mock_client)
        client_from_login_flow.assert_called_once()
        self.assertTrue(any(
                'marked as revoked' in m for m in logs.output))


# Client.revoke() and AsyncClient.revoke() submit the stored refresh token
# to Schwab's RFC 7009 revocation endpoint and tombstone the local token.
class SyncRevokeTest(unittest.TestCase):

    def setUp(self):
        self.mock_session = MagicMock()
        self.writes = []
        self.metadata = auth.TokenMetadata(
                dict(RAW_TOKEN), TOKEN_CREATION_TIMESTAMP,
                self.writes.append)
        self.client = Client(
                API_KEY, self.mock_session, token_metadata=self.metadata)

    def _ok(self):
        self.mock_session.revoke_token.return_value = (
                MockResponse({}, 200))

    @no_duplicates
    def test_revoke_posts_and_persists_tombstone(self):
        self._ok()

        self.assertIsNone(self.client.revoke())

        self.mock_session.revoke_token.assert_called_once_with(
                REVOKE_URL, 'REFRESH_TOKEN',
                token_type_hint='refresh_token')
        self.assertEqual([REVOKED_TOMBSTONE], self.writes)
        self.assertTrue(self.metadata.revoked)
        self.assertIsNone(self.metadata.token)

    @no_duplicates
    def test_revoke_custom_base_url(self):
        self._ok()

        client = Client(
                API_KEY, self.mock_session,
                token_metadata=self.metadata,
                base_url='https://proxy.example.com')
        self.assertIsNone(client.revoke())

        self.mock_session.revoke_token.assert_called_once_with(
                'https://proxy.example.com/v1/oauth/revoke', 'REFRESH_TOKEN',
                token_type_hint='refresh_token')

    @no_duplicates
    def test_revoke_tombstone_is_secretless(self):
        self._ok()
        self.client.revoke()
        serialized = json.dumps(self.writes[-1])
        for secret in RAW_TOKEN.values():
            if isinstance(secret, str):
                self.assertNotIn(secret, serialized)

    @no_duplicates
    def test_revoke_already_revoked_is_noop(self):
        self._ok()
        self.client.revoke()
        self.mock_session.revoke_token.reset_mock()

        self.assertIsNone(self.client.revoke())
        self.mock_session.revoke_token.assert_not_called()
        self.assertEqual(1, len(self.writes))

    @no_duplicates
    def test_revoke_no_metadata(self):
        client = Client(API_KEY, self.mock_session)
        with self.assertRaises(TokenRevocationError) as ctx:
            client.revoke()
        self.assertFalse(ctx.exception.endpoint_answered)
        self.assertFalse(ctx.exception.retryable)
        self.assertFalse(ctx.exception.server_revoked)
        self.mock_session.revoke_token.assert_not_called()

    @no_duplicates
    def test_revoke_no_refresh_token(self):
        client = Client(
                API_KEY, self.mock_session,
                token_metadata=auth.TokenMetadata(
                    {'access_token': 'ACCESS_TOKEN'},
                    TOKEN_CREATION_TIMESTAMP, self.writes.append))
        with self.assertRaises(TokenRevocationError) as ctx:
            client.revoke()
        self.assertFalse(ctx.exception.endpoint_answered)
        self.assertFalse(ctx.exception.retryable)
        self.mock_session.revoke_token.assert_not_called()

    @no_duplicates
    def test_revoke_rejected(self):
        self.mock_session.revoke_token.return_value = (
                MockResponse({}, 400))
        with self.assertRaises(TokenRevocationError) as ctx:
            self.client.revoke()
        self.assertTrue(ctx.exception.endpoint_answered)
        self.assertEqual(400, ctx.exception.status_code)
        self.assertFalse(ctx.exception.retryable)
        self.assertFalse(ctx.exception.server_revoked)
        # The credential must remain intact on rejection
        self.assertFalse(self.metadata.revoked)
        self.assertEqual(RAW_TOKEN, self.metadata.token)
        self.assertEqual([], self.writes)

    @no_duplicates
    def test_revoke_retryable_statuses(self):
        for status in (429, 500, 503):
            metadata = auth.TokenMetadata(
                    dict(RAW_TOKEN), TOKEN_CREATION_TIMESTAMP,
                    self.writes.append)
            client = Client(
                    API_KEY, self.mock_session, token_metadata=metadata)
            self.mock_session.revoke_token.return_value = (
                    MockResponse({}, status))
            with self.assertRaises(TokenRevocationError) as ctx:
                client.revoke()
            self.assertTrue(ctx.exception.endpoint_answered)
            self.assertEqual(status, ctx.exception.status_code)
            self.assertTrue(ctx.exception.retryable)
            self.assertFalse(ctx.exception.server_revoked)
            self.assertFalse(metadata.revoked)

    @no_duplicates
    def test_revoke_transport_failure(self):
        self.mock_session.revoke_token.side_effect = (
                httpx2.ConnectError('connection refused'))
        with self.assertRaises(TokenRevocationError) as ctx:
            self.client.revoke()
        self.assertFalse(ctx.exception.endpoint_answered)
        self.assertIsNone(ctx.exception.status_code)
        self.assertTrue(ctx.exception.retryable)
        self.assertFalse(ctx.exception.server_revoked)
        self.assertFalse(self.metadata.revoked)
        # The transport exception carries the credential-bearing request;
        # it must not be reachable through the raised error.
        self.assertIsNone(ctx.exception.__context__)
        self.assertIsNone(ctx.exception.__cause__)

    @no_duplicates
    def test_revoke_persistence_failure_reports_server_revoked(self):
        self._ok()
        self.metadata.unwrapped_token_write_func = MagicMock(
                side_effect=OSError('disk full'))
        with self.assertRaises(TokenRevocationError) as ctx:
            self.client.revoke()
        self.assertTrue(ctx.exception.endpoint_answered)
        self.assertEqual(200, ctx.exception.status_code)
        self.assertTrue(ctx.exception.retryable)
        self.assertTrue(ctx.exception.server_revoked)

    @no_duplicates
    def test_revoke_rejects_awaitable_returning_write_func(self):
        # A write function returning an awaitable slips past the
        # construction-time check but must fail loudly at revocation
        # rather than silently dropping the tombstone write.
        self._ok()

        async def coro():
            pass
        self.metadata.unwrapped_token_write_func = lambda t: coro()

        with self.assertRaisesRegex(
                TypeError, 'not an awaitable function'):
            self.client.revoke()


class AsyncRevokeTest(unittest.TestCase):

    def setUp(self):
        self.mock_session = AsyncMagicMock()
        self.writes = []
        self.metadata = auth.TokenMetadata(
                dict(RAW_TOKEN), TOKEN_CREATION_TIMESTAMP,
                self.writes.append)
        self.client = ResyncProxy(AsyncClient)(
                API_KEY, self.mock_session, token_metadata=self.metadata)

    @no_duplicates
    def test_revoke_posts_and_persists_tombstone(self):
        self.mock_session.revoke_token.return_value = (
                MockResponse({}, 200))

        self.assertIsNone(self.client.revoke())

        self.mock_session.revoke_token.assert_awaited_once_with(
                REVOKE_URL, 'REFRESH_TOKEN',
                token_type_hint='refresh_token')
        self.assertEqual([REVOKED_TOMBSTONE], self.writes)
        self.assertTrue(self.metadata.revoked)
        self.assertIsNone(self.metadata.token)

    @no_duplicates
    def test_revoke_custom_base_url(self):
        self.mock_session.revoke_token.return_value = (
                MockResponse({}, 200))

        client = ResyncProxy(AsyncClient)(
                API_KEY, self.mock_session,
                token_metadata=self.metadata,
                base_url='https://proxy.example.com')
        self.assertIsNone(client.revoke())

        self.mock_session.revoke_token.assert_awaited_once_with(
                'https://proxy.example.com/v1/oauth/revoke', 'REFRESH_TOKEN',
                token_type_hint='refresh_token')

    @no_duplicates
    def test_revoke_transport_failure(self):
        self.mock_session.revoke_token.side_effect = (
                httpx2.ConnectError('connection refused'))
        with self.assertRaises(TokenRevocationError) as ctx:
            self.client.revoke()
        self.assertFalse(ctx.exception.endpoint_answered)
        self.assertTrue(ctx.exception.retryable)
        self.assertIsNone(ctx.exception.__context__)
        self.assertIsNone(ctx.exception.__cause__)

    @no_duplicates
    def test_revoke_persistence_failure_reports_server_revoked(self):
        self.mock_session.revoke_token.return_value = (
                MockResponse({}, 200))
        self.metadata.unwrapped_token_write_func = MagicMock(
                side_effect=OSError('disk full'))
        with self.assertRaises(TokenRevocationError) as ctx:
            self.client.revoke()
        self.assertTrue(ctx.exception.server_revoked)
        self.assertTrue(ctx.exception.retryable)

    @no_duplicates
    def test_revoke_awaits_async_write_func(self):
        self.mock_session.revoke_token.return_value = (
                MockResponse({}, 200))

        writes = []

        async def write(token):
            writes.append(token)
        self.metadata.unwrapped_token_write_func = write

        self.assertIsNone(self.client.revoke())
        self.assertEqual([REVOKED_TOMBSTONE], writes)
        self.assertTrue(self.metadata.revoked)
        self.assertIsNone(self.metadata.token)

    @no_duplicates
    def test_revoke_async_write_failure_reports_server_revoked(self):
        self.mock_session.revoke_token.return_value = (
                MockResponse({}, 200))

        async def write(token):
            raise OSError('disk full')
        self.metadata.unwrapped_token_write_func = write

        with self.assertRaises(TokenRevocationError) as ctx:
            self.client.revoke()
        self.assertTrue(ctx.exception.server_revoked)
        self.assertTrue(ctx.exception.retryable)
