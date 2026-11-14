import unittest
from unittest.mock import ANY as _
from unittest.mock import patch, AsyncMock

from schwab import auth
from .utils import (
    MockAsyncOAuthClient,
    MockOAuthClient,
    no_duplicates
)

API_KEY = 'APIKEY'
APP_SECRET = '0x5EC07'
TOKEN_CREATION_TIMESTAMP = 1613745000
MOCK_NOW = 1613745082
CALLBACK_URL = 'https://redirect.url.com'


class ClientFromAccessFunctionsTest(unittest.IsolatedAsyncioTestCase):

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
    async def test_success_with_write_func_async(
            self, async_session, sync_session, client):
        token_read_func = AsyncMock()
        token_read_func.return_value = self.token

        token_writes = []


        def token_write_func(token):
            token_writes.append(token)


        client.return_value = 'returned client'
        self.assertEqual('returned client',
                         await auth.client_from_access_functions_async(
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
    async def test_success_with_async_write_func_metadata_aware_token(
            self, async_session, sync_session, client):
        token_read_func = AsyncMock()
        token_read_func.return_value = self.token

        token_writes = []


        def token_write_func(token):
            token_writes.append(token)


        client.return_value = 'returned client'
        self.assertEqual('returned client',
                         await auth.client_from_access_functions_async(
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
    async def test_success_with_enforce_enums_disabled_async(
            self, async_session, sync_session, client):
        token_read_func = AsyncMock()
        token_read_func.return_value = self.token

        token_writes = []


        def token_write_func(token):
            token_writes.append(token)


        client.return_value = 'returned client'
        self.assertEqual('returned client',
                         await auth.client_from_access_functions_async(
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
    async def test_success_with_enforce_enums_enabled_async(
            self, async_session, sync_session, client):
        token_read_func = AsyncMock()
        token_read_func.return_value = self.token

        token_writes = []


        def token_write_func(token):
            token_writes.append(token)


        client.return_value = 'returned client'
        self.assertEqual('returned client',
                         await auth.client_from_access_functions_async(
                             API_KEY,
                             APP_SECRET,
                             token_read_func,
                             token_write_func))

        client.assert_called_once_with(
            API_KEY, _, token_metadata=_, enforce_enums=True)
