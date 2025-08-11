"""Async tests for custom base_url functionality"""

import unittest
from schwab.client.asynchronous import AsyncClient
from unittest.mock import MagicMock


class AsyncCustomBaseUrlTest(unittest.IsolatedAsyncioTestCase):
    """Test that async client HTTP methods use custom base URLs"""

    async def test_async_client_http_methods_use_base_url(self):
        """Test that async client HTTP methods use the base_url"""
        custom_base_url = 'https://proxy.example.com'
        api_key = 'TEST_API_KEY'

        # Create a mock async session
        mock_session = MagicMock()
        mock_response = MagicMock()

        # Mock async methods
        async def mock_get(*args, **kwargs):
            return mock_response
        async def mock_post(*args, **kwargs):
            return mock_response
        async def mock_put(*args, **kwargs):
            return mock_response
        async def mock_delete(*args, **kwargs):
            return mock_response

        mock_session.get = MagicMock(side_effect=mock_get)
        mock_session.post = MagicMock(side_effect=mock_post)
        mock_session.put = MagicMock(side_effect=mock_put)
        mock_session.delete = MagicMock(side_effect=mock_delete)

        # Create async client with custom base URL
        client = AsyncClient(
            api_key=api_key,
            session=mock_session,
            base_url=custom_base_url
        )

        # Test GET request
        await client._get_request('/test/path', {})
        mock_session.get.assert_called_with(
            custom_base_url + '/test/path',
            params={}
        )

        # Test POST request
        await client._post_request('/test/path', {'data': 'test'})
        mock_session.post.assert_called_with(
            custom_base_url + '/test/path',
            json={'data': 'test'}
        )

        # Test PUT request
        await client._put_request('/test/path', {'data': 'test'})
        mock_session.put.assert_called_with(
            custom_base_url + '/test/path',
            json={'data': 'test'}
        )

        # Test DELETE request
        await client._delete_request('/test/path')
        mock_session.delete.assert_called_with(
            custom_base_url + '/test/path'
        )


if __name__ == '__main__':
    unittest.main()
