"""Tests for custom base_url functionality"""

from schwab import auth, DEFAULT_BASE_URL
from schwab.utils import Utils
from unittest.mock import patch, MagicMock, ANY as _
import unittest
import json
import tempfile
import os


class CustomBaseUrlTest(unittest.TestCase):
    """Test that custom base URLs work correctly throughout the system"""

    def setUp(self):
        self.custom_base_url = 'https://proxy.example.com'
        self.api_key = 'TEST_API_KEY'
        self.app_secret = 'TEST_APP_SECRET'
        self.callback_url = 'https://localhost:8080/callback'

        self.tmp_dir = tempfile.TemporaryDirectory()
        self.token_path = os.path.join(self.tmp_dir.name, 'token.json')
        self.token = {
            'token': {'access_token': 'test_token'},
            'creation_timestamp': 1234567890
        }

    def tearDown(self):
        self.tmp_dir.cleanup()

    def write_token(self):
        with open(self.token_path, 'w') as f:
            json.dump(self.token, f)

    @patch('schwab.auth.Client')
    @patch('schwab.auth.OAuth2Client')
    def test_client_from_token_file_with_custom_base_url(self, mock_oauth, mock_client):
        """Test that client_from_token_file passes base_url correctly"""
        self.write_token()

        # Call with custom base URL
        auth.client_from_token_file(
            self.token_path, self.api_key, self.app_secret,
            base_url=self.custom_base_url
        )

        # Verify Client was called with custom base_url
        mock_client.assert_called_once_with(
            self.api_key, _, token_metadata=_, enforce_enums=True,
            base_url=self.custom_base_url
        )

        # Verify OAuth2Client was called with custom token endpoint
        mock_oauth.assert_called_once()
        call_args = mock_oauth.call_args[1]
        self.assertEqual(
            call_args['token_endpoint'],
            self.custom_base_url + '/v1/oauth/token'
        )

    @patch('schwab.auth.Client')
    @patch('schwab.auth.OAuth2Client')
    def test_easy_client_with_custom_base_url(self, mock_oauth, mock_client):
        """Test that easy_client passes base_url through correctly"""
        self.write_token()

        mock_client_instance = MagicMock()
        mock_client.return_value = mock_client_instance
        mock_client_instance.token_age.return_value = 1

        # Call with custom base URL
        auth.easy_client(
            self.api_key, self.app_secret, self.callback_url, self.token_path,
            base_url=self.custom_base_url
        )

        # Verify the client was created with custom base_url
        mock_client.assert_called_once_with(
            self.api_key, _, token_metadata=_, enforce_enums=True,
            base_url=self.custom_base_url
        )

    @patch('schwab.auth.OAuth2Client')
    def test_get_auth_context_with_custom_base_url(self, mock_oauth):
        """Test that get_auth_context uses custom base_url for auth endpoint"""
        mock_oauth_instance = MagicMock()
        mock_oauth.return_value = mock_oauth_instance
        mock_oauth_instance.create_authorization_url.return_value = (
            'https://custom.auth.url', 'state123'
        )

        # Call with custom base URL
        auth.get_auth_context(
            self.api_key, self.callback_url,
            base_url=self.custom_base_url
        )

        # Verify create_authorization_url was called with custom auth endpoint
        mock_oauth_instance.create_authorization_url.assert_called_once_with(
            self.custom_base_url + '/v1/oauth/authorize',
            state=None
        )

    def test_client_http_methods_use_base_url(self):
        """Test that client HTTP methods use the base_url"""
        from schwab.client.synchronous import Client

        # Create a mock session
        mock_session = MagicMock()
        mock_response = MagicMock()
        mock_session.get.return_value = mock_response
        mock_session.post.return_value = mock_response
        mock_session.put.return_value = mock_response
        mock_session.delete.return_value = mock_response

        # Create client with custom base URL
        client = Client(
            api_key=self.api_key,
            session=mock_session,
            base_url=self.custom_base_url
        )

        # Test GET request
        client._get_request('/test/path', {})
        mock_session.get.assert_called_with(
            self.custom_base_url + '/test/path',
            params={}
        )

        # Test POST request
        client._post_request('/test/path', {'data': 'test'})
        mock_session.post.assert_called_with(
            self.custom_base_url + '/test/path',
            json={'data': 'test'}
        )

        # Test PUT request
        client._put_request('/test/path', {'data': 'test'})
        mock_session.put.assert_called_with(
            self.custom_base_url + '/test/path',
            json={'data': 'test'}
        )

        # Test DELETE request
        client._delete_request('/test/path')
        mock_session.delete.assert_called_with(
            self.custom_base_url + '/test/path'
        )

    def test_utils_extract_order_id_with_custom_domain(self):
        """Test that Utils.extract_order_id works with custom domains"""
        # Create a mock client
        mock_client = MagicMock()

        # Create Utils instance
        utils = Utils(mock_client, 'test_account_hash')

        # Test with various custom domains
        test_cases = [
            'https://api.schwabapi.com/trader/v1/accounts/test_account_hash/orders/12345',
            'https://proxy.example.com/trader/v1/accounts/test_account_hash/orders/12345',
            'https://localhost:8080/trader/v1/accounts/test_account_hash/orders/12345',
        ]

        for location_url in test_cases:
            # Create mock response
            mock_response = MagicMock()
            mock_response.is_error = False
            mock_response.headers = {'Location': location_url}

            # Extract order ID
            order_id = utils.extract_order_id(mock_response)

            # Verify it extracted the correct order ID
            self.assertEqual(order_id, 12345)

    def test_default_base_url_unchanged(self):
        """Test that DEFAULT_BASE_URL is still the original value"""
        self.assertEqual(DEFAULT_BASE_URL, 'https://api.schwabapi.com')

    @patch('schwab.auth.Client')
    @patch('schwab.auth.OAuth2Client')
    def test_backwards_compatibility_no_base_url(self, mock_oauth, mock_client):
        """Test that not specifying base_url uses the default"""
        self.write_token()

        # Call without base_url parameter
        auth.client_from_token_file(
            self.token_path, self.api_key, self.app_secret
        )

        # Verify Client was called with default base_url
        mock_client.assert_called_once_with(
            self.api_key, _, token_metadata=_, enforce_enums=True,
            base_url=DEFAULT_BASE_URL
        )

        # Verify OAuth2Client was called with default token endpoint
        mock_oauth.assert_called_once()
        call_args = mock_oauth.call_args[1]
        self.assertEqual(
            call_args['token_endpoint'],
            DEFAULT_BASE_URL + '/v1/oauth/token'
        )


if __name__ == '__main__':
    unittest.main()
