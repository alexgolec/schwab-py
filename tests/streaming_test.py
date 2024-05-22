import schwab
import urllib.parse
import json
import copy
from .utils import account_preferences, has_diff, MockResponse, no_duplicates
from unittest.mock import ANY, AsyncMock, call, MagicMock, Mock, patch
from unittest import IsolatedAsyncioTestCase
from schwab import streaming

StreamClient = streaming.StreamClient


ACCOUNT_ID = 1000
ACCESS_TOKEN = '0xACCE55'
TOKEN_TIMESTAMP = '2020-05-22T02:12:48+0000'
REQUEST_TIMESTAMP = 1590116673258

CLIENT_CUSTOMER_ID = 'client-customer-id'
CLIENT_CORRELATION_ID = 'client-correlation-id'


# For matching calls in which JSON data is passed as a string
class StringMatchesJson:
    def __init__(self, d):
        self.d = d
    def __eq__(self, other):
        return self.d == json.loads(other)
    def __repr__(self):
        return json.dumps(self.d, indent=4)


class StreamClientTest(IsolatedAsyncioTestCase):

    def setUp(self):
        self.http_client = MagicMock()
        self.client = StreamClient(self.http_client)

        self.http_client.token_metadata.token = {'access_token': ACCESS_TOKEN}

        self.maxDiff = None

        with open('tests/testdata/preferences.json', 'r') as f:
            preferences = json.load(f)
            self.pref_customer_id = \
                    preferences['streamerInfo'][0]['schwabClientCustomerId']
            self.pref_correl_id = \
                    preferences['streamerInfo'][0]['schwabClientCorrelId']

    def account(self, index):
        account = account_preferences()['accounts'][0]
        account['accountNumber'] = str(ACCOUNT_ID + index)

        def parsable_as_int(s):
            try:
                int(s)
                return True
            except ValueError:
                return False
        for key, value in list(account.items()):
            if isinstance(value, str) and not parsable_as_int(value):
                account[key] = value + '-' + str(account['accountNumber'])

        return account

    def request_from_socket_mock(self, socket):
        return json.loads(
            socket.send.call_args_list[0][0][0])['requests'][0]

    def success_response(self, request_id, service, command, msg='success'):
        return {
            'response': [
                {
                    'service': service,
                    'requestid': str(request_id),
                    'command': command,
                    'timestamp': REQUEST_TIMESTAMP,
                    'content': {
                        'code': 0,
                        'msg': msg
                    }
                }
            ]
        }

    def streaming_entry(self, service, command, content=None):
        d = {
            'data': [{
                'service': service,
                'command': command,
                'timestamp': REQUEST_TIMESTAMP
            }]
        }

        if content:
            d['data'][0]['content'] = content

        return d

    def assert_handler_called_once_with(self, handler, expected):
        handler.assert_called_once()
        self.assertEqual(len(handler.call_args_list[0]), 2)
        data = handler.call_args_list[0][0][0] # Mock from <- 3.7 has a bad api

        self.assertFalse(has_diff(data, expected))

    async def login_and_get_socket(self, ws_connect):
        preferences = account_preferences()

        self.http_client.get_user_preferences.return_value = MockResponse(
            preferences, 200)
        socket = AsyncMock()
        ws_connect.return_value = socket

        socket.recv.side_effect = [json.dumps(self.success_response(
            0, 'ADMIN', 'LOGIN'))]

        await self.client.login()

        socket.reset_mock()
        return socket


    # TODO: Revive this test once the contrib module comes back.

    '''
    ##########################################################################
    # Custom JSON Decoder


    @patch('schwab.streaming.ws_client.connect', new_callable=AsyncMock)
    async def test_default_parser_invalid_message(self, ws_connect):
        socket = await self.login_and_get_socket(ws_connect)

        socket.recv.side_effect = ['invalid json']

        # No custom parser
        msg = ('Failed to parse message. This often happens with ' +
               'unknown symbols or other error conditions. Full ' +
               'message text:')
        with self.assertRaisesRegex(schwab.streaming.UnparsableMessage, msg):
            await self.client.level_one_equity_subs(['GOOG', 'MSFT'])


    @patch('schwab.streaming.ws_client.connect', new_callable=AsyncMock)
    async def test_custom_parser_invalid_message(self, ws_connect):
        socket = await self.login_and_get_socket(ws_connect)

        socket.recv.side_effect = ['invalid json']

        class CustomJsonDecoder(schwab.contrib.util.StreamJsonDecoder):
            def decode_json_string(_, raw):
                self.assertEqual(raw, 'invalid json')
                return self.success_response(1, 'LEVELONE_EQUITIES', 'SUBS')

        self.client.set_json_decoder(CustomJsonDecoder())
        await self.client.level_one_equity_subs(['GOOG', 'MSFT'])


    @patch('schwab.streaming.ws_client.connect', new_callable=AsyncMock)
    async def test_custom_parser_wrong_type(self, ws_connect):
        socket = await self.login_and_get_socket(ws_connect)

        socket.recv.side_effect = ['invalid json']

        with self.assertRaises(ValueError):
            self.client.set_json_decoder('')
    '''


    ##########################################################################
    # Login

    @no_duplicates
    @patch('schwab.streaming.ws_client.connect', new_callable=AsyncMock)
    async def test_login_single_account_success(self, ws_connect):
        preferences = account_preferences()
        preferences['accounts'].clear()
        preferences['accounts'].append(self.account(1))

        self.http_client.get_user_preferences.return_value = MockResponse(
            preferences, 200)
        socket = AsyncMock()
        ws_connect.return_value = socket

        socket.recv.side_effect = [json.dumps(self.success_response(
            0, 'ADMIN', 'LOGIN'))]

        await self.client.login()

        socket.send.assert_awaited_once()
        request = self.request_from_socket_mock(socket)
        self.assertEqual(request['parameters']['Authorization'], ACCESS_TOKEN)
        self.assertEqual(request['parameters']['SchwabClientChannel'],
                         'client-channel')
        self.assertEqual(request['parameters']['SchwabClientFunctionId'],
                         'client-function-id')

        self.assertEqual(request['requestid'], '0')
        self.assertEqual(request['service'], 'ADMIN')
        self.assertEqual(request['command'], 'LOGIN')

        self.assertEqual(request['SchwabClientCustomerId'],
                         CLIENT_CUSTOMER_ID)
        self.assertEqual(request['SchwabClientCorrelId'],
                         CLIENT_CORRELATION_ID)


    @no_duplicates
    @patch('schwab.streaming.ws_client.connect', new_callable=AsyncMock)
    async def test_login_single_account_success_async(self, ws_connect):
        '''
        Same as test_login_single_account_success except the underlying client 
        is asynchronous and returns a coroutine for get_user_preferences.
        '''
        preferences = account_preferences()
        preferences['accounts'].clear()
        preferences['accounts'].append(self.account(1))

        async def get_user_preferences(*args, **kwargs):
            return MockResponse(preferences, 200)

        self.http_client.get_user_preferences = get_user_preferences
        socket = AsyncMock()
        ws_connect.return_value = socket

        socket.recv.side_effect = [json.dumps(self.success_response(
            0, 'ADMIN', 'LOGIN'))]

        await self.client.login()

        socket.send.assert_awaited_once()
        request = self.request_from_socket_mock(socket)
        self.assertEqual(request['parameters']['Authorization'], ACCESS_TOKEN)
        self.assertEqual(request['parameters']['SchwabClientChannel'],
                         'client-channel')
        self.assertEqual(request['parameters']['SchwabClientFunctionId'],
                         'client-function-id')

        self.assertEqual(request['requestid'], '0')
        self.assertEqual(request['service'], 'ADMIN')
        self.assertEqual(request['command'], 'LOGIN')

        self.assertEqual(request['SchwabClientCustomerId'],
                         'client-customer-id')
        self.assertEqual(request['SchwabClientCorrelId'],
                         'client-correlation-id')


    @no_duplicates
    @patch('schwab.streaming.ws_client.connect', new_callable=AsyncMock)
    async def test_login_bad_response(self, ws_connect):
        preferences = account_preferences()
        preferences['accounts'].clear()

        self.http_client.get_user_preferences.return_value = MockResponse(
            preferences, 200)
        socket = AsyncMock()
        ws_connect.return_value = socket

        response = self.success_response(0, 'ADMIN', 'LOGIN')
        response['response'][0]['content']['code'] = 21
        response['response'][0]['content']['msg'] = 'failed for some reason'
        socket.recv.side_effect = [json.dumps(response)]

        with self.assertRaises(schwab.streaming.UnexpectedResponseCode):
            await self.client.login()


    @no_duplicates
    @patch('schwab.streaming.ws_client.connect', new_callable=AsyncMock)
    async def test_login_ssl_context(self, ws_connect):
        self.client = StreamClient(self.http_client, ssl_context='ssl_context')

        self.http_client.get_user_preferences.return_value = MockResponse(
            account_preferences(), 200)
        socket = AsyncMock()
        ws_connect.return_value = socket

        socket.recv.side_effect = [json.dumps(self.success_response(
            0, 'ADMIN', 'LOGIN'))]

        await self.client.login()

        ws_connect.assert_awaited_once_with(ANY, ssl='ssl_context')


    @no_duplicates
    @patch('schwab.streaming.ws_client.connect', new_callable=AsyncMock)
    async def test_login_websocket_connect_args(self, ws_connect):
        self.client = StreamClient(self.http_client, ssl_context='ssl_context')

        self.http_client.get_user_preferences.return_value = MockResponse(
            account_preferences(), 200)
        socket = AsyncMock()
        ws_connect.return_value = socket

        socket.recv.side_effect = [json.dumps(self.success_response(
            0, 'ADMIN', 'LOGIN'))]

        await self.client.login(websocket_connect_args={'args': 'yes'})

        ws_connect.assert_awaited_once_with(ANY, ssl='ssl_context', args='yes')


    @no_duplicates
    @patch('schwab.streaming.ws_client.connect', new_callable=AsyncMock)
    async def test_login_unexpected_request_id(self, ws_connect):
        preferences = account_preferences()
        preferences['accounts'].clear()
        preferences['accounts'].append(self.account(1))

        self.http_client.get_user_preferences.return_value = MockResponse(
            preferences, 200)
        socket = AsyncMock()
        ws_connect.return_value = socket

        response = self.success_response(0, 'ADMIN', 'LOGIN')
        response['response'][0]['requestid'] = 9999
        socket.recv.side_effect = [json.dumps(response)]

        with self.assertRaisesRegex(schwab.streaming.UnexpectedResponse,
                                    'unexpected requestid: 9999'):
            await self.client.login()


    @no_duplicates
    @patch('schwab.streaming.ws_client.connect', new_callable=AsyncMock)
    async def test_login_unexpected_service(self, ws_connect):
        preferences = account_preferences()
        preferences['accounts'].clear()
        preferences['accounts'].append(self.account(1))

        self.http_client.get_user_preferences.return_value = MockResponse(
            preferences, 200)
        socket = AsyncMock()
        ws_connect.return_value = socket

        response = self.success_response(0, 'NOT_ADMIN', 'LOGIN')
        socket.recv.side_effect = [json.dumps(response)]

        with self.assertRaisesRegex(schwab.streaming.UnexpectedResponse,
                                    'unexpected service: NOT_ADMIN'):
            await self.client.login()


    @no_duplicates
    @patch('schwab.streaming.ws_client.connect', new_callable=AsyncMock)
    async def test_login_unexpected_command(self, ws_connect):
        preferences = account_preferences()
        preferences['accounts'].clear()
        preferences['accounts'].append(self.account(1))

        self.http_client.get_user_preferences.return_value = MockResponse(
            preferences, 200)
        socket = AsyncMock()
        ws_connect.return_value = socket

        response = self.success_response(0, 'ADMIN', 'NOT_LOGIN')
        socket.recv.side_effect = [json.dumps(response)]

        with self.assertRaisesRegex(schwab.streaming.UnexpectedResponse,
                                    'unexpected command: NOT_LOGIN'):
            await self.client.login()


    ##########################################################################
    # ACCT_ACTIVITY

    @no_duplicates
    @patch('schwab.streaming.ws_client.connect', new_callable=AsyncMock)
    async def test_account_activity_subs_success(self, ws_connect):
        socket = await self.login_and_get_socket(ws_connect)

        socket.recv.side_effect = [json.dumps(self.success_response(
            1, 'ACCT_ACTIVITY', 'SUBS'))]

        await self.client.account_activity_sub()
        socket.recv.assert_awaited_once()
        request = self.request_from_socket_mock(socket)

        self.assertEqual(request, {
            'service': 'ACCT_ACTIVITY',
            'command': 'SUBS',
            'requestid': '1',
            "SchwabClientCustomerId": CLIENT_CUSTOMER_ID,
            "SchwabClientCorrelId": CLIENT_CORRELATION_ID,
            'parameters': {
                'keys': CLIENT_CORRELATION_ID,
                'fields': '0,1,2,3'
            }
        })

    @no_duplicates
    @patch('schwab.streaming.ws_client.connect', new_callable=AsyncMock)
    async def test_account_activity_unsubs_success(self, ws_connect):
        socket = await self.login_and_get_socket(ws_connect)

        stream_item = self.streaming_entry('ACCT_ACTIVITY', 'SUBS')

        socket.recv.side_effect = [
            json.dumps(self.success_response(1, 'ACCT_ACTIVITY', 'SUBS')),
            json.dumps(stream_item),
            json.dumps(self.success_response(2, 'ACCT_ACTIVITY', 'UNSUBS'))
        ]
        handler = Mock()
        async_handler = AsyncMock()
        self.client.add_account_activity_handler(handler)
        self.client.add_account_activity_handler(async_handler)

        await self.client.account_activity_sub()
        await self.client.handle_message()
        await self.client.account_activity_unsubs()

        self.assert_handler_called_once_with(
                handler, {'service': 'ACCT_ACTIVITY',
                          'command': 'SUBS',
                          'timestamp': REQUEST_TIMESTAMP})
        self.assert_handler_called_once_with(
                async_handler, {'service': 'ACCT_ACTIVITY',
                                'command': 'SUBS',
                                'timestamp': REQUEST_TIMESTAMP})
        send_awaited = [
            call(StringMatchesJson({
                "requests": [{
                    "service": "ACCT_ACTIVITY",
                    "requestid": "1",
                    "command": "SUBS",
                    "SchwabClientCustomerId": CLIENT_CUSTOMER_ID,
                    "SchwabClientCorrelId": CLIENT_CORRELATION_ID,
                    "parameters": {
                        "keys": CLIENT_CORRELATION_ID,
                        "fields": "0,1,2,3"
                    }
                }]
            })),
            call(StringMatchesJson({
                "requests": [{
                    "service": "ACCT_ACTIVITY",
                    "requestid": "2",
                    "command": "UNSUBS",
                    "SchwabClientCustomerId": CLIENT_CUSTOMER_ID,
                    "SchwabClientCorrelId": CLIENT_CORRELATION_ID,
                    "parameters": {
                        "keys": CLIENT_CORRELATION_ID
                    }
                }]
            })),
        ]
        socket.send.assert_has_awaits(send_awaited, any_order=False)

    @no_duplicates
    @patch('schwab.streaming.ws_client.connect', new_callable=AsyncMock)
    async def test_account_activity_subs_failure(self, ws_connect):
        socket = await self.login_and_get_socket(ws_connect)

        response = self.success_response(1, 'ACCT_ACTIVITY', 'SUBS')
        response['response'][0]['content']['code'] = 21
        socket.recv.side_effect = [json.dumps(response)]

        with self.assertRaises(schwab.streaming.UnexpectedResponseCode):
            await self.client.account_activity_sub()

    @no_duplicates
    @patch('schwab.streaming.ws_client.connect', new_callable=AsyncMock)
    async def test_account_activity_unsubs_failure(self, ws_connect):
        socket = await self.login_and_get_socket(ws_connect)

        response = self.success_response(1, 'ACCT_ACTIVITY', 'UNSUBS')
        response['response'][0]['content']['code'] = 21
        socket.recv.side_effect = [json.dumps(response)]

        with self.assertRaises(schwab.streaming.UnexpectedResponseCode):
            await self.client.account_activity_unsubs()

    @no_duplicates
    @patch('schwab.streaming.ws_client.connect', new_callable=AsyncMock)
    async def test_account_activity_handler(self, ws_connect):
        socket = await self.login_and_get_socket(ws_connect)

        stream_item = {
            'data': [
                {
                    'service': 'ACCT_ACTIVITY',
                    'timestamp': 1591754497594,
                    'command': 'SUBS',
                    'content': [
                        {
                            'seq': 1,
                            'key': CLIENT_CORRELATION_ID,
                            '1': '1001',
                            '2': 'OrderEntryRequest',
                            '3': ''
                        }
                    ]
                }
            ]
        }

        socket.recv.side_effect = [
            json.dumps(self.success_response(1, 'ACCT_ACTIVITY', 'SUBS')),
            json.dumps(stream_item)]
        await self.client.account_activity_sub()

        handler = Mock()
        async_handler = AsyncMock()
        self.client.add_account_activity_handler(handler)
        self.client.add_account_activity_handler(async_handler)
        await self.client.handle_message()

        expected_item = {
            'service': 'ACCT_ACTIVITY',
            'timestamp': 1591754497594,
            'command': 'SUBS',
            'content': [
                {
                    'seq': 1,
                    'key': CLIENT_CORRELATION_ID,
                    'FIELD_1': '1001',
                    'FIELD_2': 'OrderEntryRequest',
                    'FIELD_3': ''
                }
            ]
        }

        self.assert_handler_called_once_with(handler, expected_item)
        self.assert_handler_called_once_with(async_handler, expected_item)


    ##########################################################################
    # CHART_EQUITY

    @no_duplicates
    @patch('schwab.streaming.ws_client.connect', new_callable=AsyncMock)
    async def test_chart_equity_subs_and_add_success(self, ws_connect):
        socket = await self.login_and_get_socket(ws_connect)

        socket.recv.side_effect = [json.dumps(self.success_response(
            1, 'CHART_EQUITY', 'SUBS'))]

        await self.client.chart_equity_subs(['GOOG', 'MSFT'])
        socket.recv.assert_awaited_once()
        request = self.request_from_socket_mock(socket)

        self.assertEqual(request, {
            'service': 'CHART_EQUITY',
            'command': 'SUBS',
            'requestid': '1',
            'SchwabClientCustomerId': self.pref_customer_id,
            'SchwabClientCorrelId': self.pref_correl_id,
            'parameters': {
                'keys': 'GOOG,MSFT',
                'fields': '0,1,2,3,4,5,6,7,8'
            }
        })

        socket.reset_mock()

        socket.recv.side_effect = [json.dumps(self.success_response(
            2, 'CHART_EQUITY', 'ADD'))]

        await self.client.chart_equity_add(['INTC'])
        socket.recv.assert_awaited_once()
        request = self.request_from_socket_mock(socket)

        self.assertEqual(request, {
            'service': 'CHART_EQUITY',
            'command': 'ADD',
            'requestid': '2',
            'SchwabClientCustomerId': self.pref_customer_id,
            'SchwabClientCorrelId': self.pref_correl_id,
            'parameters': {
                'keys': 'INTC',
                'fields': '0,1,2,3,4,5,6,7,8'
            }
        })

    @no_duplicates
    @patch('schwab.streaming.ws_client.connect', new_callable=AsyncMock)
    async def test_chart_equity_unsubs_success(self, ws_connect):
        socket = await self.login_and_get_socket(ws_connect)

        stream_item = self.streaming_entry('CHART_EQUITY', 'SUBS')

        socket.recv.side_effect = [
            json.dumps(self.success_response(1, 'CHART_EQUITY', 'SUBS')),
            json.dumps(stream_item),
            json.dumps(self.success_response(2, 'CHART_EQUITY', 'UNSUBS', 'UNSUBS command succeeded'))
        ]
        handler = Mock()
        async_handler = AsyncMock()
        self.client.add_chart_equity_handler(handler)
        self.client.add_chart_equity_handler(async_handler)

        await self.client.chart_equity_subs(['GOOG', 'MSFT'])
        await self.client.handle_message()
        await self.client.chart_equity_unsubs(['GOOG', 'MSFT'])

        self.assert_handler_called_once_with(
                handler, {'service': 'CHART_EQUITY',
                          'command': 'SUBS',
                          'timestamp': REQUEST_TIMESTAMP})
        self.assert_handler_called_once_with(
                async_handler, {'service': 'CHART_EQUITY',
                                'command': 'SUBS',
                                'timestamp': REQUEST_TIMESTAMP})

        send_awaited = [
            call(StringMatchesJson({
                "requests": [{
                    "service": "CHART_EQUITY",
                    "requestid": "1",
                    "command": "SUBS",
                    "SchwabClientCustomerId": CLIENT_CUSTOMER_ID,
                    "SchwabClientCorrelId": CLIENT_CORRELATION_ID,
                    "parameters": {
                        "keys": "GOOG,MSFT",
                        "fields": "0,1,2,3,4,5,6,7,8"
                    }
                }]
            })),
            call(StringMatchesJson(
                {"requests": [{
                    "service": "CHART_EQUITY", 
                    "requestid": "2",
                    "command": "UNSUBS",
                    "SchwabClientCustomerId": CLIENT_CUSTOMER_ID,
                    "SchwabClientCorrelId": CLIENT_CORRELATION_ID,
                    "parameters": {
                        "keys": "GOOG,MSFT"
                    }
                }]
            })),
        ]
        socket.send.assert_has_awaits(send_awaited, any_order=False)


    @no_duplicates
    @patch('schwab.streaming.ws_client.connect', new_callable=AsyncMock)
    async def test_chart_equity_subs_failure(self, ws_connect):
        socket = await self.login_and_get_socket(ws_connect)

        response = self.success_response(1, 'CHART_EQUITY', 'SUBS')
        response['response'][0]['content']['code'] = 21
        socket.recv.side_effect = [json.dumps(response)]

        with self.assertRaises(schwab.streaming.UnexpectedResponseCode):
            await self.client.chart_equity_subs(['GOOG', 'MSFT'])

    @no_duplicates
    @patch('schwab.streaming.ws_client.connect', new_callable=AsyncMock)
    async def test_chart_equity_unsubs_failure(self, ws_connect):
        socket = await self.login_and_get_socket(ws_connect)

        response = self.success_response(1, 'CHART_EQUITY', 'UNSUBS')
        response['response'][0]['content']['code'] = 21
        socket.recv.side_effect = [json.dumps(response)]

        with self.assertRaises(schwab.streaming.UnexpectedResponseCode):
            await self.client.chart_equity_unsubs(['GOOG', 'MSFT'])

    @no_duplicates
    @patch('schwab.streaming.ws_client.connect', new_callable=AsyncMock)
    async def test_chart_equity_add_failure(self, ws_connect):
        socket = await self.login_and_get_socket(ws_connect)

        response_subs = self.success_response(1, 'CHART_EQUITY', 'SUBS')

        response_add = self.success_response(2, 'CHART_EQUITY', 'ADD')
        response_add['response'][0]['content']['code'] = 21
        socket.recv.side_effect = [
            json.dumps(response_subs),
            json.dumps(response_add)]

        await self.client.chart_equity_subs(['GOOG', 'MSFT'])

        with self.assertRaises(schwab.streaming.UnexpectedResponseCode):
            await self.client.chart_equity_add(['INTC'])

    @no_duplicates
    @patch('schwab.streaming.ws_client.connect', new_callable=AsyncMock)
    async def test_chart_equity_handler(self, ws_connect):
        socket = await self.login_and_get_socket(ws_connect)

        stream_item = {
            'data': [{
                "service": "CHART_EQUITY",
                "timestamp": 1715908546054,
                "command": "SUBS",
                "content": [
                    {
                        "seq": 0,
                        "key": "MSFT",
                        "1": 779,
                        "2": 421.65,
                        "3": 421.79,
                        "4": 421.65,
                        "5": 421.755,
                        "6": 26.0,
                        "7": 1715903940000,
                        "8": 19859
                    },
                    {
                        "seq": 0,
                        "key": "GOOG",
                        "1": 779,
                        "2": 175.16,
                        "3": 175.21,
                        "4": 175.06,
                        "5": 175.06,
                        "6": 145.0,
                        "7": 1715903940000,
                        "8": 19859
                    }
                ]
            }]
        }

        socket.recv.side_effect = [
            json.dumps(self.success_response(1, 'CHART_EQUITY', 'SUBS')),
            json.dumps(stream_item)]
        await self.client.chart_equity_subs(['GOOG', 'MSFT'])

        handler = Mock()
        async_handler = AsyncMock()
        self.client.add_chart_equity_handler(handler)
        self.client.add_chart_equity_handler(async_handler)
        await self.client.handle_message()

        expected_item = {
            "service": "CHART_EQUITY",
            "timestamp": 1715908546054,
            "command": "SUBS",
            "content": [
                {
                    "seq": 0,
                    "key": "MSFT",
                    "SEQUENCE": 779,
                    "OPEN_PRICE": 421.65,
                    "HIGH_PRICE": 421.79,
                    "LOW_PRICE": 421.65,
                    "CLOSE_PRICE": 421.755,
                    "VOLUME": 26.0,
                    "CHART_TIME_MILLIS": 1715903940000,
                    "CHART_DAY": 19859
                },
                {
                    "seq": 0,
                    "key": "GOOG",
                    "SEQUENCE": 779,
                    "OPEN_PRICE": 175.16,
                    "HIGH_PRICE": 175.21,
                    "LOW_PRICE": 175.06,
                    "CLOSE_PRICE": 175.06,
                    "VOLUME": 145.0,
                    "CHART_TIME_MILLIS": 1715903940000,
                    "CHART_DAY": 19859
                }
            ]
        }

        self.assert_handler_called_once_with(handler, expected_item)
        self.assert_handler_called_once_with(async_handler, expected_item)

    ##########################################################################
    # CHART_FUTURES

    @no_duplicates
    @patch('schwab.streaming.ws_client.connect', new_callable=AsyncMock)
    async def test_chart_futures_subs_and_add_success(self, ws_connect):
        socket = await self.login_and_get_socket(ws_connect)

        socket.recv.side_effect = [json.dumps(self.success_response(
            1, 'CHART_FUTURES', 'SUBS'))]

        await self.client.chart_futures_subs(['/ES', '/CL'])
        socket.recv.assert_awaited_once()
        request = self.request_from_socket_mock(socket)

        self.assertEqual(request, {
            'service': 'CHART_FUTURES',
            'command': 'SUBS',
            'requestid': '1',
            "SchwabClientCustomerId": CLIENT_CUSTOMER_ID,
            "SchwabClientCorrelId": CLIENT_CORRELATION_ID,
            'parameters': {
                'keys': '/ES,/CL',
                'fields': '0,1,2,3,4,5,6'
            }
        })

        socket.reset_mock()

        socket.recv.side_effect = [json.dumps(self.success_response(
            2, 'CHART_FUTURES', 'ADD'))]

        await self.client.chart_futures_add(['/ZC'])
        socket.recv.assert_awaited_once()
        request = self.request_from_socket_mock(socket)

        self.assertEqual(request, {
            'service': 'CHART_FUTURES',
            'command': 'ADD',
            'requestid': '2',
            "SchwabClientCustomerId": CLIENT_CUSTOMER_ID,
            "SchwabClientCorrelId": CLIENT_CORRELATION_ID,
            'parameters': {
                'keys': '/ZC',
                'fields': '0,1,2,3,4,5,6'
            }
        })

    @no_duplicates
    @patch('schwab.streaming.ws_client.connect', new_callable=AsyncMock)
    async def test_chart_futures_unsubs_success(self, ws_connect):
        socket = await self.login_and_get_socket(ws_connect)

        stream_item = self.streaming_entry('CHART_FUTURES', 'SUBS')

        socket.recv.side_effect = [
            json.dumps(self.success_response(1, 'CHART_FUTURES', 'SUBS')),
            json.dumps(stream_item),
            json.dumps(self.success_response(2, 'CHART_FUTURES', 'UNSUBS', 'UNSUBS command succeeded'))
        ]
        handler = Mock()
        async_handler = AsyncMock()
        self.client.add_chart_futures_handler(handler)
        self.client.add_chart_futures_handler(async_handler)

        await self.client.chart_futures_subs(['/ES', '/CL'])
        await self.client.handle_message()
        await self.client.chart_futures_unsubs(['/ES', '/CL'])

        self.assert_handler_called_once_with(handler, {'service': 'CHART_FUTURES', 'command': 'SUBS',
                                                       'timestamp': REQUEST_TIMESTAMP})
        self.assert_handler_called_once_with(async_handler, {'service': 'CHART_FUTURES', 'command': 'SUBS',
                                                             'timestamp': REQUEST_TIMESTAMP})
        send_awaited = [
            call(StringMatchesJson({
                "requests": [{
                    "service": "CHART_FUTURES",
                    "requestid": "1",
                    "command": "SUBS",
                    'SchwabClientCustomerId': self.pref_customer_id,
                    'SchwabClientCorrelId': self.pref_correl_id,
                    "parameters": {
                        "keys": "/ES,/CL",
                        "fields": "0,1,2,3,4,5,6"
                    }
                }]
            })),
            call(StringMatchesJson({
                "requests": [{
                    "service": "CHART_FUTURES", 
                    "requestid": "2",
                    "command": "UNSUBS",
                    'SchwabClientCustomerId': self.pref_customer_id,
                    'SchwabClientCorrelId': self.pref_correl_id,
                    "parameters": {
                        "keys": 
                        "/ES,/CL"
                    }
                }]
            })),
        ]
        socket.send.assert_has_awaits(send_awaited, any_order=False)

    @no_duplicates
    @patch('schwab.streaming.ws_client.connect', new_callable=AsyncMock)
    async def test_chart_futures_subs_failure(self, ws_connect):
        socket = await self.login_and_get_socket(ws_connect)

        response = self.success_response(1, 'CHART_FUTURES', 'SUBS')
        response['response'][0]['content']['code'] = 21
        socket.recv.side_effect = [json.dumps(response)]

        with self.assertRaises(schwab.streaming.UnexpectedResponseCode):
            await self.client.chart_futures_subs(['/ES', '/CL'])

    @no_duplicates
    @patch('schwab.streaming.ws_client.connect', new_callable=AsyncMock)
    async def test_chart_futures_unsubs_failure(self, ws_connect):
        socket = await self.login_and_get_socket(ws_connect)

        response = self.success_response(1, 'CHART_FUTURES', 'UNSUBS')
        response['response'][0]['content']['code'] = 21
        socket.recv.side_effect = [json.dumps(response)]

        with self.assertRaises(schwab.streaming.UnexpectedResponseCode):
            await self.client.chart_futures_unsubs(['/ES', '/CL'])

    @no_duplicates
    @patch('schwab.streaming.ws_client.connect', new_callable=AsyncMock)
    async def test_chart_futures_add_failure(self, ws_connect):
        socket = await self.login_and_get_socket(ws_connect)

        response_subs = self.success_response(1, 'CHART_FUTURES', 'SUBS')

        response_add = self.success_response(2, 'CHART_FUTURES', 'ADD')
        response_add['response'][0]['content']['code'] = 21
        socket.recv.side_effect = [
            json.dumps(response_subs),
            json.dumps(response_add)]

        await self.client.chart_futures_subs(['/ES', '/CL'])

        with self.assertRaises(schwab.streaming.UnexpectedResponseCode):
            await self.client.chart_futures_add(['/ZC'])

    @no_duplicates
    @patch('schwab.streaming.ws_client.connect', new_callable=AsyncMock)
    async def test_chart_futures_handler(self, ws_connect):
        socket = await self.login_and_get_socket(ws_connect)

        stream_item = {
            'data': [
                {
                    'service': 'CHART_FUTURES',
                    'timestamp': 1590597913941,
                    'command': 'SUBS',
                    'content': [
                        {
                            'seq': 0,
                            'key': '/ES',
                            '1': 1590597840000,
                            '2': 2996.25,
                            '3': 2997.25,
                            '4': 2995.25,
                            '5': 2997.25,
                            '6': 1501.0
                        },
                        {
                            'seq': 0,
                            'key': '/CL',
                            '1': 1590597840000,
                            '2': 33.34,
                            '3': 33.35,
                            '4': 33.32,
                            '5': 33.35,
                            '6': 186.0
                        }
                    ]
                }
            ]
        }

        socket.recv.side_effect = [
            json.dumps(self.success_response(1, 'CHART_FUTURES', 'SUBS')),
            json.dumps(stream_item)]
        await self.client.chart_futures_subs(['/ES', '/CL'])

        handler = Mock()
        async_handler = AsyncMock()
        self.client.add_chart_futures_handler(handler)
        self.client.add_chart_futures_handler(async_handler)
        await self.client.handle_message()

        expected_item = {
            'service': 'CHART_FUTURES',
            'timestamp': 1590597913941,
            'command': 'SUBS',
            'content': [{
                'seq': 0,
                'key': '/ES',
                'FIELD_1': 1590597840000,
                'FIELD_2': 2996.25,
                'FIELD_3': 2997.25,
                'FIELD_4': 2995.25,
                'FIELD_5': 2997.25,
                'FIELD_6': 1501.0
            }, {
                'seq': 0,
                'key': '/CL',
                'FIELD_1': 1590597840000,
                'FIELD_2': 33.34,
                'FIELD_3': 33.35,
                'FIELD_4': 33.32,
                'FIELD_5': 33.35,
                'FIELD_6': 186.0
            }]
        }

        self.assert_handler_called_once_with(handler, expected_item)
        self.assert_handler_called_once_with(async_handler, expected_item)

    ##########################################################################
    # LEVELONE_EQUITIES

    @no_duplicates
    @patch('schwab.streaming.ws_client.connect', new_callable=AsyncMock)
    async def test_level_one_equity_subs_success_all_fields(self, ws_connect):
        socket = await self.login_and_get_socket(ws_connect)

        socket.recv.side_effect = [json.dumps(self.success_response(
            1, 'LEVELONE_EQUITIES', 'SUBS'))]

        await self.client.level_one_equity_subs(['GOOG', 'MSFT'])
        socket.recv.assert_awaited_once()
        request = self.request_from_socket_mock(socket)

        self.assertEqual(request, {
            'service': 'LEVELONE_EQUITIES',
            'command': 'SUBS',
            'requestid': '1',
            'SchwabClientCustomerId': self.pref_customer_id,
            'SchwabClientCorrelId': self.pref_correl_id,
            'parameters': {
                'keys': 'GOOG,MSFT',
                'fields': ('0,1,2,3,4,5,6,7,8,9,10,11,12,13,14,15,16,17,18,19,' +
                           '20,21,22,23,24,25,26,27,28,29,30,31,32,33,34,35,' +
                           '36,37,38,39,40,41,42,43,44,45,46,47,48,49,50,51')
            }
        })

    @no_duplicates
    @patch('schwab.streaming.ws_client.connect', new_callable=AsyncMock)
    async def test_level_one_equity_unsubs_success(self, ws_connect):
        socket = await self.login_and_get_socket(ws_connect)

        stream_item = self.streaming_entry('LEVELONE_EQUITIES', 'SUBS')

        socket.recv.side_effect = [
            json.dumps(self.success_response(1, 'LEVELONE_EQUITIES', 'SUBS')),
            json.dumps(stream_item),
            json.dumps(self.success_response(2, 'LEVELONE_EQUITIES', 'UNSUBS'))
        ]
        handler = Mock()
        async_handler = AsyncMock()
        self.client.add_level_one_equity_handler(async_handler)
        self.client.add_level_one_equity_handler(handler)

        await self.client.level_one_equity_subs(['GOOG', 'MSFT'])
        await self.client.handle_message()
        await self.client.level_one_equity_unsubs(['GOOG', 'MSFT'])

        self.assert_handler_called_once_with(handler,
                                             {'service': 'LEVELONE_EQUITIES', 'command': 'SUBS', 'timestamp': REQUEST_TIMESTAMP})
        self.assert_handler_called_once_with(async_handler,
                                             {'service': 'LEVELONE_EQUITIES', 'command': 'SUBS', 'timestamp': REQUEST_TIMESTAMP})
        send_awaited = [
            call(StringMatchesJson({
                "requests": [{
                    "service": "LEVELONE_EQUITIES",
                    "requestid": "1",
                    "command": "SUBS", 
                    "SchwabClientCustomerId": CLIENT_CUSTOMER_ID,
                    "SchwabClientCorrelId": CLIENT_CORRELATION_ID,
                    "parameters": {
                        "keys": "GOOG,MSFT", 
                        "fields": 
                        "0,1,2,3,4,5,6,7,8,9,10,11,12,13,14,15,16,17,18,19,"+
                        "20,21,22,23,24,25,26,27,28,29,30,31,32,33,34,35,36,"+
                        "37,38,39,40,41,42,43,44,45,46,47,48,49,50,51"
                    }
                }]
            })),
            call(StringMatchesJson({
                "requests": [{
                    "service": "LEVELONE_EQUITIES",
                    "requestid": "2",
                    "command": "UNSUBS",
                    "SchwabClientCustomerId": CLIENT_CUSTOMER_ID,
                    "SchwabClientCorrelId": CLIENT_CORRELATION_ID,
                    "parameters": {
                        "keys": "GOOG,MSFT"
                    }
                }]
            })),
        ]

        socket.send.assert_has_awaits(send_awaited, any_order=False)


    @no_duplicates
    @patch('schwab.streaming.ws_client.connect', new_callable=AsyncMock)
    async def test_level_one_equity_subs_success_some_fields(self, ws_connect):
        socket = await self.login_and_get_socket(ws_connect)

        socket.recv.side_effect = [json.dumps(self.success_response(
            1, 'LEVELONE_EQUITIES', 'SUBS'))]

        await self.client.level_one_equity_subs(['GOOG', 'MSFT'], fields=[
            StreamClient.LevelOneEquityFields.SYMBOL,
            StreamClient.LevelOneEquityFields.BID_PRICE,
            StreamClient.LevelOneEquityFields.ASK_PRICE,
            StreamClient.LevelOneEquityFields.LOW_PRICE,
        ])
        socket.recv.assert_awaited_once()
        request = self.request_from_socket_mock(socket)

        self.assertEqual(request, {
            'service': 'LEVELONE_EQUITIES',
            'command': 'SUBS',
            'requestid': '1',
            "SchwabClientCustomerId": CLIENT_CUSTOMER_ID,
            "SchwabClientCorrelId": CLIENT_CORRELATION_ID,
            'parameters': {
                'keys': 'GOOG,MSFT',
                'fields': '0,1,2,11'
            }
        })

    @no_duplicates
    @patch('schwab.streaming.ws_client.connect', new_callable=AsyncMock)
    async def test_level_one_equity_subs_success_some_fields_no_symbol(
            self, ws_connect):
        socket = await self.login_and_get_socket(ws_connect)

        socket.recv.side_effect = [json.dumps(self.success_response(
            1, 'LEVELONE_EQUITIES', 'SUBS'))]

        await self.client.level_one_equity_subs(['GOOG', 'MSFT'], fields=[
            StreamClient.LevelOneEquityFields.BID_PRICE,
            StreamClient.LevelOneEquityFields.ASK_PRICE,
            StreamClient.LevelOneEquityFields.LOW_PRICE,
        ])
        socket.recv.assert_awaited_once()
        request = self.request_from_socket_mock(socket)

        self.assertEqual(request, {
            'service': 'LEVELONE_EQUITIES',
            'command': 'SUBS',
            'requestid': '1',
            "SchwabClientCustomerId": CLIENT_CUSTOMER_ID,
            "SchwabClientCorrelId": CLIENT_CORRELATION_ID,
            'parameters': {
                'keys': 'GOOG,MSFT',
                'fields': '0,1,2,11'
            }
        })

    @no_duplicates
    @patch('schwab.streaming.ws_client.connect', new_callable=AsyncMock)
    async def test_level_one_equity_subs_failure(self, ws_connect):
        socket = await self.login_and_get_socket(ws_connect)

        response = self.success_response(1, 'LEVELONE_EQUITIES', 'SUBS')
        response['response'][0]['content']['code'] = 21
        socket.recv.side_effect = [json.dumps(response)]

        with self.assertRaises(schwab.streaming.UnexpectedResponseCode):
            await self.client.level_one_equity_subs(['GOOG', 'MSFT'])

    @no_duplicates
    @patch('schwab.streaming.ws_client.connect', new_callable=AsyncMock)
    async def test_level_one_equity_unsubs_failure(self, ws_connect):
        socket = await self.login_and_get_socket(ws_connect)

        response = self.success_response(1, 'LEVELONE_EQUITIES', 'UNSUBS')
        response['response'][0]['content']['code'] = 21
        socket.recv.side_effect = [json.dumps(response)]

        with self.assertRaises(schwab.streaming.UnexpectedResponseCode):
            await self.client.level_one_equity_unsubs(['GOOG', 'MSFT'])

    @no_duplicates
    @patch('schwab.streaming.ws_client.connect', new_callable=AsyncMock)
    async def test_level_one_quote_handler(self, ws_connect):
        socket = await self.login_and_get_socket(ws_connect)

        stream_item = {
            'data': [{
                "service": "LEVELONE_EQUITIES",
                "timestamp": 1715777956144,
                "command": "SUBS",
                "content": [
                    {
                        "key": "MSFT",
                        "delayed": True,
                        "assetMainType": "EQUITY",
                        "assetSubType": "COE",
                        "cusip": "594918104",
                        "1": 417.01,
                        "2": 417.08,
                        "3": 417.09,
                        "4": 1,
                        "5": 0,
                        "6": "Z",
                        "7": "Z",
                        "8": 162750,
                        "9": 10,
                        "10": 0,
                        "11": 0,
                        "12": 415.81,
                        "13": "Q",
                        "14": False,
                        "15": "Microsoft Corp",
                        "16": "Q",
                        "17": 0,
                        "18": 1.28,
                        "19": 430.82,
                        "20": 307.59,
                        "21": 36.09605,
                        "22": 3,
                        "23": 0.72513,
                        "24": 0,
                        "25": "NASDAQ",
                        "26": "2024-05-15 00:00:00.0",
                        "27": False,
                        "28": False,
                        "29": 415.81,
                        "30": 408,
                        "31": 0,
                        "32": "Unknown",
                        "33": 417.01,
                        "34": 1715777955574,
                        "35": 1715777953982,
                        "36": 1715716801392,
                        "37": 1715777955574,
                        "38": 1715777955574,
                        "39": "BATS",
                        "40": "BATS",
                        "41": "XBOS",
                        "42": 0.3078329,
                        "43": 0,
                        "44": 1.2,
                        "45": 0.28859335,
                        "46": 95711793,
                        "47": 0,
                        "48": 0,
                        "49": 1,
                        "50": 1.28,
                        "51": 0.3078329
                    },
                    {
                        "key": "GOOG",
                        "delayed": True,
                        "assetMainType": "EQUITY",
                        "assetSubType": "COE",
                        "cusip": "02079K107",
                        "1": 172.75,
                        "2": 172.77,
                        "3": 172.7786,
                        "4": 0,
                        "5": 1,
                        "6": "Q",
                        "7": "Z",
                        "8": 167934,
                        "9": 15,
                        "10": 0,
                        "11": 0,
                        "12": 171.93,
                        "13": "Q",
                        "14": False,
                        "15": "Alphabet Inc. C",
                        "16": "L",
                        "17": 0,
                        "18": 0.8486,
                        "19": 176.42,
                        "20": 115.83,
                        "21": 26.38849,
                        "22": 0.8,
                        "23": 0.46811,
                        "24": 0,
                        "25": "NASDAQ",
                        "26": "2024-06-10 00:00:00.0",
                        "27": False,
                        "28": False,
                        "29": 171.93,
                        "30": 210,
                        "31": 0,
                        "32": "Unknown",
                        "33": 172.75,
                        "34": 1715777954819,
                        "35": 1715777950470,
                        "36": 1715716801295,
                        "37": 1715777954819,
                        "38": 1715777954819,
                        "39": "XBOS",
                        "40": "BATS",
                        "41": "TRFC",
                        "42": 0.49357297,
                        "43": 0,
                        "44": 0.82,
                        "45": 0.47693829,
                        "46": 67295343,
                        "47": 0,
                        "48": 0,
                        "49": 1,
                        "50": 0.8486,
                        "51": 0.49357297
                    }
                ]
            }]
        }

        socket.recv.side_effect = [
            json.dumps(self.success_response(1, 'LEVELONE_EQUITIES', 'SUBS')),
            json.dumps(stream_item)]
        await self.client.level_one_equity_subs(['GOOG', 'MSFT'])

        handler = Mock()
        async_handler = AsyncMock()
        self.client.add_level_one_equity_handler(handler)
        self.client.add_level_one_equity_handler(async_handler)
        await self.client.handle_message()

        expected_item = {
            "service": "LEVELONE_EQUITIES",
            "timestamp": 1715777956144,
            "command": "SUBS",
            "content": [
                {
                    "key": "MSFT",
                    "delayed": True,
                    "assetMainType": "EQUITY",
                    "assetSubType": "COE",
                    "cusip": "594918104",
                    "BID_PRICE": 417.01,
                    "ASK_PRICE": 417.08,
                    "LAST_PRICE": 417.09,
                    "BID_SIZE": 1,
                    "ASK_SIZE": 0,
                    "ASK_ID": "Z",
                    "BID_ID": "Z",
                    "TOTAL_VOLUME": 162750,
                    "LAST_SIZE": 10,
                    "HIGH_PRICE": 0,
                    "LOW_PRICE": 0,
                    "CLOSE_PRICE": 415.81,
                    "EXCHANGE_ID": "Q",
                    "MARGINABLE": False,
                    "DESCRIPTION": "Microsoft Corp",
                    "LAST_ID": "Q",
                    "OPEN_PRICE": 0,
                    "NET_CHANGE": 1.28,
                    "HIGH_PRICE_52_WEEK": 430.82,
                    "LOW_PRICE_52_WEEK": 307.59,
                    "PE_RATIO": 36.09605,
                    "DIVIDEND_AMOUNT": 3,
                    "DIVIDEND_YIELD": 0.72513,
                    "NAV": 0,
                    "EXCHANGE_NAME": "NASDAQ",
                    "DIVIDEND_DATE": "2024-05-15 00:00:00.0",
                    "REGULAR_MARKET_QUOTE": False,
                    "REGULAR_MARKET_TRADE": False,
                    "REGULAR_MARKET_LAST_PRICE": 415.81,
                    "REGULAR_MARKET_LAST_SIZE": 408,
                    "REGULAR_MARKET_NET_CHANGE": 0,
                    "SECURITY_STATUS": "Unknown",
                    "MARK": 417.01,
                    "QUOTE_TIME_MILLIS": 1715777955574,
                    "TRADE_TIME_MILLIS": 1715777953982,
                    "REGULAR_MARKET_TRADE_MILLIS": 1715716801392,
                    "BID_TIME_MILLIS": 1715777955574,
                    "ASK_TIME_MILLIS": 1715777955574,
                    "ASK_MIC_ID": "BATS",
                    "BID_MIC_ID": "BATS",
                    "LAST_MIC_ID": "XBOS",
                    "NET_CHANGE_PERCENT": 0.3078329,
                    "REGULAR_MARKET_CHANGE_PERCENT": 0,
                    "MARK_CHANGE": 1.2,
                    "MARK_CHANGE_PERCENT": 0.28859335,
                    "HTB_QUALITY": 95711793,
                    "HTB_RATE": 0,
                    "HARD_TO_BORROW": 0,
                    "IS_SHORTABLE": 1,
                    "POST_MARKET_NET_CHANGE": 1.28,
                    "POST_MARKET_NET_CHANGE_PERCENT": 0.3078329
                },
                {
                    "key": "GOOG",
                    "delayed": True,
                    "assetMainType": "EQUITY",
                    "assetSubType": "COE",
                    "cusip": "02079K107",
                    "BID_PRICE": 172.75,
                    "ASK_PRICE": 172.77,
                    "LAST_PRICE": 172.7786,
                    "BID_SIZE": 0,
                    "ASK_SIZE": 1,
                    "ASK_ID": "Q",
                    "BID_ID": "Z",
                    "TOTAL_VOLUME": 167934,
                    "LAST_SIZE": 15,
                    "HIGH_PRICE": 0,
                    "LOW_PRICE": 0,
                    "CLOSE_PRICE": 171.93,
                    "EXCHANGE_ID": "Q",
                    "MARGINABLE": False,
                    "DESCRIPTION": "Alphabet Inc. C",
                    "LAST_ID": "L",
                    "OPEN_PRICE": 0,
                    "NET_CHANGE": 0.8486,
                    "HIGH_PRICE_52_WEEK": 176.42,
                    "LOW_PRICE_52_WEEK": 115.83,
                    "PE_RATIO": 26.38849,
                    "DIVIDEND_AMOUNT": 0.8,
                    "DIVIDEND_YIELD": 0.46811,
                    "NAV": 0,
                    "EXCHANGE_NAME": "NASDAQ",
                    "DIVIDEND_DATE": "2024-06-10 00:00:00.0",
                    "REGULAR_MARKET_QUOTE": False,
                    "REGULAR_MARKET_TRADE": False,
                    "REGULAR_MARKET_LAST_PRICE": 171.93,
                    "REGULAR_MARKET_LAST_SIZE": 210,
                    "REGULAR_MARKET_NET_CHANGE": 0,
                    "SECURITY_STATUS": "Unknown",
                    "MARK": 172.75,
                    "QUOTE_TIME_MILLIS": 1715777954819,
                    "TRADE_TIME_MILLIS": 1715777950470,
                    "REGULAR_MARKET_TRADE_MILLIS": 1715716801295,
                    "BID_TIME_MILLIS": 1715777954819,
                    "ASK_TIME_MILLIS": 1715777954819,
                    "ASK_MIC_ID": "XBOS",
                    "BID_MIC_ID": "BATS",
                    "LAST_MIC_ID": "TRFC",
                    "NET_CHANGE_PERCENT": 0.49357297,
                    "REGULAR_MARKET_CHANGE_PERCENT": 0,
                    "MARK_CHANGE": 0.82,
                    "MARK_CHANGE_PERCENT": 0.47693829,
                    "HTB_QUALITY": 67295343,
                    "HTB_RATE": 0,
                    "HARD_TO_BORROW": 0,
                    "IS_SHORTABLE": 1,
                    "POST_MARKET_NET_CHANGE": 0.8486,
                    "POST_MARKET_NET_CHANGE_PERCENT": 0.49357297
                }
            ]
        }

        self.assert_handler_called_once_with(handler, expected_item)
        self.assert_handler_called_once_with(async_handler, expected_item)

    ##########################################################################
    # LEVELONE_OPTIONS

    @no_duplicates
    @patch('schwab.streaming.ws_client.connect', new_callable=AsyncMock)
    async def test_level_one_option_subs_success_all_fields(self, ws_connect):
        socket = await self.login_and_get_socket(ws_connect)

        socket.recv.side_effect = [json.dumps(self.success_response(
            1, 'LEVELONE_OPTIONS', 'SUBS'))]

        await self.client.level_one_option_subs(
            ['GOOG_052920C620', 'MSFT_052920C145'])
        socket.recv.assert_awaited_once()
        request = self.request_from_socket_mock(socket)

        self.assertEqual(request, {
            'service': 'LEVELONE_OPTIONS',
            'command': 'SUBS',
            'requestid': '1',
            "SchwabClientCustomerId": CLIENT_CUSTOMER_ID,
            "SchwabClientCorrelId": CLIENT_CORRELATION_ID,
            'parameters': {
                'keys': 'GOOG_052920C620,MSFT_052920C145',
                'fields': ('0,1,2,3,4,5,6,7,8,9,10,11,12,13,14,15,16,17,18,19,' +
                           '20,21,22,23,24,25,26,27,28,29,30,31,32,33,34,35,' +
                           '36,37,38,39,40,41,42,43,44,45,46,47,48,49,50,51,' +
                           '52,53,54,55')
            }
        })

    @no_duplicates
    @patch('schwab.streaming.ws_client.connect', new_callable=AsyncMock)
    async def test_level_one_option_unsubs_success_all_fields(self, ws_connect):
        socket = await self.login_and_get_socket(ws_connect)

        stream_item = self.streaming_entry('LEVELONE_OPTIONS', 'SUBS')

        socket.recv.side_effect = [
            json.dumps(self.success_response(1, 'LEVELONE_OPTIONS', 'SUBS')),
            json.dumps(stream_item),
            json.dumps(self.success_response(2, 'LEVELONE_OPTIONS', 'UNSUBS'))
        ]
        handler = Mock()
        async_handler = AsyncMock()
        self.client.add_level_one_option_handler(handler)
        self.client.add_level_one_option_handler(async_handler)

        await self.client.level_one_option_subs(
            ['GOOG_052920C620', 'MSFT_052920C145'])
        await self.client.handle_message()
        await self.client.level_one_option_unsubs(
            ['GOOG_052920C620', 'MSFT_052920C145'])

        self.assert_handler_called_once_with(
                handler, {'service': 'LEVELONE_OPTIONS',
                          'command': 'SUBS',
                          'timestamp': REQUEST_TIMESTAMP})
        self.assert_handler_called_once_with(
                async_handler, {'service': 'LEVELONE_OPTIONS',
                                'command': 'SUBS',
                                'timestamp': REQUEST_TIMESTAMP})

        send_awaited = [
            call(StringMatchesJson({
                "requests": [{
                    "service": "LEVELONE_OPTIONS",
                    "requestid": "1",
                    "command": "SUBS", 
                    "SchwabClientCustomerId": CLIENT_CUSTOMER_ID,
                    "SchwabClientCorrelId": CLIENT_CORRELATION_ID,
                    "parameters": {
                        "keys": "GOOG_052920C620,MSFT_052920C145", 
                        "fields": "0,1,2,3,4,5,6,7,8,9,10,11,12,13,14,15,16,"+
                        "17,18,19,20,21,22,23,24,25,26,27,28,29,30,31,32,33,"+
                        "34,35,36,37,38,39,40,41,42,43,44,45,46,47,48,49,50,"+
                        "51,52,53,54,55"
                    }
                }]
            })),
            call(StringMatchesJson({
                "requests": [{
                    "service": "LEVELONE_OPTIONS",
                    "requestid": "2",
                    "command": "UNSUBS",
                    "SchwabClientCustomerId": CLIENT_CUSTOMER_ID,
                    "SchwabClientCorrelId": CLIENT_CORRELATION_ID,
                    "parameters": {
                        "keys": "GOOG_052920C620,MSFT_052920C145"
                    }
                }]
            })),
        ]

        socket.send.assert_has_awaits(send_awaited, any_order=False)

    @no_duplicates
    @patch('schwab.streaming.ws_client.connect', new_callable=AsyncMock)
    async def test_level_one_option_subs_success_some_fields(self, ws_connect):
        socket = await self.login_and_get_socket(ws_connect)

        socket.recv.side_effect = [json.dumps(self.success_response(
            1, 'LEVELONE_OPTIONS', 'SUBS'))]

        await self.client.level_one_option_subs(
            ['GOOG_052920C620', 'MSFT_052920C145'], fields=[
                StreamClient.LevelOneOptionFields.SYMBOL,
                StreamClient.LevelOneOptionFields.BID_PRICE,
                StreamClient.LevelOneOptionFields.ASK_PRICE,
                StreamClient.LevelOneOptionFields.VOLATILITY,
            ])
        socket.recv.assert_awaited_once()
        request = self.request_from_socket_mock(socket)

        self.assertEqual(request, {
            'service': 'LEVELONE_OPTIONS',
            'command': 'SUBS',
            'requestid': '1',
            "SchwabClientCustomerId": CLIENT_CUSTOMER_ID,
            "SchwabClientCorrelId": CLIENT_CORRELATION_ID,
            'parameters': {
                'keys': 'GOOG_052920C620,MSFT_052920C145',
                'fields': '0,2,3,10'
            }
        })

    @no_duplicates
    @patch('schwab.streaming.ws_client.connect', new_callable=AsyncMock)
    async def test_level_one_option_subs_success_some_fields_no_symbol(
            self, ws_connect):
        socket = await self.login_and_get_socket(ws_connect)

        socket.recv.side_effect = [json.dumps(self.success_response(
            1, 'LEVELONE_OPTIONS', 'SUBS'))]

        await self.client.level_one_option_subs(
            ['GOOG_052920C620', 'MSFT_052920C145'], fields=[
                StreamClient.LevelOneOptionFields.BID_PRICE,
                StreamClient.LevelOneOptionFields.ASK_PRICE,
                StreamClient.LevelOneOptionFields.VOLATILITY,
            ])
        socket.recv.assert_awaited_once()
        request = self.request_from_socket_mock(socket)

        self.assertEqual(request, {
            'service': 'LEVELONE_OPTIONS',
            'command': 'SUBS',
            'requestid': '1',
            "SchwabClientCustomerId": CLIENT_CUSTOMER_ID,
            "SchwabClientCorrelId": CLIENT_CORRELATION_ID,
            'parameters': {
                'keys': 'GOOG_052920C620,MSFT_052920C145',
                'fields': '0,2,3,10'
            }
        })

    @no_duplicates
    @patch('schwab.streaming.ws_client.connect', new_callable=AsyncMock)
    async def test_level_one_option_subs_failure(self, ws_connect):
        socket = await self.login_and_get_socket(ws_connect)

        response = self.success_response(1, 'LEVELONE_OPTIONS', 'SUBS')
        response['response'][0]['content']['code'] = 21
        socket.recv.side_effect = [json.dumps(response)]

        with self.assertRaises(schwab.streaming.UnexpectedResponseCode):
            await self.client.level_one_option_subs(
                ['GOOG_052920C620', 'MSFT_052920C145'])

    @no_duplicates
    @patch('schwab.streaming.ws_client.connect', new_callable=AsyncMock)
    async def test_level_one_option_unsubs_failure(self, ws_connect):
        socket = await self.login_and_get_socket(ws_connect)

        response = self.success_response(1, 'LEVELONE_OPTIONS', 'UNSUBS')
        response['response'][0]['content']['code'] = 21
        socket.recv.side_effect = [json.dumps(response)]

        with self.assertRaises(schwab.streaming.UnexpectedResponseCode):
            await self.client.level_one_option_unsubs(
                ['GOOG_052920C620', 'MSFT_052920C145'])

    @no_duplicates
    @patch('schwab.streaming.ws_client.connect', new_callable=AsyncMock)
    async def test_level_one_option_handler(self, ws_connect):
        socket = await self.login_and_get_socket(ws_connect)

        stream_item = {
            'data': [{
                "service": "LEVELONE_OPTIONS",
                "timestamp": 1715787814441,
                "command": "SUBS",
                "content": [
                    {
                        "key": "GOOG  240517C00070000",
                        "delayed": True,
                        "assetMainType": "OPTION",
                        "cusip": "",
                        "1": "GOOG 05/17/2024 70.00 C",
                        "2": 102.15,
                        "3": 103.75,
                        "4": 103.07,
                        "5": 0,
                        "6": 0,
                        "7": 101.9504,
                        "8": 0,
                        "9": 5,
                        "10": 354.99208367,
                        "11": 102.9299,
                        "12": 2024,
                        "13": 100,
                        "14": 2,
                        "15": 0,
                        "16": 20,
                        "17": 20,
                        "18": 1,
                        "19": 1.1196,
                        "20": 70,
                        "21": "C",
                        "22": "GOOG",
                        "23": 5,
                        "24": "100 GOOG",
                        "25": 0.14009969,
                        "26": 17,
                        "27": 2,
                        "28": 0.99961827,
                        "29": 2.799e-05,
                        "30": -0.01339331,
                        "31": 0.00018508,
                        "32": 0.00434917,
                        "33": "Normal",
                        "34": 103.02414938,
                        "35": 172.9299,
                        "36": "S",
                        "37": 102.95,
                        "38": 1715786878997,
                        "39": 1714140219464,
                        "40": "O",
                        "41": "OPR",
                        "42": 1715990400000,
                        "43": "P",
                        "44": 1.09818108,
                        "45": 0.9996,
                        "46": 0.98047678,
                        "47": 0,
                        "48": True,
                        "49": "GOOG",
                        "50": 103.07,
                        "51": 68.45,
                        "52": 0,
                        "53": 0,
                        "54": 0,
                        "55": "A"
                    },
                    {
                        "key": "MSFT  240517C00160000",
                        "delayed": True,
                        "assetMainType": "OPTION",
                        "cusip": "",
                        "1": "MSFT 05/17/2024 160.00 C",
                        "2": 259.9,
                        "3": 262.1,
                        "4": 255.53,
                        "5": 0,
                        "6": 0,
                        "7": 256.56,
                        "8": 0,
                        "9": 2,
                        "10": 355.24400385,
                        "11": 261.38,
                        "12": 2024,
                        "13": 100,
                        "14": 2,
                        "15": 0,
                        "16": 52,
                        "17": 51,
                        "18": 1,
                        "19": -1.03,
                        "20": 160,
                        "21": "C",
                        "22": "MSFT",
                        "23": 5,
                        "24": "100 MSFT",
                        "25": -5.85000122,
                        "26": 17,
                        "27": 2,
                        "28": 1,
                        "29": 0,
                        "30": 0,
                        "31": 0,
                        "32": 0,
                        "33": "Normal",
                        "34": 261.39,
                        "35": 421.38,
                        "36": "S",
                        "37": 261,
                        "38": 1715786912341,
                        "39": 1715696927227,
                        "40": "O",
                        "41": "OPR",
                        "42": 1715990400000,
                        "43": "P",
                        "44": -0.40146554,
                        "45": 4.44,
                        "46": 1.73058934,
                        "47": 0,
                        "48": True,
                        "49": "MSFT",
                        "50": 271.45,
                        "51": 199.23,
                        "52": 0,
                        "53": 0,
                        "54": 0,
                        "55": "A"
                    }
                ]
            }]
        }

        socket.recv.side_effect = [
            json.dumps(self.success_response(1, 'LEVELONE_OPTIONS', 'SUBS')),
            json.dumps(stream_item)]
        await self.client.level_one_option_subs(
            ['GOOG_052920C620', 'MSFT_052920C145'])

        handler = Mock()
        async_handler = AsyncMock()
        self.client.add_level_one_option_handler(handler)
        self.client.add_level_one_option_handler(async_handler)
        await self.client.handle_message()

        expected_item = {
            "service": "LEVELONE_OPTIONS",
            "timestamp": 1715787814441,
            "command": "SUBS",
            "content": [
                {
                    "key": "GOOG  240517C00070000",
                    "delayed": True,
                    "assetMainType": "OPTION",
                    "cusip": "",
                    "DESCRIPTION": "GOOG 05/17/2024 70.00 C",
                    "BID_PRICE": 102.15,
                    "ASK_PRICE": 103.75,
                    "LAST_PRICE": 103.07,
                    "HIGH_PRICE": 0,
                    "LOW_PRICE": 0,
                    "CLOSE_PRICE": 101.9504,
                    "TOTAL_VOLUME": 0,
                    "OPEN_INTEREST": 5,
                    "VOLATILITY": 354.99208367,
                    "MONEY_INTRINSIC_VALUE": 102.9299,
                    "EXPIRATION_YEAR": 2024,
                    "MULTIPLIER": 100,
                    "DIGITS": 2,
                    "OPEN_PRICE": 0,
                    "BID_SIZE": 20,
                    "ASK_SIZE": 20,
                    "LAST_SIZE": 1,
                    "NET_CHANGE": 1.1196,
                    "STRIKE_TYPE": 70,
                    "CONTRACT_TYPE": "C",
                    "UNDERLYING": "GOOG",
                    "EXPIRATION_MONTH": 5,
                    "DELIVERABLES": "100 GOOG",
                    "TIME_VALUE": 0.14009969,
                    "EXPIRATION_DAY": 17,
                    "DAYS_TO_EXPIRATION": 2,
                    "DELTA": 0.99961827,
                    "GAMMA": 2.799e-05,
                    "THETA": -0.01339331,
                    "VEGA": 0.00018508,
                    "RHO": 0.00434917,
                    "SECURITY_STATUS": "Normal",
                    "THEORETICAL_OPTION_VALUE": 103.02414938,
                    "UNDERLYING_PRICE": 172.9299,
                    "UV_EXPIRATION_TYPE": "S",
                    "MARK": 102.95,
                    "QUOTE_TIME_MILLIS": 1715786878997,
                    "TRADE_TIME_MILLIS": 1714140219464,
                    "EXCHANGE_ID": "O",
                    "EXCHANGE_NAME": "OPR",
                    "LAST_TRADING_DAY": 1715990400000,
                    "SETTLEMENT_TYPE": "P",
                    "NET_PERCENT_CHANGE": 1.09818108,
                    "MARK_CHANGE": 0.9996,
                    "MARK_CHANGE_PERCENT": 0.98047678,
                    "IMPLIED_YIELD": 0,
                    "IS_PENNY": True,
                    "OPTION_ROOT": "GOOG",
                    "HIGH_PRICE_52_WEEK": 103.07,
                    "LOW_PRICE_52_WEEK": 68.45,
                    "INDICATIVE_ASKING_PRICE": 0,
                    "INDICATIVE_BID_PRICE": 0,
                    "INDICATIVE_QUOTE_TIME": 0,
                    "EXERCISE_TYPE": "A"
                },
                {
                    "key": "MSFT  240517C00160000",
                    "delayed": True,
                    "assetMainType": "OPTION",
                    "cusip": "",
                    "DESCRIPTION": "MSFT 05/17/2024 160.00 C",
                    "BID_PRICE": 259.9,
                    "ASK_PRICE": 262.1,
                    "LAST_PRICE": 255.53,
                    "HIGH_PRICE": 0,
                    "LOW_PRICE": 0,
                    "CLOSE_PRICE": 256.56,
                    "TOTAL_VOLUME": 0,
                    "OPEN_INTEREST": 2,
                    "VOLATILITY": 355.24400385,
                    "MONEY_INTRINSIC_VALUE": 261.38,
                    "EXPIRATION_YEAR": 2024,
                    "MULTIPLIER": 100,
                    "DIGITS": 2,
                    "OPEN_PRICE": 0,
                    "BID_SIZE": 52,
                    "ASK_SIZE": 51,
                    "LAST_SIZE": 1,
                    "NET_CHANGE": -1.03,
                    "STRIKE_TYPE": 160,
                    "CONTRACT_TYPE": "C",
                    "UNDERLYING": "MSFT",
                    "EXPIRATION_MONTH": 5,
                    "DELIVERABLES": "100 MSFT",
                    "TIME_VALUE": -5.85000122,
                    "EXPIRATION_DAY": 17,
                    "DAYS_TO_EXPIRATION": 2,
                    "DELTA": 1,
                    "GAMMA": 0,
                    "THETA": 0,
                    "VEGA": 0,
                    "RHO": 0,
                    "SECURITY_STATUS": "Normal",
                    "THEORETICAL_OPTION_VALUE": 261.39,
                    "UNDERLYING_PRICE": 421.38,
                    "UV_EXPIRATION_TYPE": "S",
                    "MARK": 261,
                    "QUOTE_TIME_MILLIS": 1715786912341,
                    "TRADE_TIME_MILLIS": 1715696927227,
                    "EXCHANGE_ID": "O",
                    "EXCHANGE_NAME": "OPR",
                    "LAST_TRADING_DAY": 1715990400000,
                    "SETTLEMENT_TYPE": "P",
                    "NET_PERCENT_CHANGE": -0.40146554,
                    "MARK_CHANGE": 4.44,
                    "MARK_CHANGE_PERCENT": 1.73058934,
                    "IMPLIED_YIELD": 0,
                    "IS_PENNY": True,
                    "OPTION_ROOT": "MSFT",
                    "HIGH_PRICE_52_WEEK": 271.45,
                    "LOW_PRICE_52_WEEK": 199.23,
                    "INDICATIVE_ASKING_PRICE": 0,
                    "INDICATIVE_BID_PRICE": 0,
                    "INDICATIVE_QUOTE_TIME": 0,
                    "EXERCISE_TYPE": "A"
                }
            ]
        }
        self.assert_handler_called_once_with(handler, expected_item)
        self.assert_handler_called_once_with(async_handler, expected_item)


    ##########################################################################
    # LEVELONE_FUTURES

    @no_duplicates
    @patch('schwab.streaming.ws_client.connect', new_callable=AsyncMock)
    async def test_level_one_futures_subs_success_all_fields(self, ws_connect):
        socket = await self.login_and_get_socket(ws_connect)

        socket.recv.side_effect = [json.dumps(self.success_response(
            1, 'LEVELONE_FUTURES', 'SUBS'))]

        await self.client.level_one_futures_subs(['/ES', '/CL'])
        socket.recv.assert_awaited_once()
        request = self.request_from_socket_mock(socket)

        self.assertEqual(request, {
            'service': 'LEVELONE_FUTURES',
            'command': 'SUBS',
            'requestid': '1',
            "SchwabClientCustomerId": CLIENT_CUSTOMER_ID,
            "SchwabClientCorrelId": CLIENT_CORRELATION_ID,
            'parameters': {
                'keys': '/ES,/CL',
                'fields': ('0,1,2,3,4,5,6,7,8,9,10,11,12,13,14,15,16,17,18,19,' +
                           '20,21,22,23,24,25,26,27,28,29,30,31,32,33,34,35')
            }
        })

    @no_duplicates
    @patch('schwab.streaming.ws_client.connect', new_callable=AsyncMock)
    async def test_level_one_futures_unsubs_success_all_fields(self, ws_connect):
        socket = await self.login_and_get_socket(ws_connect)

        stream_item = self.streaming_entry('LEVELONE_FUTURES', 'SUBS')

        socket.recv.side_effect = [
            json.dumps(self.success_response(1, 'LEVELONE_FUTURES', 'SUBS')),
            json.dumps(stream_item),
            json.dumps(self.success_response(2, 'LEVELONE_FUTURES', 'UNSUBS'))
        ]
        handler = Mock()
        async_handler = AsyncMock()
        self.client.add_level_one_futures_handler(handler)
        self.client.add_level_one_futures_handler(async_handler)

        await self.client.level_one_futures_subs(['/ES', '/CL'])
        await self.client.handle_message()
        await self.client.level_one_futures_unsubs(['/ES', '/CL'])

        self.assert_handler_called_once_with(handler, {'service': 'LEVELONE_FUTURES', 'command': 'SUBS',
                                                       'timestamp': REQUEST_TIMESTAMP})
        self.assert_handler_called_once_with(async_handler, {'service': 'LEVELONE_FUTURES', 'command': 'SUBS',
                                                             'timestamp': REQUEST_TIMESTAMP})
        send_awaited = [
            call(StringMatchesJson({
                "requests": [{
                    "service": "LEVELONE_FUTURES",
                    "requestid": "1",
                    "command": "SUBS", 
                    "SchwabClientCustomerId": CLIENT_CUSTOMER_ID,
                    "SchwabClientCorrelId": CLIENT_CORRELATION_ID,
                    "parameters": {
                        "keys": "/ES,/CL", 
                        "fields": "0,1,2,3,4,5,6,7,8,9,10,11,12,13,14,15,16,"+
                        "17,18,19,20,21,22,23,24,25,26,27,28,29,30,31,32,33,"+
                        "34,35"
                    }
                }]
            })),
            call(StringMatchesJson({
                "requests": [{
                    "service": "LEVELONE_FUTURES",
                    "requestid": "2",
                    "command": "UNSUBS", 
                    "SchwabClientCustomerId": CLIENT_CUSTOMER_ID,
                    "SchwabClientCorrelId": CLIENT_CORRELATION_ID,
                    "parameters": {
                        "keys": "/ES,/CL"
                    }
                }]
            }))
        ]
        socket.send.assert_has_awaits(send_awaited, any_order=False)

    @no_duplicates
    @patch('schwab.streaming.ws_client.connect', new_callable=AsyncMock)
    async def test_level_one_futures_subs_success_some_fields(self, ws_connect):
        socket = await self.login_and_get_socket(ws_connect)

        socket.recv.side_effect = [json.dumps(self.success_response(
            1, 'LEVELONE_FUTURES', 'SUBS'))]

        await self.client.level_one_futures_subs(['/ES', '/CL'], fields=[
            StreamClient.LevelOneFuturesFields.FIELD_0,
            StreamClient.LevelOneFuturesFields.FIELD_1,
            StreamClient.LevelOneFuturesFields.FIELD_2,
            StreamClient.LevelOneFuturesFields.FIELD_28,
        ])
        socket.recv.assert_awaited_once()
        request = self.request_from_socket_mock(socket)

        self.assertEqual(request, {
            'service': 'LEVELONE_FUTURES',
            'command': 'SUBS',
            'requestid': '1',
            "SchwabClientCustomerId": CLIENT_CUSTOMER_ID,
            "SchwabClientCorrelId": CLIENT_CORRELATION_ID,
            'parameters': {
                'keys': '/ES,/CL',
                'fields': '0,1,2,28'
            }
        })

    @no_duplicates
    @patch('schwab.streaming.ws_client.connect', new_callable=AsyncMock)
    async def test_level_one_futures_subs_success_some_fields_no_symbol(
            self, ws_connect):
        socket = await self.login_and_get_socket(ws_connect)

        socket.recv.side_effect = [json.dumps(self.success_response(
            1, 'LEVELONE_FUTURES', 'SUBS'))]

        await self.client.level_one_futures_subs(['/ES', '/CL'], fields=[
            StreamClient.LevelOneFuturesFields.FIELD_1,
            StreamClient.LevelOneFuturesFields.FIELD_2,
            StreamClient.LevelOneFuturesFields.FIELD_28,
        ])
        socket.recv.assert_awaited_once()
        request = self.request_from_socket_mock(socket)

        self.assertEqual(request, {
            'service': 'LEVELONE_FUTURES',
            'command': 'SUBS',
            'requestid': '1',
            "SchwabClientCustomerId": CLIENT_CUSTOMER_ID,
            "SchwabClientCorrelId": CLIENT_CORRELATION_ID,
            'parameters': {
                'keys': '/ES,/CL',
                'fields': '0,1,2,28'
            }
        })

    @no_duplicates
    @patch('schwab.streaming.ws_client.connect', new_callable=AsyncMock)
    async def test_level_one_futures_subs_failure(self, ws_connect):
        socket = await self.login_and_get_socket(ws_connect)

        response = self.success_response(1, 'LEVELONE_FUTURES', 'SUBS')
        response['response'][0]['content']['code'] = 21
        socket.recv.side_effect = [json.dumps(response)]

        with self.assertRaises(schwab.streaming.UnexpectedResponseCode):
            await self.client.level_one_futures_subs(['/ES', '/CL'])

    @no_duplicates
    @patch('schwab.streaming.ws_client.connect', new_callable=AsyncMock)
    async def test_level_one_futures_unsubs_failure(self, ws_connect):
        socket = await self.login_and_get_socket(ws_connect)

        response = self.success_response(1, 'LEVELONE_FUTURES', 'UNSUBS')
        response['response'][0]['content']['code'] = 21
        socket.recv.side_effect = [json.dumps(response)]

        with self.assertRaises(schwab.streaming.UnexpectedResponseCode):
            await self.client.level_one_futures_unsubs(['/ES', '/CL'])

    @no_duplicates
    @patch('schwab.streaming.ws_client.connect', new_callable=AsyncMock)
    async def test_level_one_futures_handler(self, ws_connect):
        socket = await self.login_and_get_socket(ws_connect)

        stream_item = {
            'data': [{
                'service': 'LEVELONE_FUTURES',
                'timestamp': 1590598762176,
                'command': 'SUBS',
                'content': [{
                    'key': '/ES',
                    'delayed': False,
                    '1': 2998.75,
                    '2': 2999,
                    '3': 2998.75,
                    '4': 15,
                    '5': 47,
                    '6': '?',
                    '7': '?',
                    '8': 1489587,
                    '9': 6,
                    '10': 1590598761934,
                    '11': 1590598761921,
                    '12': 3035,
                    '13': 2965.5,
                    '14': 2994.5,
                    '15': 'E',
                    '16': 'E-mini S&P 500 Index Futures,Jun-2020,ETH',
                    '17': '?',
                    '18': 2994,
                    '19': 4.25,
                    '20': 0.0014,
                    '21': 'XCME',
                    '22': 'Unknown',
                    '23': 3121588,
                    '24': 2999.25,
                    '25': 0.25,
                    '26': 12.5,
                    '27': '/ES',
                    '28': 'D,D',
                    '29': ('GLBX(de=1640;0=-1700151515301600;' +
                           '1=r-17001515r15301600d-15551640;' +
                           '7=d-16401555)'),
                    '30': True,
                    '31': 50,
                    '32': True,
                    '33': 2994.5,
                    '34': '/ESM20',
                    '35': 1592539200000
                }, {
                    'key': '/CL',
                    'delayed': False,
                    '1': 33.33,
                    '2': 33.34,
                    '3': 33.34,
                    '4': 13,
                    '5': 3,
                    '6': '?',
                    '7': '?',
                    '8': 325014,
                    '9': 2,
                    '10': 1590598761786,
                    '11': 1590598761603,
                    '12': 34.32,
                    '13': 32.18,
                    '14': 34.35,
                    '15': 'E',
                    '16': 'Light Sweet Crude Oil Futures,Jul-2020,ETH',
                    '17': '?',
                    '18': 34.14,
                    '19': -1.01,
                    '20': -0.0294,
                    '21': 'XNYM',
                    '22': 'Unknown',
                    '23': 270931,
                    '24': 33.35,
                    '25': 0.01,
                    '26': 10,
                    '27': '/CL',
                    '28': 'D,D',
                    '29': ('GLBX(de=1640;0=-17001600;' +
                           '1=-17001600d-15551640;7=d-16401555)'),
                    '30': True,
                    '31': 1000,
                    '32': True,
                    '33': 34.35,
                    '34': '/CLN20',
                    '35': 1592798400000
                }]
            }]
        }

        socket.recv.side_effect = [
            json.dumps(self.success_response(1, 'LEVELONE_FUTURES', 'SUBS')),
            json.dumps(stream_item)]
        await self.client.level_one_futures_subs(['/ES', '/CL'])

        handler = Mock()
        async_handler = AsyncMock()
        self.client.add_level_one_futures_handler(handler)
        self.client.add_level_one_futures_handler(async_handler)
        await self.client.handle_message()

        expected_item = {
            'service': 'LEVELONE_FUTURES',
            'timestamp': 1590598762176,
            'command': 'SUBS',
            'content': [{
                'key': '/ES',
                'delayed': False,
                'FIELD_1': 2998.75,
                'FIELD_2': 2999,
                'FIELD_3': 2998.75,
                'FIELD_4': 15,
                'FIELD_5': 47,
                'FIELD_6': '?',
                'FIELD_7': '?',
                'FIELD_8': 1489587,
                'FIELD_9': 6,
                'FIELD_10': 1590598761934,
                'FIELD_11': 1590598761921,
                'FIELD_12': 3035,
                'FIELD_13': 2965.5,
                'FIELD_14': 2994.5,
                'FIELD_15': 'E',
                'FIELD_16': 'E-mini S&P 500 Index Futures,Jun-2020,ETH',
                'FIELD_17': '?',
                'FIELD_18': 2994,
                'FIELD_19': 4.25,
                'FIELD_20': 0.0014,
                'FIELD_21': 'XCME',
                'FIELD_22': 'Unknown',
                'FIELD_23': 3121588,
                'FIELD_24': 2999.25,
                'FIELD_25': 0.25,
                'FIELD_26': 12.5,
                'FIELD_27': '/ES',
                'FIELD_28': 'D,D',
                'FIELD_29': (
                    'GLBX(de=1640;0=-1700151515301600;' +
                    '1=r-17001515r15301600d-15551640;' +
                    '7=d-16401555)'),
                'FIELD_30': True,
                'FIELD_31': 50,
                'FIELD_32': True,
                'FIELD_33': 2994.5,
                'FIELD_34': '/ESM20',
                'FIELD_35': 1592539200000
            }, {
                'key': '/CL',
                'delayed': False,
                'FIELD_1': 33.33,
                'FIELD_2': 33.34,
                'FIELD_3': 33.34,
                'FIELD_4': 13,
                'FIELD_5': 3,
                'FIELD_6': '?',
                'FIELD_7': '?',
                'FIELD_8': 325014,
                'FIELD_9': 2,
                'FIELD_10': 1590598761786,
                'FIELD_11': 1590598761603,
                'FIELD_12': 34.32,
                'FIELD_13': 32.18,
                'FIELD_14': 34.35,
                'FIELD_15': 'E',
                'FIELD_16': 'Light Sweet Crude Oil Futures,Jul-2020,ETH',
                'FIELD_17': '?',
                'FIELD_18': 34.14,
                'FIELD_19': -1.01,
                'FIELD_20': -0.0294,
                'FIELD_21': 'XNYM',
                'FIELD_22': 'Unknown',
                'FIELD_23': 270931,
                'FIELD_24': 33.35,
                'FIELD_25': 0.01,
                'FIELD_26': 10,
                'FIELD_27': '/CL',
                'FIELD_28': 'D,D',
                'FIELD_29': (
                    'GLBX(de=1640;0=-17001600;' +
                    '1=-17001600d-15551640;7=d-16401555)'),
                'FIELD_30': True,
                'FIELD_31': 1000,
                'FIELD_32': True,
                'FIELD_33': 34.35,
                'FIELD_34': '/CLN20',
                'FIELD_35': 1592798400000
            }]
        }

        self.assert_handler_called_once_with(handler, expected_item)
        self.assert_handler_called_once_with(async_handler, expected_item)


    ##########################################################################
    # LEVELONE_FOREX

    @no_duplicates
    @patch('schwab.streaming.ws_client.connect', new_callable=AsyncMock)
    async def test_level_one_forex_subs_success_all_fields(self, ws_connect):
        socket = await self.login_and_get_socket(ws_connect)

        socket.recv.side_effect = [json.dumps(self.success_response(
            1, 'LEVELONE_FOREX', 'SUBS'))]

        await self.client.level_one_forex_subs(['EUR/USD', 'EUR/GBP'])
        socket.recv.assert_awaited_once()
        request = self.request_from_socket_mock(socket)

        self.assertEqual(request, {
            'service': 'LEVELONE_FOREX',
            'command': 'SUBS',
            'requestid': '1',
            "SchwabClientCustomerId": CLIENT_CUSTOMER_ID,
            "SchwabClientCorrelId": CLIENT_CORRELATION_ID,
            'parameters': {
                'keys': 'EUR/USD,EUR/GBP',
                'fields': ('0,1,2,3,4,5,6,7,8,9,10,11,12,13,14,15,16,17,18,19,' +
                           '20,21,22,23,24,25,26,27,28,29')
            }
        })

    @no_duplicates
    @patch('schwab.streaming.ws_client.connect', new_callable=AsyncMock)
    async def test_level_one_forex_unsubs_success_all_fields(self, ws_connect):
        socket = await self.login_and_get_socket(ws_connect)

        stream_item = self.streaming_entry('LEVELONE_FOREX', 'SUBS')

        socket.recv.side_effect = [
            json.dumps(self.success_response(1, 'LEVELONE_FOREX', 'SUBS')),
            json.dumps(stream_item),
            json.dumps(self.success_response(2, 'LEVELONE_FOREX', 'UNSUBS'))
        ]
        handler = Mock()
        async_handler = AsyncMock()
        self.client.add_level_one_forex_handler(handler)
        self.client.add_level_one_forex_handler(async_handler)

        await self.client.level_one_forex_subs(['EUR/USD', 'EUR/GBP'])
        await self.client.handle_message()
        await self.client.level_one_forex_unsubs(['EUR/USD', 'EUR/GBP'])

        self.assert_handler_called_once_with(handler, {'service': 'LEVELONE_FOREX', 'command': 'SUBS',
                                                       'timestamp': REQUEST_TIMESTAMP})
        self.assert_handler_called_once_with(async_handler, {'service': 'LEVELONE_FOREX', 'command': 'SUBS',
                                                             'timestamp': REQUEST_TIMESTAMP})
        send_awaited = [
            call(StringMatchesJson({
                "requests": [{
                    "service": "LEVELONE_FOREX",
                    "requestid": "1",
                    "command": "SUBS", 
                    "SchwabClientCustomerId": CLIENT_CUSTOMER_ID,
                    "SchwabClientCorrelId": CLIENT_CORRELATION_ID,
                    "parameters": {
                        "keys": "EUR/USD,EUR/GBP",
                        "fields": "0,1,2,3,4,5,6,7,8,9,10,11,12,13,14,15,16,"+
                        "17,18,19,20,21,22,23,24,25,26,27,28,29"
                    }
                }]
            })),
            call(StringMatchesJson({
                "requests": [{
                    "service": "LEVELONE_FOREX",
                    "requestid": "2",
                    "command": "UNSUBS",
                    "SchwabClientCustomerId": CLIENT_CUSTOMER_ID,
                    "SchwabClientCorrelId": CLIENT_CORRELATION_ID,
                    "parameters": {
                        "keys": "EUR/USD,EUR/GBP"
                    }
                }]
            }))
        ]
        socket.send.assert_has_awaits(send_awaited, any_order=False)

    @no_duplicates
    @patch('schwab.streaming.ws_client.connect', new_callable=AsyncMock)
    async def test_level_one_forex_subs_success_some_fields(self, ws_connect):
        socket = await self.login_and_get_socket(ws_connect)

        socket.recv.side_effect = [json.dumps(self.success_response(
            1, 'LEVELONE_FOREX', 'SUBS'))]

        await self.client.level_one_forex_subs(['EUR/USD', 'EUR/GBP'], fields=[
            StreamClient.LevelOneForexFields.FIELD_0,
            StreamClient.LevelOneForexFields.FIELD_10,
            StreamClient.LevelOneForexFields.FIELD_11,
            StreamClient.LevelOneForexFields.FIELD_26,
        ])
        socket.recv.assert_awaited_once()
        request = self.request_from_socket_mock(socket)

        self.assertEqual(request, {
            'service': 'LEVELONE_FOREX',
            'command': 'SUBS',
            'requestid': '1',
            "SchwabClientCustomerId": CLIENT_CUSTOMER_ID,
            "SchwabClientCorrelId": CLIENT_CORRELATION_ID,
            'parameters': {
                'keys': 'EUR/USD,EUR/GBP',
                'fields': '0,10,11,26'
            }
        })

    @no_duplicates
    @patch('schwab.streaming.ws_client.connect', new_callable=AsyncMock)
    async def test_level_one_forex_subs_success_some_fields_no_symbol(
            self, ws_connect):
        socket = await self.login_and_get_socket(ws_connect)

        socket.recv.side_effect = [json.dumps(self.success_response(
            1, 'LEVELONE_FOREX', 'SUBS'))]

        await self.client.level_one_forex_subs(['EUR/USD', 'EUR/GBP'], fields=[
            StreamClient.LevelOneForexFields.FIELD_10,
            StreamClient.LevelOneForexFields.FIELD_11,
            StreamClient.LevelOneForexFields.FIELD_26,
        ])
        socket.recv.assert_awaited_once()
        request = self.request_from_socket_mock(socket)

        self.assertEqual(request, {
            'service': 'LEVELONE_FOREX',
            'command': 'SUBS',
            'requestid': '1',
            "SchwabClientCustomerId": CLIENT_CUSTOMER_ID,
            "SchwabClientCorrelId": CLIENT_CORRELATION_ID,
            'parameters': {
                'keys': 'EUR/USD,EUR/GBP',
                'fields': '0,10,11,26'
            }
        })

    @no_duplicates
    @patch('schwab.streaming.ws_client.connect', new_callable=AsyncMock)
    async def test_level_one_forex_subs_failure(self, ws_connect):
        socket = await self.login_and_get_socket(ws_connect)

        response = self.success_response(1, 'LEVELONE_FOREX', 'SUBS')
        response['response'][0]['content']['code'] = 21
        socket.recv.side_effect = [json.dumps(response)]

        with self.assertRaises(schwab.streaming.UnexpectedResponseCode):
            await self.client.level_one_forex_subs(['EUR/USD', 'EUR/GBP'])

    @no_duplicates
    @patch('schwab.streaming.ws_client.connect', new_callable=AsyncMock)
    async def test_level_one_forex_unsubs_failure(self, ws_connect):
        socket = await self.login_and_get_socket(ws_connect)

        response = self.success_response(1, 'LEVELONE_FOREX', 'UNSUBS')
        response['response'][0]['content']['code'] = 21
        socket.recv.side_effect = [json.dumps(response)]

        with self.assertRaises(schwab.streaming.UnexpectedResponseCode):
            await self.client.level_one_forex_unsubs(['EUR/USD', 'EUR/GBP'])

    @no_duplicates
    @patch('schwab.streaming.ws_client.connect', new_callable=AsyncMock)
    async def test_level_one_forex_handler(self, ws_connect):
        socket = await self.login_and_get_socket(ws_connect)

        stream_item = {
            'data': [{
                'service': 'LEVELONE_FOREX',
                'timestamp': 1590599267920,
                'command': 'SUBS',
                'content': [{
                    'key': 'EUR/GBP',
                    'delayed': False,
                    'assetMainType': 'FOREX',
                    '1': 0.8967,
                    '2': 0.8969,
                    '3': 0.8968,
                    '4': 1000000,
                    '5': 1000000,
                    '6': 19000000,
                    '7': 370000,
                    '8': 1590599267658,
                    '9': 1590599267658,
                    '10': 0.8994,
                    '11': 0.8896,
                    '12': 0.894,
                    '13': 'T',
                    '14': 'Euro/GBPound Spot',
                    '15': 0.8901,
                    '16': 0.0028,
                    '17': '??',
                    '18': 'GFT',
                    '19': 2,
                    '20': 'Unknown',
                    '21': 'UNUSED',
                    '22': 'UNUSED',
                    '23': 'UNUSED',
                    '24': 'UNUSED',
                    '25': 'UNUSED',
                    '26': 'UNUSED',
                    '27': 0.8994,
                    '28': 0.8896,
                    '29': 0.8968
                }, {
                    'key': 'EUR/USD',
                    'delayed': False,
                    'assetMainType': 'FOREX',
                    '1': 1.0976,
                    '2': 1.0978,
                    '3': 1.0977,
                    '4': 1000000,
                    '5': 2800000,
                    '6': 633170000,
                    '7': 10000,
                    '8': 1590599267658,
                    '9': 1590599267658,
                    '10': 1.1031,
                    '11': 1.0936,
                    '12': 1.0893,
                    '13': 'T',
                    '14': 'Euro/USDollar Spot',
                    '15': 1.0982,
                    '16': 0.0084,
                    '17': '???',
                    '18': 'GFT',
                    '19': 2,
                    '20': 'Unknown',
                    '21': 'UNUSED',
                    '22': 'UNUSED',
                    '23': 'UNUSED',
                    '24': 'UNUSED',
                    '25': 'UNUSED',
                    '26': 'UNUSED',
                    '27': 1.1031,
                    '28': 1.0936,
                    '29': 1.0977
                }]
            }]
        }

        socket.recv.side_effect = [
            json.dumps(self.success_response(1, 'LEVELONE_FOREX', 'SUBS')),
            json.dumps(stream_item)]
        await self.client.level_one_forex_subs(['EUR/USD', 'EUR/GBP'])

        handler = Mock()
        async_handler = AsyncMock()
        self.client.add_level_one_forex_handler(handler)
        self.client.add_level_one_forex_handler(async_handler)
        await self.client.handle_message()

        expected_item = {
            'service': 'LEVELONE_FOREX',
            'timestamp': 1590599267920,
            'command': 'SUBS',
            'content': [{
                'key': 'EUR/GBP',
                'delayed': False,
                'assetMainType': 'FOREX',
                'FIELD_1': 0.8967,
                'FIELD_2': 0.8969,
                'FIELD_3': 0.8968,
                'FIELD_4': 1000000,
                'FIELD_5': 1000000,
                'FIELD_6': 19000000,
                'FIELD_7': 370000,
                'FIELD_8': 1590599267658,
                'FIELD_9': 1590599267658,
                'FIELD_10': 0.8994,
                'FIELD_11': 0.8896,
                'FIELD_12': 0.894,
                'FIELD_13': 'T',
                'FIELD_14': 'Euro/GBPound Spot',
                'FIELD_15': 0.8901,
                'FIELD_16': 0.0028,
                'FIELD_17': '??',
                'FIELD_18': 'GFT',
                'FIELD_19': 2,
                'FIELD_20': 'Unknown',
                'FIELD_21': 'UNUSED',
                'FIELD_22': 'UNUSED',
                'FIELD_23': 'UNUSED',
                'FIELD_24': 'UNUSED',
                'FIELD_25': 'UNUSED',
                'FIELD_26': 'UNUSED',
                'FIELD_27': 0.8994,
                'FIELD_28': 0.8896,
                'FIELD_29': 0.8968
            }, {
                'key': 'EUR/USD',
                'delayed': False,
                'assetMainType': 'FOREX',
                'FIELD_1': 1.0976,
                'FIELD_2': 1.0978,
                'FIELD_3': 1.0977,
                'FIELD_4': 1000000,
                'FIELD_5': 2800000,
                'FIELD_6': 633170000,
                'FIELD_7': 10000,
                'FIELD_8': 1590599267658,
                'FIELD_9': 1590599267658,
                'FIELD_10': 1.1031,
                'FIELD_11': 1.0936,
                'FIELD_12': 1.0893,
                'FIELD_13': 'T',
                'FIELD_14': 'Euro/USDollar Spot',
                'FIELD_15': 1.0982,
                'FIELD_16': 0.0084,
                'FIELD_17': '???',
                'FIELD_18': 'GFT',
                'FIELD_19': 2,
                'FIELD_20': 'Unknown',
                'FIELD_21': 'UNUSED',
                'FIELD_22': 'UNUSED',
                'FIELD_23': 'UNUSED',
                'FIELD_24': 'UNUSED',
                'FIELD_25': 'UNUSED',
                'FIELD_26': 'UNUSED',
                'FIELD_27': 1.1031,
                'FIELD_28': 1.0936,
                'FIELD_29': 1.0977
            }]
        }

        self.assert_handler_called_once_with(handler, expected_item)
        self.assert_handler_called_once_with(async_handler, expected_item)


    ##########################################################################
    # LEVELONE_FUTURES_OPTIONS

    @no_duplicates
    @patch('schwab.streaming.ws_client.connect', new_callable=AsyncMock)
    async def test_level_one_futures_options_subs_success_all_fields(
            self, ws_connect):
        socket = await self.login_and_get_socket(ws_connect)

        socket.recv.side_effect = [json.dumps(self.success_response(
            1, 'LEVELONE_FUTURES_OPTIONS', 'SUBS'))]

        await self.client.level_one_futures_options_subs(
            ['NQU20_C6500', 'NQU20_P6500'])
        socket.recv.assert_awaited_once()
        request = self.request_from_socket_mock(socket)

        self.assertEqual(request, {
            'service': 'LEVELONE_FUTURES_OPTIONS',
            'command': 'SUBS',
            'requestid': '1',
            "SchwabClientCustomerId": CLIENT_CUSTOMER_ID,
            "SchwabClientCorrelId": CLIENT_CORRELATION_ID,
            'parameters': {
                'keys': 'NQU20_C6500,NQU20_P6500',
                'fields': ('0,1,2,3,4,5,6,7,8,9,10,11,12,13,14,15,16,17,18,' +
                           '19,20,21,22,23,24,25,26,27,28,29,30,31,32,33,34,35')
            }
        })

    @no_duplicates
    @patch('schwab.streaming.ws_client.connect', new_callable=AsyncMock)
    async def test_level_one_futures_options_unsubs_success_all_fields(
            self, ws_connect):
        socket = await self.login_and_get_socket(ws_connect)

        stream_item = self.streaming_entry('LEVELONE_FUTURES_OPTIONS', 'SUBS')

        socket.recv.side_effect = [
            json.dumps(self.success_response(1, 'LEVELONE_FUTURES_OPTIONS', 'SUBS')),
            json.dumps(stream_item),
            json.dumps(self.success_response(2, 'LEVELONE_FUTURES_OPTIONS', 'UNSUBS'))
        ]
        handler = Mock()
        async_handler = AsyncMock()
        self.client.add_level_one_futures_options_handler(handler)
        self.client.add_level_one_futures_options_handler(async_handler)

        await self.client.level_one_futures_options_subs(
            ['NQU20_C6500', 'NQU20_P6500'])
        await self.client.handle_message()
        await self.client.level_one_futures_options_unsubs(
            ['NQU20_C6500', 'NQU20_P6500'])

        self.assert_handler_called_once_with(
                handler, {'service': 'LEVELONE_FUTURES_OPTIONS',
                          'command': 'SUBS',
                          'timestamp': REQUEST_TIMESTAMP})
        self.assert_handler_called_once_with(
                async_handler, {'service': 'LEVELONE_FUTURES_OPTIONS',
                                'command': 'SUBS',
                                'timestamp': REQUEST_TIMESTAMP})
        send_awaited = [
            call(StringMatchesJson({
                "requests": [{
                    "service": "LEVELONE_FUTURES_OPTIONS",
                    "requestid": "1",
                    "command": "SUBS", 
                    "SchwabClientCustomerId": CLIENT_CUSTOMER_ID,
                    "SchwabClientCorrelId": CLIENT_CORRELATION_ID,
                    "parameters": {
                        "keys": "NQU20_C6500,NQU20_P6500", 
                        "fields": "0,1,2,3,4,5,6,7,8,9,10,11,12,13,14,15,16,"+
                        "17,18,19,20,21,22,23,24,25,26,27,28,29,30,31,32,33,"+
                        "34,35"
                    }
                }]
            })),
            call(StringMatchesJson({
                "requests": [{
                    "service": "LEVELONE_FUTURES_OPTIONS",
                    "requestid": "2",
                    "command": "UNSUBS",
                    "SchwabClientCustomerId": CLIENT_CUSTOMER_ID,
                    "SchwabClientCorrelId": CLIENT_CORRELATION_ID,
                    "parameters": {
                        "keys": "NQU20_C6500,NQU20_P6500"
                    }
                }]
            })),
        ]
        socket.send.assert_has_awaits(send_awaited, any_order=False)

    @no_duplicates
    @patch('schwab.streaming.ws_client.connect', new_callable=AsyncMock)
    async def test_level_one_futures_options_subs_success_some_fields(
            self, ws_connect):
        socket = await self.login_and_get_socket(ws_connect)

        socket.recv.side_effect = [json.dumps(self.success_response(
            1, 'LEVELONE_FUTURES_OPTIONS', 'SUBS'))]

        await self.client.level_one_futures_options_subs(
            ['NQU20_C6500', 'NQU20_P6500'], fields=[
                StreamClient.LevelOneFuturesOptionsFields.FIELD_0,
                StreamClient.LevelOneFuturesOptionsFields.FIELD_4,
                StreamClient.LevelOneFuturesOptionsFields.FIELD_5,
                StreamClient.LevelOneFuturesOptionsFields.FIELD_28,
            ])
        socket.recv.assert_awaited_once()
        request = self.request_from_socket_mock(socket)

        self.assertEqual(request, {
            'service': 'LEVELONE_FUTURES_OPTIONS',
            'command': 'SUBS',
            'requestid': '1',
            "SchwabClientCustomerId": CLIENT_CUSTOMER_ID,
            "SchwabClientCorrelId": CLIENT_CORRELATION_ID,
            'parameters': {
                'keys': 'NQU20_C6500,NQU20_P6500',
                'fields': '0,4,5,28'
            }
        })

    @no_duplicates
    @patch('schwab.streaming.ws_client.connect', new_callable=AsyncMock)
    async def test_level_one_futures_options_subs_success_some_fields_no_symol(
            self, ws_connect):
        socket = await self.login_and_get_socket(ws_connect)

        socket.recv.side_effect = [json.dumps(self.success_response(
            1, 'LEVELONE_FUTURES_OPTIONS', 'SUBS'))]

        await self.client.level_one_futures_options_subs(
            ['NQU20_C6500', 'NQU20_P6500'], fields=[
                StreamClient.LevelOneFuturesOptionsFields.FIELD_4,
                StreamClient.LevelOneFuturesOptionsFields.FIELD_5,
                StreamClient.LevelOneFuturesOptionsFields.FIELD_28,
            ])
        socket.recv.assert_awaited_once()
        request = self.request_from_socket_mock(socket)

        self.assertEqual(request, {
            'service': 'LEVELONE_FUTURES_OPTIONS',
            'command': 'SUBS',
            'requestid': '1',
            "SchwabClientCustomerId": CLIENT_CUSTOMER_ID,
            "SchwabClientCorrelId": CLIENT_CORRELATION_ID,
            'parameters': {
                'keys': 'NQU20_C6500,NQU20_P6500',
                'fields': '0,4,5,28'
            }
        })

    @no_duplicates
    @patch('schwab.streaming.ws_client.connect', new_callable=AsyncMock)
    async def test_level_one_futures_options_subs_failure(self, ws_connect):
        socket = await self.login_and_get_socket(ws_connect)

        response = self.success_response(1, 'LEVELONE_FUTURES_OPTIONS', 'SUBS')
        response['response'][0]['content']['code'] = 21
        socket.recv.side_effect = [json.dumps(response)]

        with self.assertRaises(schwab.streaming.UnexpectedResponseCode):
            await self.client.level_one_futures_options_subs(
                ['NQU20_C6500', 'NQU20_P6500'])

    @no_duplicates
    @patch('schwab.streaming.ws_client.connect', new_callable=AsyncMock)
    async def test_level_one_futures_options_unsubs_failure(self, ws_connect):
        socket = await self.login_and_get_socket(ws_connect)

        response = self.success_response(1, 'LEVELONE_FUTURES_OPTIONS', 'UNSUBS')
        response['response'][0]['content']['code'] = 21
        socket.recv.side_effect = [json.dumps(response)]

        with self.assertRaises(schwab.streaming.UnexpectedResponseCode):
            await self.client.level_one_futures_options_unsubs(
                ['NQU20_C6500', 'NQU20_P6500'])

    @no_duplicates
    # TODO: Replace this with real messages
    @patch('schwab.streaming.ws_client.connect', new_callable=AsyncMock)
    async def test_level_one_futures_options_handler(self, ws_connect):
        socket = await self.login_and_get_socket(ws_connect)

        stream_item = {
            'data': [{
                'service': 'LEVELONE_FUTURES_OPTIONS',
                'timestamp': 1590245129396,
                'command': 'SUBS',
                'content': [{
                    'key': 'NQU20_C6500',
                    'delayed': False,
                    'assetMainType': 'FUTURES_OPTION',
                    '1': 2956,
                    '2': 2956.5,
                    '3': 2956.4,
                    '4': 3,
                    '5': 2,
                    '6': 'E',
                    '7': 'T',
                    '8': 1293,
                    '9': 6,
                    '10': 1590181200064,
                    '11': 1590181199726,
                    '12': 2956.6,
                    '13': 2956.3,
                    '14': 2956.25,
                    '15': '?',
                    '16': 'NASDAQ Call',
                    '17': '?',
                    '18': 2956.0,
                    '19': 0.1,
                    '20': 1.2,
                    '21': 'EXCH',
                    '22': 'Unknown',
                    '23': 19,
                    '24': 2955.9,
                    '25': 0.1,
                    '26': 100,
                    '27': 'NQU',
                    '28': '0.01',
                    '29': ('GLBX(de=1640;0=-1700151515301596;' +
                           '1=r-17001515r15301600d-15551640;' +
                           '7=d-16401555)'),
                    '30': True,
                    '31': 100,
                    '32': True,
                    '33': 17.9,
                    '34': 'NQU',
                    '35': '2020-03-01'
                }, {
                    'key': 'NQU20_C6500',
                    'delayed': False,
                    'assetMainType': 'FUTURES_OPTION',
                    '1': 2957,
                    '2': 2958.5,
                    '3': 2957.4,
                    '4': 4,
                    '5': 3,
                    '6': 'Q',
                    '7': 'V',
                    '8': 1294,
                    '9': 7,
                    '10': 1590181200065,
                    '11': 1590181199727,
                    '12': 2956.7,
                    '13': 2956.4,
                    '14': 2956.26,
                    '15': '?',
                    '16': 'NASDAQ Put',
                    '17': '?',
                    '18': 2956.1,
                    '19': 0.2,
                    '20': 1.3,
                    '21': 'EXCH',
                    '22': 'Unknown',
                    '23': 20,
                    '24': 2956.9,
                    '25': 0.2,
                    '26': 101,
                    '27': 'NQU',
                    '28': '0.02',
                    '29': ('GLBX(de=1641;0=-1700151515301596;' +
                           '1=r-17001515r15301600d-15551640;' +
                           '7=d-16401555)'),
                    '30': True,
                    '31': 101,
                    '32': True,
                    '33': 17.10,
                    '34': 'NQU',
                    '35': '2021-03-01'
                }]
            }]
        }

        socket.recv.side_effect = [
            json.dumps(self.success_response(
                1, 'LEVELONE_FUTURES_OPTIONS', 'SUBS')),
            json.dumps(stream_item)]
        await self.client.level_one_futures_options_subs(
            ['NQU20_C6500', 'NQU20_P6500'])

        handler = Mock()
        async_handler = AsyncMock()
        self.client.add_level_one_futures_options_handler(handler)
        self.client.add_level_one_futures_options_handler(async_handler)
        await self.client.handle_message()

        expected_item = {
            'service': 'LEVELONE_FUTURES_OPTIONS',
            'timestamp': 1590245129396,
            'command': 'SUBS',
            'content': [{
                'key': 'NQU20_C6500',
                'delayed': False,
                'assetMainType': 'FUTURES_OPTION',
                'FIELD_1': 2956,
                'FIELD_2': 2956.5,
                'FIELD_3': 2956.4,
                'FIELD_4': 3,
                'FIELD_5': 2,
                'FIELD_6': 'E',
                'FIELD_7': 'T',
                'FIELD_8': 1293,
                'FIELD_9': 6,
                'FIELD_10': 1590181200064,
                'FIELD_11': 1590181199726,
                'FIELD_12': 2956.6,
                'FIELD_13': 2956.3,
                'FIELD_14': 2956.25,
                'FIELD_15': '?',
                'FIELD_16': 'NASDAQ Call',
                'FIELD_17': '?',
                'FIELD_18': 2956.0,
                'FIELD_19': 0.1,
                'FIELD_20': 1.2,
                'FIELD_21': 'EXCH',
                'FIELD_22': 'Unknown',
                'FIELD_23': 19,
                'FIELD_24': 2955.9,
                'FIELD_25': 0.1,
                'FIELD_26': 100,
                'FIELD_27': 'NQU',
                'FIELD_28': '0.01',
                'FIELD_29': ('GLBX(de=1640;0=-1700151515301596;' +
                                         '1=r-17001515r15301600d-15551640;' +
                                         '7=d-16401555)'),
                'FIELD_30': True,
                'FIELD_31': 100,
                'FIELD_32': True,
                'FIELD_33': 17.9,
                'FIELD_34': 'NQU',
                'FIELD_35': '2020-03-01'
            }, {
                'key': 'NQU20_C6500',
                'delayed': False,
                'assetMainType': 'FUTURES_OPTION',
                'FIELD_1': 2957,
                'FIELD_2': 2958.5,
                'FIELD_3': 2957.4,
                'FIELD_4': 4,
                'FIELD_5': 3,
                'FIELD_6': 'Q',
                'FIELD_7': 'V',
                'FIELD_8': 1294,
                'FIELD_9': 7,
                'FIELD_10': 1590181200065,
                'FIELD_11': 1590181199727,
                'FIELD_12': 2956.7,
                'FIELD_13': 2956.4,
                'FIELD_14': 2956.26,
                'FIELD_15': '?',
                'FIELD_16': 'NASDAQ Put',
                'FIELD_17': '?',
                'FIELD_18': 2956.1,
                'FIELD_19': 0.2,
                'FIELD_20': 1.3,
                'FIELD_21': 'EXCH',
                'FIELD_22': 'Unknown',
                'FIELD_23': 20,
                'FIELD_24': 2956.9,
                'FIELD_25': 0.2,
                'FIELD_26': 101,
                'FIELD_27': 'NQU',
                'FIELD_28': '0.02',
                'FIELD_29': ('GLBX(de=1641;0=-1700151515301596;' +
                                         '1=r-17001515r15301600d-15551640;' +
                                         '7=d-16401555)'),
                'FIELD_30': True,
                'FIELD_31': 101,
                'FIELD_32': True,
                'FIELD_33': 17.10,
                'FIELD_34': 'NQU',
                'FIELD_35': '2021-03-01'
            }]
        }

        self.assert_handler_called_once_with(handler, expected_item)
        self.assert_handler_called_once_with(async_handler, expected_item)

    ##########################################################################
    # TIMESALE_EQUITY

    @no_duplicates
    @patch('schwab.streaming.ws_client.connect', new_callable=AsyncMock)
    async def test_timesale_equity_subs_success_all_fields(self, ws_connect):
        socket = await self.login_and_get_socket(ws_connect)

        socket.recv.side_effect = [json.dumps(self.success_response(
            1, 'TIMESALE_EQUITY', 'SUBS'))]

        await self.client.timesale_equity_subs(['GOOG', 'MSFT'])
        socket.recv.assert_awaited_once()
        request = self.request_from_socket_mock(socket)

        self.assertEqual(request, {
            'service': 'TIMESALE_EQUITY',
            'command': 'SUBS',
            'requestid': '1',
            "SchwabClientCustomerId": CLIENT_CUSTOMER_ID,
            "SchwabClientCorrelId": CLIENT_CORRELATION_ID,
            'parameters': {
                'keys': 'GOOG,MSFT',
                'fields': ('0,1,2,3,4')
            }
        })

    @no_duplicates
    @patch('schwab.streaming.ws_client.connect', new_callable=AsyncMock)
    async def test_timesale_equity_unsubs_success_all_fields(self, ws_connect):
        socket = await self.login_and_get_socket(ws_connect)

        stream_item = self.streaming_entry('TIMESALE_EQUITY', 'SUBS')

        socket.recv.side_effect = [
            json.dumps(self.success_response(1, 'TIMESALE_EQUITY', 'SUBS')),
            json.dumps(stream_item),
            json.dumps(self.success_response(2, 'TIMESALE_EQUITY', 'UNSUBS')),
        ]
        handler = Mock()
        async_handler = AsyncMock()
        self.client.add_timesale_equity_handler(handler)
        self.client.add_timesale_equity_handler(async_handler)

        await self.client.timesale_equity_subs(['GOOG', 'MSFT'])
        await self.client.handle_message()
        await self.client.timesale_equity_unsubs(['GOOG', 'MSFT'])

        self.assert_handler_called_once_with(handler, {'service': 'TIMESALE_EQUITY', 'command': 'SUBS',
                                                       'timestamp': REQUEST_TIMESTAMP})
        self.assert_handler_called_once_with(async_handler, {'service': 'TIMESALE_EQUITY', 'command': 'SUBS',
                                                             'timestamp': REQUEST_TIMESTAMP})
        send_awaited = [
            call(StringMatchesJson({
                "requests": [{
                    "service": "TIMESALE_EQUITY",
                    "requestid": "1",
                    "command": "SUBS",
                    "SchwabClientCustomerId": CLIENT_CUSTOMER_ID,
                    "SchwabClientCorrelId": CLIENT_CORRELATION_ID,
                    "parameters": {
                        "keys": "GOOG,MSFT",
                        "fields": "0,1,2,3,4"
                    }
                }]
            })),
            call(StringMatchesJson({
                "requests": [{
                    "service": "TIMESALE_EQUITY",
                    "requestid": "2",
                    "command": "UNSUBS",
                    "SchwabClientCustomerId": CLIENT_CUSTOMER_ID,
                    "SchwabClientCorrelId": CLIENT_CORRELATION_ID,
                    "parameters": {
                        "keys": "GOOG,MSFT"
                    }
                }]
            }))
        ]
        socket.send.assert_has_awaits(send_awaited, any_order=False)

    @no_duplicates
    @patch('schwab.streaming.ws_client.connect', new_callable=AsyncMock)
    async def test_timesale_equity_subs_success_some_fields(self, ws_connect):
        socket = await self.login_and_get_socket(ws_connect)

        socket.recv.side_effect = [json.dumps(self.success_response(
            1, 'TIMESALE_EQUITY', 'SUBS'))]

        await self.client.timesale_equity_subs(['GOOG', 'MSFT'], fields=[
            StreamClient.TimesaleFields.FIELD_0,
            StreamClient.TimesaleFields.FIELD_1,
            StreamClient.TimesaleFields.FIELD_3,
        ])
        socket.recv.assert_awaited_once()
        request = self.request_from_socket_mock(socket)

        self.assertEqual(request, {
            'service': 'TIMESALE_EQUITY',
            'command': 'SUBS',
            'requestid': '1',
            "SchwabClientCustomerId": CLIENT_CUSTOMER_ID,
            "SchwabClientCorrelId": CLIENT_CORRELATION_ID,
            'parameters': {
                'keys': 'GOOG,MSFT',
                'fields': '0,1,3'
            }
        })

    @no_duplicates
    @patch('schwab.streaming.ws_client.connect', new_callable=AsyncMock)
    async def test_timesale_equity_subs_success_some_fields_no_symbol(
            self, ws_connect):
        socket = await self.login_and_get_socket(ws_connect)

        socket.recv.side_effect = [json.dumps(self.success_response(
            1, 'TIMESALE_EQUITY', 'SUBS'))]

        await self.client.timesale_equity_subs(['GOOG', 'MSFT'], fields=[
            StreamClient.TimesaleFields.FIELD_1,
            StreamClient.TimesaleFields.FIELD_3,
        ])
        socket.recv.assert_awaited_once()
        request = self.request_from_socket_mock(socket)

        self.assertEqual(request, {
            'service': 'TIMESALE_EQUITY',
            'command': 'SUBS',
            'requestid': '1',
            "SchwabClientCustomerId": CLIENT_CUSTOMER_ID,
            "SchwabClientCorrelId": CLIENT_CORRELATION_ID,
            'parameters': {
                'keys': 'GOOG,MSFT',
                'fields': '0,1,3'
            }
        })

    @no_duplicates
    @patch('schwab.streaming.ws_client.connect', new_callable=AsyncMock)
    async def test_timesale_equity_subs_failure(self, ws_connect):
        socket = await self.login_and_get_socket(ws_connect)

        response = self.success_response(1, 'TIMESALE_EQUITY', 'SUBS')
        response['response'][0]['content']['code'] = 21
        socket.recv.side_effect = [json.dumps(response)]

        with self.assertRaises(schwab.streaming.UnexpectedResponseCode):
            await self.client.timesale_equity_subs(['GOOG', 'MSFT'])

    @no_duplicates
    @patch('schwab.streaming.ws_client.connect', new_callable=AsyncMock)
    async def test_timesale_equity_unsubs_failure(self, ws_connect):
        socket = await self.login_and_get_socket(ws_connect)

        response = self.success_response(1, 'TIMESALE_EQUITY', 'UNSUBS')
        response['response'][0]['content']['code'] = 21
        socket.recv.side_effect = [json.dumps(response)]

        with self.assertRaises(schwab.streaming.UnexpectedResponseCode):
            await self.client.timesale_equity_unsubs(['GOOG', 'MSFT'])

    @no_duplicates
    @patch('schwab.streaming.ws_client.connect', new_callable=AsyncMock)
    async def test_timesale_equity_handler(self, ws_connect):
        socket = await self.login_and_get_socket(ws_connect)

        stream_item = {
            'data': [{
                'service': 'TIMESALE_EQUITY',
                'timestamp': 1590599684016,
                'command': 'SUBS',
                'content': [{
                    'seq': 43,
                    'key': 'MSFT',
                    '1': 1590599683785,
                    '2': 179.64,
                    '3': 100.0,
                    '4': 111626
                }, {
                    'seq': 0,
                    'key': 'GOOG',
                    '1': 1590599678467,
                    '2': 1406.91,
                    '3': 100.0,
                    '4': 8620
                }]
            }]
        }

        socket.recv.side_effect = [
            json.dumps(self.success_response(1, 'TIMESALE_EQUITY', 'SUBS')),
            json.dumps(stream_item)]
        await self.client.timesale_equity_subs(['GOOG', 'MSFT'])

        handler = Mock()
        async_handler = AsyncMock()
        self.client.add_timesale_equity_handler(handler)
        self.client.add_timesale_equity_handler(async_handler)
        await self.client.handle_message()

        expected_item = {
            'service': 'TIMESALE_EQUITY',
            'timestamp': 1590599684016,
            'command': 'SUBS',
            'content': [{
                'seq': 43,
                'key': 'MSFT',
                'FIELD_1': 1590599683785,
                'FIELD_2': 179.64,
                'FIELD_3': 100.0,
                'FIELD_4': 111626
            }, {
                'seq': 0,
                'key': 'GOOG',
                'FIELD_1': 1590599678467,
                'FIELD_2': 1406.91,
                'FIELD_3': 100.0,
                'FIELD_4': 8620
            }]
        }

        self.assert_handler_called_once_with(handler, expected_item)
        self.assert_handler_called_once_with(async_handler, expected_item)

    ##########################################################################
    # TIMESALE_FUTURES

    @no_duplicates
    @patch('schwab.streaming.ws_client.connect', new_callable=AsyncMock)
    async def test_timesale_futures_subs_success_all_fields(self, ws_connect):
        socket = await self.login_and_get_socket(ws_connect)

        socket.recv.side_effect = [json.dumps(self.success_response(
            1, 'TIMESALE_FUTURES', 'SUBS'))]

        await self.client.timesale_futures_subs(['/ES', '/CL'])
        socket.recv.assert_awaited_once()
        request = self.request_from_socket_mock(socket)

        self.assertEqual(request, {
            'service': 'TIMESALE_FUTURES',
            'command': 'SUBS',
            'requestid': '1',
            "SchwabClientCustomerId": CLIENT_CUSTOMER_ID,
            "SchwabClientCorrelId": CLIENT_CORRELATION_ID,
            'parameters': {
                'keys': '/ES,/CL',
                'fields': ('0,1,2,3,4')
            }
        })

    @no_duplicates
    @patch('schwab.streaming.ws_client.connect', new_callable=AsyncMock)
    async def test_timesale_futures_unsubs_success_all_fields(self, ws_connect):
        socket = await self.login_and_get_socket(ws_connect)

        stream_item = self.streaming_entry('TIMESALE_FUTURES', 'SUBS')

        socket.recv.side_effect = [
            json.dumps(self.success_response(1, 'TIMESALE_FUTURES', 'SUBS')),
            json.dumps(stream_item),
            json.dumps(self.success_response(2, 'TIMESALE_FUTURES', 'UNSUBS'))
        ]
        handler = Mock()
        async_handler = AsyncMock()
        self.client.add_timesale_futures_handler(handler)
        self.client.add_timesale_futures_handler(async_handler)

        await self.client.timesale_futures_subs(['/ES', '/CL'])
        await self.client.handle_message()
        await self.client.timesale_futures_unsubs(['/ES', '/CL'])

        self.assert_handler_called_once_with(
                handler, {'service': 'TIMESALE_FUTURES',
                          'command': 'SUBS',
                          'timestamp': REQUEST_TIMESTAMP})
        self.assert_handler_called_once_with(
                async_handler, {'service': 'TIMESALE_FUTURES',
                                'command': 'SUBS',
                                'timestamp': REQUEST_TIMESTAMP})
        send_awaited = [
            call(StringMatchesJson({
                "requests": [{
                    "service": "TIMESALE_FUTURES",
                    "requestid": "1",
                    "command": "SUBS",
                    "SchwabClientCustomerId": CLIENT_CUSTOMER_ID,
                    "SchwabClientCorrelId": CLIENT_CORRELATION_ID,
                    "parameters": {
                        "keys": "/ES,/CL",
                        "fields": "0,1,2,3,4"
                    }
                }]
            })),
            call(StringMatchesJson({
                "requests": [{
                    "service": "TIMESALE_FUTURES",
                    "requestid": "2",
                    "command": "UNSUBS",
                    "SchwabClientCustomerId": CLIENT_CUSTOMER_ID,
                    "SchwabClientCorrelId": CLIENT_CORRELATION_ID,
                    "parameters": {
                        "keys": "/ES,/CL"
                    }
                }]
            }))
        ]
        socket.send.assert_has_awaits(send_awaited, any_order=False)

    @no_duplicates
    @patch('schwab.streaming.ws_client.connect', new_callable=AsyncMock)
    async def test_timesale_futures_subs_success_some_fields(self, ws_connect):
        socket = await self.login_and_get_socket(ws_connect)

        socket.recv.side_effect = [json.dumps(self.success_response(
            1, 'TIMESALE_FUTURES', 'SUBS'))]

        await self.client.timesale_futures_subs(['/ES', '/CL'], fields=[
            StreamClient.TimesaleFields.FIELD_0,
            StreamClient.TimesaleFields.FIELD_1,
            StreamClient.TimesaleFields.FIELD_3,
        ])
        socket.recv.assert_awaited_once()
        request = self.request_from_socket_mock(socket)

        self.assertEqual(request, {
            'service': 'TIMESALE_FUTURES',
            'command': 'SUBS',
            'requestid': '1',
            "SchwabClientCustomerId": CLIENT_CUSTOMER_ID,
            "SchwabClientCorrelId": CLIENT_CORRELATION_ID,
            'parameters': {
                'keys': '/ES,/CL',
                'fields': '0,1,3'
            }
        })

    @no_duplicates
    @patch('schwab.streaming.ws_client.connect', new_callable=AsyncMock)
    async def test_timesale_futures_subs_success_some_fields_no_symbol(
            self, ws_connect):
        socket = await self.login_and_get_socket(ws_connect)

        socket.recv.side_effect = [json.dumps(self.success_response(
            1, 'TIMESALE_FUTURES', 'SUBS'))]

        await self.client.timesale_futures_subs(['/ES', '/CL'], fields=[
            StreamClient.TimesaleFields.FIELD_1,
            StreamClient.TimesaleFields.FIELD_3,
        ])
        socket.recv.assert_awaited_once()
        request = self.request_from_socket_mock(socket)

        self.assertEqual(request, {
            'service': 'TIMESALE_FUTURES',
            'command': 'SUBS',
            'requestid': '1',
            "SchwabClientCustomerId": CLIENT_CUSTOMER_ID,
            "SchwabClientCorrelId": CLIENT_CORRELATION_ID,
            'parameters': {
                'keys': '/ES,/CL',
                'fields': '0,1,3'
            }
        })

    @no_duplicates
    @patch('schwab.streaming.ws_client.connect', new_callable=AsyncMock)
    async def test_timesale_futures_subs_failure(self, ws_connect):
        socket = await self.login_and_get_socket(ws_connect)

        response = self.success_response(1, 'TIMESALE_FUTURES', 'SUBS')
        response['response'][0]['content']['code'] = 21
        socket.recv.side_effect = [json.dumps(response)]

        with self.assertRaises(schwab.streaming.UnexpectedResponseCode):
            await self.client.timesale_futures_subs(['/ES', '/CL'])

    @no_duplicates
    @patch('schwab.streaming.ws_client.connect', new_callable=AsyncMock)
    async def test_timesale_futures_unsubs_failure(self, ws_connect):
        socket = await self.login_and_get_socket(ws_connect)

        response = self.success_response(1, 'TIMESALE_FUTURES', 'UNSUBS')
        response['response'][0]['content']['code'] = 21
        socket.recv.side_effect = [json.dumps(response)]

        with self.assertRaises(schwab.streaming.UnexpectedResponseCode):
            await self.client.timesale_futures_unsubs(['/ES', '/CL'])

    @no_duplicates
    @patch('schwab.streaming.ws_client.connect', new_callable=AsyncMock)
    async def test_timesale_futures_handler(self, ws_connect):
        socket = await self.login_and_get_socket(ws_connect)

        stream_item = {
            'data': [{
                'service': 'TIMESALE_FUTURES',
                'timestamp': 1590600568685,
                'command': 'SUBS',
                'content': [{
                    'seq': 0,
                    'key': '/ES',
                    '1': 1590600568524,
                    '2': 2998.0,
                    '3': 1.0,
                    '4': 9236856
                }, {
                    'seq': 0,
                    'key': '/CL',
                    '1': 1590600568328,
                    '2': 33.08,
                    '3': 1.0,
                    '4': 68989244
                }]
            }]
        }

        socket.recv.side_effect = [
            json.dumps(self.success_response(1, 'TIMESALE_FUTURES', 'SUBS')),
            json.dumps(stream_item)]
        await self.client.timesale_futures_subs(['/ES', '/CL'])

        handler = Mock()
        async_handler = AsyncMock()
        self.client.add_timesale_futures_handler(handler)
        self.client.add_timesale_futures_handler(async_handler)
        await self.client.handle_message()

        expected_item = {
            'service': 'TIMESALE_FUTURES',
            'timestamp': 1590600568685,
            'command': 'SUBS',
            'content': [{
                'seq': 0,
                'key': '/ES',
                'FIELD_1': 1590600568524,
                'FIELD_2': 2998.0,
                'FIELD_3': 1.0,
                'FIELD_4': 9236856
            }, {
                'seq': 0,
                'key': '/CL',
                'FIELD_1': 1590600568328,
                'FIELD_2': 33.08,
                'FIELD_3': 1.0,
                'FIELD_4': 68989244
            }]
        }
        self.assert_handler_called_once_with(handler, expected_item)
        self.assert_handler_called_once_with(async_handler, expected_item)

    ##########################################################################
    # TIMESALE_OPTIONS

    @no_duplicates
    @patch('schwab.streaming.ws_client.connect', new_callable=AsyncMock)
    async def test_timesale_options_subs_success_all_fields(self, ws_connect):
        socket = await self.login_and_get_socket(ws_connect)

        socket.recv.side_effect = [json.dumps(self.success_response(
            1, 'TIMESALE_OPTIONS', 'SUBS'))]

        await self.client.timesale_options_subs(['/ES', '/CL'])
        socket.recv.assert_awaited_once()
        request = self.request_from_socket_mock(socket)

        self.assertEqual(request, {
            'service': 'TIMESALE_OPTIONS',
            'command': 'SUBS',
            'requestid': '1',
            "SchwabClientCustomerId": CLIENT_CUSTOMER_ID,
            "SchwabClientCorrelId": CLIENT_CORRELATION_ID,
            'parameters': {
                'keys': '/ES,/CL',
                'fields': ('0,1,2,3,4')
            }
        })

    @no_duplicates
    @patch('schwab.streaming.ws_client.connect', new_callable=AsyncMock)
    async def test_timesale_options_unsubs_success_all_fields(self, ws_connect):
        socket = await self.login_and_get_socket(ws_connect)

        stream_item = self.streaming_entry('TIMESALE_OPTIONS', 'SUBS')

        socket.recv.side_effect = [
            json.dumps(self.success_response(1, 'TIMESALE_OPTIONS', 'SUBS')),
            json.dumps(stream_item),
            json.dumps(self.success_response(2, 'TIMESALE_OPTIONS', 'UNSUBS'))
        ]
        handler = Mock()
        async_handler = AsyncMock()
        self.client.add_timesale_options_handler(handler)
        self.client.add_timesale_options_handler(async_handler)

        await self.client.timesale_options_subs(['GOOG_052920C620', 'MSFT_052920C145'])
        await self.client.handle_message()
        await self.client.timesale_options_unsubs(['GOOG_052920C620', 'MSFT_052920C145'])

        self.assert_handler_called_once_with(
                handler, {'service': 'TIMESALE_OPTIONS',
                          'command': 'SUBS',
                          'timestamp': REQUEST_TIMESTAMP})
        self.assert_handler_called_once_with(
                async_handler, {'service': 'TIMESALE_OPTIONS',
                                'command': 'SUBS',
                                'timestamp': REQUEST_TIMESTAMP})
        send_awaited = [
            call(StringMatchesJson({
                "requests": [{
                    "service": "TIMESALE_OPTIONS",
                    "requestid": "1",
                    "command": "SUBS",
                    "SchwabClientCustomerId": CLIENT_CUSTOMER_ID,
                    "SchwabClientCorrelId": CLIENT_CORRELATION_ID,
                    "parameters": {
                        "keys": "GOOG_052920C620,MSFT_052920C145",
                        "fields": "0,1,2,3,4"
                    }
                }]
            })),
            call(StringMatchesJson({
                "requests": [{
                    "service": "TIMESALE_OPTIONS",
                    "requestid": "2",
                    "command": "UNSUBS",
                    "SchwabClientCustomerId": CLIENT_CUSTOMER_ID,
                    "SchwabClientCorrelId": CLIENT_CORRELATION_ID,
                    "parameters": {
                        "keys": "GOOG_052920C620,MSFT_052920C145"
                    }
                }]
            })),
        ]
        socket.send.assert_has_awaits(send_awaited, any_order=False)

    @no_duplicates
    @patch('schwab.streaming.ws_client.connect', new_callable=AsyncMock)
    async def test_timesale_options_subs_success_some_fields(self, ws_connect):
        socket = await self.login_and_get_socket(ws_connect)

        socket.recv.side_effect = [json.dumps(self.success_response(
            1, 'TIMESALE_OPTIONS', 'SUBS'))]

        await self.client.timesale_options_subs(
            ['GOOG_052920C620', 'MSFT_052920C145'], fields=[
                StreamClient.TimesaleFields.FIELD_0,
                StreamClient.TimesaleFields.FIELD_1,
                StreamClient.TimesaleFields.FIELD_3,
            ])
        socket.recv.assert_awaited_once()
        request = self.request_from_socket_mock(socket)

        self.assertEqual(request, {
            'service': 'TIMESALE_OPTIONS',
            'command': 'SUBS',
            'requestid': '1',
            "SchwabClientCustomerId": CLIENT_CUSTOMER_ID,
            "SchwabClientCorrelId": CLIENT_CORRELATION_ID,
            'parameters': {
                'keys': 'GOOG_052920C620,MSFT_052920C145',
                'fields': '0,1,3'
            }
        })

    @no_duplicates
    @patch('schwab.streaming.ws_client.connect', new_callable=AsyncMock)
    async def test_timesale_options_subs_success_some_fields_no_symbol(self, ws_connect):
        socket = await self.login_and_get_socket(ws_connect)

        socket.recv.side_effect = [json.dumps(self.success_response(
            1, 'TIMESALE_OPTIONS', 'SUBS'))]

        await self.client.timesale_options_subs(
            ['GOOG_052920C620', 'MSFT_052920C145'], fields=[
                StreamClient.TimesaleFields.FIELD_1,
                StreamClient.TimesaleFields.FIELD_3,
            ])
        socket.recv.assert_awaited_once()
        request = self.request_from_socket_mock(socket)

        self.assertEqual(request, {
            'service': 'TIMESALE_OPTIONS',
            'command': 'SUBS',
            'requestid': '1',
            "SchwabClientCustomerId": CLIENT_CUSTOMER_ID,
            "SchwabClientCorrelId": CLIENT_CORRELATION_ID,
            'parameters': {
                'keys': 'GOOG_052920C620,MSFT_052920C145',
                'fields': '0,1,3'
            }
        })

    @no_duplicates
    @patch('schwab.streaming.ws_client.connect', new_callable=AsyncMock)
    async def test_timesale_options_subs_failure(self, ws_connect):
        socket = await self.login_and_get_socket(ws_connect)

        response = self.success_response(1, 'TIMESALE_OPTIONS', 'SUBS')
        response['response'][0]['content']['code'] = 21
        socket.recv.side_effect = [json.dumps(response)]

        with self.assertRaises(schwab.streaming.UnexpectedResponseCode):
            await self.client.timesale_options_subs(
                ['GOOG_052920C620', 'MSFT_052920C145'])

    @no_duplicates
    @patch('schwab.streaming.ws_client.connect', new_callable=AsyncMock)
    async def test_timesale_options_unsubs_failure(self, ws_connect):
        socket = await self.login_and_get_socket(ws_connect)

        response = self.success_response(1, 'TIMESALE_OPTIONS', 'UNSUBS')
        response['response'][0]['content']['code'] = 21
        socket.recv.side_effect = [json.dumps(response)]

        with self.assertRaises(schwab.streaming.UnexpectedResponseCode):
            await self.client.timesale_options_unsubs(
                ['GOOG_052920C620', 'MSFT_052920C145'])

    @no_duplicates
    # TODO: Replace this with real messages
    @patch('schwab.streaming.ws_client.connect', new_callable=AsyncMock)
    async def test_timesale_options_handler(self, ws_connect):
        socket = await self.login_and_get_socket(ws_connect)

        stream_item = {
            'data': [{
                'service': 'TIMESALE_OPTIONS',
                'timestamp': 1590245129396,
                'command': 'SUBS',
                'content': [{
                    'key': 'GOOG_052920C620',
                    'delayed': False,
                    '1': 1590181199726,
                    '2': 1000,
                    '3': 100,
                    '4': 9990
                }, {
                    'key': 'MSFT_052920C145',
                    'delayed': False,
                    '1': 1590181199727,
                    '2': 1100,
                    '3': 110,
                    '4': 9991
                }]
            }]
        }

        socket.recv.side_effect = [
            json.dumps(self.success_response(1, 'TIMESALE_OPTIONS', 'SUBS')),
            json.dumps(stream_item)]
        await self.client.timesale_options_subs(
            ['GOOG_052920C620', 'MSFT_052920C145'])

        handler = Mock()
        async_handler = AsyncMock()
        self.client.add_timesale_options_handler(handler)
        self.client.add_timesale_options_handler(async_handler)
        await self.client.handle_message()

        expected_item = {
            'service': 'TIMESALE_OPTIONS',
            'timestamp': 1590245129396,
            'command': 'SUBS',
            'content': [{
                'key': 'GOOG_052920C620',
                'delayed': False,
                'FIELD_1': 1590181199726,
                'FIELD_2': 1000,
                'FIELD_3': 100,
                'FIELD_4': 9990
            }, {
                'key': 'MSFT_052920C145',
                'delayed': False,
                'FIELD_1': 1590181199727,
                'FIELD_2': 1100,
                'FIELD_3': 110,
                'FIELD_4': 9991
            }]
        }

        self.assert_handler_called_once_with(handler, expected_item)
        self.assert_handler_called_once_with(async_handler, expected_item)


    ##########################################################################
    # LISTED_BOOK

    @no_duplicates
    @patch('schwab.streaming.ws_client.connect', new_callable=AsyncMock)
    async def test_listed_book_subs_success_all_fields(self, ws_connect):
        socket = await self.login_and_get_socket(ws_connect)

        socket.recv.side_effect = [json.dumps(self.success_response(
            1, 'LISTED_BOOK', 'SUBS'))]

        await self.client.listed_book_subs(['GOOG', 'MSFT'])
        socket.recv.assert_awaited_once()
        request = self.request_from_socket_mock(socket)

        self.assertEqual(request, {
            'service': 'LISTED_BOOK',
            'command': 'SUBS',
            'requestid': '1',
            "SchwabClientCustomerId": CLIENT_CUSTOMER_ID,
            "SchwabClientCorrelId": CLIENT_CORRELATION_ID,
            'parameters': {
                'keys': 'GOOG,MSFT',
                'fields': ('0,1,2,3')
            }
        })

    @no_duplicates
    @patch('schwab.streaming.ws_client.connect', new_callable=AsyncMock)
    async def test_listed_book_unsubs_success_all_fields(self, ws_connect):
        socket = await self.login_and_get_socket(ws_connect)

        stream_item = {'data': [{'service': 'LISTED_BOOK', 'command': 'SUBS', 'timestamp': REQUEST_TIMESTAMP, 'content': {}}]}

        socket.recv.side_effect = [
            json.dumps(self.success_response(1, 'LISTED_BOOK', 'SUBS')),
            json.dumps(stream_item),
            json.dumps(self.success_response(2, 'LISTED_BOOK', 'UNSUBS'))
        ]
        handler = Mock()
        async_handler = AsyncMock()
        self.client.add_listed_book_handler(handler)
        self.client.add_listed_book_handler(async_handler)

        await self.client.listed_book_subs(['GOOG', 'MSFT'])
        await self.client.handle_message()
        await self.client.listed_book_unsubs(['GOOG', 'MSFT'])

        self.assert_handler_called_once_with(
                handler, {'service': 'LISTED_BOOK',
                          'command': 'SUBS',
                          'timestamp': REQUEST_TIMESTAMP,
                          'content': {}})
        self.assert_handler_called_once_with(
                async_handler, {'service': 'LISTED_BOOK',
                                'command': 'SUBS',
                                'timestamp': REQUEST_TIMESTAMP,
                                'content': {}})
        send_awaited = [
            call(StringMatchesJson({
                "requests": [{
                    "service": "LISTED_BOOK",
                    "requestid": "1",
                    "command": "SUBS",
                    "SchwabClientCustomerId": CLIENT_CUSTOMER_ID,
                    "SchwabClientCorrelId": CLIENT_CORRELATION_ID,
                    "parameters": {
                        "keys": "GOOG,MSFT",
                        "fields": "0,1,2,3"
                    }
                }]
            })),
            call(StringMatchesJson({
                "requests": [{
                    "service": "LISTED_BOOK",
                    "requestid": "2",
                    "command": "UNSUBS",
                    "SchwabClientCustomerId": CLIENT_CUSTOMER_ID,
                    "SchwabClientCorrelId": CLIENT_CORRELATION_ID,
                    "parameters": {
                        "keys": "GOOG,MSFT"
                    }
                }]
            })),
        ]
        socket.send.assert_has_awaits(send_awaited, any_order=False)

    @no_duplicates
    @patch('schwab.streaming.ws_client.connect', new_callable=AsyncMock)
    async def test_listed_book_subs_failure(self, ws_connect):
        socket = await self.login_and_get_socket(ws_connect)

        response = self.success_response(1, 'LISTED_BOOK', 'SUBS')
        response['response'][0]['content']['code'] = 21
        socket.recv.side_effect = [json.dumps(response)]

        with self.assertRaises(schwab.streaming.UnexpectedResponseCode):
            await self.client.listed_book_subs(['GOOG', 'MSFT'])

    @no_duplicates
    @patch('schwab.streaming.ws_client.connect', new_callable=AsyncMock)
    async def test_listed_book_unsubs_failure(self, ws_connect):
        socket = await self.login_and_get_socket(ws_connect)

        response = self.success_response(1, 'LISTED_BOOK', 'UNSUBS')
        response['response'][0]['content']['code'] = 21
        socket.recv.side_effect = [json.dumps(response)]

        with self.assertRaises(schwab.streaming.UnexpectedResponseCode):
            await self.client.listed_book_unsubs(['GOOG', 'MSFT'])

    ##########################################################################
    # NASDAQ_BOOK

    @no_duplicates
    @patch('schwab.streaming.ws_client.connect', new_callable=AsyncMock)
    async def test_nasdaq_book_subs_success_all_fields(self, ws_connect):
        socket = await self.login_and_get_socket(ws_connect)

        socket.recv.side_effect = [json.dumps(self.success_response(
            1, 'NASDAQ_BOOK', 'SUBS'))]

        await self.client.nasdaq_book_subs(['GOOG', 'MSFT'])
        socket.recv.assert_awaited_once()
        request = self.request_from_socket_mock(socket)

        self.assertEqual(request, {
            'service': 'NASDAQ_BOOK',
            'command': 'SUBS',
            'requestid': '1',
            "SchwabClientCustomerId": CLIENT_CUSTOMER_ID,
            "SchwabClientCorrelId": CLIENT_CORRELATION_ID,
            'parameters': {
                'keys': 'GOOG,MSFT',
                'fields': ('0,1,2,3')
            }
        })

    @no_duplicates
    @patch('schwab.streaming.ws_client.connect', new_callable=AsyncMock)
    async def test_nasdaq_book_unsubs_success_all_fields(self, ws_connect):
        socket = await self.login_and_get_socket(ws_connect)

        stream_item = {"data": [{"service": "NASDAQ_BOOK", "command": "SUBS", "timestamp": REQUEST_TIMESTAMP, 'content': {}}]}

        socket.recv.side_effect = [
            json.dumps(self.success_response(1, 'NASDAQ_BOOK', 'SUBS')),
            json.dumps(stream_item),
            json.dumps(self.success_response(2, 'NASDAQ_BOOK', 'UNSUBS'))
        ]
        handler = Mock()
        async_handler = AsyncMock()
        self.client.add_nasdaq_book_handler(handler)
        self.client.add_nasdaq_book_handler(async_handler)

        await self.client.nasdaq_book_subs(['GOOG', 'MSFT'])
        await self.client.handle_message()
        await self.client.nasdaq_book_unsubs(['GOOG', 'MSFT'])

        self.assert_handler_called_once_with(
                handler, {"service": "NASDAQ_BOOK",
                          "command": "SUBS",
                          "timestamp": REQUEST_TIMESTAMP,
                          'content': {}})
        self.assert_handler_called_once_with(
                async_handler, {"service": "NASDAQ_BOOK",
                                "command": "SUBS",
                                "timestamp": REQUEST_TIMESTAMP,
                                'content': {}})
        send_awaited = [
            call(StringMatchesJson({
                "requests": [{
                    "service": "NASDAQ_BOOK",
                    "requestid": "1",
                    "command": "SUBS",
                    "SchwabClientCustomerId": CLIENT_CUSTOMER_ID,
                    "SchwabClientCorrelId": CLIENT_CORRELATION_ID,
                    "parameters": {
                        "keys": "GOOG,MSFT",
                        "fields": "0,1,2,3"
                    }
                }]
            })),
            call(StringMatchesJson({
                "requests": [{
                    "service": "NASDAQ_BOOK",
                    "requestid": "2",
                    "command": "UNSUBS",
                    "SchwabClientCustomerId": CLIENT_CUSTOMER_ID,
                    "SchwabClientCorrelId": CLIENT_CORRELATION_ID,
                    "parameters": {
                        "keys": "GOOG,MSFT"
                    }
                }]
            })),
        ]
        socket.send.assert_has_awaits(send_awaited, any_order=False)

    @no_duplicates
    @patch('schwab.streaming.ws_client.connect', new_callable=AsyncMock)
    async def test_nasdaq_book_subs_failure(self, ws_connect):
        socket = await self.login_and_get_socket(ws_connect)

        response = self.success_response(1, 'NASDAQ_BOOK', 'SUBS')
        response['response'][0]['content']['code'] = 21
        socket.recv.side_effect = [json.dumps(response)]

        with self.assertRaises(schwab.streaming.UnexpectedResponseCode):
            await self.client.nasdaq_book_subs(['GOOG', 'MSFT'])

    @no_duplicates
    @patch('schwab.streaming.ws_client.connect', new_callable=AsyncMock)
    async def test_nasdaq_book_unsubs_failure(self, ws_connect):
        socket = await self.login_and_get_socket(ws_connect)

        response = self.success_response(1, 'NASDAQ_BOOK', 'UNSUBS')
        response['response'][0]['content']['code'] = 21
        socket.recv.side_effect = [json.dumps(response)]

        with self.assertRaises(schwab.streaming.UnexpectedResponseCode):
            await self.client.nasdaq_book_unsubs(['GOOG', 'MSFT'])

    ##########################################################################
    # OPTIONS_BOOK

    @no_duplicates
    @patch('schwab.streaming.ws_client.connect', new_callable=AsyncMock)
    async def test_options_book_subs_success_all_fields(self, ws_connect):
        socket = await self.login_and_get_socket(ws_connect)

        socket.recv.side_effect = [json.dumps(self.success_response(
            1, 'OPTIONS_BOOK', 'SUBS'))]

        await self.client.options_book_subs(
            ['GOOG_052920C620', 'MSFT_052920C145'])
        socket.recv.assert_awaited_once()
        request = self.request_from_socket_mock(socket)

        self.assertEqual(request, {
            'service': 'OPTIONS_BOOK',
            'command': 'SUBS',
            'requestid': '1',
            "SchwabClientCustomerId": CLIENT_CUSTOMER_ID,
            "SchwabClientCorrelId": CLIENT_CORRELATION_ID,
            'parameters': {
                'keys': 'GOOG_052920C620,MSFT_052920C145',
                'fields': ('0,1,2,3')
            }
        })

    @no_duplicates
    @patch('schwab.streaming.ws_client.connect', new_callable=AsyncMock)
    async def test_options_book_unsubs_success_all_fields(self, ws_connect):
        socket = await self.login_and_get_socket(ws_connect)

        stream_item = {"data": [{"service": "OPTIONS_BOOK", "command": "SUBS", "timestamp": REQUEST_TIMESTAMP, 'content': {}}]}

        socket.recv.side_effect = [
            json.dumps(self.success_response(1, 'OPTIONS_BOOK', 'SUBS')),
            json.dumps(stream_item),
            json.dumps(self.success_response(2, 'OPTIONS_BOOK', 'UNSUBS'))
        ]
        handler = Mock()
        async_handler = AsyncMock()
        self.client.add_options_book_handler(handler)
        self.client.add_options_book_handler(async_handler)

        await self.client.options_book_subs(
            ['GOOG_052920C620', 'MSFT_052920C145'])
        await self.client.handle_message()
        await self.client.options_book_unsubs(
            ['GOOG_052920C620', 'MSFT_052920C145'])

        self.assert_handler_called_once_with(
                handler, {"service": "OPTIONS_BOOK",
                          "command": "SUBS",
                          "timestamp": REQUEST_TIMESTAMP,
                          'content': {}})
        self.assert_handler_called_once_with(
                async_handler, {"service": "OPTIONS_BOOK",
                                "command": "SUBS",
                                "timestamp": REQUEST_TIMESTAMP,
                                'content': {}})
        send_awaited = [
            call(StringMatchesJson({
                "requests": [{
                    "service": "OPTIONS_BOOK",
                    "requestid": "1",
                    "command": "SUBS",
                    "SchwabClientCustomerId": CLIENT_CUSTOMER_ID,
                    "SchwabClientCorrelId": CLIENT_CORRELATION_ID,
                    "parameters": {
                        "keys": "GOOG_052920C620,MSFT_052920C145",
                        "fields": "0,1,2,3"
                    }
                }]
            })),
            call(StringMatchesJson({
                "requests": [{
                    "service": "OPTIONS_BOOK",
                    "requestid": "2",
                    "command": "UNSUBS",
                    "SchwabClientCustomerId": CLIENT_CUSTOMER_ID,
                    "SchwabClientCorrelId": CLIENT_CORRELATION_ID,
                    "parameters": {
                        "keys": "GOOG_052920C620,MSFT_052920C145"
                    }
                }]
            })),
        ]
        socket.send.assert_has_awaits(send_awaited, any_order=False)

    @no_duplicates
    @patch('schwab.streaming.ws_client.connect', new_callable=AsyncMock)
    async def test_options_book_subs_failure(self, ws_connect):
        socket = await self.login_and_get_socket(ws_connect)

        response = self.success_response(1, 'OPTIONS_BOOK', 'SUBS')
        response['response'][0]['content']['code'] = 21
        socket.recv.side_effect = [json.dumps(response)]

        with self.assertRaises(schwab.streaming.UnexpectedResponseCode):
            await self.client.options_book_subs(
                ['GOOG_052920C620', 'MSFT_052920C145'])

    @no_duplicates
    @patch('schwab.streaming.ws_client.connect', new_callable=AsyncMock)
    async def test_options_book_unsubs_failure(self, ws_connect):
        socket = await self.login_and_get_socket(ws_connect)

        response = self.success_response(1, 'OPTIONS_BOOK', 'UNSUBS')
        response['response'][0]['content']['code'] = 21
        socket.recv.side_effect = [json.dumps(response)]

        with self.assertRaises(schwab.streaming.UnexpectedResponseCode):
            await self.client.options_book_unsubs(
                ['GOOG_052920C620', 'MSFT_052920C145'])

    ##########################################################################
    # Common book handler functionality

    @no_duplicates
    @patch('schwab.streaming.ws_client.connect', new_callable=AsyncMock)
    async def test_listed_book_handler(self, ws_connect):
        async def subs():
            await self.client.listed_book_subs(['GOOG', 'MSFT'])

        def register_handler():
            handler = Mock()
            async_handler = AsyncMock()
            self.client.add_listed_book_handler(handler)
            self.client.add_listed_book_handler(async_handler)
            return handler, async_handler

        return await self.__test_book_handler(
            ws_connect, 'LISTED_BOOK', subs, register_handler)

    @no_duplicates
    @patch('schwab.streaming.ws_client.connect', new_callable=AsyncMock)
    async def test_nasdaq_book_handler(self, ws_connect):
        async def subs():
            await self.client.nasdaq_book_subs(['GOOG', 'MSFT'])

        def register_handler():
            handler = Mock()
            async_handler = AsyncMock()
            self.client.add_nasdaq_book_handler(handler)
            self.client.add_nasdaq_book_handler(async_handler)
            return handler, async_handler

        return await self.__test_book_handler(
            ws_connect, 'NASDAQ_BOOK', subs, register_handler)

    @no_duplicates
    @patch('schwab.streaming.ws_client.connect', new_callable=AsyncMock)
    async def test_options_book_handler(self, ws_connect):
        async def subs():
            await self.client.options_book_subs(['GOOG', 'MSFT'])

        def register_handler():
            handler = Mock()
            async_handler = AsyncMock()
            self.client.add_options_book_handler(handler)
            self.client.add_options_book_handler(async_handler)
            return handler, async_handler

        return await self.__test_book_handler(
            ws_connect, 'OPTIONS_BOOK', subs, register_handler)

    @no_duplicates
    async def __test_book_handler(
            self, ws_connect, service, subs, register_handler):
        socket = await self.login_and_get_socket(ws_connect)

        stream_item = {
            'data': [
                {
                    'service': service,
                    'timestamp': 1590532470149,
                    'command': 'SUBS',
                    'content': [
                        {
                            'key': 'MSFT',
                            '1': 1590532442608,
                            '2': [
                                {
                                    '0': 181.77,
                                    '1': 100,
                                    '2': 1,
                                    '3': [
                                        {
                                            '0': 'edgx',
                                            '1': 100,
                                            '2': 63150257
                                        }
                                    ]
                                },
                                {
                                    '0': 181.75,
                                    '1': 545,
                                    '2': 2,
                                    '3': [
                                        {
                                            '0': 'NSDQ',
                                            '1': 345,
                                            '2': 62685730
                                        },
                                        {
                                            '0': 'arcx',
                                            '1': 200,
                                            '2': 63242588
                                        }
                                    ]
                                },
                                {
                                    '0': 157.0,
                                    '1': 100,
                                    '2': 1,
                                    '3': [
                                        {
                                            '0': 'batx',
                                            '1': 100,
                                            '2': 63082708
                                        }
                                    ]
                                }
                            ],
                            '3': [
                                {
                                    '0': 181.95,
                                    '1': 100,
                                    '2': 1,
                                    '3': [
                                        {
                                            '0': 'arcx',
                                            '1': 100,
                                            '2': 63006734
                                        }
                                    ]
                                },
                                {
                                    '0': 181.98,
                                    '1': 48,
                                    '2': 1,
                                    '3': [
                                        {
                                            '0': 'NSDQ',
                                            '1': 48,
                                            '2': 62327464
                                        }
                                    ]
                                },
                                {
                                    '0': 182.3,
                                    '1': 100,
                                    '2': 1,
                                    '3': [
                                        {
                                            '0': 'edgx',
                                            '1': 100,
                                            '2': 63192542
                                        }
                                    ]
                                },
                                {
                                    '0': 186.8,
                                    '1': 700,
                                    '2': 1,
                                    '3': [
                                        {
                                            '0': 'batx',
                                            '1': 700,
                                            '2': 60412822
                                        }
                                    ]
                                }
                            ]
                        },
                        {
                            'key': 'GOOG',
                            '1': 1590532323728,
                            '2': [
                                {
                                    '0': 1418.0,
                                    '1': 1,
                                    '2': 1,
                                    '3': [
                                        {
                                            '0': 'NSDQ',
                                            '1': 1,
                                            '2': 54335011
                                        }
                                    ]
                                },
                                {
                                    '0': 1417.26,
                                    '1': 100,
                                    '2': 1,
                                    '3': [
                                        {
                                            '0': 'batx',
                                            '1': 100,
                                            '2': 62782324
                                        }
                                    ]
                                },
                                {
                                    '0': 1417.25,
                                    '1': 100,
                                    '2': 1,
                                    '3': [
                                        {
                                            '0': 'arcx',
                                            '1': 100,
                                            '2': 62767878
                                        }
                                    ]
                                },
                                {
                                    '0': 1400.88,
                                    '1': 100,
                                    '2': 1,
                                    '3': [
                                        {
                                            '0': 'edgx',
                                            '1': 100,
                                            '2': 54000952
                                        }
                                    ]
                                }
                            ],
                            '3': [
                                {
                                    '0': 1421.0,
                                    '1': 300,
                                    '2': 2,
                                    '3': [
                                        {
                                            '0': 'edgx',
                                            '1': 200,
                                            '2': 56723908
                                        },
                                        {
                                            '0': 'arcx',
                                            '1': 100,
                                            '2': 62709059
                                        }
                                    ]
                                },
                                {
                                    '0': 1421.73,
                                    '1': 10,
                                    '2': 1,
                                    '3': [
                                        {
                                            '0': 'NSDQ',
                                            '1': 10,
                                            '2': 62737731
                                        }
                                    ]
                                }
                            ]
                        }
                    ]
                }
            ]
        }

        socket.recv.side_effect = [
            json.dumps(self.success_response(1, service, 'SUBS')),
            json.dumps(stream_item)]
        await subs()

        handler, async_handler = register_handler()
        await self.client.handle_message()

        expected_item = {
            'service': service,
            'timestamp': 1590532470149,
            'command': 'SUBS',
            'content': [
                        {
                            'key': 'MSFT',
                            'BOOK_TIME': 1590532442608,
                            'BIDS': [
                                {
                                    'BID_PRICE': 181.77,
                                    'TOTAL_VOLUME': 100,
                                    'NUM_BIDS': 1,
                                    'BIDS': [
                                        {
                                            'EXCHANGE': 'edgx',
                                            'BID_VOLUME': 100,
                                            'SEQUENCE': 63150257
                                        }
                                    ]
                                },
                                {
                                    'BID_PRICE': 181.75,
                                    'TOTAL_VOLUME': 545,
                                    'NUM_BIDS': 2,
                                    'BIDS': [
                                        {
                                            'EXCHANGE': 'NSDQ',
                                            'BID_VOLUME': 345,
                                            'SEQUENCE': 62685730
                                        },
                                        {
                                            'EXCHANGE': 'arcx',
                                            'BID_VOLUME': 200,
                                            'SEQUENCE': 63242588
                                        }
                                    ]
                                },
                                {
                                    'BID_PRICE': 157.0,
                                    'TOTAL_VOLUME': 100,
                                    'NUM_BIDS': 1,
                                    'BIDS': [
                                        {
                                            'EXCHANGE': 'batx',
                                            'BID_VOLUME': 100,
                                            'SEQUENCE': 63082708
                                        }
                                    ]
                                }
                            ],
                            'ASKS': [
                                {
                                    'ASK_PRICE': 181.95,
                                    'TOTAL_VOLUME': 100,
                                    'NUM_ASKS': 1,
                                    'ASKS': [
                                        {
                                            'EXCHANGE': 'arcx',
                                            'ASK_VOLUME': 100,
                                            'SEQUENCE': 63006734
                                        }
                                    ]
                                },
                                {
                                    'ASK_PRICE': 181.98,
                                    'TOTAL_VOLUME': 48,
                                    'NUM_ASKS': 1,
                                    'ASKS': [
                                        {
                                            'EXCHANGE': 'NSDQ',
                                            'ASK_VOLUME': 48,
                                            'SEQUENCE': 62327464
                                        }
                                    ]
                                },
                                {
                                    'ASK_PRICE': 182.3,
                                    'TOTAL_VOLUME': 100,
                                    'NUM_ASKS': 1,
                                    'ASKS': [
                                        {
                                            'EXCHANGE': 'edgx',
                                            'ASK_VOLUME': 100,
                                            'SEQUENCE': 63192542
                                        }
                                    ]
                                },
                                {
                                    'ASK_PRICE': 186.8,
                                    'TOTAL_VOLUME': 700,
                                    'NUM_ASKS': 1,
                                    'ASKS': [
                                        {
                                            'EXCHANGE': 'batx',
                                            'ASK_VOLUME': 700,
                                            'SEQUENCE': 60412822
                                        }
                                    ]
                                }
                            ]
                        },
                {
                            'key': 'GOOG',
                            'BOOK_TIME': 1590532323728,
                            'BIDS': [
                                {
                                    'BID_PRICE': 1418.0,
                                    'TOTAL_VOLUME': 1,
                                    'NUM_BIDS': 1,
                                    'BIDS': [
                                        {
                                            'EXCHANGE': 'NSDQ',
                                            'BID_VOLUME': 1,
                                            'SEQUENCE': 54335011
                                        }
                                    ]
                                },
                                {
                                    'BID_PRICE': 1417.26,
                                    'TOTAL_VOLUME': 100,
                                    'NUM_BIDS': 1,
                                    'BIDS': [
                                        {
                                            'EXCHANGE': 'batx',
                                            'BID_VOLUME': 100,
                                            'SEQUENCE': 62782324
                                        }
                                    ]
                                },
                                {
                                    'BID_PRICE': 1417.25,
                                    'TOTAL_VOLUME': 100,
                                    'NUM_BIDS': 1,
                                    'BIDS': [
                                        {
                                            'EXCHANGE': 'arcx',
                                            'BID_VOLUME': 100,
                                            'SEQUENCE': 62767878
                                        }
                                    ]
                                },
                                {
                                    'BID_PRICE': 1400.88,
                                    'TOTAL_VOLUME': 100,
                                    'NUM_BIDS': 1,
                                    'BIDS': [
                                        {
                                            'EXCHANGE': 'edgx',
                                            'BID_VOLUME': 100,
                                            'SEQUENCE': 54000952
                                        }
                                    ]
                                }
                            ],
                            'ASKS': [
                                {
                                    'ASK_PRICE': 1421.0,
                                    'TOTAL_VOLUME': 300,
                                    'NUM_ASKS': 2,
                                    'ASKS': [
                                        {
                                            'EXCHANGE': 'edgx',
                                            'ASK_VOLUME': 200,
                                            'SEQUENCE': 56723908
                                        },
                                        {
                                            'EXCHANGE': 'arcx',
                                            'ASK_VOLUME': 100,
                                            'SEQUENCE': 62709059
                                        }
                                    ]
                                },
                                {
                                    'ASK_PRICE': 1421.73,
                                    'TOTAL_VOLUME': 10,
                                    'NUM_ASKS': 1,
                                    'ASKS': [
                                        {
                                            'EXCHANGE': 'NSDQ',
                                            'ASK_VOLUME': 10,
                                            'SEQUENCE': 62737731
                                        }
                                    ]
                                }
                            ]
                        }
            ]
        }

        self.assert_handler_called_once_with(handler, expected_item)
        self.assert_handler_called_once_with(async_handler, expected_item)

    ##########################################################################
    # NEWS_HEADLINE

    @no_duplicates
    @patch('schwab.streaming.ws_client.connect', new_callable=AsyncMock)
    async def test_news_headline_subs_success(self, ws_connect):
        socket = await self.login_and_get_socket(ws_connect)

        socket.recv.side_effect = [json.dumps(self.success_response(
            1, 'NEWS_HEADLINE', 'SUBS'))]

        await self.client.news_headline_subs(['GOOG', 'MSFT'])
        socket.recv.assert_awaited_once()
        request = self.request_from_socket_mock(socket)

        self.assertEqual(request, {
            'service': 'NEWS_HEADLINE',
            'command': 'SUBS',
            'requestid': '1',
            "SchwabClientCustomerId": CLIENT_CUSTOMER_ID,
            "SchwabClientCorrelId": CLIENT_CORRELATION_ID,
            'parameters': {
                'keys': 'GOOG,MSFT',
                'fields': ('0,1,2,3,4,5,6,7,8,9,10')
            }
        })

    @no_duplicates
    @patch('schwab.streaming.ws_client.connect', new_callable=AsyncMock)
    async def test_news_headline_unsubs_success(self, ws_connect):
        socket = await self.login_and_get_socket(ws_connect)

        stream_item = {"data": [{"service": "NEWS_HEADLINE", "command": "SUBS", "timestamp": REQUEST_TIMESTAMP, 'content': {}}]}

        socket.recv.side_effect = [
            json.dumps(self.success_response(1, 'NEWS_HEADLINE', 'SUBS')),
            json.dumps(stream_item),
            json.dumps(self.success_response(2, 'NEWS_HEADLINE', 'UNSUBS'))
        ]
        handler = Mock()
        async_handler = AsyncMock()
        self.client.add_news_headline_handler(handler)
        self.client.add_news_headline_handler(async_handler)

        await self.client.news_headline_subs(['GOOG', 'MSFT'])
        await self.client.handle_message()
        await self.client.news_headline_unsubs(['GOOG', 'MSFT'])

        self.assert_handler_called_once_with(
                handler, {"service": "NEWS_HEADLINE",
                          "command": "SUBS",
                          "timestamp": REQUEST_TIMESTAMP,
                          'content': {}})
        self.assert_handler_called_once_with(
                async_handler, {"service": "NEWS_HEADLINE",
                                "command": "SUBS",
                                "timestamp": REQUEST_TIMESTAMP,
                                'content': {}})
        send_awaited = [
            call(StringMatchesJson({
                "requests": [{
                    "service": "NEWS_HEADLINE",
                    "requestid": "1",
                    "command": "SUBS",
                    "SchwabClientCustomerId": CLIENT_CUSTOMER_ID,
                    "SchwabClientCorrelId": CLIENT_CORRELATION_ID,
                    "parameters": {
                        "keys": "GOOG,MSFT",
                        "fields": "0,1,2,3,4,5,6,7,8,9,10"
                    }
                }]
            })),
            call(StringMatchesJson({
                "requests": [{
                    "service": "NEWS_HEADLINE",
                    "requestid": "2",
                    "command": "UNSUBS",
                    "SchwabClientCustomerId": CLIENT_CUSTOMER_ID,
                    "SchwabClientCorrelId": CLIENT_CORRELATION_ID,
                    "parameters": {
                        "keys": "GOOG,MSFT"
                    }
                }]
            })),
        ]
        socket.send.assert_has_awaits(send_awaited, any_order=False)

    @no_duplicates
    @patch('schwab.streaming.ws_client.connect', new_callable=AsyncMock)
    async def test_news_headline_subs_failure(self, ws_connect):
        socket = await self.login_and_get_socket(ws_connect)

        response = self.success_response(1, 'NEWS_HEADLINE', 'SUBS')
        response['response'][0]['content']['code'] = 21
        socket.recv.side_effect = [json.dumps(response)]

        with self.assertRaises(schwab.streaming.UnexpectedResponseCode):
            await self.client.news_headline_subs(['GOOG', 'MSFT'])

    @no_duplicates
    @patch('schwab.streaming.ws_client.connect', new_callable=AsyncMock)
    async def test_news_headline_unsubs_failure(self, ws_connect):
        socket = await self.login_and_get_socket(ws_connect)

        response = self.success_response(1, 'NEWS_HEADLINE', 'UNSUBS')
        response['response'][0]['content']['code'] = 21
        socket.recv.side_effect = [json.dumps(response)]

        with self.assertRaises(schwab.streaming.UnexpectedResponseCode):
            await self.client.news_headline_unsubs(['GOOG', 'MSFT'])

    @no_duplicates
    # TODO: Replace this with real messages.
    @patch('schwab.streaming.ws_client.connect', new_callable=AsyncMock)
    async def test_news_headline_handler(self, ws_connect):
        socket = await self.login_and_get_socket(ws_connect)

        stream_item = {
            'data': [{
                'service': 'NEWS_HEADLINE',
                'timestamp': 1590245129396,
                'command': 'SUBS',
                'content': [{
                    'key': 'GOOG',
                    'delayed': False,
                    '1': 0,
                    '2': 1590181199727,
                    '3': '0S21111333342',
                    '4': 'Active',
                    '5': 'Google Does Something',
                    '6': '0S1113435443',
                    '7': '1',
                    '8': 'GOOG',
                    '9': False,
                    '10': 'Bloomberg',
                }, {
                    'key': 'MSFT',
                    'delayed': False,
                    '1': 0,
                    '2': 1590181199728,
                    '3': '0S21111333343',
                    '4': 'Active',
                    '5': 'Microsoft Does Something',
                    '6': '0S1113435444',
                    '7': '2',
                    '8': 'MSFT',
                    '9': False,
                    '10': 'WSJ',
                }]
            }]
        }

        socket.recv.side_effect = [
            json.dumps(self.success_response(1, 'NEWS_HEADLINE', 'SUBS')),
            json.dumps(stream_item)]
        await self.client.news_headline_subs(['GOOG', 'MSFT'])

        handler = Mock()
        async_handler = AsyncMock()
        self.client.add_news_headline_handler(handler)
        self.client.add_news_headline_handler(async_handler)
        await self.client.handle_message()

        expected_item = {
            'service': 'NEWS_HEADLINE',
            'timestamp': 1590245129396,
            'command': 'SUBS',
            'content': [{
                'key': 'GOOG',
                'delayed': False,
                'ERROR_CODE': 0,
                'STORY_DATETIME': 1590181199727,
                'HEADLINE_ID': '0S21111333342',
                'STATUS': 'Active',
                'HEADLINE': 'Google Does Something',
                'STORY_ID': '0S1113435443',
                'COUNT_FOR_KEYWORD': '1',
                'KEYWORD_ARRAY': 'GOOG',
                'IS_HOT': False,
                'STORY_SOURCE': 'Bloomberg',
            }, {
                'key': 'MSFT',
                'delayed': False,
                'ERROR_CODE': 0,
                'STORY_DATETIME': 1590181199728,
                'HEADLINE_ID': '0S21111333343',
                'STATUS': 'Active',
                'HEADLINE': 'Microsoft Does Something',
                'STORY_ID': '0S1113435444',
                'COUNT_FOR_KEYWORD': '2',
                'KEYWORD_ARRAY': 'MSFT',
                'IS_HOT': False,
                'STORY_SOURCE': 'WSJ',
            }]
        }

        self.assert_handler_called_once_with(handler, expected_item)
        self.assert_handler_called_once_with(async_handler, expected_item)

    @no_duplicates
    @patch('schwab.streaming.ws_client.connect', new_callable=AsyncMock)
    async def test_news_headline_not_authorized_notification(self, ws_connect):
        socket = await self.login_and_get_socket(ws_connect)

        stream_item = {
            "notify": [
                {
                    "service": "NEWS_HEADLINE",
                    "timestamp": 1591500923797,
                    "content": {
                        "code": 17,
                        "msg": "Not authorized for all quotes."
                    }
                }
            ]
        }

        socket.recv.side_effect = [
            json.dumps(self.success_response(1, 'NEWS_HEADLINE', 'SUBS')),
            json.dumps(stream_item)]
        await self.client.news_headline_subs(['GOOG', 'MSFT'])

        handler = Mock()
        async_handler = AsyncMock()
        self.client.add_news_headline_handler(handler)
        self.client.add_news_headline_handler(async_handler)
        await self.client.handle_message()

        expected_item = {
            "service": "NEWS_HEADLINE",
            "timestamp": 1591500923797,
            "content": {
                "code": 17,
                "msg": "Not authorized for all quotes."
            }
        }

        self.assert_handler_called_once_with(handler, expected_item)
        self.assert_handler_called_once_with(async_handler, expected_item)

    ###########################################################################
    # Handler edge cases
    #
    # Note: We use CHART_EQUITY as a test case, which leaks the implementation
    # detail that the handler dispatching is implemented by a common component.
    # If this were to ever change, these tests will have to be revisited.

    @no_duplicates
    @patch('schwab.streaming.ws_client.connect', new_callable=AsyncMock)
    async def test_messages_received_while_awaiting_response(self, ws_connect):
        socket = await self.login_and_get_socket(ws_connect)

        stream_item = self.streaming_entry('CHART_EQUITY', 'SUBS')

        socket.recv.side_effect = [
            json.dumps(self.success_response(1, 'CHART_EQUITY', 'SUBS')),
            json.dumps(stream_item),
            json.dumps(self.success_response(2, 'CHART_EQUITY', 'ADD'))]

        await self.client.chart_equity_subs(['GOOG,MSFT'])
        await self.client.chart_equity_add(['INTC'])

        handler = Mock()
        async_handler = AsyncMock()
        self.client.add_chart_equity_handler(handler)
        self.client.add_chart_equity_handler(async_handler)
        await self.client.handle_message()
        handler.assert_called_once_with(stream_item['data'][0])
        async_handler.assert_called_once_with(stream_item['data'][0])

    @no_duplicates
    @patch('schwab.streaming.ws_client.connect', new_callable=AsyncMock)
    async def test_messages_received_while_awaiting_failed_response_bad_code(
            self, ws_connect):
        socket = await self.login_and_get_socket(ws_connect)

        stream_item = self.streaming_entry('CHART_EQUITY', 'SUBS')

        failed_add_response = self.success_response(2, 'CHART_EQUITY', 'ADD')
        failed_add_response['response'][0]['content']['code'] = 21

        socket.recv.side_effect = [
            json.dumps(self.success_response(1, 'CHART_EQUITY', 'SUBS')),
            json.dumps(stream_item),
            json.dumps(failed_add_response)]

        await self.client.chart_equity_subs(['GOOG,MSFT'])
        with self.assertRaises(schwab.streaming.UnexpectedResponseCode):
            await self.client.chart_equity_add(['INTC'])

        handler = Mock()
        async_handler = AsyncMock()
        self.client.add_chart_equity_handler(handler)
        self.client.add_chart_equity_handler(async_handler)
        await self.client.handle_message()
        handler.assert_called_once_with(stream_item['data'][0])
        async_handler.assert_called_once_with(stream_item['data'][0])

    @no_duplicates
    @patch('schwab.streaming.ws_client.connect', new_callable=AsyncMock)
    async def test_messages_received_while_receiving_unexpected_response(
            self, ws_connect):
        socket = await self.login_and_get_socket(ws_connect)

        stream_item = self.streaming_entry('CHART_EQUITY', 'SUBS')

        failed_add_response = self.success_response(999, 'CHART_EQUITY', 'ADD')
        failed_add_response['response'][0]['content']['code'] = 21

        socket.recv.side_effect = [
            json.dumps(self.success_response(1, 'CHART_EQUITY', 'SUBS')),
            json.dumps(stream_item),
            json.dumps(failed_add_response)]

        await self.client.chart_equity_subs(['GOOG,MSFT'])
        with self.assertRaises(schwab.streaming.UnexpectedResponse):
            await self.client.chart_equity_add(['INTC'])

        handler = Mock()
        async_handler = AsyncMock()
        self.client.add_chart_equity_handler(handler)
        self.client.add_chart_equity_handler(async_handler)
        await self.client.handle_message()
        handler.assert_called_once_with(stream_item['data'][0])
        async_handler.assert_called_once_with(stream_item['data'][0])

    @no_duplicates
    @patch('schwab.streaming.ws_client.connect', new_callable=AsyncMock)
    async def test_notify_heartbeat_messages_ignored(self, ws_connect):
        socket = await self.login_and_get_socket(ws_connect)

        socket.recv.side_effect = [
            json.dumps(self.success_response(1, 'CHART_EQUITY', 'SUBS')),
            json.dumps({'notify': [{'heartbeat': '1591499624412'}]})]

        await self.client.chart_equity_subs(['GOOG,MSFT'])

        handler = Mock()
        async_handler = AsyncMock()
        self.client.add_chart_equity_handler(handler)
        self.client.add_chart_equity_handler(async_handler)
        await self.client.handle_message()
        handler.assert_not_called()
        async_handler.assert_not_called()

    @no_duplicates
    @patch('schwab.streaming.ws_client.connect', new_callable=AsyncMock)
    async def test_handle_message_unexpected_response(self, ws_connect):
        socket = await self.login_and_get_socket(ws_connect)

        socket.recv.side_effect = [
            json.dumps(self.success_response(1, 'CHART_EQUITY', 'SUBS')),
            json.dumps(self.success_response(2, 'CHART_EQUITY', 'SUBS'))]

        await self.client.chart_equity_subs(['GOOG,MSFT'])

        with self.assertRaises(schwab.streaming.UnexpectedResponse):
            await self.client.handle_message()

    @no_duplicates
    @patch('schwab.streaming.ws_client.connect', new_callable=AsyncMock)
    async def test_handle_message_unparsable_message(self, ws_connect):
        socket = await self.login_and_get_socket(ws_connect)

        socket.recv.side_effect = [
            json.dumps(self.success_response(1, 'CHART_EQUITY', 'SUBS')),
            '{"data":[{"service":"LEVELONE_FUTURES", ' +
            '"timestamp":1590248118165,"command":"SUBS",' +
            '"content":[{"key":"/GOOG","delayed":false,' +
            '"1":�,"2":�,"3":�,"6":"?","7":"?","12":�,"13":�,' +
            '"14":�,"15":"?","16":"Symbol not found","17":"?",' +
            '"18":�,"21":"unavailable","22":"Unknown","24":�,'
            '"28":"D,D","33":�}]}]}']

        await self.client.chart_equity_subs(['GOOG,MSFT'])

        with self.assertRaises(schwab.streaming.UnparsableMessage):
            await self.client.handle_message()

    @no_duplicates
    @patch('schwab.streaming.ws_client.connect', new_callable=AsyncMock)
    async def test_handle_message_multiple_handlers(self, ws_connect):
        socket = await self.login_and_get_socket(ws_connect)

        stream_item_1 = self.streaming_entry('CHART_EQUITY', 'SUBS')

        socket.recv.side_effect = [
            json.dumps(self.success_response(1, 'CHART_EQUITY', 'SUBS')),
            json.dumps(stream_item_1)]

        await self.client.chart_equity_subs(['GOOG,MSFT'])

        handler = Mock()
        async_handler = AsyncMock()
        self.client.add_chart_equity_handler(handler)
        self.client.add_chart_equity_handler(async_handler)

        await self.client.handle_message()
        handler.assert_called_once_with(stream_item_1['data'][0])
        async_handler.assert_called_once_with(stream_item_1['data'][0])

    @no_duplicates
    @patch('schwab.streaming.ws_client.connect', new_callable=AsyncMock)
    async def test_multiple_data_per_message(self, ws_connect):
        socket = await self.login_and_get_socket(ws_connect)

        stream_item = self.streaming_entry(
            'CHART_EQUITY', 'SUBS', [{'msg': 1}])
        stream_item['data'].append(self.streaming_entry(
            'CHART_EQUITY', 'SUBS', [{'msg': 2}])['data'][0])

        socket.recv.side_effect = [
            json.dumps(self.success_response(1, 'CHART_EQUITY', 'SUBS')),
            json.dumps(stream_item)]

        await self.client.chart_equity_subs(['GOOG,MSFT'])

        handler = Mock()
        async_handler = AsyncMock()
        self.client.add_chart_equity_handler(handler)
        self.client.add_chart_equity_handler(async_handler)

        await self.client.handle_message()
        handler.assert_has_calls(
            [call(stream_item['data'][0]), call(stream_item['data'][1])])
        async_handler.assert_has_calls(
            [call(stream_item['data'][0]), call(stream_item['data'][1])])

    @no_duplicates
    @patch('schwab.streaming.ws_client.connect', new_callable=AsyncMock)
    async def test_handle_message_without_login(self, ws_connect):
        with self.assertRaisesRegex(ValueError, '.*Socket not open.*'):
            await self.client.handle_message()

    @no_duplicates
    @patch('schwab.streaming.ws_client.connect', new_callable=AsyncMock)
    async def test_subscribe_without_login(self, ws_connect):
        with self.assertRaisesRegex(ValueError, '.*Socket not open.*'):
            await self.client.chart_equity_subs(['GOOG,MSFT'])

    @no_duplicates
    @patch('schwab.streaming.ws_client.connect', new_callable=AsyncMock)
    async def test_unsubscribe_without_login(self, ws_connect):
        with self.assertRaisesRegex(ValueError, '.*Socket not open.*'):
            await self.client.chart_equity_unsubs(['GOOG,MSFT'])

    ###########################################################################
    # Private member _service_op
    #
    # Note: https://developer.schwabmeritrade.com/content/streaming-data#_Toc504640564
    # parameters are optional and in the case of UNSUBS commands,
    # fields should not be required since unsubscribing from a service
    # will return no data on the service or symbol

    @no_duplicates
    @patch('schwab.streaming.ws_client.connect', new_callable=AsyncMock)
    async def test_service_op_sends_some_fields_with_field_type_and_fields(self, ws_connect):
        socket = await self.login_and_get_socket(ws_connect)

        socket.recv.side_effect = [json.dumps(self.success_response(
            1, 'LEVELONE_EQUITIES', 'SUBS'))]

        await self.client._service_op(
            symbols=['GOOG', 'MSFT'],
            service='LEVELONE_EQUITIES',
            command='SUBS',
            field_type=StreamClient.LevelOneEquityFields,
            fields=[
            StreamClient.LevelOneEquityFields.DESCRIPTION,
            StreamClient.LevelOneEquityFields.ASK_PRICE
        ])
        socket.recv.assert_awaited_once()
        request = self.request_from_socket_mock(socket)

        self.assertEqual(request, {
            'service': 'LEVELONE_EQUITIES',
            'command': 'SUBS',
            'requestid': '1',
            "SchwabClientCustomerId": CLIENT_CUSTOMER_ID,
            "SchwabClientCorrelId": CLIENT_CORRELATION_ID,
            'parameters': {
                'keys': 'GOOG,MSFT',
                'fields': '2,15'
            }
        })

    @no_duplicates
    @patch('schwab.streaming.ws_client.connect', new_callable=AsyncMock)
    async def test_service_op_sends_no_fields_without_field_type(self, ws_connect):
        socket = await self.login_and_get_socket(ws_connect)

        socket.recv.side_effect = [json.dumps(self.success_response(
            1, 'LEVELONE_EQUITIES', 'UNSUBS'))]

        await self.client._service_op(
            ['GOOG','MSFT'],
            'LEVELONE_EQUITIES',
            'UNSUBS'
        )
        socket.recv.assert_awaited_once()
        request = self.request_from_socket_mock(socket)

        self.assertFalse('fields' in request['parameters'])

    @no_duplicates
    @patch('schwab.streaming.ws_client.connect', new_callable=AsyncMock)
    async def test_service_op_sends_no_fields_for_sub_without_field_type(self, ws_connect):
        """
        There's no service's sub/add commands without field_type defined but this tests for fields=None behavior if field_type=None
        Warning: Sub commands seems to fail if there's no fields parameters,
        check logs : https://github.com/alexgolec/schwab-api/pull/256#issuecomment-950406363

        The streaming client will properly throw UnexpectedResponse
        """
        socket = await self.login_and_get_socket(ws_connect)

        resp = self.success_response(1, 'LEVELONE_EQUITIES', 'SUBS', msg="SUBS command failed")
        resp['response'][0]['content']['code'] = 22
        socket.recv.side_effect = [
            json.dumps(resp)
        ]

        with self.assertRaises(schwab.streaming.UnexpectedResponseCode) as e:
            await self.client._service_op(
                symbols=['GOOG','MSFT'],
                service='LEVELONE_EQUITIES',
                command='SUBS'
            )
        socket.recv.assert_awaited_once()
        request = self.request_from_socket_mock(socket)

        self.assertFalse('fields' in request['parameters'])

    @no_duplicates
    @patch('schwab.streaming.ws_client.connect', new_callable=AsyncMock)
    async def test_service_op_sends_no_fields_for_sub_with_fields(self, ws_connect):
        """
        There's no service's sub/add commands without field_type defined but this tests for fields=None behavior if field_type=None
        Warning: Sub commands seems to fail if there's no fields parameters,
        check logs : https://github.com/alexgolec/schwab-api/pull/256#issuecomment-950406363

        The streaming client will properly throw UnexpectedResponse
        """
        socket = await self.login_and_get_socket(ws_connect)

        resp = self.success_response(1, 'LEVELONE_EQUITIES', 'SUBS', msg="SUBS command failed")
        resp['response'][0]['content']['code'] = 22
        socket.recv.side_effect = [
            json.dumps(resp)
        ]

        with self.assertRaises(schwab.streaming.UnexpectedResponseCode) as e:
            await self.client._service_op(
                symbols=['GOOG','MSFT'],
                service='LEVELONE_EQUITIES',
                command='SUBS',
                fields=[
                    StreamClient.LevelOneEquityFields.DESCRIPTION,
                    StreamClient.LevelOneEquityFields.ASK_PRICE
                ]
            )
        socket.recv.assert_awaited_once()
        request = self.request_from_socket_mock(socket)

        self.assertFalse('fields' in request['parameters'])

    @no_duplicates
    @patch('schwab.streaming.ws_client.connect', new_callable=AsyncMock)
    async def test_service_op_sends_all_fields_with_field_type(self, ws_connect):
        socket = await self.login_and_get_socket(ws_connect)

        socket.recv.side_effect = [json.dumps(self.success_response(
            1, 'CHART_EQUITY', 'SUBS'))]

        await self.client._service_op(
            symbols=['GOOG','MSFT'],
            service='CHART_EQUITY',
            command='SUBS',
            field_type=StreamClient.ChartEquityFields
        )
        socket.recv.assert_awaited_once()
        request = self.request_from_socket_mock(socket)

        self.assertEqual(request, {
            'service': 'CHART_EQUITY',
            'command': 'SUBS',
            'requestid': '1',
            "SchwabClientCustomerId": CLIENT_CUSTOMER_ID,
            "SchwabClientCorrelId": CLIENT_CORRELATION_ID,
            'parameters': {
                'keys': 'GOOG,MSFT',
                'fields': '0,1,2,3,4,5,6,7,8'
            }
        })

        socket.reset_mock()

        socket.recv.side_effect = [json.dumps(self.success_response(
            2, 'CHART_EQUITY', 'ADD'))]

        await self.client._service_op(
            symbols=['GOOG','MSFT'],
            service='CHART_EQUITY',
            command='ADD',
            field_type=StreamClient.ChartEquityFields
        )
        socket.recv.assert_awaited_once()
        request = self.request_from_socket_mock(socket)

        self.assertEqual(request, {
            'service': 'CHART_EQUITY',
            'command': 'ADD',
            'requestid': '2',
            "SchwabClientCustomerId": CLIENT_CUSTOMER_ID,
            "SchwabClientCorrelId": CLIENT_CORRELATION_ID,
            'parameters': {
                'keys': 'GOOG,MSFT',
                'fields': '0,1,2,3,4,5,6,7,8'
            }
        })
