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
    # Logout

    @no_duplicates
    @patch('schwab.streaming.ws_client.connect', new_callable=AsyncMock)
    async def test_logout_success(self, ws_connect):
        socket = await self.login_and_get_socket(ws_connect)

        socket.recv.side_effect = [json.dumps(self.success_response(
            1, 'ADMIN', 'LOGOUT'))]

        await self.client.logout()

        socket.send.assert_awaited_once()
        request = self.request_from_socket_mock(socket)

        self.assertEqual(request, {
            'service': 'ADMIN',
            'command': 'LOGOUT',
            'requestid': '1',
            'SchwabClientCustomerId': CLIENT_CUSTOMER_ID,
            'SchwabClientCorrelId': CLIENT_CORRELATION_ID,
            'parameters': {}
        })

    @no_duplicates
    @patch('schwab.streaming.ws_client.connect', new_callable=AsyncMock)
    async def test_logout_failure(self, ws_connect):
        socket = await self.login_and_get_socket(ws_connect)

        response = self.success_response(1, 'ADMIN', 'LOGOUT')
        response['response'][0]['content']['code'] = 9
        socket.recv.side_effect = [json.dumps(response)]

        with self.assertRaises(schwab.streaming.UnexpectedResponseCode):
            await self.client.logout()


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
                    'ACCOUNT': '1001',
                    'MESSAGE_TYPE': 'OrderEntryRequest',
                    'MESSAGE_DATA': ''
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
                'CHART_TIME_MILLIS': 1590597840000,
                'OPEN_PRICE': 2996.25,
                'HIGH_PRICE': 2997.25,
                'LOW_PRICE': 2995.25,
                'CLOSE_PRICE': 2997.25,
                'VOLUME': 1501.0
            }, {
                'seq': 0,
                'key': '/CL',
                'CHART_TIME_MILLIS': 1590597840000,
                'OPEN_PRICE': 33.34,
                'HIGH_PRICE': 33.35,
                'LOW_PRICE': 33.32,
                'CLOSE_PRICE': 33.35,
                'VOLUME': 186.0
            }]
        }

        self.assert_handler_called_once_with(handler, expected_item)
        self.assert_handler_called_once_with(async_handler, expected_item)

    ##########################################################################
    # LEVELONE_EQUITIES

    @no_duplicates
    @patch('schwab.streaming.ws_client.connect', new_callable=AsyncMock)
    async def test_level_one_equity_subs_and_add_success_all_fields(self, ws_connect):
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

        socket.reset_mock()

        socket.recv.side_effect = [json.dumps(self.success_response(
            2, 'LEVELONE_EQUITIES', 'ADD'))]

        await self.client.level_one_equity_add(['INTC'])
        socket.recv.assert_awaited_once()
        request = self.request_from_socket_mock(socket)

        self.assertEqual(request, {
            'service': 'LEVELONE_EQUITIES',
            'command': 'ADD',
            'requestid': '2',
            'SchwabClientCustomerId': self.pref_customer_id,
            'SchwabClientCorrelId': self.pref_correl_id,
            'parameters': {
                'keys': 'INTC',
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
    async def test_level_one_equity_subs_and_add_success_some_fields(self, ws_connect):
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

        socket.reset_mock()

        socket.recv.side_effect = [json.dumps(self.success_response(
            2, 'LEVELONE_EQUITIES', 'ADD'))]

        await self.client.level_one_equity_add(['INTC'], fields=[
            StreamClient.LevelOneEquityFields.SYMBOL,
            StreamClient.LevelOneEquityFields.BID_PRICE,
            StreamClient.LevelOneEquityFields.ASK_PRICE,
            StreamClient.LevelOneEquityFields.LOW_PRICE,
        ])
        socket.recv.assert_awaited_once()
        request = self.request_from_socket_mock(socket)

        self.assertEqual(request, {
            'service': 'LEVELONE_EQUITIES',
            'command': 'ADD',
            'requestid': '2',
            'SchwabClientCustomerId': CLIENT_CUSTOMER_ID,
            'SchwabClientCorrelId': CLIENT_CORRELATION_ID,
            'parameters': {
                'keys': 'INTC',
                'fields': '0,1,2,11'
            }
        })

    @no_duplicates
    @patch('schwab.streaming.ws_client.connect', new_callable=AsyncMock)
    async def test_level_one_equity_subs_and_add_success_some_fields_no_symbol(
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

        socket.reset_mock()

        socket.recv.side_effect = [json.dumps(self.success_response(
            2, 'LEVELONE_EQUITIES', 'ADD'))]

        await self.client.level_one_equity_add(['INTC'], fields=[
            StreamClient.LevelOneEquityFields.BID_PRICE,
            StreamClient.LevelOneEquityFields.ASK_PRICE,
            StreamClient.LevelOneEquityFields.LOW_PRICE,
        ])
        socket.recv.assert_awaited_once()
        request = self.request_from_socket_mock(socket)

        self.assertEqual(request, {
            'service': 'LEVELONE_EQUITIES',
            'command': 'ADD',
            'requestid': '2',
            'SchwabClientCustomerId': CLIENT_CUSTOMER_ID,
            'SchwabClientCorrelId': CLIENT_CORRELATION_ID,
            'parameters': {
                'keys': 'INTC',
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
    async def test_level_one_equity_add_failure(self, ws_connect):
        socket = await self.login_and_get_socket(ws_connect)

        response = self.success_response(1, 'LEVELONE_EQUITIES', 'ADD')
        response['response'][0]['content']['code'] = 21
        socket.recv.side_effect = [json.dumps(response)]

        with self.assertRaises(schwab.streaming.UnexpectedResponseCode):
            await self.client.level_one_equity_add(['GOOG', 'MSFT'])

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
                    "HTB_QUANTITY": 95711793,
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
                    "HTB_QUANTITY": 67295343,
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
    async def test_level_one_option_subs_and_add_success_all_fields(self, ws_connect):
        socket = await self.login_and_get_socket(ws_connect)

        socket.recv.side_effect = [json.dumps(self.success_response(
            1, 'LEVELONE_OPTIONS', 'SUBS'))]

        await self.client.level_one_option_subs(
            ['GOOG  240517C00070000', 'MSFT  240517C00160000'])
        socket.recv.assert_awaited_once()
        request = self.request_from_socket_mock(socket)

        self.assertEqual(request, {
            'service': 'LEVELONE_OPTIONS',
            'command': 'SUBS',
            'requestid': '1',
            "SchwabClientCustomerId": CLIENT_CUSTOMER_ID,
            "SchwabClientCorrelId": CLIENT_CORRELATION_ID,
            'parameters': {
                'keys': 'GOOG  240517C00070000,MSFT  240517C00160000',
                'fields': ('0,1,2,3,4,5,6,7,8,9,10,11,12,13,14,15,16,17,18,19,' +
                           '20,21,22,23,24,25,26,27,28,29,30,31,32,33,34,35,' +
                           '36,37,38,39,40,41,42,43,44,45,46,47,48,49,50,51,' +
                           '52,53,54,55')
            }
        })

        socket.reset_mock()

        socket.recv.side_effect = [json.dumps(self.success_response(
            2, 'LEVELONE_OPTIONS', 'ADD'))]

        await self.client.level_one_option_add(['ADBE  240614C00500000'])
        socket.recv.assert_awaited_once()
        request = self.request_from_socket_mock(socket)

        self.assertEqual(request, {
            'service': 'LEVELONE_OPTIONS',
            'command': 'ADD',
            'requestid': '2',
            'SchwabClientCustomerId': CLIENT_CUSTOMER_ID,
            'SchwabClientCorrelId': CLIENT_CORRELATION_ID,
            'parameters': {
                'keys': 'ADBE  240614C00500000',
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
            ['GOOG  240517C00070000', 'MSFT  240517C00160000'])
        await self.client.handle_message()
        await self.client.level_one_option_unsubs(
            ['GOOG  240517C00070000', 'MSFT  240517C00160000'])

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
                        "keys": "GOOG  240517C00070000,MSFT  240517C00160000",
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
                        "keys": "GOOG  240517C00070000,MSFT  240517C00160000"
                    }
                }]
            })),
        ]

        socket.send.assert_has_awaits(send_awaited, any_order=False)

    @no_duplicates
    @patch('schwab.streaming.ws_client.connect', new_callable=AsyncMock)
    async def test_level_one_option_subs_and_add_success_some_fields(self, ws_connect):
        socket = await self.login_and_get_socket(ws_connect)

        socket.recv.side_effect = [json.dumps(self.success_response(
            1, 'LEVELONE_OPTIONS', 'SUBS'))]

        await self.client.level_one_option_subs(
            ['GOOG  240517C00070000', 'MSFT  240517C00160000'], fields=[
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
                'keys': 'GOOG  240517C00070000,MSFT  240517C00160000',
                'fields': '0,2,3,10'
            }
        })

        socket.reset_mock()

        socket.recv.side_effect = [json.dumps(self.success_response(
            2, 'LEVELONE_OPTIONS', 'ADD'))]

        await self.client.level_one_option_add(
            ['ADBE  240614C00500000'], fields=[
                StreamClient.LevelOneOptionFields.SYMBOL,
                StreamClient.LevelOneOptionFields.BID_PRICE,
                StreamClient.LevelOneOptionFields.ASK_PRICE,
                StreamClient.LevelOneOptionFields.VOLATILITY,
            ])
        socket.recv.assert_awaited_once()
        request = self.request_from_socket_mock(socket)

        self.assertEqual(request, {
            'service': 'LEVELONE_OPTIONS',
            'command': 'ADD',
            'requestid': '2',
            'SchwabClientCustomerId': CLIENT_CUSTOMER_ID,
            'SchwabClientCorrelId': CLIENT_CORRELATION_ID,
            'parameters': {
                'keys': 'ADBE  240614C00500000',
                'fields': '0,2,3,10'
            }
        })

    @no_duplicates
    @patch('schwab.streaming.ws_client.connect', new_callable=AsyncMock)
    async def test_level_one_option_subs_and_add_success_some_fields_no_symbol(
            self, ws_connect):
        socket = await self.login_and_get_socket(ws_connect)

        socket.recv.side_effect = [json.dumps(self.success_response(
            1, 'LEVELONE_OPTIONS', 'SUBS'))]

        await self.client.level_one_option_subs(
            ['GOOG  240517C00070000', 'MSFT  240517C00160000'], fields=[
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
                'keys': 'GOOG  240517C00070000,MSFT  240517C00160000',
                'fields': '0,2,3,10'
            }
        })

        socket.reset_mock()

        socket.recv.side_effect = [json.dumps(self.success_response(
            2, 'LEVELONE_OPTIONS', 'ADD'))]

        await self.client.level_one_option_add(
            ['ADBE  240614C00500000'], fields=[
                StreamClient.LevelOneOptionFields.BID_PRICE,
                StreamClient.LevelOneOptionFields.ASK_PRICE,
                StreamClient.LevelOneOptionFields.VOLATILITY,
            ])
        socket.recv.assert_awaited_once()
        request = self.request_from_socket_mock(socket)

        self.assertEqual(request, {
            'service': 'LEVELONE_OPTIONS',
            'command': 'ADD',
            'requestid': '2',
            'SchwabClientCustomerId': CLIENT_CUSTOMER_ID,
            'SchwabClientCorrelId': CLIENT_CORRELATION_ID,
            'parameters': {
                'keys': 'ADBE  240614C00500000',
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
                ['GOOG  240517C00070000', 'MSFT  240517C00160000'])

    @no_duplicates
    @patch('schwab.streaming.ws_client.connect', new_callable=AsyncMock)
    async def test_level_one_option_unsubs_failure(self, ws_connect):
        socket = await self.login_and_get_socket(ws_connect)

        response = self.success_response(1, 'LEVELONE_OPTIONS', 'UNSUBS')
        response['response'][0]['content']['code'] = 21
        socket.recv.side_effect = [json.dumps(response)]

        with self.assertRaises(schwab.streaming.UnexpectedResponseCode):
            await self.client.level_one_option_unsubs(
                ['GOOG  240517C00070000', 'MSFT  240517C00160000'])

    @no_duplicates
    @patch('schwab.streaming.ws_client.connect', new_callable=AsyncMock)
    async def test_level_one_option_add_failure(self, ws_connect):
        socket = await self.login_and_get_socket(ws_connect)

        response = self.success_response(1, 'LEVELONE_OPTIONS', 'ADD')
        response['response'][0]['content']['code'] = 21
        socket.recv.side_effect = [json.dumps(response)]

        with self.assertRaises(schwab.streaming.UnexpectedResponseCode):
            await self.client.level_one_option_add(['ADBE  240614C00500000'])

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
            ['GOOG  240517C00070000', 'MSFT  240517C00160000'])

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
    async def test_level_one_futures_subs_and_add_success_all_fields(self, ws_connect):
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
                           '20,21,22,23,24,25,26,27,28,29,30,31,32,33,34,35,36,37,38,39,40')
            }
        })

        socket.reset_mock()

        socket.recv.side_effect = [json.dumps(self.success_response(
            2, 'LEVELONE_FUTURES', 'ADD'))]

        await self.client.level_one_futures_add(['/NQ'])
        socket.recv.assert_awaited_once()
        request = self.request_from_socket_mock(socket)

        self.assertEqual(request, {
            'service': 'LEVELONE_FUTURES',
            'command': 'ADD',
            'requestid': '2',
            'SchwabClientCustomerId': CLIENT_CUSTOMER_ID,
            'SchwabClientCorrelId': CLIENT_CORRELATION_ID,
            'parameters': {
                'keys': '/NQ',
                'fields': '0,1,2,3,4,5,6,7,8,9,10,11,12,13,14,15,16,' +
                '17,18,19,20,21,22,23,24,25,26,27,28,29,30,31,32,33,' +
                '34,35,36,37,38,39,40'
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
                        "34,35,36,37,38,39,40"
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
    async def test_level_one_futures_subs_and_add_success_some_fields(self, ws_connect):
        socket = await self.login_and_get_socket(ws_connect)

        socket.recv.side_effect = [json.dumps(self.success_response(
            1, 'LEVELONE_FUTURES', 'SUBS'))]

        await self.client.level_one_futures_subs(['/ES', '/CL'], fields=[
            StreamClient.LevelOneFuturesFields.SYMBOL,
            StreamClient.LevelOneFuturesFields.BID_PRICE,
            StreamClient.LevelOneFuturesFields.ASK_PRICE,
            StreamClient.LevelOneFuturesFields.FUTURE_PRICE_FORMAT,
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

        socket.reset_mock()

        socket.recv.side_effect = [json.dumps(self.success_response(
            2, 'LEVELONE_FUTURES', 'ADD'))]

        await self.client.level_one_futures_add(['/NQ'], fields=[
            StreamClient.LevelOneFuturesFields.SYMBOL,
            StreamClient.LevelOneFuturesFields.BID_PRICE,
            StreamClient.LevelOneFuturesFields.ASK_PRICE,
            StreamClient.LevelOneFuturesFields.FUTURE_PRICE_FORMAT,
        ])
        socket.recv.assert_awaited_once()
        request = self.request_from_socket_mock(socket)

        self.assertEqual(request, {
            'service': 'LEVELONE_FUTURES',
            'command': 'ADD',
            'requestid': '2',
            'SchwabClientCustomerId': CLIENT_CUSTOMER_ID,
            'SchwabClientCorrelId': CLIENT_CORRELATION_ID,
            'parameters': {
                'keys': '/NQ',
                'fields': '0,1,2,28'
            }
        })

    @no_duplicates
    @patch('schwab.streaming.ws_client.connect', new_callable=AsyncMock)
    async def test_level_one_futures_subs_and_add_success_some_fields_no_symbol(
            self, ws_connect):
        socket = await self.login_and_get_socket(ws_connect)

        socket.recv.side_effect = [json.dumps(self.success_response(
            1, 'LEVELONE_FUTURES', 'SUBS'))]

        await self.client.level_one_futures_subs(['/ES', '/CL'], fields=[
            StreamClient.LevelOneFuturesFields.BID_PRICE,
            StreamClient.LevelOneFuturesFields.ASK_PRICE,
            StreamClient.LevelOneFuturesFields.FUTURE_PRICE_FORMAT,
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

        socket.reset_mock()

        socket.recv.side_effect = [json.dumps(self.success_response(
            2, 'LEVELONE_FUTURES', 'ADD'))]

        await self.client.level_one_futures_add(['/NQ'], fields=[
            StreamClient.LevelOneFuturesFields.BID_PRICE,
            StreamClient.LevelOneFuturesFields.ASK_PRICE,
            StreamClient.LevelOneFuturesFields.FUTURE_PRICE_FORMAT,
        ])
        socket.recv.assert_awaited_once()
        request = self.request_from_socket_mock(socket)

        self.assertEqual(request, {
            'service': 'LEVELONE_FUTURES',
            'command': 'ADD',
            'requestid': '2',
            'SchwabClientCustomerId': CLIENT_CUSTOMER_ID,
            'SchwabClientCorrelId': CLIENT_CORRELATION_ID,
            'parameters': {
                'keys': '/NQ',
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
    async def test_level_one_futures_add_failure(self, ws_connect):
        socket = await self.login_and_get_socket(ws_connect)

        response = self.success_response(1, 'LEVELONE_FUTURES', 'ADD')
        response['response'][0]['content']['code'] = 21
        socket.recv.side_effect = [json.dumps(response)]

        with self.assertRaises(schwab.streaming.UnexpectedResponseCode):
            await self.client.level_one_futures_add(['/NQ'])

    @no_duplicates
    @patch('schwab.streaming.ws_client.connect', new_callable=AsyncMock)
    async def test_level_one_futures_handler(self, ws_connect):
        socket = await self.login_and_get_socket(ws_connect)

        stream_item = {
            'data': [{
                'service': 'LEVELONE_FUTURES',
                'timestamp': 1719002950099,
                'command': 'SUBS',
                'content': [{
                    'key': '/CL',
                    'delayed': False,
                    'assetMainType': 'FUTURE',
                    '1': 80.61,
                    '2': 80.62,
                    '3': 80.6,
                    '4': 2,
                    '5': 14,
                    '6': '?',
                    '7': '?',
                    '8': 270916,
                    '9': 1,
                    '10': 1719002948817,
                    '11': 1719002944037,
                    '12': 81.79,
                    '13': 80.35,
                    '14': 81.29,
                    '15': '@',
                    '16': 'Light Sweet Crude Oil Futures,Aug-2024,ETH',
                    '17': '?',
                    '18': 81.27,
                    '19': -0.69,
                    '20': -0.84881289,
                    '21': 'XNYM',
                    '22': 'Normal',
                    '23': 352314,
                    '24': 80.61,
                    '25': 0.01,
                    '26': 10,
                    '27': '/CL',
                    '28': 'D,D',
                    '29': 'GLBX(de=1640;0=-17001600;1=-17001600d-15551640;7=d-16401555)',
                    '30': False,
                    '31': 1000,
                    '32': True,
                    '33': 81.29,
                    '34': '/CLQ24',
                    '35': 1721620800000,
                    '36': 'Unknown',
                    '37': 1719002948347,
                    '38': 1719002948817,
                    '39': True,
                    '40': 1718928000000
                }, {
                    'key': '/ES',
                    'delayed': False,
                    'assetMainType': 'FUTURE',
                    '1': 5536.5,
                    '2': 5537,
                    '3': 5536.75,
                    '4': 61,
                    '5': 112,
                    '6': '?',
                    '7': '?',
                    '8': 1250270,
                    '9': 2,
                    '10': 1719002947349,
                    '11': 1719002945728,
                    '12': 5550.75,
                    '13': 5519,
                    '14': 5544.5,
                    '15': '@',
                    '16': 'E-mini S&P 500 Index Futures,Sep-2024,ETH',
                    '17': '?',
                    '18': 5545,
                    '19': -7.75,
                    '20': -0.13977816,
                    '21': 'XCME',
                    '22': 'Normal',
                    '23': 1976987,
                    '24': 5536.75,
                    '25': 0.25,
                    '26': 12.5,
                    '27': '/ES',
                    '28': 'D,D',
                    '29': 'GLBX(de=1640;0=-17001600;1=r-17001600d-15551640;7=d-16401555)',
                    '30': False,
                    '31': 50,
                    '32': True,
                    '33': 5544.5,
                    '34': '/ESU24',
                    '35': 1726804800000,
                    '36': 'Unknown',
                    '37': 1719002947349,
                    '38': 1719002946189,
                    '39': True,
                    '40': 1718928000000
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
            'timestamp': 1719002950099,
            'command': 'SUBS',
            'content': [
                {
                    'key': '/CL',
                    'delayed': False,
                    'assetMainType': 'FUTURE',
                    'BID_PRICE': 80.61,
                    'ASK_PRICE': 80.62,
                    'LAST_PRICE': 80.6,
                    'BID_SIZE': 2,
                    'ASK_SIZE': 14,
                    'BID_ID': '?',
                    'ASK_ID': '?',
                    'TOTAL_VOLUME': 270916,
                    'LAST_SIZE': 1,
                    'QUOTE_TIME_MILLIS': 1719002948817,
                    'TRADE_TIME_MILLIS': 1719002944037,
                    'HIGH_PRICE': 81.79,
                    'LOW_PRICE': 80.35,
                    'CLOSE_PRICE': 81.29,
                    'EXCHANGE_ID': '@',
                    'DESCRIPTION': 'Light Sweet Crude Oil Futures,Aug-2024,ETH',
                    'LAST_ID': '?',
                    'OPEN_PRICE': 81.27,
                    'NET_CHANGE': -0.69,
                    'FUTURE_CHANGE_PERCENT': -0.84881289,
                    'EXCHANGE_NAME': 'XNYM',
                    'SECURITY_STATUS': 'Normal',
                    'OPEN_INTEREST': 352314,
                    'MARK': 80.61,
                    'TICK': 0.01,
                    'TICK_AMOUNT': 10,
                    'PRODUCT': '/CL',
                    'FUTURE_PRICE_FORMAT': 'D,D',
                    'FUTURE_TRADING_HOURS': 'GLBX(de=1640;0=-17001600;1=-17001600d-15551640;7=d-16401555)',
                    'FUTURE_IS_TRADABLE': False,
                    'FUTURE_MULTIPLIER': 1000,
                    'FUTURE_IS_ACTIVE': True,
                    'FUTURE_SETTLEMENT_PRICE': 81.29,
                    'FUTURE_ACTIVE_SYMBOL': '/CLQ24',
                    'FUTURE_EXPIRATION_DATE': 1721620800000,
                    'EXPIRATION_STYLE': 'Unknown',
                    'ASK_TIME_MILLIS': 1719002948347,
                    'BID_TIME_MILLIS': 1719002948817,
                    'QUOTED_IN_SESSION': True,
                    'SETTLEMENT_DATE': 1718928000000
                },
                {
                    'key': '/ES',
                    'delayed': False,
                    'assetMainType': 'FUTURE',
                    'BID_PRICE': 5536.5,
                    'ASK_PRICE': 5537,
                    'LAST_PRICE': 5536.75,
                    'BID_SIZE': 61,
                    'ASK_SIZE': 112,
                    'BID_ID': '?',
                    'ASK_ID': '?',
                    'TOTAL_VOLUME': 1250270,
                    'LAST_SIZE': 2,
                    'QUOTE_TIME_MILLIS': 1719002947349,
                    'TRADE_TIME_MILLIS': 1719002945728,
                    'HIGH_PRICE': 5550.75,
                    'LOW_PRICE': 5519,
                    'CLOSE_PRICE': 5544.5,
                    'EXCHANGE_ID': '@',
                    'DESCRIPTION': 'E-mini S&P 500 Index Futures,Sep-2024,ETH',
                    'LAST_ID': '?',
                    'OPEN_PRICE': 5545,
                    'NET_CHANGE': -7.75,
                    'FUTURE_CHANGE_PERCENT': -0.13977816,
                    'EXCHANGE_NAME': 'XCME',
                    'SECURITY_STATUS': 'Normal',
                    'OPEN_INTEREST': 1976987,
                    'MARK': 5536.75,
                    'TICK': 0.25,
                    'TICK_AMOUNT': 12.5,
                    'PRODUCT': '/ES',
                    'FUTURE_PRICE_FORMAT': 'D,D',
                    'FUTURE_TRADING_HOURS': 'GLBX(de=1640;0=-17001600;1=r-17001600d-15551640;7=d-16401555)',
                    'FUTURE_IS_TRADABLE': False,
                    'FUTURE_MULTIPLIER': 50,
                    'FUTURE_IS_ACTIVE': True,
                    'FUTURE_SETTLEMENT_PRICE': 5544.5,
                    'FUTURE_ACTIVE_SYMBOL': '/ESU24',
                    'FUTURE_EXPIRATION_DATE': 1726804800000,
                    'EXPIRATION_STYLE': 'Unknown',
                    'ASK_TIME_MILLIS': 1719002947349,
                    'BID_TIME_MILLIS': 1719002946189,
                    'QUOTED_IN_SESSION': True,
                    'SETTLEMENT_DATE': 1718928000000
                }
            ]
        }

        self.assert_handler_called_once_with(handler, expected_item)
        self.assert_handler_called_once_with(async_handler, expected_item)


    ##########################################################################
    # LEVELONE_FOREX

    @no_duplicates
    @patch('schwab.streaming.ws_client.connect', new_callable=AsyncMock)
    async def test_level_one_forex_subs_and_add_success_all_fields(self, ws_connect):
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

        socket.reset_mock()

        socket.recv.side_effect = [json.dumps(self.success_response(
            2, 'LEVELONE_FOREX', 'ADD'))]

        await self.client.level_one_forex_add(['JPY/USD'])
        socket.recv.assert_awaited_once()
        request = self.request_from_socket_mock(socket)

        self.assertEqual(request, {
            'service': 'LEVELONE_FOREX',
            'command': 'ADD',
            'requestid': '2',
            'SchwabClientCustomerId': CLIENT_CUSTOMER_ID,
            'SchwabClientCorrelId': CLIENT_CORRELATION_ID,
            'parameters': {
                'keys': 'JPY/USD',
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
    async def test_level_one_forex_subs_and_add_success_some_fields(self, ws_connect):
        socket = await self.login_and_get_socket(ws_connect)

        socket.recv.side_effect = [json.dumps(self.success_response(
            1, 'LEVELONE_FOREX', 'SUBS'))]

        await self.client.level_one_forex_subs(['EUR/USD', 'EUR/GBP'], fields=[
            StreamClient.LevelOneForexFields.SYMBOL,
            StreamClient.LevelOneForexFields.HIGH_PRICE,
            StreamClient.LevelOneForexFields.LOW_PRICE,
            StreamClient.LevelOneForexFields.MARKET_MAKER,
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

        socket.reset_mock()

        socket.recv.side_effect = [json.dumps(self.success_response(
            2, 'LEVELONE_FOREX', 'ADD'))]

        await self.client.level_one_forex_add(['JPY/USD'], fields=[
            StreamClient.LevelOneForexFields.SYMBOL,
            StreamClient.LevelOneForexFields.HIGH_PRICE,
            StreamClient.LevelOneForexFields.LOW_PRICE,
            StreamClient.LevelOneForexFields.MARKET_MAKER,
        ])
        socket.recv.assert_awaited_once()
        request = self.request_from_socket_mock(socket)

        self.assertEqual(request, {
            'service': 'LEVELONE_FOREX',
            'command': 'ADD',
            'requestid': '2',
            'SchwabClientCustomerId': CLIENT_CUSTOMER_ID,
            'SchwabClientCorrelId': CLIENT_CORRELATION_ID,
            'parameters': {
                'keys': 'JPY/USD',
                'fields': '0,10,11,26'
            }
        })

    @no_duplicates
    @patch('schwab.streaming.ws_client.connect', new_callable=AsyncMock)
    async def test_level_one_forex_subs_and_add_success_some_fields_no_symbol(
            self, ws_connect):
        socket = await self.login_and_get_socket(ws_connect)

        socket.recv.side_effect = [json.dumps(self.success_response(
            1, 'LEVELONE_FOREX', 'SUBS'))]

        await self.client.level_one_forex_subs(['EUR/USD', 'EUR/GBP'], fields=[
            StreamClient.LevelOneForexFields.HIGH_PRICE,
            StreamClient.LevelOneForexFields.LOW_PRICE,
            StreamClient.LevelOneForexFields.MARKET_MAKER,
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

        socket.reset_mock()

        socket.recv.side_effect = [json.dumps(self.success_response(
            2, 'LEVELONE_FOREX', 'ADD'))]

        await self.client.level_one_forex_add(['JPY/USD'], fields=[
            StreamClient.LevelOneForexFields.HIGH_PRICE,
            StreamClient.LevelOneForexFields.LOW_PRICE,
            StreamClient.LevelOneForexFields.MARKET_MAKER,
        ])
        socket.recv.assert_awaited_once()
        request = self.request_from_socket_mock(socket)

        self.assertEqual(request, {
            'service': 'LEVELONE_FOREX',
            'command': 'ADD',
            'requestid': '2',
            'SchwabClientCustomerId': CLIENT_CUSTOMER_ID,
            'SchwabClientCorrelId': CLIENT_CORRELATION_ID,
            'parameters': {
                'keys': 'JPY/USD',
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
    async def test_level_one_forex_add_failure(self, ws_connect):
        socket = await self.login_and_get_socket(ws_connect)

        response = self.success_response(1, 'LEVELONE_FOREX', 'ADD')
        response['response'][0]['content']['code'] = 21
        socket.recv.side_effect = [json.dumps(response)]

        with self.assertRaises(schwab.streaming.UnexpectedResponseCode):
            await self.client.level_one_forex_add(['JPY/USD'])

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
                    '1': 0.84437,
                    '2': 0.84451,
                    '3': 0.84444,
                    '4': 1000000,
                    '5': 3000000,
                    '6': 310000,
                    '7': 10000,
                    '8': 1718811579076,
                    '9': 1718811579076,
                    '10': 0.84526,
                    '11': 0.842995,
                    '12': 0.844095,
                    '13': '!',
                    '14': 'Euro/GBPound Spot',
                    '15': 0.84526,
                    '16': 0.000345,
                    '17': 0,
                    '18': 'GFT',
                    '19': 2,
                    '20': 'Unknown',
                    '21': 0,
                    '22': 0,
                    '23': '',
                    '24': '',
                    '25': False,
                    '26': '',
                    '27': 0.84526,
                    '28': 0.842995,
                    '29': 0.84444
                }, {
                    'key': 'EUR/USD',
                    'delayed': False,
                    'assetMainType': 'FOREX',
                    '1': 1.07435,
                    '2': 1.07448,
                    '3': 1.074415,
                    '4': 3000000,
                    '5': 1000000,
                    '6': 14730000,
                    '7': 20000,
                    '8': 1718811581092,
                    '9': 1718811581092,
                    '10': 1.075305,
                    '11': 1.07272,
                    '12': 1.070485,
                    '13': '!',
                    '14': 'Euro/USDollar Spot',
                    '15': 1.07396,
                    '16': 0.00393,
                    '17': 0,
                    '18': 'GFT',
                    '19': 2,
                    '20': 'Unknown',
                    '21': 0,
                    '22': 0,
                    '23': '',
                    '24': '',
                    '25': False,
                    '26': '',
                    '27': 1.075305,
                    '28': 1.07272,
                    '29': 1.074415
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
                'BID_PRICE': 0.84437,
                'ASK_PRICE': 0.84451,
                'LAST_PRICE': 0.84444,
                'BID_SIZE': 1000000,
                'ASK_SIZE': 3000000,
                'TOTAL_VOLUME': 310000,
                'LAST_SIZE': 10000,
                'QUOTE_TIME_MILLIS': 1718811579076,
                'TRADE_TIME_MILLIS': 1718811579076,
                'HIGH_PRICE': 0.84526,
                'LOW_PRICE': 0.842995,
                'CLOSE_PRICE': 0.844095,
                'EXCHANGE_ID': '!',
                'DESCRIPTION': 'Euro/GBPound Spot',
                'OPEN_PRICE': 0.84526,
                'NET_CHANGE': 0.000345,
                'CHANGE_PERCENT': 0,
                'EXCHANGE_NAME': 'GFT',
                'DIGITS': 2,
                'SECURITY_STATUS': 'Unknown',
                'TICK': 0,
                'TICK_AMOUNT': 0,
                'PRODUCT': '',
                'TRADING_HOURS': '',
                'IS_TRADABLE': False,
                'MARKET_MAKER': '',
                'HIGH_PRICE_52_WEEK': 0.84526,
                'LOW_PRICE_52_WEEK': 0.842995,
                'MARK': 0.84444
            }, {
                'key': 'EUR/USD',
                'delayed': False,
                'assetMainType': 'FOREX',
                'BID_PRICE': 1.07435,
                'ASK_PRICE': 1.07448,
                'LAST_PRICE': 1.074415,
                'BID_SIZE': 3000000,
                'ASK_SIZE': 1000000,
                'TOTAL_VOLUME': 14730000,
                'LAST_SIZE': 20000,
                'QUOTE_TIME_MILLIS': 1718811581092,
                'TRADE_TIME_MILLIS': 1718811581092,
                'HIGH_PRICE': 1.075305,
                'LOW_PRICE': 1.07272,
                'CLOSE_PRICE': 1.070485,
                'EXCHANGE_ID': '!',
                'DESCRIPTION': 'Euro/USDollar Spot',
                'OPEN_PRICE': 1.07396,
                'NET_CHANGE': 0.00393,
                'CHANGE_PERCENT': 0,
                'EXCHANGE_NAME': 'GFT',
                'DIGITS': 2,
                'SECURITY_STATUS': 'Unknown',
                'TICK': 0,
                'TICK_AMOUNT': 0,
                'PRODUCT': '',
                'TRADING_HOURS': '',
                'IS_TRADABLE': False,
                'MARKET_MAKER': '',
                'HIGH_PRICE_52_WEEK': 1.075305,
                'LOW_PRICE_52_WEEK': 1.07272,
                'MARK': 1.074415
            }]
        }

        self.assert_handler_called_once_with(handler, expected_item)
        self.assert_handler_called_once_with(async_handler, expected_item)


    ##########################################################################
    # LEVELONE_FUTURES_OPTIONS

    @no_duplicates
    @patch('schwab.streaming.ws_client.connect', new_callable=AsyncMock)
    async def test_level_one_futures_options_subs_and_add_success_all_fields(
            self, ws_connect):
        socket = await self.login_and_get_socket(ws_connect)

        socket.recv.side_effect = [json.dumps(self.success_response(
            1, 'LEVELONE_FUTURES_OPTIONS', 'SUBS'))]

        await self.client.level_one_futures_options_subs(
            ['./E3DM24P5490', './Q3DM24C19960'])
        socket.recv.assert_awaited_once()
        request = self.request_from_socket_mock(socket)

        self.assertEqual(request, {
            'service': 'LEVELONE_FUTURES_OPTIONS',
            'command': 'SUBS',
            'requestid': '1',
            "SchwabClientCustomerId": CLIENT_CUSTOMER_ID,
            "SchwabClientCorrelId": CLIENT_CORRELATION_ID,
            'parameters': {
                'keys': './E3DM24P5490,./Q3DM24C19960',
                'fields': ('0,1,2,3,4,5,6,7,8,9,10,11,12,13,14,15,16,17,18,' +
                           '19,20,21,22,23,24,25,26,27,28,29,30,31')
            }
        })

        socket.reset_mock()

        socket.recv.side_effect = [json.dumps(self.success_response(
            2, 'LEVELONE_FUTURES_OPTIONS', 'ADD'))]

        await self.client.level_one_futures_options_add(['./OYMM24P38550'])
        socket.recv.assert_awaited_once()
        request = self.request_from_socket_mock(socket)

        self.assertEqual(request, {
            'service': 'LEVELONE_FUTURES_OPTIONS',
            'command': 'ADD',
            'requestid': '2',
            'SchwabClientCustomerId': CLIENT_CUSTOMER_ID,
            'SchwabClientCorrelId': CLIENT_CORRELATION_ID,
            'parameters': {
                'keys': './OYMM24P38550',
                'fields': ('0,1,2,3,4,5,6,7,8,9,10,11,12,13,14,15,16,17,18,' +
                           '19,20,21,22,23,24,25,26,27,28,29,30,31')
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
            ['./E3DM24P5490', './Q3DM24C19960'])
        await self.client.handle_message()
        await self.client.level_one_futures_options_unsubs(
            ['./E3DM24P5490', './Q3DM24C19960'])

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
                        "keys": "./E3DM24P5490,./Q3DM24C19960",
                        "fields": "0,1,2,3,4,5,6,7,8,9,10,11,12,13,14,15,16,"+
                        "17,18,19,20,21,22,23,24,25,26,27,28,29,30,31"
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
                        "keys": "./E3DM24P5490,./Q3DM24C19960"
                    }
                }]
            })),
        ]
        socket.send.assert_has_awaits(send_awaited, any_order=False)

    @no_duplicates
    @patch('schwab.streaming.ws_client.connect', new_callable=AsyncMock)
    async def test_level_one_futures_options_subs_and_add_success_some_fields(
            self, ws_connect):
        socket = await self.login_and_get_socket(ws_connect)

        socket.recv.side_effect = [json.dumps(self.success_response(
            1, 'LEVELONE_FUTURES_OPTIONS', 'SUBS'))]

        await self.client.level_one_futures_options_subs(
            ['./E3DM24P5490', './Q3DM24C19960'], fields=[
                StreamClient.LevelOneFuturesOptionsFields.SYMBOL,
                StreamClient.LevelOneFuturesOptionsFields.BID_SIZE,
                StreamClient.LevelOneFuturesOptionsFields.ASK_SIZE,
                StreamClient.LevelOneFuturesOptionsFields.CONTRACT_TYPE,
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
                'keys': './E3DM24P5490,./Q3DM24C19960',
                'fields': '0,4,5,28'
            }
        })

        socket.reset_mock()

        socket.recv.side_effect = [json.dumps(self.success_response(
            2, 'LEVELONE_FUTURES_OPTIONS', 'ADD'))]

        await self.client.level_one_futures_options_add(
            ['./OYMM24P38550'], fields=[
                StreamClient.LevelOneFuturesOptionsFields.SYMBOL,
                StreamClient.LevelOneFuturesOptionsFields.BID_SIZE,
                StreamClient.LevelOneFuturesOptionsFields.ASK_SIZE,
                StreamClient.LevelOneFuturesOptionsFields.CONTRACT_TYPE,
            ])
        socket.recv.assert_awaited_once()
        request = self.request_from_socket_mock(socket)

        self.assertEqual(request, {
            'service': 'LEVELONE_FUTURES_OPTIONS',
            'command': 'ADD',
            'requestid': '2',
            'SchwabClientCustomerId': CLIENT_CUSTOMER_ID,
            'SchwabClientCorrelId': CLIENT_CORRELATION_ID,
            'parameters': {
                'keys': './OYMM24P38550',
                'fields': '0,4,5,28'
            }
        })

    @no_duplicates
    @patch('schwab.streaming.ws_client.connect', new_callable=AsyncMock)
    async def test_level_one_futures_options_subs_and_add_success_some_fields_no_symbol(
            self, ws_connect):
        socket = await self.login_and_get_socket(ws_connect)

        socket.recv.side_effect = [json.dumps(self.success_response(
            1, 'LEVELONE_FUTURES_OPTIONS', 'SUBS'))]

        await self.client.level_one_futures_options_subs(
            ['./E3DM24P5490', './Q3DM24C19960'], fields=[
                StreamClient.LevelOneFuturesOptionsFields.BID_SIZE,
                StreamClient.LevelOneFuturesOptionsFields.ASK_SIZE,
                StreamClient.LevelOneFuturesOptionsFields.CONTRACT_TYPE,
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
                'keys': './E3DM24P5490,./Q3DM24C19960',
                'fields': '0,4,5,28'
            }
        })

        socket.reset_mock()

        socket.recv.side_effect = [json.dumps(self.success_response(
            2, 'LEVELONE_FUTURES_OPTIONS', 'ADD'))]

        await self.client.level_one_futures_options_add(
            ['./OYMM24P38550'], fields=[
                StreamClient.LevelOneFuturesOptionsFields.BID_SIZE,
                StreamClient.LevelOneFuturesOptionsFields.ASK_SIZE,
                StreamClient.LevelOneFuturesOptionsFields.CONTRACT_TYPE,
            ])
        socket.recv.assert_awaited_once()
        request = self.request_from_socket_mock(socket)

        self.assertEqual(request, {
            'service': 'LEVELONE_FUTURES_OPTIONS',
            'command': 'ADD',
            'requestid': '2',
            'SchwabClientCustomerId': CLIENT_CUSTOMER_ID,
            'SchwabClientCorrelId': CLIENT_CORRELATION_ID,
            'parameters': {
                'keys': './OYMM24P38550',
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
                ['./E3DM24P5490', './Q3DM24C19960'])

    @no_duplicates
    @patch('schwab.streaming.ws_client.connect', new_callable=AsyncMock)
    async def test_level_one_futures_options_unsubs_failure(self, ws_connect):
        socket = await self.login_and_get_socket(ws_connect)

        response = self.success_response(1, 'LEVELONE_FUTURES_OPTIONS', 'UNSUBS')
        response['response'][0]['content']['code'] = 21
        socket.recv.side_effect = [json.dumps(response)]

        with self.assertRaises(schwab.streaming.UnexpectedResponseCode):
            await self.client.level_one_futures_options_unsubs(
                ['./E3DM24P5490', './Q3DM24C19960'])

    @no_duplicates
    @patch('schwab.streaming.ws_client.connect', new_callable=AsyncMock)
    async def test_level_one_futures_options_add_failure(self, ws_connect):
        socket = await self.login_and_get_socket(ws_connect)

        response = self.success_response(1, 'LEVELONE_FUTURES_OPTIONS', 'ADD')
        response['response'][0]['content']['code'] = 21
        socket.recv.side_effect = [json.dumps(response)]

        with self.assertRaises(schwab.streaming.UnexpectedResponseCode):
            await self.client.level_one_futures_options_add(['./OYMM24P38550'])

    @no_duplicates
    @patch('schwab.streaming.ws_client.connect', new_callable=AsyncMock)
    async def test_level_one_futures_options_handler(self, ws_connect):
        socket = await self.login_and_get_socket(ws_connect)

        stream_item = {
            'data': [{
                'service': 'LEVELONE_FUTURES_OPTIONS',
                'timestamp': 1718814961845,
                'command': 'SUBS',
                'content': [{
                    'key': './E3DM24P5490',
                    'delayed': False,
                    'assetMainType': 'FUTURE_OPTION',
                    '1': 9.6,
                    '2': 9.7,
                    '3': 9.7,
                    '4': 19,
                    '5': 19,
                    '6': 63,
                    '7': 63,
                    '8': 959,
                    '9': 22,
                    '10': 1718814960408,
                    '11': 1718814929433,
                    '12': 11,
                    '13': 7.8,
                    '14': 11,
                    '15': 63,
                    '16': 'E-mini S&P 500 Options',
                    '17': 10,
                    '18': 524,
                    '19': 9.65,
                    '20': 0.05,
                    '21': 2.5,
                    '22': 50,
                    '23': 11,
                    '24': '/ESM24',
                    '25': 5490,
                    '26': 1718856000000,
                    '27': 'Weeklys',
                    '28': 'P',
                    '29': 'Normal',
                    '30': '@',
                    '31': 'XCME'
                }, {
                    'key': './Q3DM24C19960',
                    'delayed': False,
                    'assetMainType': 'FUTURE_OPTION',
                    '1': 54.25,
                    '2': 56.5,
                    '3': 55.5,
                    '4': 15,
                    '5': 16,
                    '6': 63,
                    '7': 63,
                    '8': 15,
                    '9': 1,
                    '10': 1718814960411,
                    '11': 1718813651721,
                    '12': 61,
                    '13': 54.5,
                    '14': 41.25,
                    '15': 63,
                    '16': 'E-mini NASDAQ-100 Options',
                    '17': 55,
                    '18': 2,
                    '19': 55.75,
                    '20': 0.05,
                    '21': 1,
                    '22': 20,
                    '23': 41.25,
                    '24': '/NQM24',
                    '25': 19960,
                    '26': 1718856000000,
                    '27': 'Weeklys',
                    '28': 'C',
                    '29': 'Normal',
                    '30': '@',
                    '31': 'XCME'
                }]
            }]
        }

        socket.recv.side_effect = [
            json.dumps(self.success_response(
                1, 'LEVELONE_FUTURES_OPTIONS', 'SUBS')),
            json.dumps(stream_item)]
        await self.client.level_one_futures_options_subs(
            ['./E3DM24P5490', './Q3DM24C19960'])

        handler = Mock()
        async_handler = AsyncMock()
        self.client.add_level_one_futures_options_handler(handler)
        self.client.add_level_one_futures_options_handler(async_handler)
        await self.client.handle_message()

        expected_item = {
            'service': 'LEVELONE_FUTURES_OPTIONS',
            'timestamp': 1718814961845,
            'command': 'SUBS',
            'content': [{
                'key': './E3DM24P5490',
                'delayed': False,
                'assetMainType': 'FUTURE_OPTION',
                'BID_PRICE': 9.6,
                'ASK_PRICE': 9.7,
                'LAST_PRICE': 9.7,
                'BID_SIZE': 19,
                'ASK_SIZE': 19,
                'BID_ID': 63,
                'ASK_ID': 63,
                'TOTAL_VOLUME': 959,
                'LAST_SIZE': 22,
                'QUOTE_TIME_MILLIS': 1718814960408,
                'TRADE_TIME_MILLIS': 1718814929433,
                'HIGH_PRICE': 11,
                'LOW_PRICE': 7.8,
                'CLOSE_PRICE': 11,
                'LAST_ID': 63,
                'DESCRIPTION': 'E-mini S&P 500 Options',
                'OPEN_PRICE': 10,
                'OPEN_INTEREST': 524,
                'MARK': 9.65,
                'TICK': 0.05,
                'TICK_AMOUNT': 2.5,
                'FUTURE_MULTIPLIER': 50,
                'FUTURE_SETTLEMENT_PRICE': 11,
                'UNDERLYING_SYMBOL': '/ESM24',
                'STRIKE_PRICE': 5490,
                'FUTURE_EXPIRATION_DATE': 1718856000000,
                'EXPIRATION_STYLE': 'Weeklys',
                'CONTRACT_TYPE': 'P',
                'SECURITY_STATUS': 'Normal',
                'EXCHANGE_ID': '@',
                'EXCHANGE_NAME': 'XCME'
            }, {
                'key': './Q3DM24C19960',
                'delayed': False,
                'assetMainType': 'FUTURE_OPTION',
                'BID_PRICE': 54.25,
                'ASK_PRICE': 56.5,
                'LAST_PRICE': 55.5,
                'BID_SIZE': 15,
                'ASK_SIZE': 16,
                'BID_ID': 63,
                'ASK_ID': 63,
                'TOTAL_VOLUME': 15,
                'LAST_SIZE': 1,
                'QUOTE_TIME_MILLIS': 1718814960411,
                'TRADE_TIME_MILLIS': 1718813651721,
                'HIGH_PRICE': 61,
                'LOW_PRICE': 54.5,
                'CLOSE_PRICE': 41.25,
                'LAST_ID': 63,
                'DESCRIPTION': 'E-mini NASDAQ-100 Options',
                'OPEN_PRICE': 55,
                'OPEN_INTEREST': 2,
                'MARK': 55.75,
                'TICK': 0.05,
                'TICK_AMOUNT': 1,
                'FUTURE_MULTIPLIER': 20,
                'FUTURE_SETTLEMENT_PRICE': 41.25,
                'UNDERLYING_SYMBOL': '/NQM24',
                'STRIKE_PRICE': 19960,
                'FUTURE_EXPIRATION_DATE': 1718856000000,
                'EXPIRATION_STYLE': 'Weeklys',
                'CONTRACT_TYPE': 'C',
                'SECURITY_STATUS': 'Normal',
                'EXCHANGE_ID': '@',
                'EXCHANGE_NAME': 'XCME'
            }]
        }

        self.assert_handler_called_once_with(handler, expected_item)
        self.assert_handler_called_once_with(async_handler, expected_item)

    ##########################################################################
    # NYSE_BOOK

    @no_duplicates
    @patch('schwab.streaming.ws_client.connect', new_callable=AsyncMock)
    async def test_nyse_book_subs_success_and_add_all_fields(self, ws_connect):
        socket = await self.login_and_get_socket(ws_connect)

        socket.recv.side_effect = [json.dumps(self.success_response(
            1, 'NYSE_BOOK', 'SUBS'))]

        await self.client.nyse_book_subs(['GOOG', 'MSFT'])
        socket.recv.assert_awaited_once()
        request = self.request_from_socket_mock(socket)

        self.assertEqual(request, {
            'service': 'NYSE_BOOK',
            'command': 'SUBS',
            'requestid': '1',
            "SchwabClientCustomerId": CLIENT_CUSTOMER_ID,
            "SchwabClientCorrelId": CLIENT_CORRELATION_ID,
            'parameters': {
                'keys': 'GOOG,MSFT',
                'fields': '0,1,2,3'
            }
        })

        socket.reset_mock()

        socket.recv.side_effect = [json.dumps(self.success_response(
            2, 'NYSE_BOOK', 'ADD'))]

        await self.client.nyse_book_add(['INTC'])
        socket.recv.assert_awaited_once()
        request = self.request_from_socket_mock(socket)

        self.assertEqual(request, {
            'service': 'NYSE_BOOK',
            'command': 'ADD',
            'requestid': '2',
            'SchwabClientCustomerId': CLIENT_CUSTOMER_ID,
            'SchwabClientCorrelId': CLIENT_CORRELATION_ID,
            'parameters': {
                'keys': 'INTC',
                'fields': '0,1,2,3'
            }
        })

    @no_duplicates
    @patch('schwab.streaming.ws_client.connect', new_callable=AsyncMock)
    async def test_nyse_book_unsubs_success_all_fields(self, ws_connect):
        socket = await self.login_and_get_socket(ws_connect)

        stream_item = {'data': [{'service': 'NYSE_BOOK', 'command': 'SUBS', 'timestamp': REQUEST_TIMESTAMP, 'content': {}}]}

        socket.recv.side_effect = [
            json.dumps(self.success_response(1, 'NYSE_BOOK', 'SUBS')),
            json.dumps(stream_item),
            json.dumps(self.success_response(2, 'NYSE_BOOK', 'UNSUBS'))
        ]
        handler = Mock()
        async_handler = AsyncMock()
        self.client.add_nyse_book_handler(handler)
        self.client.add_nyse_book_handler(async_handler)

        await self.client.nyse_book_subs(['GOOG', 'MSFT'])
        await self.client.handle_message()
        await self.client.nyse_book_unsubs(['GOOG', 'MSFT'])

        self.assert_handler_called_once_with(
                handler, {'service': 'NYSE_BOOK',
                          'command': 'SUBS',
                          'timestamp': REQUEST_TIMESTAMP,
                          'content': {}})
        self.assert_handler_called_once_with(
                async_handler, {'service': 'NYSE_BOOK',
                                'command': 'SUBS',
                                'timestamp': REQUEST_TIMESTAMP,
                                'content': {}})
        send_awaited = [
            call(StringMatchesJson({
                "requests": [{
                    "service": "NYSE_BOOK",
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
                    "service": "NYSE_BOOK",
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
    async def test_nyse_book_subs_failure(self, ws_connect):
        socket = await self.login_and_get_socket(ws_connect)

        response = self.success_response(1, 'NYSE_BOOK', 'SUBS')
        response['response'][0]['content']['code'] = 21
        socket.recv.side_effect = [json.dumps(response)]

        with self.assertRaises(schwab.streaming.UnexpectedResponseCode):
            await self.client.nyse_book_subs(['GOOG', 'MSFT'])

    @no_duplicates
    @patch('schwab.streaming.ws_client.connect', new_callable=AsyncMock)
    async def test_nyse_book_unsubs_failure(self, ws_connect):
        socket = await self.login_and_get_socket(ws_connect)

        response = self.success_response(1, 'NYSE_BOOK', 'UNSUBS')
        response['response'][0]['content']['code'] = 21
        socket.recv.side_effect = [json.dumps(response)]

        with self.assertRaises(schwab.streaming.UnexpectedResponseCode):
            await self.client.nyse_book_unsubs(['GOOG', 'MSFT'])

    @no_duplicates
    @patch('schwab.streaming.ws_client.connect', new_callable=AsyncMock)
    async def test_nyse_book_add_failure(self, ws_connect):
        socket = await self.login_and_get_socket(ws_connect)

        response = self.success_response(1, 'NYSE_BOOK', 'ADD')
        response['response'][0]['content']['code'] = 21
        socket.recv.side_effect = [json.dumps(response)]

        with self.assertRaises(schwab.streaming.UnexpectedResponseCode):
            await self.client.nyse_book_add(['INTC'])

    ##########################################################################
    # NASDAQ_BOOK

    @no_duplicates
    @patch('schwab.streaming.ws_client.connect', new_callable=AsyncMock)
    async def test_nasdaq_book_subs_success_and_add_all_fields(self, ws_connect):
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

        socket.reset_mock()

        socket.recv.side_effect = [json.dumps(self.success_response(
            2, 'NASDAQ_BOOK', 'ADD'))]

        await self.client.nasdaq_book_add(['INTC'])
        socket.recv.assert_awaited_once()
        request = self.request_from_socket_mock(socket)

        self.assertEqual(request, {
            'service': 'NASDAQ_BOOK',
            'command': 'ADD',
            'requestid': '2',
            'SchwabClientCustomerId': CLIENT_CUSTOMER_ID,
            'SchwabClientCorrelId': CLIENT_CORRELATION_ID,
            'parameters': {
                'keys': 'INTC',
                'fields': '0,1,2,3'
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

    @no_duplicates
    @patch('schwab.streaming.ws_client.connect', new_callable=AsyncMock)
    async def test_nasdaq_book_add_failure(self, ws_connect):
        socket = await self.login_and_get_socket(ws_connect)

        response = self.success_response(1, 'NASDAQ_BOOK', 'ADD')
        response['response'][0]['content']['code'] = 21
        socket.recv.side_effect = [json.dumps(response)]

        with self.assertRaises(schwab.streaming.UnexpectedResponseCode):
            await self.client.nasdaq_book_add(['INTC'])

    ##########################################################################
    # OPTIONS_BOOK

    @no_duplicates
    @patch('schwab.streaming.ws_client.connect', new_callable=AsyncMock)
    async def test_options_book_subs_and_add_success_all_fields(self, ws_connect):
        socket = await self.login_and_get_socket(ws_connect)

        socket.recv.side_effect = [json.dumps(self.success_response(
            1, 'OPTIONS_BOOK', 'SUBS'))]

        await self.client.options_book_subs(
            ['GOOG  240517C00070000', 'MSFT  240517C00160000'])
        socket.recv.assert_awaited_once()
        request = self.request_from_socket_mock(socket)

        self.assertEqual(request, {
            'service': 'OPTIONS_BOOK',
            'command': 'SUBS',
            'requestid': '1',
            "SchwabClientCustomerId": CLIENT_CUSTOMER_ID,
            "SchwabClientCorrelId": CLIENT_CORRELATION_ID,
            'parameters': {
                'keys': 'GOOG  240517C00070000,MSFT  240517C00160000',
                'fields': '0,1,2,3'
            }
        })

        socket.reset_mock()

        socket.recv.side_effect = [json.dumps(self.success_response(
            2, 'OPTIONS_BOOK', 'ADD'))]

        await self.client.options_book_add(['ADBE  240614C00500000'])
        socket.recv.assert_awaited_once()
        request = self.request_from_socket_mock(socket)

        self.assertEqual(request, {
            'service': 'OPTIONS_BOOK',
            'command': 'ADD',
            'requestid': '2',
            'SchwabClientCustomerId': CLIENT_CUSTOMER_ID,
            'SchwabClientCorrelId': CLIENT_CORRELATION_ID,
            'parameters': {
                'keys': 'ADBE  240614C00500000',
                'fields': '0,1,2,3'
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
            ['GOOG  240517C00070000', 'MSFT  240517C00160000'])
        await self.client.handle_message()
        await self.client.options_book_unsubs(
            ['GOOG  240517C00070000', 'MSFT  240517C00160000'])

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
                        "keys": "GOOG  240517C00070000,MSFT  240517C00160000",
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
                        "keys": "GOOG  240517C00070000,MSFT  240517C00160000"
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
                ['GOOG  240517C00070000', 'MSFT  240517C00160000'])

    @no_duplicates
    @patch('schwab.streaming.ws_client.connect', new_callable=AsyncMock)
    async def test_options_book_unsubs_failure(self, ws_connect):
        socket = await self.login_and_get_socket(ws_connect)

        response = self.success_response(1, 'OPTIONS_BOOK', 'UNSUBS')
        response['response'][0]['content']['code'] = 21
        socket.recv.side_effect = [json.dumps(response)]

        with self.assertRaises(schwab.streaming.UnexpectedResponseCode):
            await self.client.options_book_unsubs(
                ['GOOG  240517C00070000', 'MSFT  240517C00160000'])

    @no_duplicates
    @patch('schwab.streaming.ws_client.connect', new_callable=AsyncMock)
    async def test_options_book_add_failure(self, ws_connect):
        socket = await self.login_and_get_socket(ws_connect)

        response = self.success_response(1, 'OPTIONS_BOOK', 'ADD')
        response['response'][0]['content']['code'] = 21
        socket.recv.side_effect = [json.dumps(response)]

        with self.assertRaises(schwab.streaming.UnexpectedResponseCode):
            await self.client.options_book_add(['ADBE  240614C00500000'])

    ##########################################################################
    # Common book handler functionality

    @no_duplicates
    @patch('schwab.streaming.ws_client.connect', new_callable=AsyncMock)
    async def test_nyse_book_handler(self, ws_connect):
        async def subs():
            await self.client.nyse_book_subs(['GOOG', 'MSFT'])

        def register_handler():
            handler = Mock()
            async_handler = AsyncMock()
            self.client.add_nyse_book_handler(handler)
            self.client.add_nyse_book_handler(async_handler)
            return handler, async_handler

        return await self.__test_book_handler(
            ws_connect, 'NYSE_BOOK', subs, register_handler)

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
    # SCREENER_EQUITY

    @no_duplicates
    @patch('schwab.streaming.ws_client.connect', new_callable=AsyncMock)
    async def test_screener_equity_subs_and_add_success_all_fields(
            self, ws_connect):
        socket = await self.login_and_get_socket(ws_connect)

        socket.recv.side_effect = [json.dumps(self.success_response(
            1, 'SCREENER_EQUITY', 'SUBS'))]

        await self.client.screener_equity_subs(['NYSE_VOLUME_5', 'NASDAQ_VOLUME_5'])
        socket.recv.assert_awaited_once()
        request = self.request_from_socket_mock(socket)

        self.assertEqual(request, {
            'service': 'SCREENER_EQUITY',
            'command': 'SUBS',
            'requestid': '1',
            'SchwabClientCustomerId': self.pref_customer_id,
            'SchwabClientCorrelId': self.pref_correl_id,
            'parameters': {
                'keys': 'NYSE_VOLUME_5,NASDAQ_VOLUME_5',
                'fields': '0,1,2,3,4'
            }
        })

        socket.reset_mock()

        socket.recv.side_effect = [json.dumps(self.success_response(
            2, 'SCREENER_EQUITY', 'ADD'))]

        await self.client.screener_equity_add(['$DJI_TRADES_10'])
        socket.recv.assert_awaited_once()
        request = self.request_from_socket_mock(socket)

        self.assertEqual(request, {
            'service': 'SCREENER_EQUITY',
            'command': 'ADD',
            'requestid': '2',
            'SchwabClientCustomerId': self.pref_customer_id,
            'SchwabClientCorrelId': self.pref_correl_id,
            'parameters': {
                'keys': '$DJI_TRADES_10',
                'fields': '0,1,2,3,4'
            }
        })

    @no_duplicates
    @patch('schwab.streaming.ws_client.connect', new_callable=AsyncMock)
    async def test_screener_equity_unsubs_success_all_fields(
            self, ws_connect):
        socket = await self.login_and_get_socket(ws_connect)

        stream_item = self.streaming_entry('SCREENER_EQUITY', 'SUBS')

        socket.recv.side_effect = [
            json.dumps(self.success_response(1, 'SCREENER_EQUITY', 'SUBS')),
            json.dumps(stream_item),
            json.dumps(self.success_response(2, 'SCREENER_EQUITY', 'UNSUBS', 'UNSUBS command succeeded'))
        ]
        handler = Mock()
        async_handler = AsyncMock()
        self.client.add_screener_equity_handler(handler)
        self.client.add_screener_equity_handler(async_handler)

        await self.client.screener_equity_subs(['NYSE_VOLUME_5', 'NASDAQ_VOLUME_5'])
        await self.client.handle_message()
        await self.client.screener_equity_unsubs(['NYSE_VOLUME_5', 'NASDAQ_VOLUME_5'])

        self.assert_handler_called_once_with(
                handler, {'service': 'SCREENER_EQUITY',
                          'command': 'SUBS',
                          'timestamp': REQUEST_TIMESTAMP})
        self.assert_handler_called_once_with(
                async_handler, {'service': 'SCREENER_EQUITY',
                                'command': 'SUBS',
                                'timestamp': REQUEST_TIMESTAMP})

        send_awaited = [
            call(StringMatchesJson({
                'requests': [{
                    'service': 'SCREENER_EQUITY',
                    'requestid': '1',
                    'command': 'SUBS',
                    'SchwabClientCustomerId': CLIENT_CUSTOMER_ID,
                    'SchwabClientCorrelId': CLIENT_CORRELATION_ID,
                    'parameters': {
                        'keys': 'NYSE_VOLUME_5,NASDAQ_VOLUME_5',
                        'fields': '0,1,2,3,4'
                    }
                }]
            })),
            call(StringMatchesJson({
                'requests': [{
                    'service': 'SCREENER_EQUITY',
                    'requestid': '2',
                    'command': 'UNSUBS',
                    'SchwabClientCustomerId': CLIENT_CUSTOMER_ID,
                    'SchwabClientCorrelId': CLIENT_CORRELATION_ID,
                    'parameters': {
                        'keys': 'NYSE_VOLUME_5,NASDAQ_VOLUME_5'
                    }
                }]
            })),
        ]
        socket.send.assert_has_awaits(send_awaited, any_order=False)

    @no_duplicates
    @patch('schwab.streaming.ws_client.connect', new_callable=AsyncMock)
    async def test_screener_equity_subs_failure(self, ws_connect):
        socket = await self.login_and_get_socket(ws_connect)

        response = self.success_response(1, 'SCREENER_EQUITY', 'SUBS')
        response['response'][0]['content']['code'] = 21
        socket.recv.side_effect = [json.dumps(response)]

        with self.assertRaises(schwab.streaming.UnexpectedResponseCode):
            await self.client.screener_equity_subs(['NYSE_VOLUME_5', 'NASDAQ_VOLUME_5'])

    @no_duplicates
    @patch('schwab.streaming.ws_client.connect', new_callable=AsyncMock)
    async def test_screener_equity_unsubs_failure(self, ws_connect):
        socket = await self.login_and_get_socket(ws_connect)

        response = self.success_response(1, 'SCREENER_EQUITY', 'UNSUBS')
        response['response'][0]['content']['code'] = 21
        socket.recv.side_effect = [json.dumps(response)]

        with self.assertRaises(schwab.streaming.UnexpectedResponseCode):
            await self.client.screener_equity_unsubs(['NYSE_VOLUME_5', 'NASDAQ_VOLUME_5'])

    @no_duplicates
    @patch('schwab.streaming.ws_client.connect', new_callable=AsyncMock)
    async def test_screener_equity_add_failure(self, ws_connect):
        socket = await self.login_and_get_socket(ws_connect)

        response = self.success_response(1, 'SCREENER_EQUITY', 'ADD')
        response['response'][0]['content']['code'] = 21
        socket.recv.side_effect = [json.dumps(response)]

        with self.assertRaises(schwab.streaming.UnexpectedResponseCode):
            await self.client.screener_equity_add(['$DJI_TRADES_10'])

    @no_duplicates
    @patch('schwab.streaming.ws_client.connect', new_callable=AsyncMock)
    async def test_screener_equity_handler(self, ws_connect):
        socket = await self.login_and_get_socket(ws_connect)

        stream_item = {
            'data': [{
                'service': 'SCREENER_EQUITY',
                'timestamp': 1718996308740,
                'command': 'SUBS',
                'content': [{
                    'key': 'NYSE_VOLUME_5',
                    '1': 1718996308700,
                    '2': 'VOLUME',
                    '3': 5,
                    '4': [{
                        'symbol': 'XLF',
                        'description': 'SELECT STR FINANCIAL SELECT SPDR ETF',
                        'lastPrice': 41.305,
                        'netChange': 41.305,
                        'netPercentChange': 1,
                        'marketShare': 3.40228332,
                        'totalVolume': 51730877,
                        'volume': 1760031,
                        'trades': 644
                    }, {
                        'symbol': 'HYG',
                        'description': 'ISHARES IBOXX HIGH YIELD BOND ETF',
                        'lastPrice': 77.34,
                        'netChange': 77.34,
                        'netPercentChange': 1,
                        'marketShare': 2.10192454,
                        'totalVolume': 51730877,
                        'volume': 1087344,
                        'trades': 354
                    }, {
                        'symbol': 'CX',
                        'description': 'Cemex Sab De C V ADR',
                        'lastPrice': 6.26,
                        'netChange': 6.26,
                        'netPercentChange': 1,
                        'marketShare': 1.93456028,
                        'totalVolume': 51730877,
                        'volume': 1000765,
                        'trades': 825
                    }, {
                        'symbol': 'ABEV',
                        'description': 'Ambev S A ADR',
                        'lastPrice': 2.05,
                        'netChange': 2.05,
                        'netPercentChange': 1,
                        'marketShare': 1.84930559,
                        'totalVolume': 51730877,
                        'volume': 956662,
                        'trades': 1598
                    }, {
                        'symbol': 'CHPT',
                        'description': 'Chargepoint Holdings A',
                        'lastPrice': 1.365,
                        'netChange': 1.365,
                        'netPercentChange': 1,
                        'marketShare': 1.73645809,
                        'totalVolume': 51730877,
                        'volume': 898285,
                        'trades': 1024
                    }, {
                        'symbol': 'GME',
                        'description': 'Gamestop Corp A',
                        'lastPrice': 23.78,
                        'netChange': 23.78,
                        'netPercentChange': 1,
                        'marketShare': 1.28934021,
                        'totalVolume': 51730877,
                        'volume': 666987,
                        'trades': 5590
                    }, {
                        'symbol': 'DNA',
                        'description': 'GINKGO BIOWORKS HLDG A',
                        'lastPrice': 0.4151,
                        'netChange': 0.4151,
                        'netPercentChange': 1,
                        'marketShare': 0.93249917,
                        'totalVolume': 51730877,
                        'volume': 482390,
                        'trades': 880
                    }, {
                        'symbol': 'TELL',
                        'description': 'Tellurian Investment',
                        'lastPrice': 0.6347,
                        'netChange': 0.6347,
                        'netPercentChange': 1,
                        'marketShare': 0.84341311,
                        'totalVolume': 51730877,
                        'volume': 436305,
                        'trades': 378
                    }, {
                        'symbol': 'KVUE',
                        'description': 'KENVUE Inc',
                        'lastPrice': 18.775,
                        'netChange': 18.775,
                        'netPercentChange': 1,
                        'marketShare': 0.82902519,
                        'totalVolume': 51730877,
                        'volume': 428862,
                        'trades': 1654
                    }, {
                        'symbol': 'DNN',
                        'description': 'DENISON MINES CORP',
                        'lastPrice': 2.02,
                        'netChange': 2.02,
                        'netPercentChange': 1,
                        'marketShare': 0.82405717,
                        'totalVolume': 51730877,
                        'volume': 426292,
                        'trades': 270
                    }]
                }, {
                    'key': 'NASDAQ_VOLUME_5',
                    '1': 1718996308714,
                    '2': 'VOLUME',
                    '3': 5,
                    '4': [{
                        'symbol': 'NVDA',
                        'description': 'Nvidia Corp',
                        'lastPrice': 126.5299,
                        'netChange': 126.5299,
                        'netPercentChange': 1,
                        'marketShare': 5.84329551,
                        'totalVolume': 41090169,
                        'volume': 2401020,
                        'trades': 18452
                    },
                    {
                        'symbol': 'AREB',
                        'description': 'AMERICAN REBEL HLDGS',
                        'lastPrice': 0.7776,
                        'netChange': 0.7776,
                        'netPercentChange': 1,
                        'marketShare': 4.2931729,
                        'totalVolume': 41090169,
                        'volume': 1764072,
                        'trades': 2192
                    },
                    {
                        'symbol': 'KTRA',
                        'description': 'KINTARA THERAPEUTICS',
                        'lastPrice': 0.25335,
                        'netChange': 0.25335,
                        'netPercentChange': 1,
                        'marketShare': 2.12389976,
                        'totalVolume': 41090169,
                        'volume': 872714,
                        'trades': 333
                    },
                    {
                        'symbol': 'AAPL',
                        'description': 'Apple Inc',
                        'lastPrice': 210.2967,
                        'netChange': 210.2967,
                        'netPercentChange': 1,
                        'marketShare': 1.71872012,
                        'totalVolume': 41090169,
                        'volume': 706225,
                        'trades': 7024
                    },
                    {
                        'symbol': 'NKLA',
                        'description': 'NIKOLA CORP',
                        'lastPrice': 0.359,
                        'netChange': 0.359,
                        'netPercentChange': 1,
                        'marketShare': 1.64388226,
                        'totalVolume': 41090169,
                        'volume': 675474,
                        'trades': 1016
                    },
                    {
                        'symbol': 'SHCR',
                        'description': 'SHARECARE INC A',
                        'lastPrice': 1.365,
                        'netChange': 1.365,
                        'netPercentChange': 1,
                        'marketShare': 1.6360288,
                        'totalVolume': 41090169,
                        'volume': 672247,
                        'trades': 265
                    },
                    {
                        'symbol': 'SIRI',
                        'description': 'Sirius Xm Hldgs Inc',
                        'lastPrice': 2.995,
                        'netChange': 2.995,
                        'netPercentChange': 1,
                        'marketShare': 1.63058224,
                        'totalVolume': 41090169,
                        'volume': 670009,
                        'trades': 983
                    },
                    {
                        'symbol': 'CRKN',
                        'description': 'Crown Electrokinetic',
                        'lastPrice': 0.0401,
                        'netChange': 0.0401,
                        'netPercentChange': 1,
                        'marketShare': 1.34467201,
                        'totalVolume': 41090169,
                        'volume': 552528,
                        'trades': 885
                    },
                    {
                        'symbol': 'TSLA',
                        'description': 'Tesla Inc',
                        'lastPrice': 181.4049,
                        'netChange': 181.4049,
                        'netPercentChange': 1,
                        'marketShare': 1.0218454,
                        'totalVolume': 41090169,
                        'volume': 419878,
                        'trades': 4613
                    },
                    {
                        'symbol': 'WBD',
                        'description': 'Warner Brothers Disc',
                        'lastPrice': 7.125,
                        'netChange': 7.125,
                        'netPercentChange': 1,
                        'marketShare': 0.89736793,
                        'totalVolume': 41090169,
                        'volume': 368730,
                        'trades': 1249
                    }]
                }]
            }]
        }

        socket.recv.side_effect = [
            json.dumps(self.success_response(
                1, 'SCREENER_EQUITY', 'SUBS')),
            json.dumps(stream_item)]
        await self.client.screener_equity_subs(['NYSE_VOLUME_5', 'NASDAQ_VOLUME_5'])

        handler = Mock()
        async_handler = AsyncMock()
        self.client.add_screener_equity_handler(handler)
        self.client.add_screener_equity_handler(async_handler)
        await self.client.handle_message()

        expected_item = {
            'service': 'SCREENER_EQUITY',
            'timestamp': 1718996308740,
            'command': 'SUBS',
            'content': [{
                'key': 'NYSE_VOLUME_5',
                'TIMESTAMP': 1718996308700,
                'SORT_FIELD': 'VOLUME',
                'FREQUENCY': 5,
                'ITEMS': [{
                    'symbol': 'XLF',
                    'description': 'SELECT STR FINANCIAL SELECT SPDR ETF',
                    'lastPrice': 41.305,
                    'netChange': 41.305,
                    'netPercentChange': 1,
                    'marketShare': 3.40228332,
                    'totalVolume': 51730877,
                    'volume': 1760031,
                    'trades': 644
                }, {
                    'symbol': 'HYG',
                    'description': 'ISHARES IBOXX HIGH YIELD BOND ETF',
                    'lastPrice': 77.34,
                    'netChange': 77.34,
                    'netPercentChange': 1,
                    'marketShare': 2.10192454,
                    'totalVolume': 51730877,
                    'volume': 1087344,
                    'trades': 354
                }, {
                    'symbol': 'CX',
                    'description': 'Cemex Sab De C V ADR',
                    'lastPrice': 6.26,
                    'netChange': 6.26,
                    'netPercentChange': 1,
                    'marketShare': 1.93456028,
                    'totalVolume': 51730877,
                    'volume': 1000765,
                    'trades': 825
                }, {
                    'symbol': 'ABEV',
                    'description': 'Ambev S A ADR',
                    'lastPrice': 2.05,
                    'netChange': 2.05,
                    'netPercentChange': 1,
                    'marketShare': 1.84930559,
                    'totalVolume': 51730877,
                    'volume': 956662,
                    'trades': 1598
                },{
                    'symbol': 'CHPT',
                    'description': 'Chargepoint Holdings A',
                    'lastPrice': 1.365,
                    'netChange': 1.365,
                    'netPercentChange': 1,
                    'marketShare': 1.73645809,
                    'totalVolume': 51730877,
                    'volume': 898285,
                    'trades': 1024
                }, {
                    'symbol': 'GME',
                    'description': 'Gamestop Corp A',
                    'lastPrice': 23.78,
                    'netChange': 23.78,
                    'netPercentChange': 1,
                    'marketShare': 1.28934021,
                    'totalVolume': 51730877,
                    'volume': 666987,
                    'trades': 5590
                }, {
                    'symbol': 'DNA',
                    'description': 'GINKGO BIOWORKS HLDG A',
                    'lastPrice': 0.4151,
                    'netChange': 0.4151,
                    'netPercentChange': 1,
                    'marketShare': 0.93249917,
                    'totalVolume': 51730877,
                    'volume': 482390,
                    'trades': 880
                }, {
                    'symbol': 'TELL',
                    'description': 'Tellurian Investment',
                    'lastPrice': 0.6347,
                    'netChange': 0.6347,
                    'netPercentChange': 1,
                    'marketShare': 0.84341311,
                    'totalVolume': 51730877,
                    'volume': 436305,
                    'trades': 378
                }, {
                    'symbol': 'KVUE',
                    'description': 'KENVUE Inc',
                    'lastPrice': 18.775,
                    'netChange': 18.775,
                    'netPercentChange': 1,
                    'marketShare': 0.82902519,
                    'totalVolume': 51730877,
                    'volume': 428862,
                    'trades': 1654
                }, {
                    'symbol': 'DNN',
                    'description': 'DENISON MINES CORP',
                    'lastPrice': 2.02,
                    'netChange': 2.02,
                    'netPercentChange': 1,
                    'marketShare': 0.82405717,
                    'totalVolume': 51730877,
                    'volume': 426292,
                    'trades': 270
                }]
            }, {
                'key': 'NASDAQ_VOLUME_5',
                'TIMESTAMP': 1718996308714,
                'SORT_FIELD': 'VOLUME',
                'FREQUENCY': 5,
                'ITEMS': [{
                    'symbol': 'NVDA',
                    'description': 'Nvidia Corp',
                    'lastPrice': 126.5299,
                    'netChange': 126.5299,
                    'netPercentChange': 1,
                    'marketShare': 5.84329551,
                    'totalVolume': 41090169,
                    'volume': 2401020,
                    'trades': 18452
                }, {
                    'symbol': 'AREB',
                    'description': 'AMERICAN REBEL HLDGS',
                    'lastPrice': 0.7776,
                    'netChange': 0.7776,
                    'netPercentChange': 1,
                    'marketShare': 4.2931729,
                    'totalVolume': 41090169,
                    'volume': 1764072,
                    'trades': 2192
                }, {
                    'symbol': 'KTRA',
                    'description': 'KINTARA THERAPEUTICS',
                    'lastPrice': 0.25335,
                    'netChange': 0.25335,
                    'netPercentChange': 1,
                    'marketShare': 2.12389976,
                    'totalVolume': 41090169,
                    'volume': 872714,
                    'trades': 333
                }, {
                    'symbol': 'AAPL',
                    'description': 'Apple Inc',
                    'lastPrice': 210.2967,
                    'netChange': 210.2967,
                    'netPercentChange': 1,
                    'marketShare': 1.71872012,
                    'totalVolume': 41090169,
                    'volume': 706225,
                    'trades': 7024
                }, {
                    'symbol': 'NKLA',
                    'description': 'NIKOLA CORP',
                    'lastPrice': 0.359,
                    'netChange': 0.359,
                    'netPercentChange': 1,
                    'marketShare': 1.64388226,
                    'totalVolume': 41090169,
                    'volume': 675474,
                    'trades': 1016
                }, {
                    'symbol': 'SHCR',
                    'description': 'SHARECARE INC A',
                    'lastPrice': 1.365,
                    'netChange': 1.365,
                    'netPercentChange': 1,
                    'marketShare': 1.6360288,
                    'totalVolume': 41090169,
                    'volume': 672247,
                    'trades': 265
                }, {
                    'symbol': 'SIRI',
                    'description': 'Sirius Xm Hldgs Inc',
                    'lastPrice': 2.995,
                    'netChange': 2.995,
                    'netPercentChange': 1,
                    'marketShare': 1.63058224,
                    'totalVolume': 41090169,
                    'volume': 670009,
                    'trades': 983
                }, {
                    'symbol': 'CRKN',
                    'description': 'Crown Electrokinetic',
                    'lastPrice': 0.0401,
                    'netChange': 0.0401,
                    'netPercentChange': 1,
                    'marketShare': 1.34467201,
                    'totalVolume': 41090169,
                    'volume': 552528,
                    'trades': 885
                }, {
                    'symbol': 'TSLA',
                    'description': 'Tesla Inc',
                    'lastPrice': 181.4049,
                    'netChange': 181.4049,
                    'netPercentChange': 1,
                    'marketShare': 1.0218454,
                    'totalVolume': 41090169,
                    'volume': 419878,
                    'trades': 4613
                }, {
                    'symbol': 'WBD',
                    'description': 'Warner Brothers Disc',
                    'lastPrice': 7.125,
                    'netChange': 7.125,
                    'netPercentChange': 1,
                    'marketShare': 0.89736793,
                    'totalVolume': 41090169,
                    'volume': 368730,
                    'trades': 1249
                }]
            }]
        }

        self.assert_handler_called_once_with(handler, expected_item)
        self.assert_handler_called_once_with(async_handler, expected_item)

    ##########################################################################
    # SCREENER_OPTION

    @no_duplicates
    @patch('schwab.streaming.ws_client.connect', new_callable=AsyncMock)
    async def test_screener_option_subs_and_add_success_all_fields(
            self, ws_connect):
        socket = await self.login_and_get_socket(ws_connect)

        socket.recv.side_effect = [json.dumps(self.success_response(
            1, 'SCREENER_OPTION', 'SUBS'))]

        await self.client.screener_option_subs(['OPTION_PUT_VOLUME_5', 'OPTION_CALL_VOLUME_5'])
        socket.recv.assert_awaited_once()
        request = self.request_from_socket_mock(socket)

        self.assertEqual(request, {
            'service': 'SCREENER_OPTION',
            'command': 'SUBS',
            'requestid': '1',
            'SchwabClientCustomerId': self.pref_customer_id,
            'SchwabClientCorrelId': self.pref_correl_id,
            'parameters': {
                'keys': 'OPTION_PUT_VOLUME_5,OPTION_CALL_VOLUME_5',
                'fields': '0,1,2,3,4'
            }
        })

        socket.reset_mock()

        socket.recv.side_effect = [json.dumps(self.success_response(
            2, 'SCREENER_OPTION', 'ADD'))]

        await self.client.screener_option_add(['OPTION_ALL_TRADES_10'])
        socket.recv.assert_awaited_once()
        request = self.request_from_socket_mock(socket)

        self.assertEqual(request, {
            'service': 'SCREENER_OPTION',
            'command': 'ADD',
            'requestid': '2',
            'SchwabClientCustomerId': self.pref_customer_id,
            'SchwabClientCorrelId': self.pref_correl_id,
            'parameters': {
                'keys': 'OPTION_ALL_TRADES_10',
                'fields': '0,1,2,3,4'
            }
        })

    @no_duplicates
    @patch('schwab.streaming.ws_client.connect', new_callable=AsyncMock)
    async def test_screener_option_unsubs_success_all_fields(
            self, ws_connect):
        socket = await self.login_and_get_socket(ws_connect)

        stream_item = self.streaming_entry('SCREENER_OPTION', 'SUBS')

        socket.recv.side_effect = [
            json.dumps(self.success_response(1, 'SCREENER_OPTION', 'SUBS')),
            json.dumps(stream_item),
            json.dumps(self.success_response(2, 'SCREENER_OPTION', 'UNSUBS', 'UNSUBS command succeeded'))
        ]
        handler = Mock()
        async_handler = AsyncMock()
        self.client.add_screener_option_handler(handler)
        self.client.add_screener_option_handler(async_handler)

        await self.client.screener_option_subs(['OPTION_PUT_VOLUME_5', 'OPTION_CALL_VOLUME_5'])
        await self.client.handle_message()
        await self.client.screener_option_unsubs(['OPTION_PUT_VOLUME_5', 'OPTION_CALL_VOLUME_5'])

        self.assert_handler_called_once_with(
                handler, {'service': 'SCREENER_OPTION',
                          'command': 'SUBS',
                          'timestamp': REQUEST_TIMESTAMP})
        self.assert_handler_called_once_with(
                async_handler, {'service': 'SCREENER_OPTION',
                                'command': 'SUBS',
                                'timestamp': REQUEST_TIMESTAMP})

        send_awaited = [
            call(StringMatchesJson({
                'requests': [{
                    'service': 'SCREENER_OPTION',
                    'requestid': '1',
                    'command': 'SUBS',
                    'SchwabClientCustomerId': CLIENT_CUSTOMER_ID,
                    'SchwabClientCorrelId': CLIENT_CORRELATION_ID,
                    'parameters': {
                        'keys': 'OPTION_PUT_VOLUME_5,OPTION_CALL_VOLUME_5',
                        'fields': '0,1,2,3,4'
                    }
                }]
            })),
            call(StringMatchesJson({
                'requests': [{
                    'service': 'SCREENER_OPTION',
                    'requestid': '2',
                    'command': 'UNSUBS',
                    'SchwabClientCustomerId': CLIENT_CUSTOMER_ID,
                    'SchwabClientCorrelId': CLIENT_CORRELATION_ID,
                    'parameters': {
                        'keys': 'OPTION_PUT_VOLUME_5,OPTION_CALL_VOLUME_5'
                    }
                }]
            })),
        ]
        socket.send.assert_has_awaits(send_awaited, any_order=False)

    @no_duplicates
    @patch('schwab.streaming.ws_client.connect', new_callable=AsyncMock)
    async def test_screener_option_subs_failure(self, ws_connect):
        socket = await self.login_and_get_socket(ws_connect)

        response = self.success_response(1, 'SCREENER_OPTION', 'SUBS')
        response['response'][0]['content']['code'] = 21
        socket.recv.side_effect = [json.dumps(response)]

        with self.assertRaises(schwab.streaming.UnexpectedResponseCode):
            await self.client.screener_option_subs(['OPTION_PUT_VOLUME_5', 'OPTION_CALL_VOLUME_5'])

    @no_duplicates
    @patch('schwab.streaming.ws_client.connect', new_callable=AsyncMock)
    async def test_screener_option_unsubs_failure(self, ws_connect):
        socket = await self.login_and_get_socket(ws_connect)

        response = self.success_response(1, 'SCREENER_OPTION', 'UNSUBS')
        response['response'][0]['content']['code'] = 21
        socket.recv.side_effect = [json.dumps(response)]

        with self.assertRaises(schwab.streaming.UnexpectedResponseCode):
            await self.client.screener_option_unsubs(['OPTION_PUT_VOLUME_5', 'OPTION_CALL_VOLUME_5'])

    @no_duplicates
    @patch('schwab.streaming.ws_client.connect', new_callable=AsyncMock)
    async def test_screener_option_add_failure(self, ws_connect):
        socket = await self.login_and_get_socket(ws_connect)

        response = self.success_response(1, 'SCREENER_OPTION', 'ADD')
        response['response'][0]['content']['code'] = 21
        socket.recv.side_effect = [json.dumps(response)]

        with self.assertRaises(schwab.streaming.UnexpectedResponseCode):
            await self.client.screener_option_add(['OPTION_ALL_TRADES_10'])

    @no_duplicates
    @patch('schwab.streaming.ws_client.connect', new_callable=AsyncMock)
    async def test_screener_option_handler(self, ws_connect):
        socket = await self.login_and_get_socket(ws_connect)

        stream_item = {
            'data': [{
                'service': 'SCREENER_OPTION',
                'timestamp': 1718996045319,
                'command': 'SUBS',
                'content': [{
                    'key': 'OPTION_PUT_VOLUME_5',
                    '1': 1718996045310,
                    '2': 'VOLUME',
                    '3': 5,
                    '4': [{
                        'symbol': 'SPY   240621P00541000',
                        'description': 'SPY    Jun 21 2024 541.0 Put',
                        'lastPrice': 0.02,
                        'netChange': -0.275,
                        'netPercentChange': -0.93220339,
                        'marketShare': 9.01754274,
                        'totalVolume': 218951,
                        'volume': 19744,
                        'trades': 151
                    }, {
                        'symbol': 'SPY   240816P00514000',
                        'description': 'SPY    Aug 16 2024 514.0 Put',
                        'lastPrice': 2.31,
                        'netChange': -0.045,
                        'netPercentChange': -0.01910828,
                        'marketShare': 2.84995273,
                        'totalVolume': 218951,
                        'volume': 6240,
                        'trades': 3
                    }, {
                        'symbol': 'NVDA  240621P00130000',
                        'description': 'NVDA   Jun 21 2024 130.0 Put',
                        'lastPrice': 3.35,
                        'netChange': 1.895,
                        'netPercentChange': 1.3024055,
                        'marketShare': 2.6544752,
                        'totalVolume': 218951,
                        'volume': 5812,
                        'trades': 213
                    }, {
                        'symbol': 'SPY   240621P00542000',
                        'description': 'SPY    Jun 21 2024 542.0 Put',
                        'lastPrice': 0.05,
                        'netChange': -0.395,
                        'netPercentChange': -0.88764045,
                        'marketShare': 2.44940649,
                        'totalVolume': 218951,
                        'volume': 5363,
                        'trades': 108
                    }, {
                        'symbol': 'SPY   240621P00544000',
                        'description': 'SPY    Jun 21 2024 544.0 Put',
                        'lastPrice': 0.38,
                        'netChange': -0.565,
                        'netPercentChange': -0.5978836,
                        'marketShare': 2.34481688,
                        'totalVolume': 218951,
                        'volume': 5134,
                        'trades': 427
                    }, {
                        'symbol': 'NVDA  240621P00125000',
                        'description': 'NVDA   Jun 21 2024 125.0 Put',
                        'lastPrice': 0.19,
                        'netChange': -0.1956,
                        'netPercentChange': -0.50726141,
                        'marketShare': 2.0223703,
                        'totalVolume': 218951,
                        'volume': 4428,
                        'trades': 526
                    }, {
                        'symbol': 'NVDA  240621P00126000',
                        'description': 'NVDA   Jun 21 2024 126.0 Put',
                        'lastPrice': 0.47,
                        'netChange': -0.06,
                        'netPercentChange': -0.11320755,
                        'marketShare': 1.62821819,
                        'totalVolume': 218951,
                        'volume': 3565,
                        'trades': 367
                    }, {
                        'symbol': 'SPY   240816P00530000',
                        'description': 'SPY    Aug 16 2024 530.0 Put',
                        'lastPrice': 4.33,
                        'netChange': 0.0296,
                        'netPercentChange': 0.00688308,
                        'marketShare': 1.42863015,
                        'totalVolume': 218951,
                        'volume': 3128,
                        'trades': 7
                    }, {
                        'symbol': 'QQQ   240621P00480000',
                        'description': 'QQQ    Jun 21 2024 480.0 Put',
                        'lastPrice': 0.51,
                        'netChange': -0.7029,
                        'netPercentChange': -0.57952016,
                        'marketShare': 1.25918585,
                        'totalVolume': 218951,
                        'volume': 2757,
                        'trades': 197
                    }, {
                        'symbol': 'SPY   240621P00543000',
                        'description': 'SPY    Jun 21 2024 543.0 Put',
                        'lastPrice': 0.14,
                        'netChange': -0.515,
                        'netPercentChange': -0.78625954,
                        'marketShare': 1.23909002,
                        'totalVolume': 218951,
                        'volume': 2713,
                        'trades': 237
                    }]
                }, {
                    'key': 'OPTION_CALL_VOLUME_5',
                    '1': 1718996045320,
                    '2': 'VOLUME',
                    '3': 5,
                    '4': [{
                        'symbol': 'SPY   240621C00546000',
                        'description': 'SPY    Jun 21 2024 546.0 Call',
                        'lastPrice': 0.07,
                        'netChange': -1.1656,
                        'netPercentChange': -0.94334736,
                        'marketShare': 3.07333386,
                        'totalVolume': 276898,
                        'volume': 8510,
                        'trades': 280
                    }, {
                        'symbol': 'SPY   240621C00545000',
                        'description': 'SPY    Jun 21 2024 545.0 Call',
                        'lastPrice': 0.25,
                        'netChange': -1.75,
                        'netPercentChange': -0.875,
                        'marketShare': 2.45613908,
                        'totalVolume': 276898,
                        'volume': 6801,
                        'trades': 503
                    }, {
                        'symbol': 'SIRI  240621C00003000',
                        'description': 'SIRI   Jun 21 2024 3.0 Call',
                        'lastPrice': 0.02,
                        'netChange': -0.035,
                        'netPercentChange': -0.63636364,
                        'marketShare': 1.90286676,
                        'totalVolume': 276898,
                        'volume': 5269,
                        'trades': 150
                    }, {
                        'symbol': 'NVDA  240621C00128000',
                        'description': 'NVDA   Jun 21 2024 128.0 Call',
                        'lastPrice': 0.26,
                        'netChange': -3.4431,
                        'netPercentChange': -0.92978856,
                        'marketShare': 1.77610528,
                        'totalVolume': 276898,
                        'volume': 4918,
                        'trades': 306
                    }, {
                        'symbol': 'NVDA  240621C00127000',
                        'description': 'NVDA   Jun 21 2024 127.0 Call',
                        'lastPrice': 0.6,
                        'netChange': -3.9032,
                        'netPercentChange': -0.86676141,
                        'marketShare': 1.6320089,
                        'totalVolume': 276898,
                        'volume': 4519,
                        'trades': 491
                    }, {
                        'symbol': 'NVDA  240621C00130000',
                        'description': 'NVDA   Jun 21 2024 130.0 Call',
                        'lastPrice': 0.05,
                        'netChange': -2.2177,
                        'netPercentChange': -0.97795123,
                        'marketShare': 1.4745502,
                        'totalVolume': 276898,
                        'volume': 4083,
                        'trades': 217
                    }, {
                        'symbol': 'SPY   240621C00544000',
                        'description': 'SPY    Jun 21 2024 544.0 Call',
                        'lastPrice': 0.68,
                        'netChange': -2.32,
                        'netPercentChange': -0.77333333,
                        'marketShare': 1.42254549,
                        'totalVolume': 276898,
                        'volume': 3939,
                        'trades': 286
                    }, {
                        'symbol': 'IWM   240621C00200000',
                        'description': 'IWM    Jun 21 2024 200.0 Call',
                        'lastPrice': 0.11,
                        'netChange': -0.7012,
                        'netPercentChange': -0.86439842,
                        'marketShare': 1.24197358,
                        'totalVolume': 276898,
                        'volume': 3439,
                        'trades': 108
                    }, {
                        'symbol': 'EWZ   240802C00030000',
                        'description': 'EWZ    Aug 2 2024 30.0 Call',
                        'lastPrice': 0.2,
                        'netChange': 0.0446,
                        'netPercentChange': 0.28700129,
                        'marketShare': 1.20983178,
                        'totalVolume': 276898,
                        'volume': 3350,
                        'trades': 1
                    }, {
                        'symbol': 'CYH   240719C00004000',
                        'description': 'CYH    Jul 19 2024 4.0 Call',
                        'lastPrice': 0.1,
                        'netChange': 0,
                        'netPercentChange': 0,
                        'marketShare': 1.08415373,
                        'totalVolume': 276898,
                        'volume': 3002,
                        'trades': 96
                    }]
                }]
            }]
        }

        socket.recv.side_effect = [
            json.dumps(self.success_response(
                1, 'SCREENER_OPTION', 'SUBS')),
            json.dumps(stream_item)]
        await self.client.screener_option_subs(['OPTION_PUT_VOLUME_5', 'OPTION_CALL_VOLUME_5'])

        handler = Mock()
        async_handler = AsyncMock()
        self.client.add_screener_option_handler(handler)
        self.client.add_screener_option_handler(async_handler)
        await self.client.handle_message()

        expected_item = {
            'service': 'SCREENER_OPTION',
            'timestamp': 1718996045319,
            'command': 'SUBS',
            'content': [{
                'key': 'OPTION_PUT_VOLUME_5',
                'TIMESTAMP': 1718996045310,
                'SORT_FIELD': 'VOLUME',
                'FREQUENCY': 5,
                'ITEMS': [{
                    'symbol': 'SPY   240621P00541000',
                    'description': 'SPY    Jun 21 2024 541.0 Put',
                    'lastPrice': 0.02,
                    'netChange': -0.275,
                    'netPercentChange': -0.93220339,
                    'marketShare': 9.01754274,
                    'totalVolume': 218951,
                    'volume': 19744,
                    'trades': 151
                }, {
                    'symbol': 'SPY   240816P00514000',
                    'description': 'SPY    Aug 16 2024 514.0 Put',
                    'lastPrice': 2.31,
                    'netChange': -0.045,
                    'netPercentChange': -0.01910828,
                    'marketShare': 2.84995273,
                    'totalVolume': 218951,
                    'volume': 6240,
                    'trades': 3
                }, {
                    'symbol': 'NVDA  240621P00130000',
                    'description': 'NVDA   Jun 21 2024 130.0 Put',
                    'lastPrice': 3.35,
                    'netChange': 1.895,
                    'netPercentChange': 1.3024055,
                    'marketShare': 2.6544752,
                    'totalVolume': 218951,
                    'volume': 5812,
                    'trades': 213
                }, {
                    'symbol': 'SPY   240621P00542000',
                    'description': 'SPY    Jun 21 2024 542.0 Put',
                    'lastPrice': 0.05,
                    'netChange': -0.395,
                    'netPercentChange': -0.88764045,
                    'marketShare': 2.44940649,
                    'totalVolume': 218951,
                    'volume': 5363,
                    'trades': 108
                }, {
                    'symbol': 'SPY   240621P00544000',
                    'description': 'SPY    Jun 21 2024 544.0 Put',
                    'lastPrice': 0.38,
                    'netChange': -0.565,
                    'netPercentChange': -0.5978836,
                    'marketShare': 2.34481688,
                    'totalVolume': 218951,
                    'volume': 5134,
                    'trades': 427
                }, {
                    'symbol': 'NVDA  240621P00125000',
                    'description': 'NVDA   Jun 21 2024 125.0 Put',
                    'lastPrice': 0.19,
                    'netChange': -0.1956,
                    'netPercentChange': -0.50726141,
                    'marketShare': 2.0223703,
                    'totalVolume': 218951,
                    'volume': 4428,
                    'trades': 526
                }, {
                    'symbol': 'NVDA  240621P00126000',
                    'description': 'NVDA   Jun 21 2024 126.0 Put',
                    'lastPrice': 0.47,
                    'netChange': -0.06,
                    'netPercentChange': -0.11320755,
                    'marketShare': 1.62821819,
                    'totalVolume': 218951,
                    'volume': 3565,
                    'trades': 367
                }, {
                    'symbol': 'SPY   240816P00530000',
                    'description': 'SPY    Aug 16 2024 530.0 Put',
                    'lastPrice': 4.33,
                    'netChange': 0.0296,
                    'netPercentChange': 0.00688308,
                    'marketShare': 1.42863015,
                    'totalVolume': 218951,
                    'volume': 3128,
                    'trades': 7
                }, {
                    'symbol': 'QQQ   240621P00480000',
                    'description': 'QQQ    Jun 21 2024 480.0 Put',
                    'lastPrice': 0.51,
                    'netChange': -0.7029,
                    'netPercentChange': -0.57952016,
                    'marketShare': 1.25918585,
                    'totalVolume': 218951,
                    'volume': 2757,
                    'trades': 197
                }, {
                    'symbol': 'SPY   240621P00543000',
                    'description': 'SPY    Jun 21 2024 543.0 Put',
                    'lastPrice': 0.14,
                    'netChange': -0.515,
                    'netPercentChange': -0.78625954,
                    'marketShare': 1.23909002,
                    'totalVolume': 218951,
                    'volume': 2713,
                    'trades': 237
                }]
            }, {
                'key': 'OPTION_CALL_VOLUME_5',
                'TIMESTAMP': 1718996045320,
                'SORT_FIELD': 'VOLUME',
                'FREQUENCY': 5,
                'ITEMS': [{
                    'symbol': 'SPY   240621C00546000',
                    'description': 'SPY    Jun 21 2024 546.0 Call',
                    'lastPrice': 0.07,
                    'netChange': -1.1656,
                    'netPercentChange': -0.94334736,
                    'marketShare': 3.07333386,
                    'totalVolume': 276898,
                    'volume': 8510,
                    'trades': 280
                }, {
                    'symbol': 'SPY   240621C00545000',
                    'description': 'SPY    Jun 21 2024 545.0 Call',
                    'lastPrice': 0.25,
                    'netChange': -1.75,
                    'netPercentChange': -0.875,
                    'marketShare': 2.45613908,
                    'totalVolume': 276898,
                    'volume': 6801,
                    'trades': 503
                }, {
                    'symbol': 'SIRI  240621C00003000',
                    'description': 'SIRI   Jun 21 2024 3.0 Call',
                    'lastPrice': 0.02,
                    'netChange': -0.035,
                    'netPercentChange': -0.63636364,
                    'marketShare': 1.90286676,
                    'totalVolume': 276898,
                    'volume': 5269,
                    'trades': 150
                }, {
                    'symbol': 'NVDA  240621C00128000',
                    'description': 'NVDA   Jun 21 2024 128.0 Call',
                    'lastPrice': 0.26,
                    'netChange': -3.4431,
                    'netPercentChange': -0.92978856,
                    'marketShare': 1.77610528,
                    'totalVolume': 276898,
                    'volume': 4918,
                    'trades': 306
                }, {
                    'symbol': 'NVDA  240621C00127000',
                    'description': 'NVDA   Jun 21 2024 127.0 Call',
                    'lastPrice': 0.6,
                    'netChange': -3.9032,
                    'netPercentChange': -0.86676141,
                    'marketShare': 1.6320089,
                    'totalVolume': 276898,
                    'volume': 4519,
                    'trades': 491
                }, {
                    'symbol': 'NVDA  240621C00130000',
                    'description': 'NVDA   Jun 21 2024 130.0 Call',
                    'lastPrice': 0.05,
                    'netChange': -2.2177,
                    'netPercentChange': -0.97795123,
                    'marketShare': 1.4745502,
                    'totalVolume': 276898,
                    'volume': 4083,
                    'trades': 217
                }, {
                    'symbol': 'SPY   240621C00544000',
                    'description': 'SPY    Jun 21 2024 544.0 Call',
                    'lastPrice': 0.68,
                    'netChange': -2.32,
                    'netPercentChange': -0.77333333,
                    'marketShare': 1.42254549,
                    'totalVolume': 276898,
                    'volume': 3939,
                    'trades': 286
                }, {
                    'symbol': 'IWM   240621C00200000',
                    'description': 'IWM    Jun 21 2024 200.0 Call',
                    'lastPrice': 0.11,
                    'netChange': -0.7012,
                    'netPercentChange': -0.86439842,
                    'marketShare': 1.24197358,
                    'totalVolume': 276898,
                    'volume': 3439,
                    'trades': 108
                }, {
                    'symbol': 'EWZ   240802C00030000',
                    'description': 'EWZ    Aug 2 2024 30.0 Call',
                    'lastPrice': 0.2,
                    'netChange': 0.0446,
                    'netPercentChange': 0.28700129,
                    'marketShare': 1.20983178,
                    'totalVolume': 276898,
                    'volume': 3350,
                    'trades': 1
                }, {
                    'symbol': 'CYH   240719C00004000',
                    'description': 'CYH    Jul 19 2024 4.0 Call',
                    'lastPrice': 0.1,
                    'netChange': 0,
                    'netPercentChange': 0,
                    'marketShare': 1.08415373,
                    'totalVolume': 276898,
                    'volume': 3002,
                    'trades': 96
                }]
            }]
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

    @no_duplicates
    @patch('schwab.streaming.ws_client.connect', new_callable=AsyncMock)
    async def test_service_op_sorts_fields(self, ws_connect):
        socket = await self.login_and_get_socket(ws_connect)

        socket.recv.side_effect = [json.dumps(self.success_response(
            1, 'LEVELONE_EQUITIES', 'SUBS'))]

        await self.client._service_op(
            symbols=['GOOG', 'MSFT'],
            service='LEVELONE_EQUITIES',
            command='SUBS',
            field_type=StreamClient.LevelOneEquityFields,
            fields=[
            StreamClient.LevelOneEquityFields.ASK_SIZE,  # 5
            StreamClient.LevelOneEquityFields.ASK_PRICE,  # 2
            StreamClient.LevelOneEquityFields.MARGINABLE ,  # 14
            StreamClient.LevelOneEquityFields.REGULAR_MARKET_TRADE_MILLIS,  # 36
            StreamClient.LevelOneEquityFields.BID_PRICE ,  # 1
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
                'fields': '1,2,5,14,36'
            }
        })


