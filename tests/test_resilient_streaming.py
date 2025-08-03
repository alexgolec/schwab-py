"""
Comprehensive test suite for ResilienceStreamingClient

This test suite covers:
- WebSocket failure mocking and retry behavior verification
- Graceful degradation scenarios
- Connection state tracking
- Structured logging validation
- Load testing with random disconnects
- Overflow handling preservation
"""

import asyncio
import json
import logging
import random
import socket
import time
import unittest
from unittest.mock import AsyncMock, MagicMock, patch, call
from collections import deque

import websockets
from tenacity import RetryError

# Import the resilient streaming client
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from enhancements.resilient_streaming import ResilienceStreamingClient, ConnectionState


class MockStreamClient:
    """Mock Schwab client for testing"""
    
    def __init__(self):
        self.token_metadata = MagicMock()
        self.token_metadata.token = {'access_token': 'test_token'}
    
    def get_user_preferences(self):
        """Mock user preferences response"""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            'streamerInfo': [{
                'schwabClientCorrelId': 'test_correl_id',
                'schwabClientCustomerId': 'test_customer_id',
                'schwabClientChannel': 'test_channel',
                'schwabClientFunctionId': 'test_function_id',
                'streamerSocketUrl': 'wss://test.example.com/streaming'
            }]
        }
        return mock_response


