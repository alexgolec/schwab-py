from schwab import auth
from schwab.auth import TokenMetadata
from schwab.client import AsyncClient, Client
from schwab.utils import TokenRevocationError, TokenRevokedError
from .utils import (
        AsyncMagicMock,
        MockResponse,
        ResyncProxy,
        no_duplicates,
)
from unittest.mock import MagicMock, patch

import httpx2
import json
import os
import tempfile
import unittest


API_KEY = 'APIKEY'
APP_SECRET = '0x5EC07'
CALLBACK_URL = 'https://127.0.0.1:8182'
TOKEN_CREATION_TIMESTAMP = 1613745000
REVOKE_URL = 'https://api.schwabapi.com/v1/oauth/revoke'

RAW_TOKEN = {
    'access_token': 'ACCESS_TOKEN',
    'refresh_token': 'REFRESH_TOKEN',
    'token_type': 'Bearer',
    'expires_in': 1800,
}


class SyncRevokeTest(unittest.TestCase):

    def setUp(self):
        self.mock_session = MagicMock()
        self.writes = []
        self.metadata = TokenMetadata(
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
        self.assertEqual(
                [{'creation_timestamp': TOKEN_CREATION_TIMESTAMP,
                  'revoked': True}],
                self.writes)
        self.assertTrue(self.metadata.revoked)
        self.assertIsNone(self.metadata.token)

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
                token_metadata=TokenMetadata(
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
            metadata = TokenMetadata(
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


class AsyncRevokeTest(unittest.TestCase):

    def setUp(self):
        self.mock_session = AsyncMagicMock()
        self.writes = []
        self.metadata = TokenMetadata(
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
        self.assertEqual(
                [{'creation_timestamp': TOKEN_CREATION_TIMESTAMP,
                  'revoked': True}],
                self.writes)
        self.assertTrue(self.metadata.revoked)
        self.assertIsNone(self.metadata.token)

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


class RevokedTokenLoadTest(unittest.TestCase):

    def setUp(self):
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.token_path = os.path.join(self.tmp_dir.name, 'token.json')
        self.writes = []

    def _write_token_file(self, obj):
        with open(self.token_path, 'w') as f:
            json.dump(obj, f)

    @no_duplicates
    def test_secretless_tombstone_loads_as_revoked(self):
        metadata = TokenMetadata.from_loaded_token(
                {'creation_timestamp': TOKEN_CREATION_TIMESTAMP,
                 'revoked': True},
                self.writes.append)
        self.assertTrue(metadata.revoked)
        self.assertIsNone(metadata.token)

    @no_duplicates
    def test_retained_tombstone_loads_as_revoked(self):
        # A tombstone written by a version that retained the credential
        # must load as revoked and drop the token.
        metadata = TokenMetadata.from_loaded_token(
                {'creation_timestamp': TOKEN_CREATION_TIMESTAMP,
                 'revoked': True,
                 'token': dict(RAW_TOKEN)},
                self.writes.append)
        self.assertTrue(metadata.revoked)
        self.assertIsNone(metadata.token)

    @no_duplicates
    def test_non_bool_revoked_rejected(self):
        for bogus in ('true', 1, {'revoked': True}):
            with self.assertRaises(ValueError):
                TokenMetadata.from_loaded_token(
                        {'creation_timestamp': TOKEN_CREATION_TIMESTAMP,
                         'revoked': bogus,
                         'token': dict(RAW_TOKEN)},
                        self.writes.append)

    @no_duplicates
    def test_access_functions_refuses_tombstone(self):
        tombstone = {'creation_timestamp': TOKEN_CREATION_TIMESTAMP,
                     'revoked': True}
        with self.assertRaises(TokenRevokedError):
            auth.client_from_access_functions(
                    API_KEY, APP_SECRET, lambda: tombstone,
                    self.writes.append)

    @no_duplicates
    def test_token_file_refuses_tombstone(self):
        self._write_token_file(
                {'creation_timestamp': TOKEN_CREATION_TIMESTAMP,
                 'revoked': True})
        with self.assertRaises(TokenRevokedError):
            auth.client_from_token_file(
                    self.token_path, API_KEY, APP_SECRET)

    @no_duplicates
    @patch('schwab.auth.client_from_login_flow')
    def test_easy_client_falls_through_to_login(
            self, client_from_login_flow):
        self._write_token_file(
                {'creation_timestamp': TOKEN_CREATION_TIMESTAMP,
                 'revoked': True})
        mock_client = MagicMock()
        client_from_login_flow.return_value = mock_client

        c = auth.easy_client(
                API_KEY, APP_SECRET, CALLBACK_URL, self.token_path)
        self.assertIs(c, mock_client)
        client_from_login_flow.assert_called_once()


if __name__ == '__main__':
    unittest.main()
