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
import tempfile
import unittest


API_KEY = 'APIKEY'
APP_SECRET = '0x5EC07'
MOCK_NOW = 1613745082
REDIRECT_URL = 'https://redirect.url.com'


class ClientFromTokenFileTest(unittest.TestCase):

    def setUp(self):
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.json_path = os.path.join(self.tmp_dir.name, 'token.json')
        self.token = {'token': 'yes'}

    def write_token(self):
        with open(self.json_path, 'w') as f:
            json.dump(self.token, f)

    @no_duplicates
    def test_no_such_file(self):
        with self.assertRaises(FileNotFoundError):
            auth.client_from_token_file(self.json_path, API_KEY, APP_SECRET)

    @no_duplicates
    @patch('schwab.auth.Client')
    @patch('schwab.auth.OAuth2Client', new_callable=MockOAuthClient)
    @patch('schwab.auth.AsyncOAuth2Client', new_callable=MockAsyncOAuthClient)
    def test_json_loads(self, async_session, sync_session, client):
        self.write_token()

        client.return_value = 'returned client'

        self.assertEqual('returned client',
                         auth.client_from_token_file(
                             self.json_path, API_KEY, APP_SECRET))
        client.assert_called_once_with(API_KEY, _, token_metadata=_,
                                       enforce_enums=_)
        sync_session.assert_called_once_with(
            API_KEY,
            client_secret=APP_SECRET,
            token=self.token,
            token_endpoint=_,
            update_token=_)

    @no_duplicates
    @patch('schwab.auth.Client')
    @patch('schwab.auth.OAuth2Client', new_callable=MockOAuthClient)
    @patch('schwab.auth.AsyncOAuth2Client', new_callable=MockAsyncOAuthClient)
    def test_update_token_updates_token(
            self, async_session, sync_session, client):
        self.write_token()

        auth.client_from_token_file(self.json_path, API_KEY, APP_SECRET)
        sync_session.assert_called_once()

        session_call = sync_session.mock_calls[0]
        update_token = session_call[2]['update_token']

        updated_token = {'updated': 'token'}
        update_token(updated_token)
        with open(self.json_path, 'r') as f:
            self.assertEqual(json.load(f), updated_token)

    @no_duplicates
    @patch('schwab.auth.Client')
    @patch('schwab.auth.OAuth2Client', new_callable=MockOAuthClient)
    @patch('schwab.auth.AsyncOAuth2Client', new_callable=MockAsyncOAuthClient)
    def test_enforce_enums_being_disabled(self, async_session, sync_session, client):
        self.write_token()

        client.return_value = 'returned client'

        self.assertEqual('returned client',
                         auth.client_from_token_file(
                             self.json_path, API_KEY, APP_SECRET,
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
                             self.json_path, API_KEY, APP_SECRET))
        client.assert_called_once_with(API_KEY, _, token_metadata=_,
                                       enforce_enums=True)