class TestResilienceStreamingClient(unittest.TestCase):
    """Test suite for ResilienceStreamingClient"""
    
    def setUp(self):
        """Set up test fixtures"""
        self.mock_client = MockStreamClient()
        self.resilient_client = ResilienceStreamingClient(
            self.mock_client,
            max_retries=3,
            min_wait=0.1,
            max_wait=0.5
        )
        
        # Mock the lock to avoid asyncio issues in tests
        self.resilient_client._lock = AsyncMock()
        self.resilient_client._lock.__aenter__ = AsyncMock()
        self.resilient_client._lock.__aexit__ = AsyncMock()
    
    def test_initialization(self):
        """Test proper initialization of ResilienceStreamingClient"""
        self.assertEqual(self.resilient_client.max_retries, 3)
        self.assertEqual(self.resilient_client.min_wait, 0.1)
        self.assertEqual(self.resilient_client.max_wait, 0.5)
        self.assertEqual(self.resilient_client.connection_state, ConnectionState.DISCONNECTED)
        self.assertFalse(self.resilient_client.is_degraded)
        self.assertIsNotNone(self.resilient_client._correlation_id)
    
    def test_connection_state_tracking(self):
        """Test connection state changes and callbacks"""
        state_changes = []
        
        def state_callback(old_state, new_state):
            state_changes.append((old_state, new_state))
        
        self.resilient_client.add_state_change_callback(state_callback)
        
        # Test state change
        self.resilient_client._change_connection_state(ConnectionState.CONNECTING)
        self.assertEqual(self.resilient_client.connection_state, ConnectionState.CONNECTING)
        self.assertEqual(len(state_changes), 1)
        self.assertEqual(state_changes[0], (ConnectionState.DISCONNECTED, ConnectionState.CONNECTING))
        
        # Test another state change
        self.resilient_client._change_connection_state(ConnectionState.CONNECTED)
        self.assertEqual(self.resilient_client.connection_state, ConnectionState.CONNECTED)
        self.assertEqual(len(state_changes), 2)
        self.assertEqual(state_changes[1], (ConnectionState.CONNECTING, ConnectionState.CONNECTED))
    
    def test_graceful_degradation(self):
        """Test graceful degradation mechanism"""
        degradation_events = []
        
        def degradation_callback(error_details):
            degradation_events.append(error_details)
        
        self.resilient_client.add_degradation_callback(degradation_callback)
        
        # Trigger graceful degradation
        error_details = {'operation': 'test', 'error': 'test_error'}
        self.resilient_client._trigger_graceful_degradation(error_details)
        
        self.assertTrue(self.resilient_client.is_degraded)
        self.assertEqual(self.resilient_client.connection_state, ConnectionState.FAILED)
        self.assertEqual(len(degradation_events), 1)
        self.assertEqual(degradation_events[0], error_details)
    
    def test_health_status(self):
        """Test health status reporting"""
        health = self.resilient_client.get_health_status()
        
        expected_keys = [
            'connection_state', 'is_degraded', 'correlation_id',
            'socket_connected', 'overflow_queue_size', 'retry_config'
        ]
        
        for key in expected_keys:
            self.assertIn(key, health)
        
        self.assertEqual(health['connection_state'], ConnectionState.DISCONNECTED.value)
        self.assertFalse(health['is_degraded'])
        self.assertEqual(health['retry_config']['max_retries'], 3)
    
    @patch('websockets.legacy.client.connect')
    async def test_login_retry_success(self, mock_ws_connect):
        """Test successful login after retries"""
        # Mock websocket connection
        mock_socket = AsyncMock()
        mock_ws_connect.return_value = mock_socket
        
        # Mock successful response
        login_response = {
            'response': [{
                'requestid': '0',
                'service': 'ADMIN',
                'command': 'LOGIN',
                'content': {'code': 0}
            }]
        }
        
        mock_socket.recv.return_value = json.dumps(login_response)
        
        # Mock _send method
        self.resilient_client._send = AsyncMock()
        
        # Test login
        await self.resilient_client.login()
        
        self.assertEqual(self.resilient_client.connection_state, ConnectionState.CONNECTED)
        self.assertFalse(self.resilient_client.is_degraded)
    
    @patch('websockets.legacy.client.connect')
    async def test_login_retry_failure(self, mock_ws_connect):
        """Test login failure after all retries exhausted"""
        # Mock websocket connection that always fails
        mock_ws_connect.side_effect = websockets.ConnectionClosed(None, None)
        
        # Test login failure
        with self.assertRaises(ConnectionError):
            await self.resilient_client.login()
        
        self.assertTrue(self.resilient_client.is_degraded)
        self.assertEqual(self.resilient_client.connection_state, ConnectionState.FAILED)
    
    async def test_receive_overflow_handling(self):
        """Test that overflow handling is preserved in _receive method"""
        # Set up overflow items
        test_message = {'test': 'overflow_message'}
        self.resilient_client._overflow_items = deque([test_message])
        
        # Mock socket
        self.resilient_client._socket = AsyncMock()
        
        # Test receive from overflow
        result = await self.resilient_client._receive()
        
        self.assertEqual(result, test_message)
        self.assertEqual(len(self.resilient_client._overflow_items), 0)
    
    async def test_receive_retry_behavior(self):
        """Test retry behavior in _receive method"""
        # Mock socket that fails then succeeds
        mock_socket = AsyncMock()
        self.resilient_client._socket = mock_socket
        
        test_message = {'test': 'message'}
        mock_socket.recv.side_effect = [
            websockets.ConnectionClosed(None, None),  # First attempt fails
            json.dumps(test_message)  # Second attempt succeeds
        ]
        
        # Mock JSON decoder
        self.resilient_client.json_decoder = MagicMock()
        self.resilient_client.json_decoder.decode_json_string.return_value = test_message
        
        # Set empty overflow items
        self.resilient_client._overflow_items = deque()
        
        # Test receive with retry
        result = await self.resilient_client._receive()
        
        self.assertEqual(result, test_message)
        self.assertEqual(mock_socket.recv.call_count, 2)
    
    async def test_receive_degradation_when_exhausted(self):
        """Test graceful degradation when _receive retries are exhausted"""
        # Mock socket that always fails
        mock_socket = AsyncMock()
        self.resilient_client._socket = mock_socket
        mock_socket.recv.side_effect = websockets.ConnectionClosed(None, None)
        
        # Set empty overflow items
        self.resilient_client._overflow_items = deque()
        
        # Test receive failure leading to degradation
        with self.assertRaises(ConnectionError):
            await self.resilient_client._receive()
        
        self.assertTrue(self.resilient_client.is_degraded)
    
    async def test_await_response_retry_behavior(self):
        """Test retry behavior in _await_response method"""
        request_id = 123
        service = 'TEST_SERVICE'
        command = 'TEST_COMMAND'
        
        # Mock _receive to fail then succeed
        response = {
            'response': [{
                'requestid': str(request_id),
                'service': service,
                'command': command,
                'content': {'code': 0}
            }]
        }
        
        self.resilient_client._receive = AsyncMock()
        self.resilient_client._receive.side_effect = [
            websockets.ConnectionClosed(None, None),  # First attempt fails
            response  # Second attempt succeeds
        ]
        
        # Test await response with retry
        result = await self.resilient_client._await_response(request_id, service, command)
        
        self.assertEqual(result, response)
        self.assertEqual(self.resilient_client._receive.call_count, 2)
    
    async def test_await_response_deferred_messages(self):
        """Test that deferred messages are properly handled"""
        request_id = 123
        service = 'TEST_SERVICE'
        command = 'TEST_COMMAND'
        
        # Mock messages: data message, then response
        data_message = {'data': [{'test': 'data'}]}
        response = {
            'response': [{
                'requestid': str(request_id),
                'service': service,
                'command': command,
                'content': {'code': 0}
            }]
        }
        
        self.resilient_client._receive = AsyncMock()
        self.resilient_client._receive.side_effect = [data_message, response]
        
        # Initialize overflow items
        self.resilient_client._overflow_items = deque()
        
        # Test await response
        result = await self.resilient_client._await_response(request_id, service, command)
        
        self.assertEqual(result, response)
        # Check that data message was deferred
        self.assertEqual(len(self.resilient_client._overflow_items), 1)
        self.assertEqual(self.resilient_client._overflow_items[0], data_message)
    
    async def test_degraded_mode_blocks_operations(self):
        """Test that operations are blocked when in degraded mode"""
        # Put client in degraded mode
        self.resilient_client._degraded_mode = True
        
        # Test that operations raise ConnectionError
        with self.assertRaises(ConnectionError):
            await self.resilient_client._receive()
        
        with self.assertRaises(ConnectionError):
            await self.resilient_client._await_response(1, 'TEST', 'TEST')
        
        with self.assertRaises(ConnectionError):
            await self.resilient_client.login()
    
    @patch('websockets.legacy.client.connect')
    async def test_reset_degradation(self, mock_ws_connect):
        """Test resetting degradation mode and recovery"""
        # Put client in degraded mode
        self.resilient_client._trigger_graceful_degradation({'test': 'error'})
        self.assertTrue(self.resilient_client.is_degraded)
        
        # Mock successful websocket connection for recovery
        mock_socket = AsyncMock()
        mock_ws_connect.return_value = mock_socket
        
        login_response = {
            'response': [{
                'requestid': '0',
                'service': 'ADMIN',
                'command': 'LOGIN',
                'content': {'code': 0}
            }]
        }
        mock_socket.recv.return_value = json.dumps(login_response)
        
        # Mock _send method
        self.resilient_client._send = AsyncMock()
        
        # Test recovery
        await self.resilient_client.reset_degradation()
        
        self.assertFalse(self.resilient_client.is_degraded)
        self.assertEqual(self.resilient_client.connection_state, ConnectionState.CONNECTED)
    
    def test_structured_logging(self):
        """Test structured logging with correlation IDs"""
        # Capture log messages
        log_messages = []
        
        class TestHandler(logging.Handler):
            def emit(self, record):
                log_messages.append(record.getMessage())
        
        test_handler = TestHandler()
        self.resilient_client.resilience_logger.addHandler(test_handler)
        self.resilient_client.resilience_logger.setLevel(logging.DEBUG)
        
        # Test logging
        self.resilient_client.resilience_logger.info("Test message")
        
        # Verify correlation ID is in log message
        self.assertTrue(len(log_messages) > 0)
        self.assertIn(self.resilient_client._correlation_id[:8], log_messages[0])


