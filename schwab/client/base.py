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

        tz_offset = dt.strftime('%z')
        tz_offset = tz_offset if tz_offset else '+0000'

        return dt.strftime('%Y-%m-%dT%H:%M:%S') + tz_offset

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



