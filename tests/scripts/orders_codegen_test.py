import callee
import httpx
import subprocess
import unittest
from unittest.mock import call, MagicMock, patch

from ..utils import AnyStringWith, no_duplicates
from schwab.scripts.orders_codegen import latest_order_main

class LatestOrderTest(unittest.TestCase):

    def setUp(self):
        self.args = []

    def add_arg(self, arg):
        self.args.append(arg)

    def main(self):
        return latest_order_main(self.args)

    @no_duplicates
    @patch('builtins.print')
    @patch('schwab.scripts.orders_codegen.client_from_token_file')
    @patch('schwab.scripts.orders_codegen.construct_repeat_order')
    @patch('schwab.scripts.orders_codegen.code_for_builder')
    def test_success_no_account_id(
            self,
            mock_code_for_builder,
            mock_construct_repeat_order,
            mock_client_from_token_file,
            mock_print):
        self.add_arg('--token_file')
        self.add_arg('filename.json')
        self.add_arg('--api_key')
        self.add_arg('api-key')
        self.add_arg('--app_secret')
        self.add_arg('app-secret')

        orders = [
                {'orderId': 201},
                {'orderId': 101},
                {'orderId': 301},
                {'orderId': 401},
        ]

        mock_client = MagicMock()
        mock_client_from_token_file.return_value = mock_client
        mock_client.get_orders_for_all_linked_accounts.return_value \
                = httpx.Response(200, json=orders)

        self.assertEqual(self.main(), 0)

        mock_construct_repeat_order.assert_called_once_with(orders[3])
        mock_print.assert_has_calls([
                call('# Order ID', 401),
                call(mock_code_for_builder.return_value)])


    @no_duplicates
    @patch('builtins.print')
    @patch('schwab.scripts.orders_codegen.client_from_token_file')
    @patch('schwab.scripts.orders_codegen.construct_repeat_order')
    @patch('schwab.scripts.orders_codegen.code_for_builder')
    def test_no_account_id_no_recent_orders(
            self,
            mock_code_for_builder,
            mock_construct_repeat_order,
            mock_client_from_token_file,
            mock_print):
        self.add_arg('--token_file')
        self.add_arg('filename.json')
        self.add_arg('--api_key')
        self.add_arg('api-key')
        self.add_arg('--app_secret')
        self.add_arg('app-secret')

        orders = []

        mock_client = MagicMock()
        mock_client_from_token_file.return_value = mock_client
        mock_client.get_orders_for_all_linked_accounts.return_value \
                = httpx.Response(200, json=orders)

        self.assertEqual(self.main(), 0)

        mock_construct_repeat_order.assert_not_called()
        mock_print.assert_called_once_with('No recent orders found')


    @no_duplicates
    @patch('builtins.print')
    @patch('schwab.scripts.orders_codegen.client_from_token_file')
    @patch('schwab.scripts.orders_codegen.construct_repeat_order')
    @patch('schwab.scripts.orders_codegen.code_for_builder')
    def test_no_account_id_error(
            self,
            mock_code_for_builder,
            mock_construct_repeat_order,
            mock_client_from_token_file,
            mock_print):
        self.add_arg('--token_file')
        self.add_arg('filename.json')
        self.add_arg('--api_key')
        self.add_arg('api-key')
        self.add_arg('--app_secret')
        self.add_arg('app-secret')

        orders = {'error': 'invalid'}

        mock_client = MagicMock()
        mock_client_from_token_file.return_value = mock_client
        mock_client.get_orders_for_all_linked_accounts.return_value \
                = httpx.Response(200, json=orders)

        self.assertEqual(self.main(), -1)

        mock_construct_repeat_order.assert_not_called()
        mock_print.assert_called_once_with(
                AnyStringWith('Schwab returned error: "invalid"'))


    @no_duplicates
    @patch('builtins.print')
    @patch('schwab.scripts.orders_codegen.client_from_token_file')
    @patch('schwab.scripts.orders_codegen.construct_repeat_order')
    @patch('schwab.scripts.orders_codegen.code_for_builder')
    def test_account_id_success(
            self,
            mock_code_for_builder,
            mock_construct_repeat_order,
            mock_client_from_token_file,
            mock_print):
        self.add_arg('--token_file')
        self.add_arg('filename.json')
        self.add_arg('--api_key')
        self.add_arg('api-key')
        self.add_arg('--app_secret')
        self.add_arg('app-secret')
        self.add_arg('--account_id')
        self.add_arg('123456')

        orders = [
                {'orderId': 201},
                {'orderId': 101},
                {'orderId': 301},
                {'orderId': 401},
        ]

        mock_client = MagicMock()
        mock_client_from_token_file.return_value = mock_client
        mock_client.get_account_numbers.return_value = httpx.Response(
                200,
                json=[{
                    'accountNumber': '123456',
                    'hashValue': 'hash-value',
                }])
        mock_client.get_orders_for_account.return_value \
                = httpx.Response(200, json=orders)

        self.assertEqual(self.main(), 0)

        mock_client.get_account_numbers.assert_called_once()
        mock_construct_repeat_order.assert_called_once_with(orders[3])
        mock_print.assert_has_calls([
                call('# Order ID', 401),
                call(mock_code_for_builder.return_value)])


    @no_duplicates
    @patch('builtins.print')
    @patch('schwab.scripts.orders_codegen.client_from_token_file')
    @patch('schwab.scripts.orders_codegen.construct_repeat_order')
    @patch('schwab.scripts.orders_codegen.code_for_builder')
    def test_account_id_no_corresponding_hash(
            self,
            mock_code_for_builder,
            mock_construct_repeat_order,
            mock_client_from_token_file,
            mock_print):
        self.add_arg('--token_file')
        self.add_arg('filename.json')
        self.add_arg('--api_key')
        self.add_arg('api-key')
        self.add_arg('--app_secret')
        self.add_arg('app-secret')
        self.add_arg('--account_id')
        self.add_arg('123456')

        orders = [
                {'orderId': 201},
                {'orderId': 101},
                {'orderId': 301},
                {'orderId': 401},
        ]

        mock_client = MagicMock()
        mock_client_from_token_file.return_value = mock_client
        mock_client.get_account_numbers.return_value = httpx.Response(
                200,
                json=[{
                    'accountNumber': '90009',
                    'hashValue': 'hash-value',
                }])
        mock_client.get_orders_for_account.return_value \
                = httpx.Response(200, json=orders)

        self.assertEqual(self.main(), -1)

        mock_client.get_account_numbers.assert_called_once()
        mock_print.assert_called_once_with(
                AnyStringWith('Failed to find account has for account ID'))


    @no_duplicates
    @patch('builtins.print')
    @patch('schwab.scripts.orders_codegen.client_from_token_file')
    @patch('schwab.scripts.orders_codegen.construct_repeat_order')
    @patch('schwab.scripts.orders_codegen.code_for_builder')
    def test_account_id_no_orders(
            self,
            mock_code_for_builder,
            mock_construct_repeat_order,
            mock_client_from_token_file,
            mock_print):
        self.add_arg('--token_file')
        self.add_arg('filename.json')
        self.add_arg('--api_key')
        self.add_arg('api-key')
        self.add_arg('--app_secret')
        self.add_arg('app-secret')
        self.add_arg('--account_id')
        self.add_arg('123456')

        orders = []

        mock_client = MagicMock()
        mock_client_from_token_file.return_value = mock_client
        mock_client.get_account_numbers.return_value = httpx.Response(
                200,
                json=[{
                    'accountNumber': '123456',
                    'hashValue': 'hash-value',
                }])
        mock_client.get_orders_for_account.return_value \
                = httpx.Response(200, json=orders)

        self.assertEqual(self.main(), 0)

        mock_construct_repeat_order.assert_not_called
        mock_print.assert_called_once_with('No recent orders found')


    @no_duplicates
    @patch('builtins.print')
    @patch('schwab.scripts.orders_codegen.client_from_token_file')
    @patch('schwab.scripts.orders_codegen.construct_repeat_order')
    @patch('schwab.scripts.orders_codegen.code_for_builder')
    def test_account_id_error(
            self,
            mock_code_for_builder,
            mock_construct_repeat_order,
            mock_client_from_token_file,
            mock_print):
        self.add_arg('--token_file')
        self.add_arg('filename.json')
        self.add_arg('--api_key')
        self.add_arg('api-key')
        self.add_arg('--app_secret')
        self.add_arg('app-secret')
        self.add_arg('--account_id')
        self.add_arg('123456')

        mock_client = MagicMock()
        mock_client_from_token_file.return_value = mock_client
        mock_client.get_account_numbers.return_value = httpx.Response(
                200,
                json=[{
                    'accountNumber': '123456',
                    'hashValue': 'hash-value',
                }])
        mock_client.get_orders_for_account.return_value \
                = httpx.Response(200, json={'error': 'invalid'})

        self.assertEqual(self.main(), -1)

        mock_construct_repeat_order.assert_not_called
        mock_print.assert_called_once_with(
                AnyStringWith('Schwab returned error: "invalid"'))


    @no_duplicates
    @patch('builtins.print')
    @patch('schwab.scripts.orders_codegen.client_from_token_file')
    @patch('schwab.scripts.orders_codegen.construct_repeat_order')
    @patch('schwab.scripts.orders_codegen.code_for_builder')
    def test_success_account_hash(
            self,
            mock_code_for_builder,
            mock_construct_repeat_order,
            mock_client_from_token_file,
            mock_print):
        self.add_arg('--token_file')
        self.add_arg('filename.json')
        self.add_arg('--api_key')
        self.add_arg('api-key')
        self.add_arg('--app_secret')
        self.add_arg('app-secret')
        self.add_arg('--account_hash')
        self.add_arg('account-hash')

        orders = [
                {'orderId': 201},
                {'orderId': 101},
                {'orderId': 301},
                {'orderId': 401},
        ]

        mock_client = MagicMock()
        mock_client_from_token_file.return_value = mock_client
        mock_client.get_orders_for_account.return_value \
                = httpx.Response(200, json=orders)

        self.assertEqual(self.main(), 0)

        mock_construct_repeat_order.assert_called_once_with(orders[3])
        mock_print.assert_has_calls([
                call('# Order ID', 401),
                call(mock_code_for_builder.return_value)])


    @no_duplicates
    @patch('builtins.print')
    @patch('schwab.scripts.orders_codegen.client_from_token_file')
    @patch('schwab.scripts.orders_codegen.construct_repeat_order')
    @patch('schwab.scripts.orders_codegen.code_for_builder')
    def test_order_fetching_fails_no_account_id(
            self,
            mock_code_for_builder,
            mock_construct_repeat_order,
            mock_client_from_token_file,
            mock_print):
        self.add_arg('--token_file')
        self.add_arg('filename.json')
        self.add_arg('--api_key')
        self.add_arg('api-key')
        self.add_arg('--app_secret')
        self.add_arg('app-secret')

        mock_client = MagicMock()
        mock_client_from_token_file.return_value = mock_client
        mock_client.get_orders_for_all_linked_accounts.return_value \
                = httpx.Response(400)

        self.assertEqual(self.main(), -1)

        mock_print.assert_called_once_with(
                AnyStringWith('Returned HTTP status code 400'))


    @no_duplicates
    @patch('builtins.print')
    @patch('schwab.scripts.orders_codegen.client_from_token_file')
    @patch('schwab.scripts.orders_codegen.construct_repeat_order')
    @patch('schwab.scripts.orders_codegen.code_for_builder')
    def test_order_fetching_fails_account_id(
            self,
            mock_code_for_builder,
            mock_construct_repeat_order,
            mock_client_from_token_file,
            mock_print):
        self.add_arg('--token_file')
        self.add_arg('filename.json')
        self.add_arg('--api_key')
        self.add_arg('api-key')
        self.add_arg('--app_secret')
        self.add_arg('app-secret')
        self.add_arg('--account_id')
        self.add_arg('123456')

        mock_client = MagicMock()
        mock_client_from_token_file.return_value = mock_client
        mock_client.get_account_numbers.return_value = httpx.Response(
                200,
                json=[{
                    'accountNumber': '123456',
                    'hashValue': 'hash-value',
                }])
        mock_client.get_orders_for_account.return_value = httpx.Response(400)

        self.assertEqual(self.main(), -1)

        mock_print.assert_called_once_with(
                AnyStringWith('Returned HTTP status code 400'))


    @no_duplicates
    @patch('builtins.print')
    @patch('schwab.scripts.orders_codegen.client_from_token_file')
    @patch('schwab.scripts.orders_codegen.construct_repeat_order')
    @patch('schwab.scripts.orders_codegen.code_for_builder')
    def test_warn_on_non_auto_requestedDestination(
            self,
            mock_code_for_builder,
            mock_construct_repeat_order,
            mock_client_from_token_file,
            mock_print):
        self.add_arg('--token_file')
        self.add_arg('filename.json')
        self.add_arg('--api_key')
        self.add_arg('api-key')
        self.add_arg('--app_secret')
        self.add_arg('app-secret')
        self.add_arg('--account_hash')
        self.add_arg('account-hash')

        orders = [
                {'orderId': 401,
                 'requestedDestination': 'not AUTO'},
        ]

        mock_client = MagicMock()
        mock_client_from_token_file.return_value = mock_client
        mock_client.get_orders_for_account.return_value \
                = httpx.Response(200, json=orders)

        self.assertEqual(self.main(), 0)

        mock_construct_repeat_order.assert_called_once_with(orders[0])
        mock_print.assert_has_calls([
                call(callee.Contains('requestedDestination')),
                call(callee.Contains('broken')),
                call(),
                call('# Order ID', 401),
                call(mock_code_for_builder.return_value)])


    @no_duplicates
    @patch('builtins.print')
    @patch('schwab.scripts.orders_codegen.client_from_token_file')
    @patch('schwab.scripts.orders_codegen.construct_repeat_order')
    @patch('schwab.scripts.orders_codegen.code_for_builder')
    def test_warn_on_non_auto_destinationLinkName(
            self,
            mock_code_for_builder,
            mock_construct_repeat_order,
            mock_client_from_token_file,
            mock_print):
        self.add_arg('--token_file')
        self.add_arg('filename.json')
        self.add_arg('--api_key')
        self.add_arg('api-key')
        self.add_arg('--app_secret')
        self.add_arg('app-secret')
        self.add_arg('--account_hash')
        self.add_arg('account-hash')

        orders = [
                {'orderId': 401,
                 'destinationLinkName': 'not AUTO'},
        ]

        mock_client = MagicMock()
        mock_client_from_token_file.return_value = mock_client
        mock_client.get_orders_for_account.return_value \
                = httpx.Response(200, json=orders)

        self.assertEqual(self.main(), 0)

        mock_construct_repeat_order.assert_called_once_with(orders[0])
        mock_print.assert_has_calls([
                call(callee.Contains('destinationLinkName')),
                call(callee.Contains('broken')),
                call(),
                call('# Order ID', 401),
                call(mock_code_for_builder.return_value)])


class ScriptInvocationTest(unittest.TestCase):

    def test_get_help(self):
        output = subprocess.check_output(
                'schwab-order-codegen.py --help',
                shell=True, text=True)
