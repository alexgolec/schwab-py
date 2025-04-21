from schwab import auth
from .utils import (
        AnyStringWith,
        MockAsyncOAuthClient,
        MockOAuthClient,
        no_duplicates
)
from unittest.mock import patch, ANY, MagicMock
from unittest.mock import ANY as _

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
                                       enforce_enums=_)
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
                                       enforce_enums=False)

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
                                       enforce_enums=True)


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
                API_KEY, _, token_metadata=_, enforce_enums=False)

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
                API_KEY, _, token_metadata=_, enforce_enums=True)


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
                _, client_secret=APP_SECRET, token=_, update_token=_, leeway=_)

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
                                       enforce_enums=False)

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
                                       enforce_enums=True)


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
                requested_browser='requested_browser')


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
                asyncio='asyncio', enforce_enums='enforce_enums')


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