class ClientFromAccessFunctionsTest(unittest.TestCase):

    @no_duplicates
    @patch('schwab.auth.Client')
    @patch('schwab.auth.OAuth2Client', new_callable=MockOAuthClient)
    @patch('schwab.auth.AsyncOAuth2Client', new_callable=MockAsyncOAuthClient)
    def test_success_with_write_func(
            self, async_session, sync_session, client):
        token = {'token': 'yes'}

        token_read_func = MagicMock()
        token_read_func.return_value = token

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
            token=token,
            token_endpoint=_,
            update_token=_)
        token_read_func.assert_called_once()

        # Verify that the write function is called when the updater is called
        session_call = sync_session.mock_calls[0]
        update_token = session_call[2]['update_token']


        update_token(token)
        self.assertEqual([token], token_writes)

    @no_duplicates
    @patch('schwab.auth.Client')
    @patch('schwab.auth.OAuth2Client', new_callable=MockOAuthClient)
    @patch('schwab.auth.AsyncOAuth2Client', new_callable=MockAsyncOAuthClient)
    def test_success_with_write_func_metadata_aware_token(
            self, async_session, sync_session, client):
        token = {'token': 'yes'}

        token_read_func = MagicMock()
        token_read_func.return_value = token

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
            token=token,
            token_endpoint=_,
            update_token=_)
        token_read_func.assert_called_once()

        # Verify that the write function is called when the updater is called
        session_call = sync_session.mock_calls[0]
        update_token = session_call[2]['update_token']

        update_token(token)
        self.assertEqual([token], token_writes)

    @no_duplicates
    @patch('schwab.auth.Client')
    @patch('schwab.auth.OAuth2Client', new_callable=MockOAuthClient)
    @patch('schwab.auth.AsyncOAuth2Client', new_callable=MockAsyncOAuthClient)
    def test_success_with_enforce_enums_disabled(
            self, async_session, sync_session, client):
        token = {'token': 'yes'}

        token_read_func = MagicMock()
        token_read_func.return_value = token

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
        token = {'token': 'yes'}

        token_read_func = MagicMock()
        token_read_func.return_value = token

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



