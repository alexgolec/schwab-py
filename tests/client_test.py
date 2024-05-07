import asyncio
import datetime
import logging
import os
import pytest
import pytz
import unittest
from unittest.mock import ANY, MagicMock, Mock, patch

from schwab.client import AsyncClient, Client
from schwab.orders.generic import OrderBuilder

from .utils import AsyncMagicMock, ResyncProxy, no_duplicates

# Constants

API_KEY = '1234567890'
ACCOUNT_ID = 100000
ACCOUNT_HASH = '0x0x0x0x10000'
ORDER_ID = 200000
SAVED_ORDER_ID = 300000
CUSIP = '000919239'
MARKET = 'EQUITY'
INDEX = '$SPX.X'
SYMBOL = 'AAPL'
TRANSACTION_ID = 400000
WATCHLIST_ID = 5000000

MIN_DATETIME = datetime.datetime(year=1971, month=1, day=1)
MIN_ISO = '1971-01-01T00:00:00+0000'
MIN_TIMESTAMP_MILLIS = int(MIN_DATETIME.timestamp()) * 1000

NOW_DATETIME = datetime.datetime(2020, 1, 2, 3, 4, 5)
NOW_DATE = datetime.date(2020, 1, 2)
NOW_DATETIME_ISO = '2020-01-02T03:04:05Z'
NOW_DATETIME_TRUNCATED_ISO = '2020-01-02T00:00:00Z'
NOW_DATE_ISO = '2020-01-02'

NOW_DATETIME_MINUS_60_DAYS = NOW_DATE - datetime.timedelta(days=60)
NOW_DATETIME_MINUS_60_DAYS_ISO = '2019-11-03T03:04:05Z'

NOW_DATETIME_PLUS_SEVEN_DAYS_TIMESTAMP_MILLIS = \
        int((NOW_DATETIME + datetime.timedelta(days=7)).timestamp()) * 1000


class mockdatetime(datetime.datetime):
    @classmethod
    def utcnow(cls):
        return NOW_DATETIME

    @classmethod
    def now(cls, timezone):
        return NOW_DATETIME


EARLIER_DATETIME = datetime.datetime(2001, 1, 2, 3, 4, 5,
                                     tzinfo=pytz.timezone('America/New_York'))
EARLIER_ISO = '2001-01-02T03:04:05-0456'
EARLIER_MILLIS = 978422405000
EARLIER_DATE_STR = '2001-01-02'

