from abc import ABC, abstractmethod
from collections import defaultdict, deque
from enum import Enum

import asyncio
import copy
import datetime
import httpx
import inspect
import json
import logging
import schwab
import urllib.parse

import websockets.legacy.client as ws_client

from .utils import EnumEnforcer, LazyLog


class StreamJsonDecoder(ABC):
    @abstractmethod
    def decode_json_string(self, raw):
        '''
        Parse a JSON-formatted string into a proper object. Raises
        ``JSONDecodeError`` on parse failure.
        '''
        raise NotImplementedError()


class NaiveJsonStreamDecoder(StreamJsonDecoder):
    def decode_json_string(self, raw):
        return json.loads(raw)


def get_logger():
    return logging.getLogger(__name__)


class _BaseFieldEnum(Enum):
    @classmethod
    def all_fields(cls):
        return list(cls)

    @classmethod
    def key_mapping(cls):
        try:
            return cls._key_mapping
        except AttributeError:
            cls._key_mapping = dict(
                (str(enum.value), name)
                for name, enum in cls.__members__.items())
            return cls._key_mapping

    @classmethod
    def relabel_message(cls, old_msg, new_msg):
        # Make a copy of the items so we can modify the dict during iteration
        for old_key, value in list(old_msg.items()):
            if old_key in cls.key_mapping():
                new_key = cls.key_mapping()[old_key]
                new_msg[new_key] = new_msg.pop(old_key)