class ClientFromManualFlow(unittest.TestCase):

    def setUp(self):
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.json_path = os.path.join(self.tmp_dir.name, 'token.json')
        self.token = {'token': 'yes'}

    @no_duplicates
    @patch('schwab.auth.Client')
    @patch('schwab.auth.OAuth2Client', new_callable=MockOAuthClient)
    @patch('schwab.auth.AsyncOAuth2Client', new_callable=MockAsyncOAuthClient)
    @patch('schwab.auth.prompt')
    @patch('time.time', unittest.mock.MagicMock(return_value=MOCK_NOW))
    def test_no_token_file(
            self, prompt_func, async_session, sync_session, client):
        AUTH_URL = 'https://auth.url.com'

        sync_session.return_value = sync_session
        sync_session.create_authorization_url.return_value = AUTH_URL, None
        sync_session.fetch_token.return_value = self.token

        client.return_value = 'returned client'
        prompt_func.return_value = 'http://redirect.url.com/?data'

        self.assertEqual('returned client',
                         auth.client_from_manual_flow(
                             API_KEY, APP_SECRET, REDIRECT_URL, self.json_path))

        with open(self.json_path, 'r') as f:
            self.assertEqual(self.token, json.load(f))

    @no_duplicates
    @patch('schwab.auth.Client')
    @patch('schwab.auth.OAuth2Client', new_callable=MockOAuthClient)
    @patch('schwab.auth.AsyncOAuth2Client', new_callable=MockAsyncOAuthClient)
    @patch('schwab.auth.prompt')
    @patch('time.time', unittest.mock.MagicMock(return_value=MOCK_NOW))
    def test_custom_token_write_func(
            self, prompt_func, async_session, sync_session, client):
        AUTH_URL = 'https://auth.url.com'

        sync_session.return_value = sync_session
        sync_session.create_authorization_url.return_value = AUTH_URL, None
        sync_session.fetch_token.return_value = self.token

        webdriver = MagicMock()
        webdriver.current_url = REDIRECT_URL + '/token_params'

        client.return_value = 'returned client'
        prompt_func.return_value = 'http://redirect.url.com/?data'

        token_writes = []

        def dummy_token_write_func(token):
            token_writes.append(token)

        self.assertEqual('returned client',
                         auth.client_from_manual_flow(
                             API_KEY, APP_SECRET, REDIRECT_URL,
                             self.json_path,
                             token_write_func=dummy_token_write_func))

        sync_session.assert_called_with(
                _, client_secret=APP_SECRET, token=_, update_token=_)

        self.assertEqual([self.token], token_writes)

    @no_duplicates
    @patch('schwab.auth.Client')
    @patch('schwab.auth.OAuth2Client', new_callable=MockOAuthClient)
    @patch('schwab.auth.AsyncOAuth2Client', new_callable=MockAsyncOAuthClient)
    @patch('schwab.auth.prompt')
    @patch('builtins.print')
    @patch('time.time', unittest.mock.MagicMock(return_value=MOCK_NOW))
    def test_print_warning_on_http_redirect_uri(
            self, print_func, prompt_func, async_session, sync_session, client):
        AUTH_URL = 'https://auth.url.com'

        redirect_url = 'http://redirect.url.com'

        sync_session.return_value = sync_session
        sync_session.create_authorization_url.return_value = AUTH_URL, None
        sync_session.fetch_token.return_value = self.token

        client.return_value = 'returned client'
        prompt_func.return_value = 'http://redirect.url.com/?data'

        self.assertEqual('returned client',
                         auth.client_from_manual_flow(
                             API_KEY, APP_SECRET, redirect_url, self.json_path))

        with open(self.json_path, 'r') as f:
            self.assertEqual(self.token, json.load(f))

        print_func.assert_any_call(AnyStringWith('will transmit data over HTTP'))

    @no_duplicates
    @patch('schwab.auth.Client')
    @patch('schwab.auth.OAuth2Client', new_callable=MockOAuthClient)
    @patch('schwab.auth.AsyncOAuth2Client', new_callable=MockAsyncOAuthClient)
    @patch('schwab.auth.prompt')
    @patch('time.time', unittest.mock.MagicMock(return_value=MOCK_NOW))
    def test_enforce_enums_disabled(
            self, prompt_func, async_session, sync_session, client):
        AUTH_URL = 'https://auth.url.com'

        sync_session.return_value = sync_session
        sync_session.create_authorization_url.return_value = AUTH_URL, None
        sync_session.fetch_token.return_value = self.token

        client.return_value = 'returned client'
        prompt_func.return_value = 'http://redirect.url.com/?data'

        self.assertEqual('returned client',
                         auth.client_from_manual_flow(
                             API_KEY, APP_SECRET, REDIRECT_URL, self.json_path,
                             enforce_enums=False))

        client.assert_called_once_with(API_KEY, _, token_metadata=_,
                                       enforce_enums=False)

    @no_duplicates
    @patch('schwab.auth.Client')
    @patch('schwab.auth.OAuth2Client', new_callable=MockOAuthClient)
    @patch('schwab.auth.AsyncOAuth2Client', new_callable=MockAsyncOAuthClient)
    @patch('schwab.auth.prompt')
    @patch('time.time', unittest.mock.MagicMock(return_value=MOCK_NOW))
    def test_enforce_enums_enabled(
            self, prompt_func, async_session, sync_session, client):
        AUTH_URL = 'https://auth.url.com'

        sync_session.return_value = sync_session
        sync_session.create_authorization_url.return_value = AUTH_URL, None
        sync_session.fetch_token.return_value = self.token

        client.return_value = 'returned client'
        prompt_func.return_value = 'http://redirect.url.com/?data'

        self.assertEqual('returned client',
                         auth.client_from_manual_flow(
                             API_KEY, APP_SECRET, REDIRECT_URL, self.json_path))

        client.assert_called_once_with(API_KEY, _, token_metadata=_,
                                       enforce_enums=True)


class TokenMetadataTest(unittest.TestCase):

    @no_duplicates
    def test_from_loaded_token(self):
        token = {'token': 'yes'}

        metadata = auth.TokenMetadata.from_loaded_token(
                token, unwrapped_token_write_func=None)
        self.assertEqual(metadata.token, token)


    @no_duplicates
    def test_wrapped_token_write_func_updates_stored_token(self):
        token = {'token': 'yes'}

        updated = [False]
        def update_token(token):
            updated[0] = True

        metadata = auth.TokenMetadata.from_loaded_token(
                token, unwrapped_token_write_func=update_token)

        new_token = {'updated': 'yes'}
        metadata.wrapped_token_write_func()(new_token)

        self.assertTrue(updated[0])
        self.assertEqual(new_token, metadata.token)
