'''Defines the basic client and methods for creating one. This client is
completely unopinionated, and provides an easy-to-use wrapper around the TD
Ameritrade HTTP API.'''

from abc import ABC, abstractmethod
from enum import Enum

import datetime
import json
import logging
import pickle
import schwab
import time
import warnings

from ..utils import EnumEnforcer


def get_logger():
    return logging.getLogger(__name__)


##########################################################################
# Client

class BaseClient(EnumEnforcer):
    # This docstring will appears as documentation for __init__
    '''A basic, completely unopinionated client. This client provides the most
    direct access to the API possible. All methods return the raw response which
    was returned by the underlying API call, and the user is responsible for
    checking status codes. For methods which support responses, they can be
    found in the response object's ``json()`` method.'''

    def __init__(self, api_key, session, *, enforce_enums=True,
                 token_metadata=None):
        '''Create a new client with the given API key and session. Set
        `enforce_enums=False` to disable strict input type checking.'''
        super().__init__(enforce_enums)

        self.api_key = api_key
        self.session = session

        # Logging-related fields
        self.logger = get_logger()
        self.request_number = 0

        schwab.LOG_REDACTOR.register(api_key, 'API_KEY')

        self.token_metadata = token_metadata

        # Set the default timeout configuration
        self.set_timeout(30.0)

    # XXX: This class's tests perform monkey patching to inject synthetic values
    # of utcnow(). To avoid being confused by this, capture these values here so
    # we can use them later.
    _DATETIME = datetime.datetime
    _DATE = datetime.date

    def _log_response(self, resp, req_num):
        self.logger.debug('Req %s: GET response: %s, content=%s',
            req_num, resp.status_code, resp.text)

    def _req_num(self):
        self.request_number += 1
        return self.request_number

    def _assert_type(self, name, value, exp_types):
        value_type = type(value)
        value_type_name = '{}.{}'.format(
            value_type.__module__, value_type.__name__)
        exp_type_names = ['{}.{}'.format(
            t.__module__, t.__name__) for t in exp_types]
        if not any(isinstance(value, t) for t in exp_types):
            if len(exp_types) == 1:
                error_str = "expected type '{}' for {}, got '{}'".format(
                    exp_type_names[0], name, value_type_name)
            else:
                error_str = "expected type in ({}) for {}, got '{}'".format(
                    ', '.join(exp_type_names), name, value_type_name)
            raise ValueError(error_str)

    def _format_datetime(self, var_name, dt):
        '''Formats datetime objects appropriately, depending on whether they are
        naive or timezone-aware'''
        self._assert_type(var_name, dt, [self._DATETIME])

        return dt.strftime('%Y-%m-%dT%H:%M:%SZ')

    def _format_date(self, var_name, dt):
        '''Formats datetime objects appropriately, depending on whether they are
        naive or timezone-aware'''
        self._assert_type(var_name, dt, [self._DATE, self._DATETIME])

        d = datetime.date(year=dt.year, month=dt.month, day=dt.day)

        return d.isoformat()

    def _datetime_as_millis(self, var_name, dt):
        'Converts datetime objects to compatible millisecond values'
        self._assert_type(var_name, dt, [self._DATETIME])

        return int(dt.timestamp() * 1000)

    def ensure_updated_refresh_token(self, update_interval_seconds=None):
        '''
        The client automatically performs a token refresh
        '''
        if not self.token_metadata:
            return None

        new_session = self.token_metadata.ensure_refresh_token_update(
            self.api_key, self.session, update_interval_seconds)
        if new_session:
            self.session = new_session

        return new_session is not None

    def set_timeout(self, timeout):
        '''Sets the timeout configuration for this client. Applies to all HTTP 
        calls.

        :param timeout: ``httpx`` timeout configuration. Passed directly to 
                        underlying ``httpx`` library. See
                        `here <https://www.python-httpx.org/advanced/
                        #setting-a-default-timeout-on-a-client>`__ for
                        examples.'''
        self.session.timeout = timeout


    ##########################################################################
    # Accounts

    class Account:
        class Fields(Enum):
            '''Account fields passed to :meth:`get_account` and
            :meth:`get_accounts`'''
            POSITIONS = 'positions'

    def get_account(self, account_hash, *, fields=None):
        '''Account balances, positions, and orders for a given account hash..

        :param fields: Balances displayed by default, additional fields can be
                       added here by adding values from :class:`Account.Fields`.
        '''
        fields = self.convert_enum_iterable(fields, self.Account.Fields)

        params = {}
        if fields:
            params['fields'] = ','.join(fields)

        path = '/trader/v1/accounts/{}'.format(account_hash)
        return self._get_request(path, params)

    def get_account_numbers(self):
        '''
        Returns a mapping from account IDs available to this token to the 
        account hash that should be passed whenever referring to that account in 
        API calls.
        '''
        path = '/trader/v1/accounts/accountNumbers'
        return self._get_request(path, {})

    def get_accounts(self, *, fields=None):
        '''Account balances, positions, and orders for all linked accounts. Note 
        this method does not return account hashes. See 
        :ref:`this method <account_hashes_method>` for more detail.

        :param fields: Balances displayed by default, additional fields can be
                       added here by adding values from :class:`Account.Fields`.
        '''
        fields = self.convert_enum_iterable(fields, self.Account.Fields)

        params = {}
        if fields:
            params['fields'] = ','.join(fields)

        path = '/trader/v1/accounts'
        return self._get_request(path, params)


    ##########################################################################
    # Price History

    class PriceHistory:
        class PeriodType(Enum):
            DAY = 'day'
            MONTH = 'month'
            YEAR = 'year'
            YEAR_TO_DATE = 'ytd'

        class Period(Enum):
            # Daily
            ONE_DAY = 1
            TWO_DAYS = 2
            THREE_DAYS = 3
            FOUR_DAYS = 4
            FIVE_DAYS = 5
            TEN_DAYS = 10

            # Monthly
            ONE_MONTH = 1
            TWO_MONTHS = 2
            THREE_MONTHS = 3
            SIX_MONTHS = 6

            # Year
            ONE_YEAR = 1
            TWO_YEARS = 2
            THREE_YEARS = 3
            FIVE_YEARS = 5
            TEN_YEARS = 10
            FIFTEEN_YEARS = 15
            TWENTY_YEARS = 20

            # Year to date
            YEAR_TO_DATE = 1

        class FrequencyType(Enum):
            MINUTE = 'minute'
            DAILY = 'daily'
            WEEKLY = 'weekly'
            MONTHLY = 'monthly'

        class Frequency(Enum):
            # Minute
            EVERY_MINUTE = 1
            EVERY_FIVE_MINUTES = 5
            EVERY_TEN_MINUTES = 10
            EVERY_FIFTEEN_MINUTES = 15
            EVERY_THIRTY_MINUTES = 30

            # Other frequencies
            DAILY = 1
            WEEKLY = 1
            MONTHLY = 1

    def get_price_history(
            self,
            symbol,
            *,
            period_type=None,
            period=None,
            frequency_type=None,
            frequency=None,
            start_datetime=None,
            end_datetime=None,
            need_extended_hours_data=None,
            need_previous_close=None):
        '''Get price history for a symbol.

        :param period_type: The type of period to show.
        :param period: The number of periods to show. Should not be provided if
                       ``start_datetime`` and ``end_datetime``.
        :param frequency_type: The type of frequency with which a new candle
                               is formed.
        :param frequency: The number of the frequencyType to be included in each
                          candle.
        :param start_datetime: Start date.
        :param end_datetime: End date. Default is previous trading day.
        :param need_extended_hours_data: If true, return extended hours data.
                                         Default is true.
        :param need_previous_close: If true, return the previous close price and 
                                    date.
        '''
        period_type = self.convert_enum(
            period_type, self.PriceHistory.PeriodType)
        period = self.convert_enum(period, self.PriceHistory.Period)
        frequency_type = self.convert_enum(
            frequency_type, self.PriceHistory.FrequencyType)
        frequency = self.convert_enum(
            frequency, self.PriceHistory.Frequency)

        params = {
                'symbol': symbol,
        }

        if period_type is not None:
            params['periodType'] = period_type
        if period is not None:
            params['period'] = period
        if frequency_type is not None:
            params['frequencyType'] = frequency_type
        if frequency is not None:
            params['frequency'] = frequency
        if start_datetime is not None:
            params['startDate'] = self._datetime_as_millis(
                'start_datetime', start_datetime)
        if end_datetime is not None:
            params['endDate'] = self._datetime_as_millis(
                'end_datetime', end_datetime)
        if need_extended_hours_data is not None:
            params['needExtendedHoursData'] = need_extended_hours_data
        if need_previous_close is not None:
            params['needPreviousClose'] = need_previous_close

        path = '/marketdata/v1/pricehistory'.format(symbol)
        return self._get_request(path, params)


    ##########################################################################
    # Price history utilities


    def __normalize_start_and_end_datetimes(self, start_datetime, end_datetime):
        if start_datetime is None:
            start_datetime = datetime.datetime(year=1971, month=1, day=1)
        if end_datetime is None:
            end_datetime = (datetime.datetime.utcnow() +
                    datetime.timedelta(days=7))

        return start_datetime, end_datetime


    def get_price_history_every_minute(
            self, symbol, *, start_datetime=None, end_datetime=None, 
            need_extended_hours_data=None, need_previous_close=None):
        '''
        Fetch price history for a stock or ETF symbol at a per-minute
        granularity. This endpoint currently appears to return up to 48 days of
        data.
        '''

        start_datetime, end_datetime = self.__normalize_start_and_end_datetimes(
                start_datetime, end_datetime)

        return self.get_price_history(
                symbol,
                period_type=self.PriceHistory.PeriodType.DAY,
                period=self.PriceHistory.Period.ONE_DAY,
                frequency_type=self.PriceHistory.FrequencyType.MINUTE,
                frequency=self.PriceHistory.Frequency.EVERY_MINUTE,
                start_datetime=start_datetime,
                end_datetime=end_datetime,
                need_extended_hours_data=need_extended_hours_data, 
                need_previous_close=need_previous_close)


    def get_price_history_every_five_minutes(
            self, symbol, *, start_datetime=None, end_datetime=None, 
            need_extended_hours_data=None, need_previous_close=None):
        '''
        Fetch price history for a stock or ETF symbol at a per-five-minutes
        granularity. This endpoint currently appears to return approximately
        nine months of data.
        '''

        start_datetime, end_datetime = self.__normalize_start_and_end_datetimes(
                start_datetime, end_datetime)

        return self.get_price_history(
                symbol,
                period_type=self.PriceHistory.PeriodType.DAY,
                period=self.PriceHistory.Period.ONE_DAY,
                frequency_type=self.PriceHistory.FrequencyType.MINUTE,
                frequency=self.PriceHistory.Frequency.EVERY_FIVE_MINUTES,
                start_datetime=start_datetime,
                end_datetime=end_datetime,
                need_extended_hours_data=need_extended_hours_data, 
                need_previous_close=need_previous_close)


    def get_price_history_every_ten_minutes(
            self, symbol, *, start_datetime=None, end_datetime=None, 
            need_extended_hours_data=None, need_previous_close=None):
        '''
        Fetch price history for a stock or ETF symbol at a per-ten-minutes
        granularity. This endpoint currently appears to return approximately
        nine months of data.
        '''

        start_datetime, end_datetime = self.__normalize_start_and_end_datetimes(
                start_datetime, end_datetime)

        return self.get_price_history(
                symbol,
                period_type=self.PriceHistory.PeriodType.DAY,
                period=self.PriceHistory.Period.ONE_DAY,
                frequency_type=self.PriceHistory.FrequencyType.MINUTE,
                frequency=self.PriceHistory.Frequency.EVERY_TEN_MINUTES,
                start_datetime=start_datetime,
                end_datetime=end_datetime,
                need_extended_hours_data=need_extended_hours_data, 
                need_previous_close=need_previous_close)


    def get_price_history_every_fifteen_minutes(
            self, symbol, *, start_datetime=None, end_datetime=None, 
            need_extended_hours_data=None, need_previous_close=None):
        '''
        Fetch price history for a stock or ETF symbol at a per-fifteen-minutes
        granularity. This endpoint currently appears to return approximately
        nine months of data.
        '''

        start_datetime, end_datetime = self.__normalize_start_and_end_datetimes(
                start_datetime, end_datetime)

        return self.get_price_history(
                symbol,
                period_type=self.PriceHistory.PeriodType.DAY,
                period=self.PriceHistory.Period.ONE_DAY,
                frequency_type=self.PriceHistory.FrequencyType.MINUTE,
                frequency=self.PriceHistory.Frequency.EVERY_FIFTEEN_MINUTES,
                start_datetime=start_datetime,
                end_datetime=end_datetime,
                need_extended_hours_data=need_extended_hours_data, 
                need_previous_close=need_previous_close)


    def get_price_history_every_thirty_minutes(
            self, symbol, *, start_datetime=None, end_datetime=None, 
            need_extended_hours_data=None, need_previous_close=None):
        '''
        Fetch price history for a stock or ETF symbol at a per-thirty-minutes
        granularity. This endpoint currently appears to return approximately
        nine months of data.
        '''

        start_datetime, end_datetime = self.__normalize_start_and_end_datetimes(
                start_datetime, end_datetime)

        return self.get_price_history(
                symbol,
                period_type=self.PriceHistory.PeriodType.DAY,
                period=self.PriceHistory.Period.ONE_DAY,
                frequency_type=self.PriceHistory.FrequencyType.MINUTE,
                frequency=self.PriceHistory.Frequency.EVERY_THIRTY_MINUTES,
                start_datetime=start_datetime,
                end_datetime=end_datetime,
                need_extended_hours_data=need_extended_hours_data, 
                need_previous_close=need_previous_close)


    def get_price_history_every_day(
            self, symbol, *, start_datetime=None, end_datetime=None, 
            need_extended_hours_data=None, need_previous_close=None):
        '''
        Fetch price history for a stock or ETF symbol at a daily granularity. 
        The exact period of time over which this endpoint returns data is 
        unclear, although it has been observed returning data as far back as 
        1985 (for ``AAPL``).
        '''

        start_datetime, end_datetime = self.__normalize_start_and_end_datetimes(
                start_datetime, end_datetime)

        return self.get_price_history(
                symbol,
                period_type=self.PriceHistory.PeriodType.YEAR,
                period=self.PriceHistory.Period.TWENTY_YEARS,
                frequency_type=self.PriceHistory.FrequencyType.DAILY,
                frequency=self.PriceHistory.Frequency.EVERY_MINUTE,
                start_datetime=start_datetime,
                end_datetime=end_datetime,
                need_extended_hours_data=need_extended_hours_data, 
                need_previous_close=need_previous_close)


    def get_price_history_every_week(
            self, symbol, *, start_datetime=None, end_datetime=None, 
            need_extended_hours_data=None, need_previous_close=None):
        '''
        Fetch price history for a stock or ETF symbol at a weekly granularity.
        The exact period of time over which this endpoint returns data is 
        unclear, although it has been observed returning data as far back as 
        1985 (for ``AAPL``).
        '''

        start_datetime, end_datetime = self.__normalize_start_and_end_datetimes(
                start_datetime, end_datetime)

        return self.get_price_history(
                symbol,
                period_type=self.PriceHistory.PeriodType.YEAR,
                period=self.PriceHistory.Period.TWENTY_YEARS,
                frequency_type=self.PriceHistory.FrequencyType.WEEKLY,
                frequency=self.PriceHistory.Frequency.EVERY_MINUTE,
                start_datetime=start_datetime,
                end_datetime=end_datetime,
                need_extended_hours_data=need_extended_hours_data, 
                need_previous_close=need_previous_close)


    ##########################################################################
    # Orders

    def cancel_order(self, order_id, account_hash):
        '''Cancel a specific order for a specific account'''
        path = '/trader/v1/accounts/{}/orders/{}'.format(account_hash, order_id)
        return self._delete_request(path)

    def get_order(self, order_id, account_hash):
        '''Get a specific order for a specific account by its order ID'''
        path = '/trader/v1/accounts/{}/orders/{}'.format(account_hash, order_id)
        return self._get_request(path, {})

    class Order:
        class Status(Enum):
            '''Order statuses passed to :meth:`get_orders_for_account` and
            :meth:`get_orders_for_all_linked_accounts`'''
            AWAITING_PARENT_ORDER = 'AWAITING_PARENT_ORDER'
            AWAITING_CONDITION = 'AWAITING_CONDITION'
            AWAITING_MANUAL_REVIEW = 'AWAITING_MANUAL_REVIEW'
            ACCEPTED = 'ACCEPTED'
            AWAITING_UR_OUT = 'AWAITING_UR_OUT'
            PENDING_ACTIVATION = 'PENDING_ACTIVATION'
            QUEUED = 'QUEUED'
            WORKING = 'WORKING'
            REJECTED = 'REJECTED'
            PENDING_CANCEL = 'PENDING_CANCEL'
            CANCELED = 'CANCELED'
            PENDING_REPLACE = 'PENDING_REPLACE'
            REPLACED = 'REPLACED'
            FILLED = 'FILLED'
            EXPIRED = 'EXPIRED'

    def _make_order_query(self,
                          *,
                          max_results=None,
                          from_entered_datetime=None,
                          to_entered_datetime=None,
                          status=None):
        status = self.convert_enum(status, self.Order.Status)

        if from_entered_datetime is None:
            from_entered_datetime = datetime.datetime(
                year=2024, month=4, day=1)
        if to_entered_datetime is None:
            to_entered_datetime = datetime.datetime.utcnow()

        params = {
            'fromEnteredTime': self._format_datetime(
                'from_entered_datetime', from_entered_datetime),
            'toEnteredTime': self._format_datetime(
                'to_entered_datetime', to_entered_datetime),
        }

        if max_results:
            params['maxResults'] = max_results

        if status:
            params['status'] = status

        return params

    def get_orders_for_account(self,
                               account_hash,
                               *,
                               max_results=None,
                               from_entered_datetime=None,
                               to_entered_datetime=None,
                               status=None):
        '''Orders for a specific account. Optionally specify a single status on 
        which to filter.

        :param max_results: The maximum number of orders to retrieve.
        :param from_entered_datetime: Specifies that no orders entered before
                                      this time should be returned. Date must
                                      be within 60 days from today's date.
                                      ``toEnteredTime`` must also be set.
        :param to_entered_datetime: Specifies that no orders entered after this
                                    time should be returned. ``fromEnteredTime``
                                    must also be set.
        :param status: Restrict query to orders with this status. See
                       :class:`Order.Status` for options.
        :param statuses: Restrict query to orders with any of these statuses.
                         See :class:`Order.Status` for options.
        '''
        path = '/trader/v1/accounts/{}/orders'.format(account_hash)
        return self._get_request(path, self._make_order_query(
            max_results=max_results,
            from_entered_datetime=from_entered_datetime,
            to_entered_datetime=to_entered_datetime,
            status=status))

    def get_orders_for_all_linked_accounts(self,
                                           *,
                                           max_results=None,
                                           from_entered_datetime=None,
                                           to_entered_datetime=None,
                                           status=None,
                                           statuses=None):
        '''Orders for all linked accounts. Optionally specify a single status on 
        which to filter.

        :param max_results: The maximum number of orders to retrieve.
        :param from_entered_datetime: Specifies that no orders entered before
                                      this time should be returned. Date must
                                      be within 60 days from today's date.
                                      ``toEnteredTime`` must also be set.
        :param to_entered_datetime: Specifies that no orders entered after this
                                    time should be returned. ``fromEnteredTime``
                                    must also be set.
        :param status: Restrict query to orders with this status. See
                       :class:`Order.Status` for options.
        '''
        path = '/trader/v1/orders'
        return self._get_request(path, self._make_order_query(
            max_results=max_results,
            from_entered_datetime=from_entered_datetime,
            to_entered_datetime=to_entered_datetime,
            status=status))

    def place_order(self, account_hash, order_spec):
        '''Place an order for a specific account. If order creation was
        successful, the response will contain the ID of the generated order. See
        :meth:`schwab.utils.Utils.extract_order_id` for more details. Note unlike
        most methods in this library, responses for successful calls to this
        method typically do not contain ``json()`` data, and attempting to
        extract it will likely result in an exception.'''
        if isinstance(order_spec, OrderBuilder):
            order_spec = order_spec.build()

        path = '/v1/trader/accounts/{}/orders'.format(account_hash)
        return self._post_request(path, order_spec)

    def replace_order(self, account_hash, order_id, order_spec):
        '''Replace an existing order for an account. The existing order will be
        replaced by the new order. Once replaced, the old order will be canceled
        and a new order will be created.'''
        if isinstance(order_spec, OrderBuilder):
            order_spec = order_spec.build()

        path = '/trader/v1/accounts/{}/orders/{}'.format(account_hash, order_id)
        return self._put_request(path, order_spec)

    def preview_order(self, account_hash, order_spec):
        '''Preview an order, i.e. test whether an order would be accepted by the 
        API and see the structure it would result in.'''
        if isinstance(order_spec, OrderBuilder):
            order_spec = order_spec.build()

        path = '/v1/trader/accounts/{}/previewOrder'.format(account_hash)
        return self._post_request(path, order_spec)


    ##########################################################################
    # Quotes

    class GetQuote:
        class Fields(Enum):
            QUOTE = 'quote'
            FUNDAMENTAL = 'fundamental'

    def get_quote(self, symbol, *, fields=None):
        '''
        Get quote for a symbol. Note due to limitations in URL encoding, this
        method is not recommended for instruments with symbols symbols
        containing non-alphanumeric characters, for example as futures like
        ``/ES``. To get quotes for those symbols, use :meth:`Client.get_quotes`.

        :param symbol: Single symbol to fetch
        :param fields: Fields to request. If unset, return all available data. 
                       i.e. all fields. See :class:`GetQuote.Field` for options.
        '''
        fields = self.convert_enum_iterable(fields, self.GetQuote.Fields)
        if fields:
            params = {'fields': fields}
        else:
            params = {}

        path = '/marketdata/v1/{}/quotes'.format(symbol)
        return self._get_request(path, params)

    def get_quotes(self, symbols, *, fields=None, indicative=None):
        '''Get quote for a symbol. This method supports all symbols, including
        those containing non-alphanumeric characters like ``/ES``.

        :param symbols: Iterable of symbols to fetch.
        :param fields: Fields to request. If unset, return all available data. 
                       i.e. all fields. See :class:`GetQuote.Field` for options.
        '''
        if isinstance(symbols, str):
            symbols = [symbols]

        params = {
            'symbols': ','.join(symbols)
        }

        fields = self.convert_enum_iterable(fields, self.GetQuote.Fields)
        if fields:
            params['fields'] = fields

        if indicative is not None:
            if type(indicative) is not bool:
                raise ValueError(
                        'value of \'indicative\' must be either True or False')
            params['indicative'] = 'true' if indicative else 'false'

        path = '/marketdata/v1/quotes'
        return self._get_request(path, params)