class _TestClient:
    """
    Test suite used for both Client and AsyncClient
    """

    def setUp(self):
        self.mock_session = self.magicmock_class()
        self.client = self.client_class(API_KEY, self.mock_session)

        # Set the logging level to DEBUG to force all lazily-evaluated messages
        # to be evaluated
        self.client.logger.setLevel('DEBUG')

    def make_url(self, path):
        path = path.format(
            accountId=ACCOUNT_ID,
            accountHash=ACCOUNT_HASH,
            orderId=ORDER_ID,
            savedOrderId=SAVED_ORDER_ID,
            cusip=CUSIP,
            market=MARKET,
            index=INDEX,
            symbol=SYMBOL,
            transactionId=TRANSACTION_ID,
            watchlistId=WATCHLIST_ID)
        return 'https://api.schwabapi.com' + path


    # Generic functionality


    def test_set_timeout(self):
        timeout = 'dummy'
        self.client.set_timeout(timeout)
        self.assertEqual(timeout, self.client.session.timeout)


    # get_account


    def test_get_account(self):
        self.client.get_account(ACCOUNT_HASH)
        self.mock_session.get.assert_called_once_with(
            self.make_url('/trader/v1/accounts/{accountHash}'), params={})

    
    def test_get_account_fields(self):
        self.client.get_account(ACCOUNT_HASH, fields=[
            self.client_class.Account.Fields.POSITIONS])
        self.mock_session.get.assert_called_once_with(
            self.make_url('/trader/v1/accounts/{accountHash}'),
            params={'fields': 'positions'})


    def test_get_account_fields_scalar(self):
        self.client.get_account(
                ACCOUNT_HASH, fields=self.client_class.Account.Fields.POSITIONS)
        self.mock_session.get.assert_called_once_with(
            self.make_url('/trader/v1/accounts/{accountHash}'),
            params={'fields': 'positions'})


    def test_get_account_fields_unchecked(self):
        self.client.set_enforce_enums(False)
        self.client.get_account(ACCOUNT_HASH, fields=['positions'])
        self.mock_session.get.assert_called_once_with(
            self.make_url('/trader/v1/accounts/{accountHash}'),
            params={'fields': 'positions'})


    # get_account_numbers

    def test_get_account_numbers(self):
        self.client.get_account_numbers()
        self.mock_session.get.assert_called_with(
                self.make_url('/trader/v1/accounts/accountNumbers'), params={})


    # get_accounts


    def test_get_accounts(self):
        self.client.get_accounts()
        self.mock_session.get.assert_called_once_with(
            self.make_url('/trader/v1/accounts'), params={})


    def test_get_accounts_fields(self):
        self.client.get_accounts(fields=[
            self.client_class.Account.Fields.POSITIONS])
        self.mock_session.get.assert_called_once_with(
            self.make_url('/trader/v1/accounts'),
            params={'fields': 'positions'})


    def test_get_accounts_fields_scalar(self):
        self.client.get_accounts(fields=self.client_class.Account.Fields.POSITIONS)
        self.mock_session.get.assert_called_once_with(
            self.make_url('/trader/v1/accounts'),
            params={'fields': 'positions'})


    def test_get_accounts_fields_unchecked(self):
        self.client.set_enforce_enums(False)
        self.client.get_accounts(fields=['positions'])
        self.mock_session.get.assert_called_once_with(
            self.make_url('/trader/v1/accounts'),
            params={'fields': 'positions'})

    # get_order

    
    def test_get_order(self):
        self.client.get_order(ORDER_ID, ACCOUNT_HASH)
        self.mock_session.get.assert_called_once_with(
            self.make_url('/trader/v1/accounts/{accountHash}/orders/{orderId}'),
            params={})

    def test_get_order_str(self):
        self.client.get_order(str(ORDER_ID), str(ACCOUNT_HASH))
        self.mock_session.get.assert_called_once_with(
            self.make_url('/trader/v1/accounts/{accountHash}/orders/{orderId}'),
            params={})

    # cancel_order

    def test_cancel_order(self):
        self.client.cancel_order(ORDER_ID, ACCOUNT_HASH)
        self.mock_session.delete.assert_called_once_with(
            self.make_url('/trader/v1/accounts/{accountHash}/orders/{orderId}'))

    def test_cancel_order_str(self):
        self.client.cancel_order(str(ORDER_ID), str(ACCOUNT_HASH))
        self.mock_session.delete.assert_called_once_with(
            self.make_url('/trader/v1/accounts/{accountHash}/orders/{orderId}'))

    # get_orders_for_account

    @patch('schwab.client.base.datetime.datetime', mockdatetime)
    def test_get_orders_for_account_vanilla(self):
        self.client.get_orders_for_account(ACCOUNT_HASH)
        self.mock_session.get.assert_called_once_with(
            self.make_url('/trader/v1/accounts/{accountHash}/orders'), params={
                'fromEnteredTime': NOW_DATETIME_MINUS_60_DAYS_ISO,
                'toEnteredTime': NOW_DATETIME_ISO
            })


    @patch('schwab.client.base.datetime.datetime', mockdatetime)
    def test_get_orders_for_account_from_not_datetime(self):
        with self.assertRaises(ValueError) as cm:
            self.client.get_orders_for_account(
                    ACCOUNT_HASH, from_entered_datetime='2020-01-02')
        self.assertEqual(
                str(cm.exception),
                "expected type in (datetime.date, datetime.datetime) for " +
                "from_entered_datetime, got 'builtins.str'")


    @patch('schwab.client.base.datetime.datetime', mockdatetime)
    def test_get_orders_for_account_to_not_datetime(self):
        with self.assertRaises(ValueError) as cm:
            self.client.get_orders_for_account(
                    ACCOUNT_HASH, to_entered_datetime='2020-01-02')
        self.assertEqual(
                str(cm.exception),
                "expected type in (datetime.date, datetime.datetime) for " +
                "to_entered_datetime, got 'builtins.str'")


    @patch('schwab.client.base.datetime.datetime', mockdatetime)
    def test_get_orders_for_account_max_results(self):
        self.client.get_orders_for_account(ACCOUNT_HASH, max_results=100)
        self.mock_session.get.assert_called_once_with(
            self.make_url('/trader/v1/accounts/{accountHash}/orders'), params={
                'fromEnteredTime': NOW_DATETIME_MINUS_60_DAYS_ISO,
                'toEnteredTime': NOW_DATETIME_ISO,
                'maxResults': 100,
            })


    @patch('schwab.client.base.datetime.datetime', mockdatetime)
    def test_get_orders_for_account_from_entered_datetime(self):
        self.client.get_orders_for_account(
                ACCOUNT_HASH, from_entered_datetime=datetime.datetime(
                    year=2024, month=6, day=5, hour=4, minute=3, second=2))
        self.mock_session.get.assert_called_once_with(
            self.make_url('/trader/v1/accounts/{accountHash}/orders'), params={
                'fromEnteredTime': '2024-06-05T04:03:02Z',
                'toEnteredTime': NOW_DATETIME_ISO,
            })


    @patch('schwab.client.base.datetime.datetime', mockdatetime)
    def test_get_orders_for_account_to_entered_datetime(self):
        self.client.get_orders_for_account(
                ACCOUNT_HASH, to_entered_datetime=datetime.datetime(
                    year=2024, month=6, day=5, hour=4, minute=3, second=2))
        self.mock_session.get.assert_called_once_with(
            self.make_url('/trader/v1/accounts/{accountHash}/orders'), params={
                'fromEnteredTime': NOW_DATETIME_MINUS_60_DAYS_ISO,
                'toEnteredTime': '2024-06-05T04:03:02Z',
            })


    @patch('schwab.client.base.datetime.datetime', mockdatetime)
    def test_get_orders_for_account_status(self):
        self.client.get_orders_for_account(
                ACCOUNT_HASH, status=self.client_class.Order.Status.FILLED)
        self.mock_session.get.assert_called_once_with(
            self.make_url('/trader/v1/accounts/{accountHash}/orders'), params={
                'fromEnteredTime': NOW_DATETIME_MINUS_60_DAYS_ISO,
                'toEnteredTime': NOW_DATETIME_ISO,
                'status': 'FILLED'
            })


    @patch('schwab.client.base.datetime.datetime', mockdatetime)
    def test_get_orders_for_account_multiple_statuses(self):
        with self.assertRaises(ValueError) as cm:
            self.client.get_orders_for_account(
                    ACCOUNT_HASH,
                    status=[self.client_class.Order.Status.FILLED,
                            self.client_class.Order.Status.REJECTED])
        self.assertIn(
                'expected type "Status", got type "list"',
                str(cm.exception))


    @patch('schwab.client.base.datetime.datetime', mockdatetime)
    def test_get_orders_for_account_status_unchecked(self):
        self.client.set_enforce_enums(False)
        self.client.get_orders_for_account(ACCOUNT_HASH, status='NOT_A_STATUS')
        self.mock_session.get.assert_called_once_with(
            self.make_url('/trader/v1/accounts/{accountHash}/orders'), params={
                'fromEnteredTime': NOW_DATETIME_MINUS_60_DAYS_ISO,
                'toEnteredTime': NOW_DATETIME_ISO,
                'status': 'NOT_A_STATUS'
            })


    # get_orders_for_all_linked_accounts

    @patch('schwab.client.base.datetime.datetime', mockdatetime)
    def test_get_orders_for_all_linked_accounts_vanilla(self):
        self.client.get_orders_for_all_linked_accounts()
        self.mock_session.get.assert_called_once_with(
            self.make_url('/trader/v1/orders'), params={
                'fromEnteredTime': NOW_DATETIME_MINUS_60_DAYS_ISO,
                'toEnteredTime': NOW_DATETIME_ISO
            })


    @patch('schwab.client.base.datetime.datetime', mockdatetime)
    def test_get_orders_for_all_linked_accounts_from_not_datetime(self):
        with self.assertRaises(ValueError) as cm:
            self.client.get_orders_for_all_linked_accounts(
                    from_entered_datetime='2020-01-02')
        self.assertEqual(
                str(cm.exception),
                "expected type in (datetime.date, datetime.datetime) for " +
                "from_entered_datetime, got 'builtins.str'")


    @patch('schwab.client.base.datetime.datetime', mockdatetime)
    def test_get_orders_for_all_linked_accounts_to_not_datetime(self):
        with self.assertRaises(ValueError) as cm:
            self.client.get_orders_for_all_linked_accounts(
                    to_entered_datetime='2020-01-02')
        self.assertEqual(
                str(cm.exception),
                "expected type in (datetime.date, datetime.datetime) for " +
                "to_entered_datetime, got 'builtins.str'")


    @patch('schwab.client.base.datetime.datetime', mockdatetime)
    def test_get_orders_for_all_linked_accounts_max_results(self):
        self.client.get_orders_for_all_linked_accounts(max_results=100)
        self.mock_session.get.assert_called_once_with(
            self.make_url('/trader/v1/orders'), params={
                'fromEnteredTime': NOW_DATETIME_MINUS_60_DAYS_ISO,
                'toEnteredTime': NOW_DATETIME_ISO,
                'maxResults': 100,
            })


    @patch('schwab.client.base.datetime.datetime', mockdatetime)
    def test_get_orders_for_all_linked_accounts_from_entered_datetime(self):
        self.client.get_orders_for_all_linked_accounts(
                from_entered_datetime=datetime.datetime(
                    year=2024, month=6, day=5, hour=4, minute=3, second=2))
        self.mock_session.get.assert_called_once_with(
            self.make_url('/trader/v1/orders'), params={
                'fromEnteredTime': '2024-06-05T04:03:02Z',
                'toEnteredTime': NOW_DATETIME_ISO,
            })


    @patch('schwab.client.base.datetime.datetime', mockdatetime)
    def test_get_orders_for_all_linked_accounts_to_entered_datetime(self):
        self.client.get_orders_for_all_linked_accounts(
                to_entered_datetime=datetime.datetime(
                    year=2024, month=6, day=5, hour=4, minute=3, second=2))
        self.mock_session.get.assert_called_once_with(
            self.make_url('/trader/v1/orders'), params={
                'fromEnteredTime': NOW_DATETIME_MINUS_60_DAYS_ISO,
                'toEnteredTime': '2024-06-05T04:03:02Z',
            })


    @patch('schwab.client.base.datetime.datetime', mockdatetime)
    def test_get_orders_for_all_linked_accounts_status(self):
        self.client.get_orders_for_all_linked_accounts(
                status=self.client_class.Order.Status.FILLED)
        self.mock_session.get.assert_called_once_with(
            self.make_url('/trader/v1/orders'), params={
                'fromEnteredTime': NOW_DATETIME_MINUS_60_DAYS_ISO,
                'toEnteredTime': NOW_DATETIME_ISO,
                'status': 'FILLED'
            })


    @patch('schwab.client.base.datetime.datetime', mockdatetime)
    def test_get_orders_for_all_linked_accounts_multiple_statuses(self):
        with self.assertRaises(ValueError) as cm:
            self.client.get_orders_for_all_linked_accounts(
                    status=[self.client_class.Order.Status.FILLED,
                            self.client_class.Order.Status.REJECTED])
        self.assertIn(
                'expected type "Status", got type "list"',
                str(cm.exception))


    @patch('schwab.client.base.datetime.datetime', mockdatetime)
    def test_get_orders_for_all_linked_accounts_status_unchecked(self):
        self.client.set_enforce_enums(False)
        self.client.get_orders_for_all_linked_accounts(status='NOT_A_STATUS')
        self.mock_session.get.assert_called_once_with(
            self.make_url('/trader/v1/orders'), params={
                'fromEnteredTime': NOW_DATETIME_MINUS_60_DAYS_ISO,
                'toEnteredTime': NOW_DATETIME_ISO,
                'status': 'NOT_A_STATUS'
            })


    # place_order

    
    def test_place_order(self):
        order_spec = {'order': 'spec'}
        self.client.place_order(ACCOUNT_HASH, order_spec)
        self.mock_session.post.assert_called_once_with(
            self.make_url('/trader/v1/accounts/{accountHash}/orders'), json=order_spec)

    
    def test_place_order_order_builder(self):
        order_spec = OrderBuilder(enforce_enums=False).set_order_type('LIMIT')
        expected_spec = {'orderType': 'LIMIT'}
        self.client.place_order(ACCOUNT_HASH, order_spec)
        self.mock_session.post.assert_called_once_with(
            self.make_url('/trader/v1/accounts/{accountHash}/orders'),
            json=expected_spec)

    
    def test_place_order_str(self):
        order_spec = {'order': 'spec'}
        self.client.place_order(str(ACCOUNT_HASH), order_spec)
        self.mock_session.post.assert_called_once_with(
            self.make_url('/trader/v1/accounts/{accountHash}/orders'), json=order_spec)

    # replace_order

    
    def test_replace_order(self):
        order_spec = {'order': 'spec'}
        self.client.replace_order(ACCOUNT_HASH, ORDER_ID, order_spec)
        self.mock_session.put.assert_called_once_with(
            self.make_url('/trader/v1/accounts/{accountHash}/orders/{orderId}'),
            json=order_spec)

    
    def test_replace_order_order_builder(self):
        order_spec = OrderBuilder(enforce_enums=False).set_order_type('LIMIT')
        expected_spec = {'orderType': 'LIMIT'}
        self.client.replace_order(ACCOUNT_HASH, ORDER_ID, order_spec)
        self.mock_session.put.assert_called_once_with(
            self.make_url('/trader/v1/accounts/{accountHash}/orders/{orderId}'),
            json=expected_spec)

    
    def test_replace_order_str(self):
        order_spec = {'order': 'spec'}
        self.client.replace_order(str(ACCOUNT_HASH), str(ORDER_ID), order_spec)
        self.mock_session.put.assert_called_once_with(
            self.make_url('/trader/v1/accounts/{accountHash}/orders/{orderId}'),
            json=order_spec)


    # preview_order

    
    def test_preview_order(self):
        order_spec = {'order': 'spec'}
        self.client.preview_order(ACCOUNT_HASH, order_spec)
        self.mock_session.post.assert_called_once_with(
            self.make_url('/trader/v1/accounts/{accountHash}/previewOrder'),
            json=order_spec)

    
    def test_preview_order_order_builder(self):
        order_spec = OrderBuilder(enforce_enums=False).set_order_type('LIMIT')
        expected_spec = {'orderType': 'LIMIT'}
        self.client.preview_order(ACCOUNT_HASH, order_spec)
        self.mock_session.post.assert_called_once_with(
            self.make_url('/trader/v1/accounts/{accountHash}/previewOrder'),
            json=expected_spec)

    
    # get_transactions

    
    @patch('schwab.client.base.datetime.datetime', mockdatetime)
    def test_get_transactions(self):
        self.client.get_transactions(ACCOUNT_HASH)
        self.mock_session.get.assert_called_once_with(
            self.make_url('/trader/v1/accounts/{accountHash}/transactions'),
            params={
                'types': ','.join(t.value for t in self.client.Transactions.TransactionType),
                'startDate': NOW_DATETIME_MINUS_60_DAYS_ISO,
                'endDate': NOW_DATETIME_ISO})


    @patch('schwab.client.base.datetime.datetime', mockdatetime)
    def test_get_transactions_one_type(self):
        self.client.get_transactions(
                ACCOUNT_HASH, 
                transaction_types=self.client.Transactions.TransactionType.TRADE)
        self.mock_session.get.assert_called_once_with(
            self.make_url('/trader/v1/accounts/{accountHash}/transactions'),
            params={
                'types': 'TRADE',
                'startDate': NOW_DATETIME_MINUS_60_DAYS_ISO,
                'endDate': NOW_DATETIME_ISO})


    @patch('schwab.client.base.datetime.datetime', mockdatetime)
    def test_get_transactions_type_list(self):
        self.client.get_transactions(
                ACCOUNT_HASH, 
                transaction_types=[
                    self.client.Transactions.TransactionType.TRADE,
                    self.client.Transactions.TransactionType.JOURNAL])
        self.mock_session.get.assert_called_once_with(
            self.make_url('/trader/v1/accounts/{accountHash}/transactions'),
            params={
                'types': 'TRADE,JOURNAL',
                'startDate': NOW_DATETIME_MINUS_60_DAYS_ISO,
                'endDate': NOW_DATETIME_ISO})


    @patch('schwab.client.base.datetime.datetime', mockdatetime)
    def test_get_transactions_type_list_unchecked(self):
        self.client.set_enforce_enums(False)
        self.client.get_transactions(
                ACCOUNT_HASH, transaction_types=['TRADE', 'JOURNAL'])
        self.mock_session.get.assert_called_once_with(
            self.make_url('/trader/v1/accounts/{accountHash}/transactions'),
            params={
                'types': 'TRADE,JOURNAL',
                'startDate': NOW_DATETIME_MINUS_60_DAYS_ISO,
                'endDate': NOW_DATETIME_ISO})


    @patch('schwab.client.base.datetime.datetime', mockdatetime)
    def test_get_transactions_symbol(self):
        self.client.get_transactions(ACCOUNT_HASH, symbol='AAPL')
        self.mock_session.get.assert_called_once_with(
            self.make_url('/trader/v1/accounts/{accountHash}/transactions'),
            params={
                'types': ','.join(t.value for t in self.client.Transactions.TransactionType),
                'startDate': NOW_DATETIME_MINUS_60_DAYS_ISO,
                'endDate': NOW_DATETIME_ISO,
                'symbol': 'AAPL'})


    @patch('schwab.client.base.datetime.datetime', mockdatetime)
    def test_get_transactions_symbol_start_date_as_datetime(self):
        self.client.get_transactions(
                ACCOUNT_HASH, start_date=NOW_DATETIME)
        self.mock_session.get.assert_called_once_with(
            self.make_url('/trader/v1/accounts/{accountHash}/transactions'),
            params={
                'types': ','.join(t.value for t in self.client.Transactions.TransactionType),
                'startDate': NOW_DATETIME_ISO,
                'endDate': NOW_DATETIME_ISO})


    @patch('schwab.client.base.datetime.datetime', mockdatetime)
    def test_get_transactions_symbol_start_date_as_date(self):
        self.client.get_transactions(
                ACCOUNT_HASH, start_date=NOW_DATE)
        self.mock_session.get.assert_called_once_with(
            self.make_url('/trader/v1/accounts/{accountHash}/transactions'),
            params={
                'types': ','.join(t.value for t in self.client.Transactions.TransactionType),
                'startDate': NOW_DATETIME_TRUNCATED_ISO,
                'endDate': NOW_DATETIME_ISO})


    @patch('schwab.client.base.datetime.datetime', mockdatetime)
    def test_get_transactions_symbol_end_date_as_datetime(self):
        self.client.get_transactions(
                ACCOUNT_HASH,
                # NOW_DATETIME is the default, use something different
                end_date=datetime.datetime(2020, 6, 7, 8, 9, 0))
        self.mock_session.get.assert_called_once_with(
            self.make_url('/trader/v1/accounts/{accountHash}/transactions'),
            params={
                'types': ','.join(t.value for t in self.client.Transactions.TransactionType),
                'startDate': NOW_DATETIME_MINUS_60_DAYS_ISO,
                'endDate': '2020-06-07T08:09:00Z'})


    @patch('schwab.client.base.datetime.datetime', mockdatetime)
    def test_get_transactions_symbol_end_date_as_date(self):
        self.client.get_transactions(ACCOUNT_HASH, end_date=NOW_DATE)
        self.mock_session.get.assert_called_once_with(
            self.make_url('/trader/v1/accounts/{accountHash}/transactions'),
            params={
                'types': ','.join(t.value for t in self.client.Transactions.TransactionType),
                'startDate': NOW_DATETIME_MINUS_60_DAYS_ISO,
                'endDate': NOW_DATETIME_TRUNCATED_ISO})


    # get_transaction
    
    def test_get_transaction(self):
        self.client.get_transaction(ACCOUNT_HASH, TRANSACTION_ID)
        self.mock_session.get.assert_called_once_with(
            self.make_url(
                '/trader/v1/accounts/{accountHash}/transactions/{transactionId}'),
            params={})


    # get_user_preference

    def test_get_user_preferences(self):
        self.client.get_user_preferences()
        self.mock_session.get.assert_called_once_with(
            self.make_url('/trader/v1/userPreference'), params={})


    # get_quote

    def test_get_quote(self):
        self.client.get_quote(SYMBOL)
        self.mock_session.get.assert_called_once_with(
            self.make_url('/marketdata/v1/{symbol}/quotes'), params={})


    def test_get_quote_fields_single(self):
        self.client.get_quote(SYMBOL, fields=self.client.Quote.Fields.QUOTE)
        self.mock_session.get.assert_called_once_with(
            self.make_url('/marketdata/v1/{symbol}/quotes'),
            params={'fields': 'quote'})


    def test_get_quote_fields_unchecked(self):
        self.client.set_enforce_enums(False)
        self.client.get_quote(SYMBOL, fields=['not-a-field'])
        self.mock_session.get.assert_called_once_with(
            self.make_url('/marketdata/v1/{symbol}/quotes'),
            params={'fields': 'not-a-field'})


    def test_get_quote_fields_multiple(self):
        self.client.get_quote(SYMBOL, fields=[
            self.client.Quote.Fields.QUOTE,
            self.client.Quote.Fields.FUNDAMENTAL])
        self.mock_session.get.assert_called_once_with(
            self.make_url('/marketdata/v1/{symbol}/quotes'),
            params={'fields': 'quote,fundamental'})


    # get_quotes

    def test_get_quotes(self):
        self.client.get_quotes(['AAPL', 'MSFT'])
        self.mock_session.get.assert_called_once_with(
            self.make_url('/marketdata/v1/quotes'), params={
                'symbols': 'AAPL,MSFT'})

    
    def test_get_quotes_single_symbol(self):
        self.client.get_quotes('AAPL')
        self.mock_session.get.assert_called_once_with(
            self.make_url('/marketdata/v1/quotes'), params={
                'symbols': 'AAPL'})

    def test_get_quotes_fields(self):
        self.client.get_quotes(
                ['AAPL', 'MSFT'],
                fields=self.client.Quote.Fields.QUOTE)
        self.mock_session.get.assert_called_once_with(
            self.make_url('/marketdata/v1/quotes'), params={
                'symbols': 'AAPL,MSFT',
                'fields': 'quote'})


    def test_get_quotes_fields_unchecked(self):
        self.client.set_enforce_enums(False)
        self.client.get_quotes(['AAPL', 'MSFT'], fields=['quote'])
        self.mock_session.get.assert_called_once_with(
            self.make_url('/marketdata/v1/quotes'), params={
                'symbols': 'AAPL,MSFT',
                'fields': 'quote'})


    def test_get_quotes_indicative(self):
        self.client.get_quotes(['AAPL', 'MSFT'], indicative=True)
        self.mock_session.get.assert_called_once_with(
            self.make_url('/marketdata/v1/quotes'), params={
                'symbols': 'AAPL,MSFT',
                'indicative': 'true'})


    def test_get_quotes_indicative_not_bool(self):
        with self.assertRaises(ValueError) as cm:
            self.client.get_quotes(['AAPL', 'MSFT'], indicative='false')
        self.assertEqual(str(cm.exception),
                         "value of 'indicative' must be either True or False")


    # get_price_history
    
    def test_get_price_history_vanilla(self):
        self.client.get_price_history(SYMBOL)
        self.mock_session.get.assert_called_once_with(
            self.make_url('/marketdata/v1/pricehistory'), params={
                'symbol': SYMBOL})

    
    def test_get_price_history_period_type(self):
        self.client.get_price_history(
            SYMBOL, period_type=self.client_class.PriceHistory.PeriodType.MONTH)
        self.mock_session.get.assert_called_once_with(
            self.make_url('/marketdata/v1/pricehistory'), params={
                'symbol': SYMBOL,
                'periodType': 'month'})

    
    def test_get_price_history_period_type_unchecked(self):
        self.client.set_enforce_enums(False)
        self.client.get_price_history(SYMBOL, period_type='month')
        self.mock_session.get.assert_called_once_with(
            self.make_url('/marketdata/v1/pricehistory'), params={
                'symbol': SYMBOL,
                'periodType': 'month'})

    
    def test_get_price_history_num_periods(self):
        self.client.get_price_history(
            SYMBOL, period=self.client_class.PriceHistory.Period.TEN_DAYS)
        self.mock_session.get.assert_called_once_with(
            self.make_url('/marketdata/v1/pricehistory'), params={
                'symbol': SYMBOL,
                'period': 10})

    
    def test_get_price_history_num_periods_unchecked(self):
        self.client.set_enforce_enums(False)
        self.client.get_price_history(SYMBOL, period=10)
        self.mock_session.get.assert_called_once_with(
            self.make_url('/marketdata/v1/pricehistory'), params={
                'symbol': SYMBOL,
                'period': 10})

    
    def test_get_price_history_frequency_type(self):
        self.client.get_price_history(
            SYMBOL,
            frequency_type=self.client_class.PriceHistory.FrequencyType.DAILY)
        self.mock_session.get.assert_called_once_with(
            self.make_url('/marketdata/v1/pricehistory'), params={
                'symbol': SYMBOL,
                'frequencyType': 'daily'})

    
    def test_get_price_history_frequency_type_unchecked(self):
        self.client.set_enforce_enums(False)
        self.client.get_price_history(SYMBOL, frequency_type='daily')
        self.mock_session.get.assert_called_once_with(
            self.make_url('/marketdata/v1/pricehistory'), params={
                'symbol': SYMBOL,
                'frequencyType': 'daily'})

    
    def test_get_price_history_frequency(self):
        self.client.get_price_history(
        SYMBOL,
        frequency=self.client_class.PriceHistory.Frequency.EVERY_FIVE_MINUTES)
        self.mock_session.get.assert_called_once_with(
        self.make_url('/marketdata/v1/pricehistory'), params={
            'symbol': SYMBOL,
            'frequency': 5})


    def test_get_price_history_frequency_unchecked(self):
        self.client.set_enforce_enums(False)
        self.client.get_price_history(SYMBOL, frequency=5)
        self.mock_session.get.assert_called_once_with(
            self.make_url('/marketdata/v1/pricehistory'), params={
                'symbol': SYMBOL,
                'frequency': 5})

    
    def test_get_price_history_start_datetime(self):
        self.client.get_price_history(
            SYMBOL, start_datetime=EARLIER_DATETIME)
        self.mock_session.get.assert_called_once_with(
            self.make_url('/marketdata/v1/pricehistory'), params={
                'symbol': SYMBOL,
                'startDate': EARLIER_MILLIS})

    
    def test_get_price_history_start_datetime_str(self):
        with self.assertRaises(ValueError) as cm:
            self.client.get_price_history(SYMBOL, start_datetime='2020-01-01')
        self.assertEqual(str(cm.exception),
                         "expected type 'datetime.datetime' for " +
                         "start_datetime, got 'builtins.str'")

    
    def test_get_price_history_end_datetime(self):
        self.client.get_price_history(SYMBOL, end_datetime=EARLIER_DATETIME)
        self.mock_session.get.assert_called_once_with(
            self.make_url('/marketdata/v1/pricehistory'), params={
                'symbol': SYMBOL,
                'endDate': EARLIER_MILLIS})

    
    def test_get_price_history_end_datetime_str(self):
        with self.assertRaises(ValueError) as cm:
            self.client.get_price_history(SYMBOL, end_datetime='2020-01-01')
        self.assertEqual(str(cm.exception),
                         "expected type 'datetime.datetime' for " +
                         "end_datetime, got 'builtins.str'")

    
    def test_get_price_history_need_extended_hours_data(self):
        self.client.get_price_history(SYMBOL, need_extended_hours_data=True)
        self.mock_session.get.assert_called_once_with(
            self.make_url('/marketdata/v1/pricehistory'), params={
                'symbol': SYMBOL,
                'needExtendedHoursData': True})


    def test_get_price_history_need_previous_close(self):
        self.client.get_price_history(SYMBOL, need_previous_close=True)
        self.mock_session.get.assert_called_once_with(
            self.make_url('/marketdata/v1/pricehistory'), params={
                'symbol': SYMBOL,
                'needPreviousClose': True})


    # get_option_chain
    
    def test_get_option_chain_vanilla(self):
        self.client.get_option_chain('AAPL')
        self.mock_session.get.assert_called_once_with(
            self.make_url('/marketdata/v1/chains'), params={
                'symbol': 'AAPL'})

    def test_get_option_chain_contract_type(self):
        self.client.get_option_chain(
            'AAPL', contract_type=self.client_class.Options.ContractType.PUT)
        self.mock_session.get.assert_called_once_with(
            self.make_url('/marketdata/v1/chains'), params={
                'symbol': 'AAPL',
                'contractType': 'PUT'})

    
    def test_get_option_chain_contract_type_unchecked(self):
        self.client.set_enforce_enums(False)
        self.client.get_option_chain('AAPL', contract_type='PUT')
        self.mock_session.get.assert_called_once_with(
            self.make_url('/marketdata/v1/chains'), params={
                'symbol': 'AAPL',
                'contractType': 'PUT'})

    
    def test_get_option_chain_strike_count(self):
        self.client.get_option_chain('AAPL', strike_count=100)
        self.mock_session.get.assert_called_once_with(
            self.make_url('/marketdata/v1/chains'), params={
                'symbol': 'AAPL',
                'strikeCount': 100})

    
    def test_get_option_chain_include_underlyingquotes(self):
        self.client.get_option_chain('AAPL', include_underlying_quote=True)
        self.mock_session.get.assert_called_once_with(
            self.make_url('/marketdata/v1/chains'), params={
                'symbol': 'AAPL',
                'includeUnderlyingQuote': True})

    
    def test_get_option_chain_strategy(self):
        self.client.get_option_chain(
            'AAPL', strategy=self.client_class.Options.Strategy.STRANGLE)
        self.mock_session.get.assert_called_once_with(
            self.make_url('/marketdata/v1/chains'), params={
                'symbol': 'AAPL',
                'strategy': 'STRANGLE'})

    
    def test_get_option_chain_strategy_unchecked(self):
        self.client.set_enforce_enums(False)
        self.client.get_option_chain('AAPL', strategy='STRANGLE')
        self.mock_session.get.assert_called_once_with(
            self.make_url('/marketdata/v1/chains'), params={
                'symbol': 'AAPL',
                'strategy': 'STRANGLE'})

    
    def test_get_option_chain_interval(self):
        self.client.get_option_chain('AAPL', interval=10.0)
        self.mock_session.get.assert_called_once_with(
            self.make_url('/marketdata/v1/chains'), params={
                'symbol': 'AAPL',
                'interval': 10.0})

    
    def test_get_option_chain_strike(self):
        self.client.get_option_chain('AAPL', strike=123)
        self.mock_session.get.assert_called_once_with(
            self.make_url('/marketdata/v1/chains'), params={
                'symbol': 'AAPL',
                'strike': 123})

    
    def test_get_option_chain_strike_range(self):
        self.client.get_option_chain(
            'AAPL', strike_range=self.client_class.Options.StrikeRange.IN_THE_MONEY)
        self.mock_session.get.assert_called_once_with(
            self.make_url('/marketdata/v1/chains'), params={
                'symbol': 'AAPL',
                'range': 'ITM'})

    
    def test_get_option_chain_strike_range_unchecked(self):
        self.client.set_enforce_enums(False)
        self.client.get_option_chain('AAPL', strike_range='ITM')
        self.mock_session.get.assert_called_once_with(
            self.make_url('/marketdata/v1/chains'), params={
                'symbol': 'AAPL',
                'range': 'ITM'})

    
    def test_get_option_chain_from_date_datetime(self):
        self.client.get_option_chain(
            'AAPL', from_date=NOW_DATETIME)
        self.mock_session.get.assert_called_once_with(
            self.make_url('/marketdata/v1/chains'), params={
                'symbol': 'AAPL',
                'fromDate': NOW_DATE_ISO})

    
    def test_get_option_chain_from_date_date(self):
        self.client.get_option_chain('AAPL', from_date=NOW_DATE)
        self.mock_session.get.assert_called_once_with(
            self.make_url('/marketdata/v1/chains'), params={
                'symbol': 'AAPL',
                'fromDate': NOW_DATE_ISO})

    
    def test_get_option_chain_from_date_str(self):
        with self.assertRaises(ValueError) as cm:
            self.client.get_option_chain('AAPL', from_date='2020-01-01')
        self.assertEqual(str(cm.exception),
                         "expected type 'datetime.date' for " +
                         "from_date, got 'builtins.str'")

    
    def test_get_option_chain_to_date_datetime(self):
        self.client.get_option_chain('AAPL', to_date=NOW_DATETIME)
        self.mock_session.get.assert_called_once_with(
            self.make_url('/marketdata/v1/chains'), params={
                'symbol': 'AAPL',
                'toDate': NOW_DATE_ISO})

    
    def test_get_option_chain_to_date_date(self):
        self.client.get_option_chain('AAPL', to_date=NOW_DATE)
        self.mock_session.get.assert_called_once_with(
            self.make_url('/marketdata/v1/chains'), params={
                'symbol': 'AAPL',
                'toDate': NOW_DATE_ISO})

    
    def test_get_option_chain_to_date_str(self):
        with self.assertRaises(ValueError) as cm:
            self.client.get_option_chain('AAPL', to_date='2020-01-01')
        self.assertEqual(str(cm.exception),
                         "expected type 'datetime.date' for " +
                         "to_date, got 'builtins.str'")

    
    def test_get_option_chain_volatility(self):
        self.client.get_option_chain('AAPL', volatility=40.0)
        self.mock_session.get.assert_called_once_with(
            self.make_url('/marketdata/v1/chains'), params={
                'symbol': 'AAPL',
                'volatility': 40.0})

    
    def test_get_option_chain_underlying_price(self):
        self.client.get_option_chain('AAPL', underlying_price=234.0)
        self.mock_session.get.assert_called_once_with(
            self.make_url('/marketdata/v1/chains'), params={
                'symbol': 'AAPL',
                'underlyingPrice': 234.0})

    
    def test_get_option_chain_interest_rate(self):
        self.client.get_option_chain('AAPL', interest_rate=0.07)
        self.mock_session.get.assert_called_once_with(
            self.make_url('/marketdata/v1/chains'), params={
                'symbol': 'AAPL',
                'interestRate': 0.07})

    
    def test_get_option_chain_days_to_expiration(self):
        self.client.get_option_chain('AAPL', days_to_expiration=12)
        self.mock_session.get.assert_called_once_with(
            self.make_url('/marketdata/v1/chains'), params={
                'symbol': 'AAPL',
                'daysToExpiration': 12})

    
    def test_get_option_chain_exp_month(self):
        self.client.get_option_chain(
            'AAPL', exp_month=self.client_class.Options.ExpirationMonth.JANUARY)
        self.mock_session.get.assert_called_once_with(
            self.make_url('/marketdata/v1/chains'), params={
                'symbol': 'AAPL',
                'expMonth': 'JAN'})

    
    def test_get_option_chain_exp_month_unchecked(self):
        self.client.set_enforce_enums(False)
        self.client.get_option_chain('AAPL', exp_month='JAN')
        self.mock_session.get.assert_called_once_with(
            self.make_url('/marketdata/v1/chains'), params={
                'symbol': 'AAPL',
                'expMonth': 'JAN'})

    
    def test_get_option_chain_option_type(self):
        self.client.get_option_chain(
            'AAPL', option_type=self.client_class.Options.Type.STANDARD)
        self.mock_session.get.assert_called_once_with(
            self.make_url('/marketdata/v1/chains'), params={
                'symbol': 'AAPL',
                'optionType': 'S'})

    
    def test_get_option_chain_option_type_unchecked(self):
        self.client.set_enforce_enums(False)
        self.client.get_option_chain('AAPL', option_type='S')
        self.mock_session.get.assert_called_once_with(
            self.make_url('/marketdata/v1/chains'), params={
                'symbol': 'AAPL',
                'optionType': 'S'})


    def test_get_option_chain_option_entitlement(self):
        self.client.get_option_chain(
            'AAPL', entitlement=self.client.Options.Entitlement.PAYING_PRO)
        self.mock_session.get.assert_called_once_with(
            self.make_url('/marketdata/v1/chains'), params={
                'symbol': 'AAPL',
                'entitlement': 'PP'})


    # get_option_expiration_chain

    def test_get_option_expiration_chain(self):
        self.client.get_option_expiration_chain('AAPL')
        self.mock_session.get.assert_called_once_with(
            self.make_url('/marketdata/v1/expirationchain'),
            params={'symbol': 'AAPL'})


    # get_price_history_every_minute

    @patch('schwab.client.base.datetime.datetime', mockdatetime)
    def test_get_price_history_every_minute_vanilla(self):
        self.client.get_price_history_every_minute('AAPL')
        params = {
                'symbol': 'AAPL',
                'periodType': 'day',
                # ONE_DAY
                'period': 1,
                'frequencyType': 'minute',
                # EVERY_MINUTE
                'frequency': 1,
                'startDate': MIN_TIMESTAMP_MILLIS,
                'endDate': NOW_DATETIME_PLUS_SEVEN_DAYS_TIMESTAMP_MILLIS,
        }
        self.mock_session.get.assert_called_once_with(
            self.make_url('/marketdata/v1/pricehistory'),
            params=params)


    @patch('schwab.client.base.datetime.datetime', mockdatetime)
    def test_get_price_history_every_minute_start_datetime(self):
        self.client.get_price_history_every_minute(
                'AAPL', start_datetime=EARLIER_DATETIME)
        params = {
                'symbol': SYMBOL,
                'periodType': 'day',
                # ONE_DAY
                'period': 1,
                'frequencyType': 'minute',
                # EVERY_MINUTE
                'frequency': 1,
                'startDate': EARLIER_MILLIS,
                'endDate': NOW_DATETIME_PLUS_SEVEN_DAYS_TIMESTAMP_MILLIS,
        }
        self.mock_session.get.assert_called_once_with(
            self.make_url('/marketdata/v1/pricehistory'),
            params=params)


    @patch('schwab.client.base.datetime.datetime', mockdatetime)
    def test_get_price_history_every_minute_end_datetime(self):
        self.client.get_price_history_every_minute(
                'AAPL', end_datetime=EARLIER_DATETIME)
        params = {
                'symbol': SYMBOL,
                'periodType': 'day',
                # ONE_DAY
                'period': 1,
                'frequencyType': 'minute',
                # EVERY_MINUTE
                'frequency': 1,
                'startDate': MIN_TIMESTAMP_MILLIS,
                'endDate': EARLIER_MILLIS,
        }
        self.mock_session.get.assert_called_once_with(
            self.make_url('/marketdata/v1/pricehistory'),
            params=params)


    @patch('schwab.client.base.datetime.datetime', mockdatetime)
    def test_get_price_history_every_minute_empty_extendedhours(self):
        self.client.get_price_history_every_minute(
            'AAPL', need_extended_hours_data=None)
        params = {
                'symbol': SYMBOL,
                'periodType': 'day',
                # ONE_DAY
                'period': 1,
                'frequencyType': 'minute',
                # EVERY_MINUTE
                'frequency': 1,
                'startDate': MIN_TIMESTAMP_MILLIS,
                'endDate': NOW_DATETIME_PLUS_SEVEN_DAYS_TIMESTAMP_MILLIS,
        }
        self.mock_session.get.assert_called_once_with(
            self.make_url('/marketdata/v1/pricehistory'),
            params=params)


    @patch('schwab.client.base.datetime.datetime', mockdatetime)
    def test_get_price_history_every_minute_extendedhours(self):
        self.client.get_price_history_every_minute(
            'AAPL', need_extended_hours_data=True)
        params = {
                'symbol': SYMBOL,
                'periodType': 'day',
                # ONE_DAY
                'period': 1,
                'frequencyType': 'minute',
                # EVERY_MINUTE
                'frequency': 1,
                'startDate': MIN_TIMESTAMP_MILLIS,
                'endDate': NOW_DATETIME_PLUS_SEVEN_DAYS_TIMESTAMP_MILLIS,
                'needExtendedHoursData': True,
        }
        self.mock_session.get.assert_called_once_with(
            self.make_url('/marketdata/v1/pricehistory'),
            params=params)

    @patch('schwab.client.base.datetime.datetime', mockdatetime)
    def test_get_price_history_every_minute_empty_previous_close(self):
        self.client.get_price_history_every_minute(
            'AAPL', need_previous_close=None)
        params = {
                'symbol': SYMBOL,
                'periodType': 'day',
                # ONE_DAY
                'period': 1,
                'frequencyType': 'minute',
                # EVERY_MINUTE
                'frequency': 1,
                'startDate': MIN_TIMESTAMP_MILLIS,
                'endDate': NOW_DATETIME_PLUS_SEVEN_DAYS_TIMESTAMP_MILLIS,
        }
        self.mock_session.get.assert_called_once_with(
            self.make_url('/marketdata/v1/pricehistory'),
            params=params)


    @patch('schwab.client.base.datetime.datetime', mockdatetime)
    def test_get_price_history_every_minute_previous_close(self):
        self.client.get_price_history_every_minute(
            'AAPL', need_previous_close=True)
        params = {
                'symbol': SYMBOL,
                'periodType': 'day',
                # ONE_DAY
                'period': 1,
                'frequencyType': 'minute',
                # EVERY_MINUTE
                'frequency': 1,
                'startDate': MIN_TIMESTAMP_MILLIS,
                'endDate': NOW_DATETIME_PLUS_SEVEN_DAYS_TIMESTAMP_MILLIS,
                'needPreviousClose': True,
        }
        self.mock_session.get.assert_called_once_with(
            self.make_url('/marketdata/v1/pricehistory'),
            params=params)



    # get_price_history_every_five_minutes


    @patch('schwab.client.base.datetime.datetime', mockdatetime)
    def test_get_price_history_every_five_minutes_vanilla(self):
        self.client.get_price_history_every_five_minutes('AAPL')
        params = {
                'symbol': SYMBOL,
                'periodType': 'day',
                # ONE_DAY
                'period': 1,
                'frequencyType': 'minute',
                # EVERY_FIVE_MINUTES
                'frequency': 5,
                'startDate': MIN_TIMESTAMP_MILLIS,
                'endDate': NOW_DATETIME_PLUS_SEVEN_DAYS_TIMESTAMP_MILLIS,
        }
        self.mock_session.get.assert_called_once_with(
            self.make_url('/marketdata/v1/pricehistory'),
            params=params)


    @patch('schwab.client.base.datetime.datetime', mockdatetime)
    def test_get_price_history_every_five_minutes_start_datetime(self):
        self.client.get_price_history_every_five_minutes(
                'AAPL', start_datetime=EARLIER_DATETIME)
        params = {
                'symbol': SYMBOL,
                'periodType': 'day',
                # ONE_DAY
                'period': 1,
                'frequencyType': 'minute',
                # EVERY_FIVE_MINUTES
                'frequency': 5,
                'startDate': EARLIER_MILLIS,
                'endDate': NOW_DATETIME_PLUS_SEVEN_DAYS_TIMESTAMP_MILLIS,
        }
        self.mock_session.get.assert_called_once_with(
            self.make_url('/marketdata/v1/pricehistory'),
            params=params)


    @patch('schwab.client.base.datetime.datetime', mockdatetime)
    def test_get_price_history_every_five_minutes_end_datetime(self):
        self.client.get_price_history_every_five_minutes(
                'AAPL', end_datetime=EARLIER_DATETIME)
        params = {
                'symbol': SYMBOL,
                'periodType': 'day',
                # ONE_DAY
                'period': 1,
                'frequencyType': 'minute',
                # EVERY_FIVE_MINUTES
                'frequency': 5,
                'startDate': MIN_TIMESTAMP_MILLIS,
                'endDate': EARLIER_MILLIS,
        }
        self.mock_session.get.assert_called_once_with(
            self.make_url('/marketdata/v1/pricehistory'),
            params=params)


    @patch('schwab.client.base.datetime.datetime', mockdatetime)
    def test_get_price_history_every_five_minutes_empty_extendedhours(self):
        self.client.get_price_history_every_five_minutes(
            'AAPL', need_extended_hours_data=None)
        params = {
                'symbol': SYMBOL,
                'periodType': 'day',
                # ONE_DAY
                'period': 1,
                'frequencyType': 'minute',
                # EVERY_FIVE_MINUTES
                'frequency': 5,
                'startDate': MIN_TIMESTAMP_MILLIS,
                'endDate': NOW_DATETIME_PLUS_SEVEN_DAYS_TIMESTAMP_MILLIS,
        }
        self.mock_session.get.assert_called_once_with(
            self.make_url('/marketdata/v1/pricehistory'),
            params=params)


    @patch('schwab.client.base.datetime.datetime', mockdatetime)
    def test_get_price_history_every_five_minutes_extendedhours(self):
        self.client.get_price_history_every_five_minutes(
            'AAPL', need_extended_hours_data=True)
        params = {
                'symbol': SYMBOL,
                'periodType': 'day',
                # ONE_DAY
                'period': 1,
                'frequencyType': 'minute',
                # EVERY_FIVE_MINUTES
                'frequency': 5,
                'startDate': MIN_TIMESTAMP_MILLIS,
                'endDate': NOW_DATETIME_PLUS_SEVEN_DAYS_TIMESTAMP_MILLIS,
                'needExtendedHoursData': True,
        }
        self.mock_session.get.assert_called_once_with(
            self.make_url('/marketdata/v1/pricehistory'),
            params=params)

    @patch('schwab.client.base.datetime.datetime', mockdatetime)
    def test_get_price_history_every_five_minutes_empty_previous_close(self):
        self.client.get_price_history_every_five_minutes(
            'AAPL', need_previous_close=None)
        params = {
                'symbol': SYMBOL,
                'periodType': 'day',
                # ONE_DAY
                'period': 1,
                'frequencyType': 'minute',
                # EVERY_FIVE_MINUTES
                'frequency': 5,
                'startDate': MIN_TIMESTAMP_MILLIS,
                'endDate': NOW_DATETIME_PLUS_SEVEN_DAYS_TIMESTAMP_MILLIS,
        }
        self.mock_session.get.assert_called_once_with(
            self.make_url('/marketdata/v1/pricehistory'),
            params=params)


    @patch('schwab.client.base.datetime.datetime', mockdatetime)
    def test_get_price_history_every_five_minutes_previous_close(self):
        self.client.get_price_history_every_five_minutes(
            'AAPL', need_previous_close=True)
        params = {
                'symbol': SYMBOL,
                'periodType': 'day',
                # ONE_DAY
                'period': 1,
                'frequencyType': 'minute',
                # EVERY_FIVE_MINUTES
                'frequency': 5,
                'startDate': MIN_TIMESTAMP_MILLIS,
                'endDate': NOW_DATETIME_PLUS_SEVEN_DAYS_TIMESTAMP_MILLIS,
                'needPreviousClose': True,
        }
        self.mock_session.get.assert_called_once_with(
            self.make_url('/marketdata/v1/pricehistory'),
            params=params)


    # get_price_history_every_ten_minutes


    @patch('schwab.client.base.datetime.datetime', mockdatetime)
    def test_get_price_history_every_ten_minutes_vanilla(self):
        self.client.get_price_history_every_ten_minutes('AAPL')
        params = {
                'symbol': SYMBOL,
                'periodType': 'day',
                # ONE_DAY
                'period': 1,
                'frequencyType': 'minute',
                # EVERY_TEN_MINUTES
                'frequency': 10,
                'startDate': MIN_TIMESTAMP_MILLIS,
                'endDate': NOW_DATETIME_PLUS_SEVEN_DAYS_TIMESTAMP_MILLIS,
        }
        self.mock_session.get.assert_called_once_with(
            self.make_url('/marketdata/v1/pricehistory'),
            params=params)


    @patch('schwab.client.base.datetime.datetime', mockdatetime)
    def test_get_price_history_every_ten_minutes_start_datetime(self):
        self.client.get_price_history_every_ten_minutes(
                'AAPL', start_datetime=EARLIER_DATETIME)
        params = {
                'symbol': SYMBOL,
                'periodType': 'day',
                # ONE_DAY
                'period': 1,
                'frequencyType': 'minute',
                # EVERY_TEN_MINUTES
                'frequency': 10,
                'startDate': EARLIER_MILLIS,
                'endDate': NOW_DATETIME_PLUS_SEVEN_DAYS_TIMESTAMP_MILLIS,
        }
        self.mock_session.get.assert_called_once_with(
            self.make_url('/marketdata/v1/pricehistory'),
            params=params)


    @patch('schwab.client.base.datetime.datetime', mockdatetime)
    def test_get_price_history_every_ten_minutes_end_datetime(self):
        self.client.get_price_history_every_ten_minutes(
                'AAPL', end_datetime=EARLIER_DATETIME)
        params = {
                'symbol': SYMBOL,
                'periodType': 'day',
                # ONE_DAY
                'period': 1,
                'frequencyType': 'minute',
                # EVERY_TEN_MINUTES
                'frequency': 10,
                'startDate': MIN_TIMESTAMP_MILLIS,
                'endDate': EARLIER_MILLIS,
        }
        self.mock_session.get.assert_called_once_with(
            self.make_url('/marketdata/v1/pricehistory'),
            params=params)


    @patch('schwab.client.base.datetime.datetime', mockdatetime)
    def test_get_price_history_every_ten_minutes_empty_extendedhours(self):
        self.client.get_price_history_every_ten_minutes(
            'AAPL', need_extended_hours_data=None)
        params = {
                'symbol': SYMBOL,
                'periodType': 'day',
                # ONE_DAY
                'period': 1,
                'frequencyType': 'minute',
                # EVERY_TEN_MINUTES
                'frequency': 10,
                'startDate': MIN_TIMESTAMP_MILLIS,
                'endDate': NOW_DATETIME_PLUS_SEVEN_DAYS_TIMESTAMP_MILLIS,
        }
        self.mock_session.get.assert_called_once_with(
            self.make_url('/marketdata/v1/pricehistory'),
            params=params)


    @patch('schwab.client.base.datetime.datetime', mockdatetime)
    def test_get_price_history_every_ten_minutes_extendedhours(self):
        self.client.get_price_history_every_ten_minutes(
            'AAPL', need_extended_hours_data=True)
        params = {
                'symbol': SYMBOL,
                'periodType': 'day',
                # ONE_DAY
                'period': 1,
                'frequencyType': 'minute',
                # EVERY_TEN_MINUTES
                'frequency': 10,
                'startDate': MIN_TIMESTAMP_MILLIS,
                'endDate': NOW_DATETIME_PLUS_SEVEN_DAYS_TIMESTAMP_MILLIS,
                'needExtendedHoursData': True,
        }
        self.mock_session.get.assert_called_once_with(
            self.make_url('/marketdata/v1/pricehistory'),
            params=params)

    @patch('schwab.client.base.datetime.datetime', mockdatetime)
    def test_get_price_history_every_ten_minutes_empty_previous_close(self):
        self.client.get_price_history_every_ten_minutes(
            'AAPL', need_previous_close=None)
        params = {
                'symbol': SYMBOL,
                'periodType': 'day',
                # ONE_DAY
                'period': 1,
                'frequencyType': 'minute',
                # EVERY_TEN_MINUTES
                'frequency': 10,
                'startDate': MIN_TIMESTAMP_MILLIS,
                'endDate': NOW_DATETIME_PLUS_SEVEN_DAYS_TIMESTAMP_MILLIS,
        }
        self.mock_session.get.assert_called_once_with(
            self.make_url('/marketdata/v1/pricehistory'),
            params=params)


    @patch('schwab.client.base.datetime.datetime', mockdatetime)
    def test_get_price_history_every_ten_minutes_previous_close(self):
        self.client.get_price_history_every_ten_minutes(
            'AAPL', need_previous_close=True)
        params = {
                'symbol': SYMBOL,
                'periodType': 'day',
                # ONE_DAY
                'period': 1,
                'frequencyType': 'minute',
                # EVERY_TEN_MINUTES
                'frequency': 10,
                'startDate': MIN_TIMESTAMP_MILLIS,
                'endDate': NOW_DATETIME_PLUS_SEVEN_DAYS_TIMESTAMP_MILLIS,
                'needPreviousClose': True,
        }
        self.mock_session.get.assert_called_once_with(
            self.make_url('/marketdata/v1/pricehistory'),
            params=params)


    # get_price_history_every_fifteen_minutes


    @patch('schwab.client.base.datetime.datetime', mockdatetime)
    def test_get_price_history_every_fifteen_minutes_vanilla(self):
        self.client.get_price_history_every_fifteen_minutes('AAPL')
        params = {
                'symbol': SYMBOL,
                'periodType': 'day',
                # ONE_DAY
                'period': 1,
                'frequencyType': 'minute',
                # EVERY_FIFTEEN_MINUTES
                'frequency': 15,
                'startDate': MIN_TIMESTAMP_MILLIS,
                'endDate': NOW_DATETIME_PLUS_SEVEN_DAYS_TIMESTAMP_MILLIS,
        }
        self.mock_session.get.assert_called_once_with(
            self.make_url('/marketdata/v1/pricehistory'),
            params=params)


    @patch('schwab.client.base.datetime.datetime', mockdatetime)
    def test_get_price_history_every_fifteen_minutes_start_datetime(self):
        self.client.get_price_history_every_fifteen_minutes(
                'AAPL', start_datetime=EARLIER_DATETIME)
        params = {
                'symbol': SYMBOL,
                'periodType': 'day',
                # ONE_DAY
                'period': 1,
                'frequencyType': 'minute',
                # EVERY_FIFTEEN_MINUTES
                'frequency': 15,
                'startDate': EARLIER_MILLIS,
                'endDate': NOW_DATETIME_PLUS_SEVEN_DAYS_TIMESTAMP_MILLIS,
        }
        self.mock_session.get.assert_called_once_with(
            self.make_url('/marketdata/v1/pricehistory'),
            params=params)


    @patch('schwab.client.base.datetime.datetime', mockdatetime)
    def test_get_price_history_every_fifteen_minutes_end_datetime(self):
        self.client.get_price_history_every_fifteen_minutes(
                'AAPL', end_datetime=EARLIER_DATETIME)
        params = {
                'symbol': SYMBOL,
                'periodType': 'day',
                # ONE_DAY
                'period': 1,
                'frequencyType': 'minute',
                # EVERY_FIFTEEN_MINUTES
                'frequency': 15,
                'startDate': MIN_TIMESTAMP_MILLIS,
                'endDate': EARLIER_MILLIS,
        }
        self.mock_session.get.assert_called_once_with(
            self.make_url('/marketdata/v1/pricehistory'),
            params=params)


    @patch('schwab.client.base.datetime.datetime', mockdatetime)
    def test_get_price_history_every_fifteen_minutes_empty_extendedhours(self):
        self.client.get_price_history_every_fifteen_minutes(
            'AAPL', need_extended_hours_data=None)
        params = {
                'symbol': SYMBOL,
                'periodType': 'day',
                # ONE_DAY
                'period': 1,
                'frequencyType': 'minute',
                # EVERY_FIFTEEN_MINUTES
                'frequency': 15,
                'startDate': MIN_TIMESTAMP_MILLIS,
                'endDate': NOW_DATETIME_PLUS_SEVEN_DAYS_TIMESTAMP_MILLIS,
        }
        self.mock_session.get.assert_called_once_with(
            self.make_url('/marketdata/v1/pricehistory'),
            params=params)


    @patch('schwab.client.base.datetime.datetime', mockdatetime)
    def test_get_price_history_every_fifteen_minutes_extendedhours(self):
        self.client.get_price_history_every_fifteen_minutes(
            'AAPL', need_extended_hours_data=True)
        params = {
                'symbol': SYMBOL,
                'periodType': 'day',
                # ONE_DAY
                'period': 1,
                'frequencyType': 'minute',
                # EVERY_FIFTEEN_MINUTES
                'frequency': 15,
                'startDate': MIN_TIMESTAMP_MILLIS,
                'endDate': NOW_DATETIME_PLUS_SEVEN_DAYS_TIMESTAMP_MILLIS,
                'needExtendedHoursData': True,
        }
        self.mock_session.get.assert_called_once_with(
            self.make_url('/marketdata/v1/pricehistory'),
            params=params)

    @patch('schwab.client.base.datetime.datetime', mockdatetime)
    def test_get_price_history_every_fifteen_minutes_empty_previous_close(self):
        self.client.get_price_history_every_fifteen_minutes(
            'AAPL', need_previous_close=None)
        params = {
                'symbol': SYMBOL,
                'periodType': 'day',
                # ONE_DAY
                'period': 1,
                'frequencyType': 'minute',
                # EVERY_FIFTEEN_MINUTES
                'frequency': 15,
                'startDate': MIN_TIMESTAMP_MILLIS,
                'endDate': NOW_DATETIME_PLUS_SEVEN_DAYS_TIMESTAMP_MILLIS,
        }
        self.mock_session.get.assert_called_once_with(
            self.make_url('/marketdata/v1/pricehistory'),
            params=params)


    @patch('schwab.client.base.datetime.datetime', mockdatetime)
    def test_get_price_history_every_fifteen_minutes_previous_close(self):
        self.client.get_price_history_every_fifteen_minutes(
            'AAPL', need_previous_close=True)
        params = {
                'symbol': SYMBOL,
                'periodType': 'day',
                # ONE_DAY
                'period': 1,
                'frequencyType': 'minute',
                # EVERY_FIFTEEN_MINUTES
                'frequency': 15,
                'startDate': MIN_TIMESTAMP_MILLIS,
                'endDate': NOW_DATETIME_PLUS_SEVEN_DAYS_TIMESTAMP_MILLIS,
                'needPreviousClose': True,
        }
        self.mock_session.get.assert_called_once_with(
            self.make_url('/marketdata/v1/pricehistory'),
            params=params)


    # get_price_history_every_thirty_minutes


    @patch('schwab.client.base.datetime.datetime', mockdatetime)
    def test_get_price_history_every_thirty_minutes_vanilla(self):
        self.client.get_price_history_every_thirty_minutes('AAPL')
        params = {
                'symbol': SYMBOL,
                'periodType': 'day',
                # ONE_DAY
                'period': 1,
                'frequencyType': 'minute',
                # EVERY_THIRTY_MINUTES
                'frequency': 30,
                'startDate': MIN_TIMESTAMP_MILLIS,
                'endDate': NOW_DATETIME_PLUS_SEVEN_DAYS_TIMESTAMP_MILLIS,
        }
        self.mock_session.get.assert_called_once_with(
            self.make_url('/marketdata/v1/pricehistory'),
            params=params)


    @patch('schwab.client.base.datetime.datetime', mockdatetime)
    def test_get_price_history_every_thirty_minutes_start_datetime(self):
        self.client.get_price_history_every_thirty_minutes(
                'AAPL', start_datetime=EARLIER_DATETIME)
        params = {
                'symbol': SYMBOL,
                'periodType': 'day',
                # ONE_DAY
                'period': 1,
                'frequencyType': 'minute',
                # EVERY_THIRTY_MINUTES
                'frequency': 30,
                'startDate': EARLIER_MILLIS,
                'endDate': NOW_DATETIME_PLUS_SEVEN_DAYS_TIMESTAMP_MILLIS,
        }
        self.mock_session.get.assert_called_once_with(
            self.make_url('/marketdata/v1/pricehistory'),
            params=params)


    @patch('schwab.client.base.datetime.datetime', mockdatetime)
    def test_get_price_history_every_thirty_minutes_end_datetime(self):
        self.client.get_price_history_every_thirty_minutes(
                'AAPL', end_datetime=EARLIER_DATETIME)
        params = {
                'symbol': SYMBOL,
                'periodType': 'day',
                # ONE_DAY
                'period': 1,
                'frequencyType': 'minute',
                # EVERY_THIRTY_MINUTES
                'frequency': 30,
                'startDate': MIN_TIMESTAMP_MILLIS,
                'endDate': EARLIER_MILLIS,
        }
        self.mock_session.get.assert_called_once_with(
            self.make_url('/marketdata/v1/pricehistory'),
            params=params)


    @patch('schwab.client.base.datetime.datetime', mockdatetime)
    def test_get_price_history_every_thirty_minutes_empty_extendedhours(self):
        self.client.get_price_history_every_thirty_minutes(
            'AAPL', need_extended_hours_data=None)
        params = {
                'symbol': SYMBOL,
                'periodType': 'day',
                # ONE_DAY
                'period': 1,
                'frequencyType': 'minute',
                # EVERY_THIRTY_MINUTES
                'frequency': 30,
                'startDate': MIN_TIMESTAMP_MILLIS,
                'endDate': NOW_DATETIME_PLUS_SEVEN_DAYS_TIMESTAMP_MILLIS,
        }
        self.mock_session.get.assert_called_once_with(
            self.make_url('/marketdata/v1/pricehistory'),
            params=params)


    @patch('schwab.client.base.datetime.datetime', mockdatetime)
    def test_get_price_history_every_thirty_minutes_extendedhours(self):
        self.client.get_price_history_every_thirty_minutes(
            'AAPL', need_extended_hours_data=True)
        params = {
                'symbol': SYMBOL,
                'periodType': 'day',
                # ONE_DAY
                'period': 1,
                'frequencyType': 'minute',
                # EVERY_THIRTY_MINUTES
                'frequency': 30,
                'startDate': MIN_TIMESTAMP_MILLIS,
                'endDate': NOW_DATETIME_PLUS_SEVEN_DAYS_TIMESTAMP_MILLIS,
                'needExtendedHoursData': True,
        }
        self.mock_session.get.assert_called_once_with(
            self.make_url('/marketdata/v1/pricehistory'),
            params=params)

    @patch('schwab.client.base.datetime.datetime', mockdatetime)
    def test_get_price_history_every_thirty_minutes_empty_previous_close(self):
        self.client.get_price_history_every_thirty_minutes(
            'AAPL', need_previous_close=None)
        params = {
                'symbol': SYMBOL,
                'periodType': 'day',
                # ONE_DAY
                'period': 1,
                'frequencyType': 'minute',
                # EVERY_THIRTY_MINUTES
                'frequency': 30,
                'startDate': MIN_TIMESTAMP_MILLIS,
                'endDate': NOW_DATETIME_PLUS_SEVEN_DAYS_TIMESTAMP_MILLIS,
        }
        self.mock_session.get.assert_called_once_with(
            self.make_url('/marketdata/v1/pricehistory'),
            params=params)


    @patch('schwab.client.base.datetime.datetime', mockdatetime)
    def test_get_price_history_every_thirty_minutes_previous_close(self):
        self.client.get_price_history_every_thirty_minutes(
            'AAPL', need_previous_close=True)
        params = {
                'symbol': SYMBOL,
                'periodType': 'day',
                # ONE_DAY
                'period': 1,
                'frequencyType': 'minute',
                # EVERY_THIRTY_MINUTES
                'frequency': 30,
                'startDate': MIN_TIMESTAMP_MILLIS,
                'endDate': NOW_DATETIME_PLUS_SEVEN_DAYS_TIMESTAMP_MILLIS,
                'needPreviousClose': True,
        }
        self.mock_session.get.assert_called_once_with(
            self.make_url('/marketdata/v1/pricehistory'),
            params=params)


    # get_price_history_every_day


    @patch('schwab.client.base.datetime.datetime', mockdatetime)
    def test_get_price_history_every_day_vanilla(self):
        self.client.get_price_history_every_day('AAPL')
        params = {
                'symbol': SYMBOL,
                'periodType': 'year',
                # TWENTY_YEARS
                'period': 20,
                'frequencyType': 'daily',
                # DAILY
                'frequency': 1,
                'startDate': MIN_TIMESTAMP_MILLIS,
                'endDate': NOW_DATETIME_PLUS_SEVEN_DAYS_TIMESTAMP_MILLIS,
        }
        self.mock_session.get.assert_called_once_with(
            self.make_url('/marketdata/v1/pricehistory'),
            params=params)


    @patch('schwab.client.base.datetime.datetime', mockdatetime)
    def test_get_price_history_every_day_start_datetime(self):
        self.client.get_price_history_every_day(
                'AAPL', start_datetime=EARLIER_DATETIME)
        params = {
                'symbol': SYMBOL,
                'periodType': 'year',
                # TWENTY_YEARS
                'period': 20,
                'frequencyType': 'daily',
                # DAILY
                'frequency': 1,
                'startDate': EARLIER_MILLIS,
                'endDate': NOW_DATETIME_PLUS_SEVEN_DAYS_TIMESTAMP_MILLIS,
        }
        self.mock_session.get.assert_called_once_with(
            self.make_url('/marketdata/v1/pricehistory'),
            params=params)


    @patch('schwab.client.base.datetime.datetime', mockdatetime)
    def test_get_price_history_every_day_end_datetime(self):
        self.client.get_price_history_every_day(
                'AAPL', end_datetime=EARLIER_DATETIME)
        params = {
                'symbol': SYMBOL,
                'periodType': 'year',
                # TWENTY_YEARS
                'period': 20,
                'frequencyType': 'daily',
                # DAILY
                'frequency': 1,
                'startDate': MIN_TIMESTAMP_MILLIS,
                'endDate': EARLIER_MILLIS,
        }
        self.mock_session.get.assert_called_once_with(
            self.make_url('/marketdata/v1/pricehistory'),
            params=params)


    @patch('schwab.client.base.datetime.datetime', mockdatetime)
    def test_get_price_history_every_day_empty_extendedhours(self):
        self.client.get_price_history_every_day(
            'AAPL', need_extended_hours_data=None)
        params = {
                'symbol': SYMBOL,
                'periodType': 'year',
                # TWENTY_YEARS
                'period': 20,
                'frequencyType': 'daily',
                # DAILY
                'frequency': 1,
                'startDate': MIN_TIMESTAMP_MILLIS,
                'endDate': NOW_DATETIME_PLUS_SEVEN_DAYS_TIMESTAMP_MILLIS,
        }
        self.mock_session.get.assert_called_once_with(
            self.make_url('/marketdata/v1/pricehistory'),
            params=params)


    @patch('schwab.client.base.datetime.datetime', mockdatetime)
    def test_get_price_history_every_day_extendedhours(self):
        self.client.get_price_history_every_day(
            'AAPL', need_extended_hours_data=True)
        params = {
                'symbol': SYMBOL,
                'periodType': 'year',
                # TWENTY_YEARS
                'period': 20,
                'frequencyType': 'daily',
                # DAILY
                'frequency': 1,
                'startDate': MIN_TIMESTAMP_MILLIS,
                'endDate': NOW_DATETIME_PLUS_SEVEN_DAYS_TIMESTAMP_MILLIS,
                'needExtendedHoursData': True,
        }
        self.mock_session.get.assert_called_once_with(
            self.make_url('/marketdata/v1/pricehistory'),
            params=params)

    @patch('schwab.client.base.datetime.datetime', mockdatetime)
    def test_get_price_history_every_day_empty_previous_close(self):
        self.client.get_price_history_every_day(
            'AAPL', need_previous_close=None)
        params = {
                'symbol': SYMBOL,
                'periodType': 'year',
                # TWENTY_YEARS
                'period': 20,
                'frequencyType': 'daily',
                # DAILY
                'frequency': 1,
                'startDate': MIN_TIMESTAMP_MILLIS,
                'endDate': NOW_DATETIME_PLUS_SEVEN_DAYS_TIMESTAMP_MILLIS,
        }
        self.mock_session.get.assert_called_once_with(
            self.make_url('/marketdata/v1/pricehistory'),
            params=params)


    @patch('schwab.client.base.datetime.datetime', mockdatetime)
    def test_get_price_history_every_day_previous_close(self):
        self.client.get_price_history_every_day(
            'AAPL', need_previous_close=True)
        params = {
                'symbol': SYMBOL,
                'periodType': 'year',
                # TWENTY_YEARS
                'period': 20,
                'frequencyType': 'daily',
                # DAILY
                'frequency': 1,
                'startDate': MIN_TIMESTAMP_MILLIS,
                'endDate': NOW_DATETIME_PLUS_SEVEN_DAYS_TIMESTAMP_MILLIS,
                'needPreviousClose': True,
        }
        self.mock_session.get.assert_called_once_with(
            self.make_url('/marketdata/v1/pricehistory'),
            params=params)


    # get_price_history_every_week


    @patch('schwab.client.base.datetime.datetime', mockdatetime)
    def test_get_price_history_every_week_vanilla(self):
        self.client.get_price_history_every_week('AAPL')
        params = {
                'symbol': SYMBOL,
                'periodType': 'year',
                # TWENTY_YEARS
                'period': 20,
                'frequencyType': 'weekly',
                # DAILY
                'frequency': 1,
                'startDate': MIN_TIMESTAMP_MILLIS,
                'endDate': NOW_DATETIME_PLUS_SEVEN_DAYS_TIMESTAMP_MILLIS,
        }
        self.mock_session.get.assert_called_once_with(
            self.make_url('/marketdata/v1/pricehistory'),
            params=params)


    @patch('schwab.client.base.datetime.datetime', mockdatetime)
    def test_get_price_history_every_week_start_datetime(self):
        self.client.get_price_history_every_week(
                'AAPL', start_datetime=EARLIER_DATETIME)
        params = {
                'symbol': SYMBOL,
                'periodType': 'year',
                # TWENTY_YEARS
                'period': 20,
                'frequencyType': 'weekly',
                # DAILY
                'frequency': 1,
                'startDate': EARLIER_MILLIS,
                'endDate': NOW_DATETIME_PLUS_SEVEN_DAYS_TIMESTAMP_MILLIS,
        }
        self.mock_session.get.assert_called_once_with(
            self.make_url('/marketdata/v1/pricehistory'),
            params=params)


    @patch('schwab.client.base.datetime.datetime', mockdatetime)
    def test_get_price_history_every_week_end_datetime(self):
        self.client.get_price_history_every_week(
                'AAPL', end_datetime=EARLIER_DATETIME)
        params = {
                'symbol': SYMBOL,
                'periodType': 'year',
                # TWENTY_YEARS
                'period': 20,
                'frequencyType': 'weekly',
                # DAILY
                'frequency': 1,
                'startDate': MIN_TIMESTAMP_MILLIS,
                'endDate': EARLIER_MILLIS,
        }
        self.mock_session.get.assert_called_once_with(
            self.make_url('/marketdata/v1/pricehistory'),
            params=params)


    @patch('schwab.client.base.datetime.datetime', mockdatetime)
    def test_get_price_history_every_week_empty_extendedhours(self):
        self.client.get_price_history_every_week(
            'AAPL', need_extended_hours_data=None)
        params = {
                'symbol': SYMBOL,
                'periodType': 'year',
                # TWENTY_YEARS
                'period': 20,
                'frequencyType': 'weekly',
                # DAILY
                'frequency': 1,
                'startDate': MIN_TIMESTAMP_MILLIS,
                'endDate': NOW_DATETIME_PLUS_SEVEN_DAYS_TIMESTAMP_MILLIS,
        }
        self.mock_session.get.assert_called_once_with(
            self.make_url('/marketdata/v1/pricehistory'),
            params=params)


    @patch('schwab.client.base.datetime.datetime', mockdatetime)
    def test_get_price_history_every_week_extendedhours(self):
        self.client.get_price_history_every_week(
            'AAPL', need_extended_hours_data=True)
        params = {
                'symbol': SYMBOL,
                'periodType': 'year',
                # TWENTY_YEARS
                'period': 20,
                'frequencyType': 'weekly',
                # DAILY
                'frequency': 1,
                'startDate': MIN_TIMESTAMP_MILLIS,
                'endDate': NOW_DATETIME_PLUS_SEVEN_DAYS_TIMESTAMP_MILLIS,
                'needExtendedHoursData': True,
        }
        self.mock_session.get.assert_called_once_with(
            self.make_url('/marketdata/v1/pricehistory'),
            params=params)

    @patch('schwab.client.base.datetime.datetime', mockdatetime)
    def test_get_price_history_every_week_empty_previous_close(self):
        self.client.get_price_history_every_week(
            'AAPL', need_previous_close=None)
        params = {
                'symbol': SYMBOL,
                'periodType': 'year',
                # TWENTY_YEARS
                'period': 20,
                'frequencyType': 'weekly',
                # DAILY
                'frequency': 1,
                'startDate': MIN_TIMESTAMP_MILLIS,
                'endDate': NOW_DATETIME_PLUS_SEVEN_DAYS_TIMESTAMP_MILLIS,
        }
        self.mock_session.get.assert_called_once_with(
            self.make_url('/marketdata/v1/pricehistory'),
            params=params)


    @patch('schwab.client.base.datetime.datetime', mockdatetime)
    def test_get_price_history_every_week_previous_close(self):
        self.client.get_price_history_every_week(
            'AAPL', need_previous_close=True)
        params = {
                'symbol': SYMBOL,
                'periodType': 'year',
                # TWENTY_YEARS
                'period': 20,
                'frequencyType': 'weekly',
                # DAILY
                'frequency': 1,
                'startDate': MIN_TIMESTAMP_MILLIS,
                'endDate': NOW_DATETIME_PLUS_SEVEN_DAYS_TIMESTAMP_MILLIS,
                'needPreviousClose': True,
        }
        self.mock_session.get.assert_called_once_with(
            self.make_url('/marketdata/v1/pricehistory'),
            params=params)


    # get_movers

    
    def test_get_movers(self):
        self.client.get_movers(
                self.client.Movers.Index.DJI)
        self.mock_session.get.assert_called_once_with(
            self.make_url('/marketdata/v1/movers/$DJI'), params={})


    def test_get_movers_index_unchecked(self):
        self.client.set_enforce_enums(False)
        self.client.get_movers('not-an-index')
        self.mock_session.get.assert_called_once_with(
            self.make_url('/marketdata/v1/movers/not-an-index'), params={})


    def test_get_movers_sort_order(self):
        self.client.get_movers(
                self.client.Movers.Index.DJI,
                sort_order=self.client.Movers.SortOrder.VOLUME)
        self.mock_session.get.assert_called_once_with(
            self.make_url('/marketdata/v1/movers/$DJI'),
            params={'sort': 'VOLUME'})


    def test_get_movers_sort_order_unchecked(self):
        self.client.set_enforce_enums(False)
        self.client.get_movers(
                self.client.Movers.Index.DJI,
                sort_order='not-a-sort-order')
        self.mock_session.get.assert_called_once_with(
            self.make_url('/marketdata/v1/movers/$DJI'),
            params={'sort': 'not-a-sort-order'})


    def test_get_movers_frequency(self):
        self.client.get_movers(
                self.client.Movers.Index.DJI,
                frequency=self.client.Movers.Frequency.ZERO)
        self.mock_session.get.assert_called_once_with(
            self.make_url('/marketdata/v1/movers/$DJI'),
            params={'frequency': '0'})


    def test_get_movers_frequency_unchecked(self):
        self.client.set_enforce_enums(False)
        self.client.get_movers(
                self.client.Movers.Index.DJI,
                frequency='999999')
        self.mock_session.get.assert_called_once_with(
            self.make_url('/marketdata/v1/movers/$DJI'),
            params={'frequency': '999999'})


    # get_market_hours

    
    def test_get_market_hours_single_market(self):
        self.client.get_market_hours(
                self.client_class.MarketHours.Market.EQUITY)
        self.mock_session.get.assert_called_once_with(
            self.make_url('/marketdata/v1/markets'), params={
                'markets': 'equity'})


    def test_get_market_hours_market_list(self):
        self.client.get_market_hours(
                [self.client_class.MarketHours.Market.EQUITY,
                 self.client_class.MarketHours.Market.OPTION])
        self.mock_session.get.assert_called_once_with(
            self.make_url('/marketdata/v1/markets'), params={
                'markets': 'equity,option'})


    def test_get_market_hours_market_unchecked(self):
        self.client.set_enforce_enums(False)
        self.client.get_market_hours(['not-a-market'])
        self.mock_session.get.assert_called_once_with(
            self.make_url('/marketdata/v1/markets'), params={
                'markets': 'not-a-market'})


    def test_get_market_hours_date(self):
        self.client.get_market_hours(
                self.client_class.MarketHours.Market.EQUITY,
                date=NOW_DATE)
        self.mock_session.get.assert_called_once_with(
            self.make_url('/marketdata/v1/markets'), params={
                'markets': 'equity',
                'date': NOW_DATE_ISO})


    def test_get_market_hours_date_str(self):
        with self.assertRaises(ValueError) as cm:
            self.client.get_market_hours(
                    self.client_class.MarketHours.Market.EQUITY,
                    date='2020-01-02')
        self.assertEqual(str(cm.exception),
                         "expected type 'datetime.date' for " +
                         "date, got 'builtins.str'")


    # get_instruments
    
    def test_get_instruments(self):
        self.client.get_instruments(
            ['AAPL', 'MSFT'], self.client_class.Instrument.Projection.FUNDAMENTAL)
        self.mock_session.get.assert_called_once_with(
            self.make_url('/marketdata/v1/instruments'), params={
                'symbol': 'AAPL,MSFT',
                'projection': 'fundamental'})


    def test_get_instruments_projection_unchecked(self):
        self.client.set_enforce_enums(False)
        self.client.get_instruments(
            ['AAPL', 'MSFT'], 'not-a-projection')
        self.mock_session.get.assert_called_once_with(
            self.make_url('/marketdata/v1/instruments'), params={
                'symbol': 'AAPL,MSFT',
                'projection': 'not-a-projection'})


    # get_instrument_by_cusip
    
    def test_get_instrument_by_cusip(self):
        self.client.get_instrument_by_cusip('037833100')
        self.mock_session.get.assert_called_once_with(
            self.make_url('/marketdata/v1/instruments/037833100'), params={})


    def test_get_instrument_by_cusip_cusip_must_be_string(self):
        with self.assertRaises(ValueError) as cm:
            self.client.get_instrument_by_cusip(37833100)
        self.assertEqual(str(cm.exception), 'cusip must be passed as str')


class ClientTest(_TestClient, unittest.TestCase):
    """
    Subclass set to use Client and MagicMock
    """
    client_class    = Client
    magicmock_class = MagicMock

class AsyncClientTest(_TestClient, unittest.TestCase):
    """
    Subclass set to resync AsyncClient and use AsyncMagicMock
    """
    client_class    = ResyncProxy(AsyncClient)
    magicmock_class = AsyncMagicMock

    def test_async_close(self):
        self.client.close_async_session()
