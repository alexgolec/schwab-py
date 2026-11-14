import argparse
import unittest
from unittest.mock import patch

from schwab.scripts import generate_token


class GenerateTokenTest(unittest.TestCase):

    @patch('schwab.scripts.generate_token.argparse.ArgumentParser.parse_args')
    @patch('schwab.scripts.generate_token.schwab')
    def test_login_flow_success(self, mock_schwab, mock_parse_args):
        mock_parse_args.return_value = argparse.Namespace(
                token_file='token.json', api_key='API_KEY',
                app_secret='APP_SECRET',
                callback_url='https://127.0.0.1:8182/callback',
                browser='firefox')

        self.assertEqual(0, generate_token.main())

        mock_schwab.auth.client_from_login_flow.assert_called_once_with(
                'API_KEY', 'APP_SECRET', 'https://127.0.0.1:8182/callback',
                'token.json', requested_browser='firefox',
                callback_timeout=300)
        mock_schwab.auth.client_from_manual_flow.assert_not_called()

    @patch('schwab.scripts.generate_token.argparse.ArgumentParser.parse_args')
    @patch('schwab.scripts.generate_token.schwab')
    def test_login_flow_failure_falls_back_to_manual(
            self, mock_schwab, mock_parse_args):
        mock_parse_args.return_value = argparse.Namespace(
                token_file='token.json', api_key='API_KEY',
                app_secret='APP_SECRET',
                callback_url='https://127.0.0.1:8182/callback',
                browser='firefox')
        mock_schwab.auth.client_from_login_flow.side_effect = Exception

        self.assertEqual(0, generate_token.main())

        mock_schwab.auth.client_from_manual_flow.assert_called_once_with(
                'API_KEY', 'APP_SECRET', 'https://127.0.0.1:8182/callback',
                'token.json')
