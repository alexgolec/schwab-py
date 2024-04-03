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
            ORDERS = 'orders'

    def get_account(self, account_id, *, fields=None):
        '''Account balances, positions, and orders for a specific account.
        `Official documentation
        <https://developer.tdameritrade.com/account-access/apis/get/accounts/
        %7BaccountId%7D-0>`__.

        :param fields: Balances displayed by default, additional fields can be
                       added here by adding values from :class:`Account.Fields`.
        '''
        fields = self.convert_enum_iterable(fields, self.Account.Fields)

        params = {}
        if fields:
            params['fields'] = ','.join(fields)

        path = '/trader/v1/accounts/{}'.format(account_id)
        return self._get_request(path, params)

    def get_account_numbers(self):
        '''
        TODO
        '''
        path = '/trader/v1/accounts/accountNumbers'
        return self._get_request(path, {})

    def get_accounts(self, *, fields=None):
        '''Account balances, positions, and orders for all linked accounts.
        `Official documentation
        <https://developer.tdameritrade.com/account-access/apis/get/
        accounts-0>`__.

        :param fields: Balances displayed by default, additional fields can be
                       added here by adding values from :class:`Account.Fields`.
        '''
        fields = self.convert_enum_iterable(fields, self.Account.Fields)

        params = {}
        if fields:
            params['fields'] = ','.join(fields)

        path = '/trader/v1/accounts'
        return self._get_request(path, params)