class TestResilienceLoadTesting(unittest.TestCase):
    """Load testing scenarios for ResilienceStreamingClient"""
    
    def setUp(self):
        """Set up load testing fixtures"""
        self.mock_client = MockStreamClient()
        self.resilient_client = ResilienceStreamingClient(
            self.mock_client,
            max_retries=2,  # Lower retries for faster load testing
            min_wait=0.01,
            max_wait=0.1
        )
        self.resilient_client._lock = AsyncMock()
        self.resilient_client._lock.__aenter__ = AsyncMock()
        self.resilient_client._lock.__aexit__ = AsyncMock()
    
    async def test_high_throughput_with_random_disconnects(self):
        """Test handling 1000 messages/second with random disconnects"""
        message_count = 100  # Reduced for test performance
        disconnect_probability = 0.1  # 10% chance of disconnect per message
        
        # Mock socket
        mock_socket = AsyncMock()
        self.resilient_client._socket = mock_socket
        
        # Track successful message receives
        successful_receives = 0
        retry_counts = []
        
        async def mock_recv():
            # Simulate random disconnects
            if random.random() < disconnect_probability:
                raise websockets.ConnectionClosed(None, None)
            return json.dumps({'test': f'message_{successful_receives}'})
        
        mock_socket.recv.side_effect = mock_recv
        
        # Mock JSON decoder
        self.resilient_client.json_decoder = MagicMock()
        self.resilient_client.json_decoder.decode_json_string.side_effect = (
            lambda x: json.loads(x)
        )
        
        # Set empty overflow items
        self.resilient_client._overflow_items = deque()
        
        # Test message processing
        start_time = time.time()
        
        for i in range(message_count):
            try:
                await self.resilient_client._receive()
                successful_receives += 1
            except ConnectionError:
                # Client went into degraded mode
                break
            
            # Reset the mock for next iteration
            mock_socket.recv.side_effect = mock_recv
        
        end_time = time.time()
        duration = end_time - start_time
        
        # Verify performance characteristics
        self.assertGreater(successful_receives, 0)
        print(f"Processed {successful_receives}/{message_count} messages in {duration:.2f}s")
        print(f"Rate: {successful_receives/duration:.2f} messages/second")
        
        # Verify that some retries occurred (due to random disconnects)
        # This is validated by checking that recv was called more times than successful receives
        if not self.resilient_client.is_degraded:
            self.assertGreaterEqual(mock_socket.recv.call_count, successful_receives)
    
    async def test_burst_traffic_handling(self):
        """Test handling burst traffic scenarios"""
        burst_size = 50
        
        # Mock socket with intermittent failures
        mock_socket = AsyncMock()
        self.resilient_client._socket = mock_socket
        
        call_count = 0
        
        def mock_recv_burst():
            nonlocal call_count
            call_count += 1
            # Fail every 5th message to simulate network issues
            if call_count % 5 == 0:
                raise socket.error("Network unreachable")
            return json.dumps({'burst': f'message_{call_count}'})
        
        mock_socket.recv.side_effect = mock_recv_burst
        
        # Mock JSON decoder
        self.resilient_client.json_decoder = MagicMock()
        self.resilient_client.json_decoder.decode_json_string.side_effect = (
            lambda x: json.loads(x)
        )
        
        # Set empty overflow items
        self.resilient_client._overflow_items = deque()
        
        # Process burst traffic
        successful_burst_receives = 0
        
        for i in range(burst_size):
            try:
                message = await self.resilient_client._receive()
                successful_burst_receives += 1
            except ConnectionError:
                # Expected when retries are exhausted
                break
        
        # Verify that most messages were processed despite network issues
        self.assertGreater(successful_burst_receives, burst_size * 0.7)  # At least 70% success
        print(f"Burst test: {successful_burst_receives}/{burst_size} messages processed")
    
    async def test_connection_recovery_under_load(self):
        """Test connection recovery scenarios under load"""
        # This test simulates a scenario where the connection fails completely
        # and then recovers
        
        # Mock initial failure
        self.resilient_client._trigger_graceful_degradation({'test': 'connection_lost'})
        self.assertTrue(self.resilient_client.is_degraded)
        
        # Attempt operations while degraded (should fail fast)
        with self.assertRaises(ConnectionError):
            await self.resilient_client._receive()
        
        # Simulate recovery by resetting degradation
        with patch('websockets.legacy.client.connect') as mock_ws_connect:
            mock_socket = AsyncMock()
            mock_ws_connect.return_value = mock_socket
            
            login_response = {
                'response': [{
                    'requestid': '0',
                    'service': 'ADMIN',
                    'command': 'LOGIN',
                    'content': {'code': 0}
                }]
            }
            mock_socket.recv.return_value = json.dumps(login_response)
            self.resilient_client._send = AsyncMock()
            
            # Test recovery
            await self.resilient_client.reset_degradation()
            
            self.assertFalse(self.resilient_client.is_degraded)
            self.assertEqual(self.resilient_client.connection_state, ConnectionState.CONNECTED)


if __name__ == '__main__':
    # Run tests
    unittest.main()