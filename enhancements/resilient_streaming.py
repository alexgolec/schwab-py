"""
Resilient Streaming Client with Tenacity Retry Logic

This module provides a resilient wrapper around the Schwab StreamClient that implements
bulletproof retry logic for network failures, structured logging with correlation IDs,
and graceful degradation when all retries fail.

Key Features:
- Exponential backoff with configurable parameters
- Retry on websocket, timeout, and socket errors
- Structured logging with correlation IDs for observability
- Connection state change events for system monitoring
- Graceful degradation when all retries fail
- Maintains same public API as original StreamClient
"""

import asyncio
import inspect
import json
import logging
import socket
import uuid
from enum import Enum
from typing import Any, Dict, Optional

import websockets
from tenacity import (
    retry,
    stop_after_attempt,
    wait_exponential,
    retry_if_exception_type,
    before_sleep_log,
    after_log,
    RetryError
)

from schwab.streaming import StreamClient


class ConnectionState(Enum):
    """Connection state enumeration for monitoring"""
    DISCONNECTED = "disconnected"
    CONNECTING = "connecting"
    CONNECTED = "connected"
    RECONNECTING = "reconnecting"
    FAILED = "failed"


class ResilienceStreamingClient(StreamClient):
    """
    A resilient streaming client that extends StreamClient with retry logic.
    
    This client maintains the same public API as the original StreamClient but adds:
    - Automatic retry on network failures
    - Structured logging with correlation IDs
    - Connection state monitoring
    - Graceful degradation capabilities
    """
    
    def __init__(self, client, *, account_id=None, enforce_enums=True, 
                 ssl_context=None, max_retries=5, min_wait=2, max_wait=30):
        """
        Initialize the resilient streaming client.
        
        Args:
            client: The Schwab HTTP client
            account_id: Account ID for the stream
            enforce_enums: Whether to enforce enum validation
            ssl_context: SSL context for websocket connections
            max_retries: Maximum number of retry attempts (default: 5)
            min_wait: Minimum wait time between retries in seconds (default: 2)
            max_wait: Maximum wait time between retries in seconds (default: 30)
        """
        super().__init__(client, account_id=account_id, 
                        enforce_enums=enforce_enums, ssl_context=ssl_context)
        
        # Retry configuration
        self.max_retries = max_retries
        self.min_wait = min_wait
        self.max_wait = max_wait
        
        # Connection state tracking
        self._connection_state = ConnectionState.DISCONNECTED
        self._state_change_callbacks = []
        
        # Correlation ID for request tracking
        self._correlation_id = str(uuid.uuid4())
        
        # Enhanced logger with correlation context
        self.resilience_logger = self._setup_resilience_logger()
        
        # Graceful degradation state
        self._degraded_mode = False
        self._degradation_callbacks = []
        
    def _setup_resilience_logger(self) -> logging.Logger:
        """Setup structured logger with correlation ID context"""
        logger = logging.getLogger(f"{__name__}.{self._correlation_id[:8]}")
        
        # Create custom formatter with correlation ID
        formatter = logging.Formatter(
            '%(asctime)s - %(name)s - %(levelname)s - '
            f'[CorrID: {self._correlation_id[:8]}] - %(message)s'
        )
        
        # Add handler if not already present
        if not logger.handlers:
            handler = logging.StreamHandler()
            handler.setFormatter(formatter)
            logger.addHandler(handler)
            logger.setLevel(logging.INFO)
        
        return logger
    
    def add_state_change_callback(self, callback):
        """
        Add a callback to be notified of connection state changes.
        
        Args:
            callback: Function that takes (old_state, new_state) parameters
        """
        self._state_change_callbacks.append(callback)
    
    def add_degradation_callback(self, callback):
        """
        Add a callback to be notified when graceful degradation occurs.
        
        Args:
            callback: Function that takes (error_details) parameter
        """
        self._degradation_callbacks.append(callback)
    
    def _change_connection_state(self, new_state: ConnectionState):
        """Update connection state and notify callbacks"""
        old_state = self._connection_state
        self._connection_state = new_state
        
        self.resilience_logger.info(
            f"Connection state changed: {old_state.value} -> {new_state.value}"
        )
        
        # Notify callbacks
        for callback in self._state_change_callbacks:
            try:
                callback(old_state, new_state)
            except Exception as e:
                self.resilience_logger.error(f"State change callback error: {e}")
    
    def _trigger_graceful_degradation(self, error_details: Dict[str, Any]):
        """Trigger graceful degradation mode"""
        self._degraded_mode = True
        self._change_connection_state(ConnectionState.FAILED)
        
        self.resilience_logger.error(
            f"Entering graceful degradation mode: {error_details}"
        )
        
        # Notify degradation callbacks
        for callback in self._degradation_callbacks:
            try:
                callback(error_details)
            except Exception as e:
                self.resilience_logger.error(f"Degradation callback error: {e}")
    
    @property
    def is_degraded(self) -> bool:
        """Check if client is in degraded mode"""
        return self._degraded_mode
    
    @property
    def connection_state(self) -> ConnectionState:
        """Get current connection state"""
        return self._connection_state
    
    def _create_retry_decorator(self, operation_name: str):
        """Create a retry decorator for a specific operation"""
        return retry(
            stop=stop_after_attempt(self.max_retries),
            wait=wait_exponential(
                multiplier=1,
                min=self.min_wait,
                max=self.max_wait
            ),
            retry=retry_if_exception_type((
                websockets.ConnectionClosed,
                asyncio.TimeoutError,
                socket.error,
                ConnectionError,
                OSError
            )),
            before_sleep=before_sleep_log(
                self.resilience_logger, 
                logging.WARNING,
                exc_info=True
            ),
            after=after_log(
                self.resilience_logger,
                logging.INFO
            ),
            reraise=True
        )
    
    async def _receive(self):
        """
        Override _receive with retry logic while maintaining overflow handling.
        
        This method maintains the same behavior as the parent class but adds
        retry logic for network failures.
        """
        if self._degraded_mode:
            raise ConnectionError("Client is in degraded mode")
        
        @self._create_retry_decorator("receive")
        async def _receive_with_retry():
            self.resilience_logger.debug("Attempting to receive message")
            
            if self._socket is None:
                raise ValueError(
                    'Socket not open. Did you forget to call login()?')
            
            # Handle overflow items first (same as parent)
            if len(self._overflow_items) > 0:
                ret = self._overflow_items.pop()
                
                self.resilience_logger.debug(
                    f"Returning message from overflow: {len(self._overflow_items)} remaining"
                )
                from schwab.utils import LazyLog
                self.logger.debug(
                    'Receive %s: Returning message from overflow: %s',
                    self.req_num(), LazyLog(lambda: json.dumps(ret, indent=4))
                )
                return ret
            
            # Receive from websocket with retry protection
            try:
                raw = await self._socket.recv()
                ret = self.json_decoder.decode_json_string(raw)
                
                self.resilience_logger.debug("Successfully received and parsed message")
                from schwab.utils import LazyLog
                self.logger.debug(
                    'Receive %s: Returning message from stream: %s',
                    self.req_num(), LazyLog(lambda: json.dumps(ret, indent=4))
                )
                
                return ret
                
            except Exception as e:
                self.resilience_logger.warning(f"Receive operation failed: {e}")
                raise
        
        try:
            return await _receive_with_retry()
        except RetryError as e:
            error_details = {
                'operation': 'receive',
                'attempts': self.max_retries,
                'last_error': str(e.last_attempt.exception()),
                'correlation_id': self._correlation_id
            }
            self._trigger_graceful_degradation(error_details)
            raise ConnectionError(f"Failed to receive after {self.max_retries} attempts") from e
    
    async def _await_response(self, request_id, service, command):
        """
        Override _await_response with retry logic.
        
        This method maintains the same response validation logic as the parent
        but adds retry capabilities for network failures.
        """
        if self._degraded_mode:
            raise ConnectionError("Client is in degraded mode")
        
        @self._create_retry_decorator("await_response")
        async def _await_response_with_retry():
            self.resilience_logger.debug(
                f"Awaiting response for request_id={request_id}, service={service}, command={command}"
            )
            
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
                        from schwab.streaming import UnexpectedResponse
                        raise UnexpectedResponse(
                            resp, 'unexpected requestid: {}'.format(resp_request_id))
                    
                    # Validate service
                    resp_service = resp['response'][0]['service']
                    if resp_service != service:
                        from schwab.streaming import UnexpectedResponse
                        raise UnexpectedResponse(
                            resp, 'unexpected service: {}'.format(resp_service))
                    
                    # Validate command
                    resp_command = resp['response'][0]['command']
                    if resp_command != command:
                        from schwab.streaming import UnexpectedResponse
                        raise UnexpectedResponse(
                            resp, 'unexpected command: {}'.format(resp_command))
                    
                    # Validate response code
                    resp_code = resp['response'][0]['content']['code']
                    if resp_code != 0:
                        from schwab.streaming import UnexpectedResponse
                        raise UnexpectedResponse(
                            resp, 'unexpected response code: {}'.format(resp_code))
                    
                    self.resilience_logger.debug(
                        f"Successfully received valid response for request_id={request_id}"
                    )
                    return resp
        
        try:
            return await _await_response_with_retry()
        except RetryError as e:
            error_details = {
                'operation': 'await_response',
                'request_id': request_id,
                'service': service,
                'command': command,
                'attempts': self.max_retries,
                'last_error': str(e.last_attempt.exception()),
                'correlation_id': self._correlation_id
            }
            self._trigger_graceful_degradation(error_details)
            raise ConnectionError(f"Failed to await response after {self.max_retries} attempts") from e
    
    async def login(self, websocket_connect_args=None):
        """
        Override login with retry logic and connection state tracking.
        
        This method implements the same login handshake as the parent but adds
        retry logic and connection state monitoring.
        """
        if self._degraded_mode:
            raise ConnectionError("Client is in degraded mode")
        
        self._change_connection_state(ConnectionState.CONNECTING)
        
        @self._create_retry_decorator("login")
        async def _login_with_retry():
            self.resilience_logger.info("Starting login handshake")
            
            # Fetch required data and initialize the client
            r = self._client.get_user_preferences()
            
            # We don't actually know whether the client is synchronous or
            # asynchronous, so work around by awaiting the response if necessary
            if inspect.iscoroutine(r):
                r = await r
            
            import httpx
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
            
            self.resilience_logger.info("Login handshake completed successfully")
        
        try:
            await _login_with_retry()
            self._change_connection_state(ConnectionState.CONNECTED)
            self._degraded_mode = False  # Reset degraded mode on successful login
        except RetryError as e:
            error_details = {
                'operation': 'login',
                'attempts': self.max_retries,
                'last_error': str(e.last_attempt.exception()),
                'correlation_id': self._correlation_id
            }
            self._trigger_graceful_degradation(error_details)
            raise ConnectionError(f"Failed to login after {self.max_retries} attempts") from e
    
    async def logout(self):
        """
        Override logout to update connection state.
        """
        try:
            await super().logout()
            self._change_connection_state(ConnectionState.DISCONNECTED)
            self.resilience_logger.info("Logout completed successfully")
        except Exception as e:
            self.resilience_logger.error(f"Logout failed: {e}")
            self._change_connection_state(ConnectionState.FAILED)
            raise
    
    def get_health_status(self) -> Dict[str, Any]:
        """
        Get comprehensive health status of the client.
        
        Returns:
            Dict containing connection state, degradation status, correlation ID, etc.
        """
        return {
            'connection_state': self._connection_state.value,
            'is_degraded': self._degraded_mode,
            'correlation_id': self._correlation_id,
            'socket_connected': self._socket is not None,
            'overflow_queue_size': len(self._overflow_items) if hasattr(self, '_overflow_items') else 0,
            'retry_config': {
                'max_retries': self.max_retries,
                'min_wait': self.min_wait,
                'max_wait': self.max_wait
            }
        }
    
    async def reset_degradation(self):
        """
        Reset graceful degradation mode and attempt to reconnect.
        
        This method allows recovery from degraded mode by attempting a fresh login.
        """
        self.resilience_logger.info("Resetting degradation mode and attempting recovery")
        
        self._degraded_mode = False
        self._correlation_id = str(uuid.uuid4())  # New correlation ID for recovery
        self.resilience_logger = self._setup_resilience_logger()
        
        try:
            await self.login()
            self.resilience_logger.info("Successfully recovered from degraded mode")
        except Exception as e:
            self.resilience_logger.error(f"Failed to recover from degraded mode: {e}")
            self._trigger_graceful_degradation({
                'operation': 'recovery',
                'error': str(e),
                'correlation_id': self._correlation_id
            })
            raise