class UnexpectedResponse(Exception):
    def __init__(self, response, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.response = response


class UnexpectedResponseCode(Exception):
    def __init__(self, response, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.response = response


class UnparsableMessage(Exception):
    def __init__(self, raw_msg, json_parse_exception, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.raw_msg = raw_msg
        self.json_parse_exception = json_parse_exception


class _Handler:
    def __init__(self, func, field_enum_type):
        self._func = func
        self._field_enum_type = field_enum_type

    def __call__(self, *args, **kwargs):
        return self._func(*args, **kwargs)

    def label_message(self, msg):
        if 'content' in msg:
            new_msg = copy.deepcopy(msg)
            for idx in range(len(msg['content'])):
                self._field_enum_type.relabel_message(msg['content'][idx],
                                                      new_msg['content'][idx])
            return new_msg
        else:
            return msg


class StreamClient(EnumEnforcer):

    def __init__(self, client, *, account_id=None,
                 enforce_enums=True, ssl_context=None):
        super().__init__(enforce_enums)

        self._ssl_context = ssl_context
        self._client = client

        # Set by the login() function
        self._account = None
        self._stream_correl_id = None
        self._stream_customer_id = None
        self._stream_channel = None
        self._stream_function_id = None
        self._socket = None

        # Internal fields
        self._request_id = 0
        self._handlers = defaultdict(list)

        # When listening for responses, we sometimes encounter non-response
        # messages. Since this happens outside the context of the handler
        # dispatcher, we cannot handle these messages. However, we still need to
        # deliver these messages. This list records the messages that were read
        # from the stream but not handled yet. Messages should be read from this
        # list before they are read from the stream.
        self._overflow_items = deque()

        # Logging-related fields
        self.logger = get_logger()
        self.request_number = 0

        # Initialize the JSON parser to be the naive parser which directly calls
        # ``json.loads``
        self.json_decoder = NaiveJsonStreamDecoder()
        self._lock = asyncio.Lock()

    def set_json_decoder(self, json_decoder):
        '''
        Sets a custom JSON decoder.

        :param json_decoder: Custom JSON decoder to use for to decode all
                             incoming JSON strings. See
                             :class:`StreamJsonDecoder` for details.
        '''
        if not isinstance(json_decoder, schwab.contrib.util.StreamJsonDecoder):
            raise ValueError('Custom JSON parser must be a subclass of ' +
                             'schwab.contrib.util.StreamJsonDecoder')
        self.json_decoder = json_decoder

    def req_num(self):
        self.request_number += 1
        return self.request_number

    async def _send(self, obj):
        if self._socket is None:
            raise ValueError(
                'Socket not open. Did you forget to call login()?')

        self.logger.debug('Send %s: Sending %s',
                self.req_num(), LazyLog(lambda: json.dumps(obj, indent=4)))

        await self._socket.send(json.dumps(obj))

    async def _receive(self):
        if self._socket is None:
            raise ValueError(
                'Socket not open. Did you forget to call login()?')

        if len(self._overflow_items) > 0:
            ret = self._overflow_items.pop()

            self.logger.debug(
                'Receive %s: Returning message from overflow: %s',
                self.req_num(), LazyLog(lambda: json.dumps(ret, indent=4)))
        else:
            raw = await self._socket.recv()
            try:
                ret = self.json_decoder.decode_json_string(raw)
            except json.decoder.JSONDecodeError as e:
                msg = ('Failed to parse message. This often happens with ' +
                       'unknown symbols or other error conditions. Full ' +
                       'message text: ' + raw)
                raise UnparsableMessage(raw, e, msg)

            self.logger.debug(
                'Receive %s: Returning message from stream: %s',
                self.req_num(), LazyLog(lambda: json.dumps(ret, indent=4)))

        return ret

    async def _init_from_preferences(self, prefs, websocket_connect_args):
        # Record streamer subscription keys
        stream_info = prefs['streamerInfo'][0]

        self._stream_correl_id = stream_info['schwabClientCorrelId']
        self._stream_customer_id = stream_info['schwabClientCustomerId']
        self._stream_channel = stream_info['schwabClientChannel']
        self._stream_function_id = stream_info['schwabClientFunctionId']

        # Initialize socket
        wss_url = stream_info['streamerSocketUrl']

        if self._ssl_context:
            websocket_connect_args['ssl'] = self._ssl_context

        self._socket = await ws_client.connect(
                wss_url, **websocket_connect_args)


    def _make_request(self, *, service, command, parameters):
        request_id = self._request_id
        self._request_id += 1

        request = {
            'service': service,
            'requestid': str(request_id),
            'command': command,
            'SchwabClientCustomerId': self._stream_customer_id,
            'SchwabClientCorrelId': self._stream_correl_id,
            'parameters': parameters,
        }

        return request, request_id

    async def _await_response(self, request_id, service, command):
        deferred_messages = []

        # Context handler to ensure we always append the deferred messages,
        # regardless of how we exit the await loop below
        class WriteDeferredMessages:
            def __init__(self, this_client):
                self.this_client = this_client

            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc_val, exc_tb):
                self.this_client._overflow_items.extendleft(deferred_messages)

        with WriteDeferredMessages(self):
            while True:
                resp = await self._receive()

                if 'response' not in resp:
                    deferred_messages.append(resp)
                    continue

                # Validate request ID
                resp_request_id = int(resp['response'][0]['requestid'])
                if resp_request_id != request_id:
                    raise UnexpectedResponse(
                        resp, 'unexpected requestid: {}'.format(
                            resp_request_id))

                # Validate service
                resp_service = resp['response'][0]['service']
                if resp_service != service:
                    raise UnexpectedResponse(
                        resp, 'unexpected service: {}'.format(
                            resp_service))

                # Validate command
                resp_command = resp['response'][0]['command']
                if resp_command != command:
                    raise UnexpectedResponse(
                        resp, 'unexpected command: {}'.format(
                            resp_command))

                # Validate response code
                resp_code = resp['response'][0]['content']['code']
                if resp_code != 0:
                    raise UnexpectedResponseCode(
                        resp,
                        'unexpected response code: {}, msg is \'{}\''.format(
                            resp_code,
                            resp['response'][0]['content']['msg']))

                break

    async def _service_op(self, symbols, service, command, field_type=None,
                          *, fields=None):
        parameters = {
            'keys': ','.join(symbols)
        }

        if field_type is not None:
            if fields is None:
                fields = field_type.all_fields()

            fields = sorted(self.convert_enum_iterable(fields, field_type))
            parameters['fields'] = ','.join(str(f) for f in fields)

        request, request_id = self._make_request(
            service=service, command=command,
            parameters=parameters)

        async with self._lock:
            await self._send({'requests': [request]})
            await self._await_response(request_id, service, command)

    async def handle_message(self):
        async with self._lock:
            msg = await self._receive()

        # response
        if 'response' in msg:
            raise UnexpectedResponse(msg,
                                     'unexpected response code during message handling: {}, msg is \'{}\''.format(
                                         msg['response'][0]['content']['code'],
                                         msg['response'][0]['content']['msg']))

        # data
        if 'data' in msg:
            for d in msg['data']:
                if d['service'] in self._handlers:
                    for handler in self._handlers[d['service']]:
                        labeled_d = handler.label_message(d)
                        h = handler(labeled_d)

                        # Check if h is an awaitable, if so schedule it
                        # This allows for both sync and async handlers
                        if inspect.isawaitable(h):
                            asyncio.ensure_future(h)

        # notify
        if 'notify' in msg:
            for d in msg['notify']:
                if 'heartbeat' in d:
                    pass
                else:
                    for handler in self._handlers[d['service']]:
                        h = handler(d)

                        # Check if h is an awaitable, if so schedule oit
                        # This allows for both sync and async handlers
                        if inspect.isawaitable(h):
                            asyncio.ensure_future(h)

    ##########################################################################
    # LOGIN

    async def login(self, websocket_connect_args=None):
        '''
        `Official Documentation <https://developer.tdameritrade.com/content/
        streaming-data#_Toc504640574>`__

        Performs initial stream setup:
         * Fetches streaming information from the HTTP client's
           :meth:`~tda.client.Client.get_user_principals` method
         * Initializes the socket
         * Builds and sends and authentication request
         * Waits for response indicating login success

        All stream operations are available after this method completes.

        :param websocket_connect_args: ``dict`` of additional arguments to pass
                                       to the websocket ``connect`` call. Useful 
                                       for setting timeouts and other connection 
                                       parameters. See `the official 
                                       documentation <https://websockets.readthedocs.io/en/stable/reference/client.html#websockets.client.connect>`__
                                       for details.
        '''

        # Fetch required data and initialize the client
        r = self._client.get_user_preferences()

        # We don't actually know whether the client is synchronous or
        # asynchronous, so work around by awaiting the response if necessary
        if inspect.iscoroutine(r):
            r = await r
        assert r.status_code == httpx.codes.OK, r.raise_for_status()
        r = r.json()

        await self._init_from_preferences(
                r, websocket_connect_args if websocket_connect_args else {})

        # Build and send the request object
        request_parameters = {
                'Authorization': self._client.token_metadata.token['access_token'],
                'SchwabClientChannel': self._stream_channel,
                'SchwabClientFunctionId': self._stream_function_id,
        }

        request, request_id = self._make_request(
            service='ADMIN', command='LOGIN',
            parameters=request_parameters)
        async with self._lock:
            await self._send({'requests': [request]})
            await self._await_response(request_id, 'ADMIN', 'LOGIN')

    ##########################################################################
    # ACCT_ACTIVITY

    class AccountActivityFields(_BaseFieldEnum):
        '''
        `Official documentation <https://developer.tdameritrade.com/content/
        streaming-data#_Toc504640580>`__

        Data fields for equity account activity. Primarily an implementation detail
        and not used in client code. Provided here as documentation for key
        values stored returned in the stream messages.
        '''

        #: Unknown
        FIELD_0 = 0

        #: Unknown
        FIELD_1 = 1

        #: Unknown
        FIELD_2 = 2

        #: Unknown
        FIELD_3 = 3

    async def account_activity_sub(self):
        '''
        `Official documentation <https://developer.tdameritrade.com/content/
        streaming-data#_Toc504640580>`__

        Subscribe to account activity for the account id associated with this
        streaming client. See :class:`AccountActivityFields` for more info.
        '''
        await self._service_op(
            [self._stream_correl_id], 'ACCT_ACTIVITY', 'SUBS',
            self.AccountActivityFields)

    async def account_activity_unsubs(self):
        '''
        `Official documentation <https://developer.tdameritrade.com/content/
        streaming-data#_Toc504640580>`__

        Un-Subscribe to account activity for the account id associated with this
        streaming client. See :class:`AccountActivityFields` for more info.
        '''
        await self._service_op([self._stream_correl_id], 'ACCT_ACTIVITY', 'UNSUBS')

    def add_account_activity_handler(self, handler):
        '''
        Adds a handler to the account activity subscription. See
        :ref:`registering_handlers` for details.
        '''
        self._handlers['ACCT_ACTIVITY'].append(_Handler(handler,
                                                        self.AccountActivityFields))

    ##########################################################################
    # CHART_EQUITY

    class ChartEquityFields(_BaseFieldEnum):
        '''
        `Official documentation <https://developer.tdameritrade.com/content/
        streaming-data#_Toc504640589>`__

        Data fields for equity OHLCV data. Primarily an implementation detail
        and not used in client code. Provided here as documentation for key
        values stored returned in the stream messages.
        '''

        #: Ticker symbol
        SYMBOL = 0

        #: Sequence number
        SEQUENCE = 1

        #: Today's open price
        OPEN_PRICE = 2

        #: Today's high price
        HIGH_PRICE = 3

        #: Today's low price
        LOW_PRICE = 4

        #: Previous day's close price
        CLOSE_PRICE = 5

        #: Today's trading volume
        VOLUME = 6

        #: Chart timestamp
        CHART_TIME_MILLIS = 7

        #: Chart day
        CHART_DAY = 8

    async def chart_equity_subs(self, symbols):
        '''
        `Official documentation <https://developer.tdameritrade.com/content/
        streaming-data#_Toc504640587>`__

        Subscribe to equity charts. Behavior is undefined if called multiple
        times.

        :param symbols: Equity symbols to subscribe to.'''
        await self._service_op(
            symbols, 'CHART_EQUITY', 'SUBS', self.ChartEquityFields,
            fields=self.ChartEquityFields.all_fields())

    async def chart_equity_unsubs(self, symbols):
        '''
        `Official documentation <https://developer.tdameritrade.com/content/
        streaming-data#_Toc504640587>`__

        Un-Subscribe to equity charts. Behavior is undefined if called multiple
        times.

        :param symbols: Equity symbols to subscribe to.'''
        await self._service_op(symbols, 'CHART_EQUITY', 'UNSUBS')

    async def chart_equity_add(self, symbols):
        '''
        `Official documentation <https://developer.tdameritrade.com/content/
        streaming-data#_Toc504640588>`__

        Add a symbol to the equity charts subscription. Behavior is undefined
        if called before :meth:`chart_equity_subs`.

        :param symbols: Equity symbols to add to the subscription.
        '''
        await self._service_op(
            symbols, 'CHART_EQUITY', 'ADD', self.ChartEquityFields,
            fields=self.ChartEquityFields.all_fields())

    def add_chart_equity_handler(self, handler):
        '''
        Adds a handler to the equity chart subscription. See
        :ref:`registering_handlers` for details.
        '''
        self._handlers['CHART_EQUITY'].append(_Handler(handler,
                                                       self.ChartEquityFields))

    ##########################################################################
    # CHART_FUTURES

    class ChartFuturesFields(_BaseFieldEnum):
        '''
        `Official documentation <https://developer.tdameritrade.com/content/
        streaming-data#_Toc504640592>`__

        Data fields for equity OHLCV data. Primarily an implementation detail
        and not used in client code. Provided here as documentation for key
        values stored returned in the stream messages.
        '''

        #: UNKNOWN
        FIELD_0 = 0

        #: UNKNOWN
        FIELD_1 = 1

        #: UNKNOWN
        FIELD_2 = 2

        #: UNKNOWN
        FIELD_3 = 3

        #: UNKNOWN
        FIELD_4 = 4

        #: UNKNOWN
        FIELD_5 = 5

        #: UNKNOWN
        FIELD_6 = 6

    async def chart_futures_subs(self, symbols):
        '''
        `Official documentation <https://developer.tdameritrade.com/content/
        streaming-data#_Toc504640587>`__

        Subscribe to futures charts. Behavior is undefined if called multiple
        times.

        :param symbols: Futures symbols to subscribe to.
        '''
        await self._service_op(
            symbols, 'CHART_FUTURES', 'SUBS', self.ChartFuturesFields,
            fields=self.ChartFuturesFields.all_fields())

    async def chart_futures_unsubs(self, symbols):
        '''
        `Official documentation <https://developer.tdameritrade.com/content/
        streaming-data#_Toc504640587>`__

        Un-Subscribe to futures charts. Behavior is undefined if called multiple
        times.

        :param symbols: Futures symbols to subscribe to.
        '''
        await self._service_op(symbols, 'CHART_FUTURES', 'UNSUBS')

    async def chart_futures_add(self, symbols):
        '''
        `Official documentation <https://developer.tdameritrade.com/content/
        streaming-data#_Toc504640590>`__

        Add a symbol to the futures chart subscription. Behavior is undefined
        if called before :meth:`chart_futures_subs`.

        :param symbols: Futures symbols to add to the subscription.
        '''
        await self._service_op(
            symbols, 'CHART_FUTURES', 'ADD', self.ChartFuturesFields,
            fields=self.ChartFuturesFields.all_fields())

    def add_chart_futures_handler(self, handler):
        '''
        Adds a handler to the futures chart subscription. See
        :ref:`registering_handlers` for details.
        '''
        self._handlers['CHART_FUTURES'].append(_Handler(handler,
                                                        self.ChartFuturesFields))

    ##########################################################################
    # LEVELONE_EQUITIES

    class LevelOneEquityFields(_BaseFieldEnum):
        '''
        `Official documentation <https://developer.tdameritrade.com/content/
        streaming-data#_Toc504640599>`__

        Fields for equity quotes.
        '''

        #: Ticker symbol
        SYMBOL = 0

        #: Bid price
        BID_PRICE = 1

        #: Ask price
        ASK_PRICE = 2

        #: Last trade price
        LAST_PRICE = 3

        #: Size of the highest bid
        BID_SIZE = 4

        #: Size of the lowest ask
        ASK_SIZE = 5

        #: Exchange ID of the lowest ask
        ASK_ID = 6

        #: Exchange ID of the highest bid
        BID_ID = 7

        #: Total volume trade to date
        TOTAL_VOLUME = 8

        #: Size of the last trade
        LAST_SIZE = 9

        #: Daily high price
        HIGH_PRICE = 10

        #: Daily low price
        LOW_PRICE = 11

        #: Previous close price
        CLOSE_PRICE = 12

        #: Exchange ID
        EXCHANGE_ID = 13

        #: Is this equity marginable?
        MARGINABLE = 14

        #: Description
        DESCRIPTION = 15

        #: Exchange ID of the last trade
        LAST_ID = 16

        #: Today's open price
        OPEN_PRICE = 17

        #: Net change
        NET_CHANGE = 18

        #: 52 week high price
        HIGH_PRICE_52_WEEK = 19

        #: 52 week low price
        LOW_PRICE_52_WEEK = 20

        #: P/E ratio
        PE_RATIO = 21

        #: Dividend amount
        DIVIDEND_AMOUNT = 22

        #: Dividend yield
        DIVIDEND_YIELD = 23

        #: ETF net asset value
        NAV = 24

        #: Exchange name
        EXCHANGE_NAME = 25

        #: Dividend date
        DIVIDEND_DATE = 26

        #: Is this a regular market quote?
        REGULAR_MARKET_QUOTE = 27

        #: Is this a regular market trade?
        REGULAR_MARKET_TRADE = 28

        #: Regular market last price
        REGULAR_MARKET_LAST_PRICE = 29

        #: Regular market last size
        REGULAR_MARKET_LAST_SIZE = 30

        #: Regular market net change
        REGULAR_MARKET_NET_CHANGE = 31

        #: Security status
        SECURITY_STATUS = 32

        #: Mark
        MARK = 33

        #: Quote time in milliseconds
        QUOTE_TIME_MILLIS = 34

        #: Last trade time in milliseconds
        TRADE_TIME_MILLIS = 35

        #: Regular market trade time in milliseconds
        REGULAR_MARKET_TRADE_MILLIS = 36

        #: Bid time in millis
        BID_TIME_MILLIS = 37

        #: Ask time in millis
        ASK_TIME_MILLIS = 38

        #: Ask MIC ID
        ASK_MIC_ID = 39

        #: Bid MIC ID
        BID_MIC_ID = 40

        #: Last trade MIC ID
        LAST_MIC_ID = 41

        #: Net change in percent
        NET_CHANGE_PERCENT = 42

        #: Regular market change in percent
        REGULAR_MARKET_CHANGE_PERCENT = 43

        #: Mark change
        MARK_CHANGE = 44

        #: Mark change in percent
        MARK_CHANGE_PERCENT = 45

        #: HTB quality
        HTB_QUALITY = 46

        #: HTB rate
        HTB_RATE = 47

        #: Is this equity hard to borrow?
        HARD_TO_BORROW = 48

        #: Is this equity shortable
        IS_SHORTABLE = 49

        #: Post market net change
        POST_MARKET_NET_CHANGE = 50

        #: Post market net change percent
        POST_MARKET_NET_CHANGE_PERCENT = 51

    async def level_one_equity_subs(self, symbols, *, fields=None):
        '''
        `Official documentation <https://developer.tdameritrade.com/content/
        streaming-data#_Toc504640599>`__

        Subscribe to level one equity quote data.

        :param symbols: Equity symbols to receive quotes for
        :param fields: Iterable of :class:`LevelOneEquityFields` representing
                       the fields to return in streaming entries. If unset, all
                       fields will be requested.
        '''
        if fields and self.LevelOneEquityFields.SYMBOL not in fields:
            fields.append(self.LevelOneEquityFields.SYMBOL)
        await self._service_op(
            symbols, 'LEVELONE_EQUITIES', 'SUBS', self.LevelOneEquityFields,
            fields=fields)

    async def level_one_equity_unsubs(self, symbols):
        '''
        `Official documentation <https://developer.tdameritrade.com/content/
        streaming-data#_Toc504640599>`__

        Un-Subscribe to level one equity quote data.

        :param symbols: Equity symbols to receive quotes for
        '''

        await self._service_op(symbols, 'LEVELONE_EQUITIES', 'UNSUBS')

    def add_level_one_equity_handler(self, handler):
        '''
        Register a function to handle level one equity quotes as they are sent.
        See :ref:`registering_handlers` for details.
        '''
        self._handlers['LEVELONE_EQUITIES'].append(
                _Handler(handler, self.LevelOneEquityFields))

    ##########################################################################
    # LEVELONE_OPTIONS

    class LevelOneOptionFields(_BaseFieldEnum):
        '''
        `Official documentation <https://developer.tdameritrade.com/content/
        streaming-data#_Toc504640601>`__
        '''

        #: Option symbol
        SYMBOL = 0

        #: Description
        DESCRIPTION = 1

        #: Highest bid price
        BID_PRICE = 2

        #: Lowest ask price
        ASK_PRICE = 3

        #: Last trade price
        LAST_PRICE = 4

        #: Today's high price
        HIGH_PRICE = 5

        #: Today's low price
        LOW_PRICE = 6

        #: Last close price
        CLOSE_PRICE = 7

        #: Today's total volume
        TOTAL_VOLUME = 8

        #: Open interest
        OPEN_INTEREST = 9

        #: Volatility
        VOLATILITY = 10

        #: Money intrinsic value
        MONEY_INTRINSIC_VALUE = 11

        #: Expiration year
        EXPIRATION_YEAR = 12

        #: MULTIPLIER
        MULTIPLIER = 13

        #: Digits
        DIGITS = 14

        #: Open price
        OPEN_PRICE = 15

        #: Highest bid size
        BID_SIZE = 16

        #: Lowest ask size
        ASK_SIZE = 17

        #: Last trade size
        LAST_SIZE = 18

        #: Net change
        NET_CHANGE = 19

        #: Strike type
        STRIKE_TYPE = 20

        #: Contract type
        CONTRACT_TYPE = 21

        #: Underlying symbol
        UNDERLYING = 22

        #: Expiration month
        EXPIRATION_MONTH = 23

        #: Deliverables
        DELIVERABLES = 24

        #: Time value
        TIME_VALUE = 25

        #: Expiration day
        EXPIRATION_DAY = 26

        #: Days to expiration
        DAYS_TO_EXPIRATION = 27

        #: Delta
        DELTA = 28

        #: GAMMA
        GAMMA = 29

        #: Theta
        THETA = 30

        #: Vega
        VEGA = 31

        #: Rho
        RHO = 32

        #: Security status
        SECURITY_STATUS = 33

        #: Theoretical option value
        THEORETICAL_OPTION_VALUE = 34

        #: Underlying price
        UNDERLYING_PRICE = 35

        #: UV expiration type
        UV_EXPIRATION_TYPE = 36

        #: Mark
        MARK = 37

        #: Quote time in millis
        QUOTE_TIME_MILLIS = 38

        #: Last trade time in millis
        TRADE_TIME_MILLIS = 39

        #: Exchange ID
        EXCHANGE_ID = 40

        #: Exchange name
        EXCHANGE_NAME = 41

        #: Last trading day
        LAST_TRADING_DAY = 42

        #: Settlement type
        SETTLEMENT_TYPE = 43

        #: Net percent change
        NET_PERCENT_CHANGE = 44

        #: Mark change
        MARK_CHANGE = 45

        #: Mark change in percent
        MARK_CHANGE_PERCENT = 46

        #: Implied yield
        IMPLIED_YIELD = 47

        #: Is penny stock?
        IS_PENNY = 48

        #: Option root
        OPTION_ROOT = 49

        #: 52 week high price
        HIGH_PRICE_52_WEEK = 50

        #: 52 week low price
        LOW_PRICE_52_WEEK = 51

        #: Indicative asking price
        INDICATIVE_ASKING_PRICE = 52

        #: Indicative bid price
        INDICATIVE_BID_PRICE = 53

        #: Indicative quote time
        INDICATIVE_QUOTE_TIME = 54

        #: Exercise type
        EXERCISE_TYPE = 55

    async def level_one_option_subs(self, symbols, *, fields=None):
        '''
        `Official documentation <https://developer.tdameritrade.com/content/
        streaming-data#_Toc504640602>`__

        Subscribe to level one option quote data.

        :param symbols: Option symbols to receive quotes for
        :param fields: Iterable of :class:`LevelOneOptionFields` representing
                       the fields to return in streaming entries. If unset, all
                       fields will be requested.
        '''
        if fields and self.LevelOneOptionFields.SYMBOL not in fields:
            fields.append(self.LevelOneOptionFields.SYMBOL)
        await self._service_op(
            symbols, 'LEVELONE_OPTIONS', 'SUBS', self.LevelOneOptionFields,
            fields=fields)

    async def level_one_option_unsubs(self, symbols):
        '''
        `Official documentation <https://developer.tdameritrade.com/content/
        streaming-data#_Toc504640602>`__

        Un-Subscribe to level one option quote data.

        :param symbols: Option symbols to receive quotes for
        '''
        await self._service_op(symbols, 'LEVELONE_OPTIONS', 'UNSUBS')

    def add_level_one_option_handler(self, handler):
        '''
        Register a function to handle level one options quotes as they are sent.
        See :ref:`registering_handlers` for details.
        '''
        self._handlers['LEVELONE_OPTIONS'].append(
                _Handler(handler, self.LevelOneOptionFields))

    ##########################################################################
    # LEVELONE_FUTURES

    class LevelOneFuturesFields(_BaseFieldEnum):
        '''
        `Official documentation <https://developer.tdameritrade.com/content/
        streaming-data#_Toc504640603>`__
        '''

        #: UNKNOWN
        FIELD_0 = 0

        #: UNKNOWN
        FIELD_1 = 1

        #: UNKNOWN
        FIELD_2 = 2

        #: UNKNOWN
        FIELD_3 = 3

        #: UNKNOWN
        FIELD_4 = 4

        #: UNKNOWN
        FIELD_5 = 5

        #: UNKNOWN
        FIELD_6 = 6

        #: UNKNOWN
        FIELD_7 = 7

        #: UNKNOWN
        FIELD_8 = 8

        #: UNKNOWN
        FIELD_9 = 9

        #: UNKNOWN
        FIELD_10 = 10

        #: UNKNOWN
        FIELD_11 = 11

        #: UNKNOWN
        FIELD_12 = 12

        #: UNKNOWN
        FIELD_13 = 13

        #: UNKNOWN
        FIELD_14 = 14

        #: UNKNOWN
        FIELD_15 = 15

        #: UNKNOWN
        FIELD_16 = 16

        #: UNKNOWN
        FIELD_17 = 17

        #: UNKNOWN
        FIELD_18 = 18

        #: UNKNOWN
        FIELD_19 = 19

        #: UNKNOWN
        FIELD_20 = 20

        #: UNKNOWN
        FIELD_21 = 21

        #: UNKNOWN
        FIELD_22 = 22

        #: UNKNOWN
        FIELD_23 = 23

        #: UNKNOWN
        FIELD_24 = 24

        #: UNKNOWN
        FIELD_25 = 25

        #: UNKNOWN
        FIELD_26 = 26

        #: UNKNOWN
        FIELD_27 = 27

        #: UNKNOWN
        FIELD_28 = 28

        #: UNKNOWN
        FIELD_29 = 29

        #: UNKNOWN
        FIELD_30 = 30

        #: UNKNOWN
        FIELD_31 = 31

        #: UNKNOWN
        FIELD_32 = 32

        #: UNKNOWN
        FIELD_33 = 33

        #: UNKNOWN
        FIELD_34 = 34

        #: UNKNOWN
        FIELD_35 = 35

    async def level_one_futures_subs(self, symbols, *, fields=None):
        '''
        `Official documentation <https://developer.tdameritrade.com/content/
        streaming-data#_Toc504640604>`__

        Subscribe to level one futures quote data.

        :param symbols: Futures symbols to receive quotes for
        :param fields: Iterable of :class:`LevelOneFuturesFields` representing
                       the fields to return in streaming entries. If unset, all
                       fields will be requested.
        '''
        if fields and self.LevelOneFuturesFields.FIELD_0 not in fields:
            fields.append(self.LevelOneFuturesFields.FIELD_0)
        await self._service_op(
            symbols, 'LEVELONE_FUTURES', 'SUBS', self.LevelOneFuturesFields,
            fields=fields)

    async def level_one_futures_unsubs(self, symbols):
        '''
        `Official documentation <https://developer.tdameritrade.com/content/
        streaming-data#_Toc504640604>`__

        Un-Subscribe to level one futures quote data.

        :param symbols: Futures symbols to receive quotes for
        '''

        await self._service_op(symbols, 'LEVELONE_FUTURES', 'UNSUBS')

    def add_level_one_futures_handler(self, handler):
        '''
        Register a function to handle level one futures quotes as they are sent.
        See :ref:`registering_handlers` for details.
        '''
        self._handlers['LEVELONE_FUTURES'].append(
            _Handler(handler, self.LevelOneFuturesFields))

    ##########################################################################
    # LEVELONE_FOREX

    class LevelOneForexFields(_BaseFieldEnum):
        '''
        `Official documentation <https://developer.tdameritrade.com/content/
        streaming-data#_Toc504640606>`__
        '''

        #: UNKNOWN
        FIELD_0 = 0

        #: UNKNOWN
        FIELD_1 = 1

        #: UNKNOWN
        FIELD_2 = 2

        #: UNKNOWN
        FIELD_3 = 3

        #: UNKNOWN
        FIELD_4 = 4

        #: UNKNOWN
        FIELD_5 = 5

        #: UNKNOWN
        FIELD_6 = 6

        #: UNKNOWN
        FIELD_7 = 7

        #: UNKNOWN
        FIELD_8 = 8

        #: UNKNOWN
        FIELD_9 = 9

        #: UNKNOWN
        FIELD_10 = 10

        #: UNKNOWN
        FIELD_11 = 11

        #: UNKNOWN
        FIELD_12 = 12

        #: UNKNOWN
        FIELD_13 = 13

        #: UNKNOWN
        FIELD_14 = 14

        #: UNKNOWN
        FIELD_15 = 15

        #: UNKNOWN
        FIELD_16 = 16

        #: UNKNOWN
        FIELD_17 = 17

        #: UNKNOWN
        FIELD_18 = 18

        #: UNKNOWN
        FIELD_19 = 19

        #: UNKNOWN
        FIELD_20 = 20

        #: UNKNOWN
        FIELD_21 = 21

        #: UNKNOWN
        FIELD_22 = 22

        #: UNKNOWN
        FIELD_23 = 23

        #: UNKNOWN
        FIELD_24 = 24

        #: UNKNOWN
        FIELD_25 = 25

        #: UNKNOWN
        FIELD_26 = 26

        #: UNKNOWN
        FIELD_27 = 27

        #: UNKNOWN
        FIELD_28 = 28

        #: UNKNOWN
        FIELD_29 = 29

    async def level_one_forex_subs(self, symbols, *, fields=None):
        '''
        `Official documentation <https://developer.tdameritrade.com/content/
        streaming-data#_Toc504640606>`__

        Subscribe to level one forex quote data.

        :param symbols: Forex symbols to receive quotes for
        :param fields: Iterable of :class:`LevelOneForexFields` representing
                       the fields to return in streaming entries. If unset, all
                       fields will be requested.
        '''
        if fields and self.LevelOneForexFields.FIELD_0 not in fields:
            fields.append(self.LevelOneForexFields.FIELD_0)
        await self._service_op(
            symbols, 'LEVELONE_FOREX', 'SUBS', self.LevelOneForexFields,
            fields=fields)

    async def level_one_forex_unsubs(self, symbols):
        '''
        `Official documentation <https://developer.tdameritrade.com/content/
        streaming-data#_Toc504640606>`__

        Un-Subscribe to level one forex quote data.

        :param symbols: Forex symbols to receive quotes for
        '''

        await self._service_op(symbols, 'LEVELONE_FOREX', 'UNSUBS')

    def add_level_one_forex_handler(self, handler):
        '''
        Register a function to handle level one forex quotes as they are sent.
        See :ref:`registering_handlers` for details.
        '''
        self._handlers['LEVELONE_FOREX'].append(_Handler(handler,
                                                         self.LevelOneForexFields))

    ##########################################################################
    # LEVELONE_FUTURES_OPTIONS

    class LevelOneFuturesOptionsFields(_BaseFieldEnum):
        '''
        `Official documentation <https://developer.tdameritrade.com/content/
        streaming-data#_Toc504640609>`__
        '''

        #: UNKNOWN
        FIELD_0 = 0

        #: UNKNOWN
        FIELD_1 = 1

        #: UNKNOWN
        FIELD_2 = 2

        #: UNKNOWN
        FIELD_3 = 3

        #: UNKNOWN
        FIELD_4 = 4

        #: UNKNOWN
        FIELD_5 = 5

        #: UNKNOWN
        FIELD_6 = 6

        #: UNKNOWN
        FIELD_7 = 7

        #: UNKNOWN
        FIELD_8 = 8

        #: UNKNOWN
        FIELD_9 = 9

        #: UNKNOWN
        FIELD_10 = 10

        #: UNKNOWN
        FIELD_11 = 11

        #: UNKNOWN
        FIELD_12 = 12

        #: UNKNOWN
        FIELD_13 = 13

        #: UNKNOWN
        FIELD_14 = 14

        #: UNKNOWN
        FIELD_15 = 15

        #: UNKNOWN
        FIELD_16 = 16

        #: UNKNOWN
        FIELD_17 = 17

        #: UNKNOWN
        FIELD_18 = 18

        #: UNKNOWN
        FIELD_19 = 19

        #: UNKNOWN
        FIELD_20 = 20

        #: UNKNOWN
        FIELD_21 = 21

        #: UNKNOWN
        FIELD_22 = 22

        #: UNKNOWN
        FIELD_23 = 23

        #: UNKNOWN
        FIELD_24 = 24

        #: UNKNOWN
        FIELD_25 = 25

        #: UNKNOWN
        FIELD_26 = 26

        #: UNKNOWN
        FIELD_27 = 27

        #: UNKNOWN
        FIELD_28 = 28

        #: UNKNOWN
        FIELD_29 = 29

        #: UNKNOWN
        FIELD_30 = 30

        #: UNKNOWN
        FIELD_31 = 31

        #: UNKNOWN
        FIELD_32 = 32

        #: UNKNOWN
        FIELD_33 = 33

        #: UNKNOWN
        FIELD_34 = 34

        #: UNKNOWN
        FIELD_35 = 35

    async def level_one_futures_options_subs(self, symbols, *, fields=None):
        '''
        `Official documentation <https://developer.tdameritrade.com/content/
        streaming-data#_Toc504640610>`__

        Subscribe to level one futures options quote data.

        :param symbols: Futures options symbols to receive quotes for
        :param fields: Iterable of :class:`LevelOneFuturesOptionsFields`
                       representing the fields to return in streaming entries.
                       If unset, all fields will be requested.
        '''
        if fields and self.LevelOneFuturesOptionsFields.FIELD_0 not in fields:
            fields.append(self.LevelOneFuturesOptionsFields.FIELD_0)
        await self._service_op(
            symbols, 'LEVELONE_FUTURES_OPTIONS', 'SUBS',
            self.LevelOneFuturesOptionsFields, fields=fields)

    async def level_one_futures_options_unsubs(self, symbols):
        '''
        `Official documentation <https://developer.tdameritrade.com/content/
        streaming-data#_Toc504640610>`__

        Un-Subscribe to level one futures options quote data.

        :param symbols: Futures options symbols to receive quotes for
        '''

        await self._service_op(symbols, 'LEVELONE_FUTURES_OPTIONS', 'UNSUBS')

    def add_level_one_futures_options_handler(self, handler):
        '''
        Register a function to handle level one futures options quotes as they
        are sent. See :ref:`registering_handlers` for details.
        '''
        self._handlers['LEVELONE_FUTURES_OPTIONS'].append(
            _Handler(handler, self.LevelOneFuturesOptionsFields))

    ##########################################################################
    # TIMESALE

    class TimesaleFields(_BaseFieldEnum):
        '''
        `Official documentation <https://developer.tdameritrade.com/content/
        streaming-data#_Toc504640626>`__
        '''

        #: UNKNOWN
        FIELD_0 = 0

        #: UNKNOWN
        FIELD_1 = 1

        #: UNKNOWN
        FIELD_2 = 2

        #: UNKNOWN
        FIELD_3 = 3

        #: UNKNOWN
        FIELD_4 = 4

    async def timesale_equity_subs(self, symbols, *, fields=None):
        '''
        `Official documentation <https://developer.tdameritrade.com/content/
        streaming-data#_Toc504640628>`__

        Subscribe to time of sale notifications for equities.

        :param symbols: Equity symbols to subscribe to
        '''
        if fields and self.TimesaleFields.FIELD_0 not in fields:
            fields.append(self.TimesaleFields.FIELD_0)
        await self._service_op(
            symbols, 'TIMESALE_EQUITY', 'SUBS',
            self.TimesaleFields, fields=fields)

    async def timesale_equity_unsubs(self, symbols):
        '''
        `Official documentation <https://developer.tdameritrade.com/content/
        streaming-data#_Toc504640628>`__

        Un-Subscribe to time of sale notifications for equities.

        :param symbols: Equity symbols to subscribe to
        '''

        await self._service_op(symbols, 'TIMESALE_EQUITY', 'UNSUBS')

    def add_timesale_equity_handler(self, handler):
        '''
        Register a function to handle equity trade notifications as they happen
        See :ref:`registering_handlers` for details.
        '''
        self._handlers['TIMESALE_EQUITY'].append(_Handler(handler,
                                                          self.TimesaleFields))

    async def timesale_futures_subs(self, symbols, *, fields=None):
        '''
        `Official documentation <https://developer.tdameritrade.com/content/
        streaming-data#_Toc504640628>`__

        Subscribe to time of sale notifications for futures.

        :param symbols: Futures symbols to subscribe to
        '''
        if fields and self.TimesaleFields.FIELD_0 not in fields:
            fields.append(self.TimesaleFields.FIELD_0)
        await self._service_op(
            symbols, 'TIMESALE_FUTURES', 'SUBS',
            self.TimesaleFields, fields=fields)

    async def timesale_futures_unsubs(self, symbols):
        '''
        `Official documentation <https://developer.tdameritrade.com/content/
        streaming-data#_Toc504640628>`__

        Un-Subscribe to time of sale notifications for futures.

        :param symbols: Futures symbols to subscribe to
        '''

        await self._service_op(symbols, 'TIMESALE_FUTURES', 'UNSUBS')

    def add_timesale_futures_handler(self, handler):
        '''
        Register a function to handle futures trade notifications as they happen
        See :ref:`registering_handlers` for details.
        '''
        self._handlers['TIMESALE_FUTURES'].append(_Handler(handler,
                                                           self.TimesaleFields))

    async def timesale_options_subs(self, symbols, *, fields=None):
        '''
        `Official documentation <https://developer.tdameritrade.com/content/
        streaming-data#_Toc504640628>`__

        Subscribe to time of sale notifications for options.

        :param symbols: Options symbols to subscribe to
        '''
        if fields and self.TimesaleFields.FIELD_0 not in fields:
            fields.append(self.TimesaleFields.FIELD_0)
        await self._service_op(
            symbols, 'TIMESALE_OPTIONS', 'SUBS',
            self.TimesaleFields, fields=fields)

    async def timesale_options_unsubs(self, symbols):
        '''
        `Official documentation <https://developer.tdameritrade.com/content/
        streaming-data#_Toc504640628>`__

        Un-Subscribe to time of sale notifications for options.

        :param symbols: Options symbols to subscribe to
        '''

        await self._service_op(symbols, 'TIMESALE_OPTIONS', 'UNSUBS')

    def add_timesale_options_handler(self, handler):
        '''
        Register a function to handle options trade notifications as they happen
        See :ref:`registering_handlers` for details.
        '''
        self._handlers['TIMESALE_OPTIONS'].append(_Handler(handler,
                                                           self.TimesaleFields))

    ##########################################################################
    # Common book utilities

    class BookFields(_BaseFieldEnum):
        SYMBOL = 0
        BOOK_TIME = 1
        BIDS = 2
        ASKS = 3

    class BidFields(_BaseFieldEnum):
        BID_PRICE = 0
        TOTAL_VOLUME = 1
        NUM_BIDS = 2
        BIDS = 3

    class PerExchangeBidFields(_BaseFieldEnum):
        EXCHANGE = 0
        BID_VOLUME = 1
        SEQUENCE = 2

    class AskFields(_BaseFieldEnum):
        ASK_PRICE = 0
        TOTAL_VOLUME = 1
        NUM_ASKS = 2
        ASKS = 3

    class PerExchangeAskFields(_BaseFieldEnum):
        EXCHANGE = 0
        ASK_VOLUME = 1
        SEQUENCE = 2

    class _BookHandler(_Handler):
        def label_message(self, msg):
            # Relabel top-level fields
            new_msg = super().label_message(msg)

            # Relabel bids
            for content in new_msg['content']:
                if 'BIDS' in content:
                    for bid in content['BIDS']:
                        # Relabel top-level bids
                        StreamClient.BidFields.relabel_message(bid, bid)

                        # Relabel per-exchange bids
                        for e_bid in bid['BIDS']:
                            StreamClient.PerExchangeBidFields.relabel_message(
                                e_bid, e_bid)

            # Relabel asks
            for content in new_msg['content']:
                if 'ASKS' in content:
                    for ask in content['ASKS']:
                        # Relabel top-level asks
                        StreamClient.AskFields.relabel_message(ask, ask)

                        # Relabel per-exchange bids
                        for e_ask in ask['ASKS']:
                            StreamClient.PerExchangeAskFields.relabel_message(
                                e_ask, e_ask)

            return new_msg

    ##########################################################################
    # LISTED_BOOK

    async def listed_book_subs(self, symbols):
        '''
        Subscribe to the NYSE level two order book. Note this stream has no
        official documentation.
        '''
        await self._service_op(
            symbols, 'LISTED_BOOK', 'SUBS',
            self.BookFields, fields=self.BookFields.all_fields())

    async def listed_book_unsubs(self, symbols):
        '''
        Un-Subscribe to the NYSE level two order book. Note this stream has no
        official documentation.
        '''
        await self._service_op(symbols, 'LISTED_BOOK', 'UNSUBS')

    def add_listed_book_handler(self, handler):
        '''
        Register a function to handle level two NYSE book data as it is updated
        See :ref:`registering_handlers` for details.
        '''
        self._handlers['LISTED_BOOK'].append(
            self._BookHandler(handler, self.BookFields))

    ##########################################################################
    # NASDAQ_BOOK

    async def nasdaq_book_subs(self, symbols):
        '''
        Subscribe to the NASDAQ level two order book. Note this stream has no
        official documentation.
        '''
        await self._service_op(symbols, 'NASDAQ_BOOK', 'SUBS',
                               self.BookFields,
                               fields=self.BookFields.all_fields())

    async def nasdaq_book_unsubs(self, symbols):
        '''
        Un-Subscribe to the NASDAQ level two order book. Note this stream has no
        official documentation.
        '''
        await self._service_op(symbols, 'NASDAQ_BOOK', 'UNSUBS')

    def add_nasdaq_book_handler(self, handler):
        '''
        Register a function to handle level two NASDAQ book data as it is
        updated See :ref:`registering_handlers` for details.
        '''
        self._handlers['NASDAQ_BOOK'].append(
            self._BookHandler(handler, self.BookFields))

    ##########################################################################
    # OPTIONS_BOOK

    async def options_book_subs(self, symbols):
        '''
        Subscribe to the level two order book for options. Note this stream has no
        official documentation, and it's not entirely clear what exchange it
        corresponds to. Use at your own risk.
        '''
        await self._service_op(symbols, 'OPTIONS_BOOK', 'SUBS',
                               self.BookFields,
                               fields=self.BookFields.all_fields())

    async def options_book_unsubs(self, symbols):
        '''
        Un-Subscribe to the level two order book for options. Note this stream has no
        official documentation, and it's not entirely clear what exchange it
        corresponds to. Use at your own risk.
        '''
        await self._service_op(symbols, 'OPTIONS_BOOK', 'UNSUBS')

    def add_options_book_handler(self, handler):
        '''
        Register a function to handle level two options book data as it is
        updated See :ref:`registering_handlers` for details.
        '''
        self._handlers['OPTIONS_BOOK'].append(
            self._BookHandler(handler, self.BookFields))

    ##########################################################################
    # NEWS_HEADLINE

    class NewsHeadlineFields(_BaseFieldEnum):
        '''
        `Official documentation <https://developer.tdameritrade.com/content/
        streaming-data#_Toc504640626>`__
        '''

        #: Ticker symbol in upper case. Represented in the stream as the
        #: ``key`` field.
        SYMBOL = 0

        #: Specifies if there is any error
        ERROR_CODE = 1

        #: Headline’s datetime in milliseconds since epoch
        STORY_DATETIME = 2

        #: Unique ID for the headline
        HEADLINE_ID = 3
        STATUS = 4

        #: News headline
        HEADLINE = 5
        STORY_ID = 6
        COUNT_FOR_KEYWORD = 7
        KEYWORD_ARRAY = 8
        IS_HOT = 9
        STORY_SOURCE = 10

    async def news_headline_subs(self, symbols):
        '''
        `Official documentation <https://developer.tdameritrade.com/content/
        streaming-data#_Toc504640626>`__

        Subscribe to news headlines related to the given symbols.
        '''
        await self._service_op(symbols, 'NEWS_HEADLINE', 'SUBS',
                               self.NewsHeadlineFields,
                               fields=self.NewsHeadlineFields.all_fields())

    async def news_headline_unsubs(self, symbols):
        '''
        `Official documentation <https://developer.tdameritrade.com/content/
        streaming-data#_Toc504640626>`__

        Un-Subscribe to news headlines related to the given symbols.
        '''
        await self._service_op(symbols, 'NEWS_HEADLINE', 'UNSUBS')

    def add_news_headline_handler(self, handler):
        '''
        Register a function to handle news headlines as they are provided. See
        :ref:`registering_handlers` for details.
        '''
        self._handlers['NEWS_HEADLINE'].append(
            self._BookHandler(handler, self.NewsHeadlineFields))
