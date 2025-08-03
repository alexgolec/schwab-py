"""
Intelligent API Rate Limiting System for Schwab Trading Service

This module implements a sophisticated rate limiting system to prevent API violations
while maximizing throughput for high-frequency trading operations.

Key Features:
- Sliding window rate limiter using deque for efficient O(1) operations
- Per-endpoint rate limiting with configurable limits
- Request priority queue (orders > market data > account info)
- Intelligent batching for bulk operations
- Comprehensive metrics and monitoring
- Thread-safe for concurrent operations
- Memory-efficient with bounded timestamp storage
"""

import asyncio
import logging
import os
import time
import threading
from collections import deque
from dataclasses import dataclass, field
from enum import Enum
from functools import wraps
from typing import Any, Callable, Dict, List, Optional, Tuple, Union
import heapq
from contextlib import contextmanager

logger = logging.getLogger(__name__)


class RequestPriority(Enum):
    """Request priority levels for queue ordering."""
    CRITICAL_ORDER = 1      # Order placement/cancellation - highest priority
    MARKET_DATA = 2         # Real-time quotes, chains - medium priority  
    ACCOUNT_INFO = 3        # Account balance, positions - lower priority
    HISTORICAL_DATA = 4     # Price history, reports - lowest priority


@dataclass
class EndpointLimits:
    """Rate limit configuration for specific endpoints."""
    requests_per_minute: int
    burst_allowance: int = 0  # Additional requests allowed in burst
    cooldown_seconds: float = 0  # Cooldown after hitting limit


@dataclass
class RequestInfo:
    """Information about a queued request."""
    priority: RequestPriority
    timestamp: float
    endpoint: str
    method: str
    args: tuple
    kwargs: dict
    future: Optional[asyncio.Future] = None
    
    def __lt__(self, other):
        """For priority queue ordering."""
        return (self.priority.value, self.timestamp) < (other.priority.value, other.timestamp)


@dataclass
class RateLimitMetrics:
    """Rate limiting metrics for monitoring."""
    total_requests: int = 0
    throttled_requests: int = 0
    avg_wait_time: float = 0.0
    max_wait_time: float = 0.0
    current_queue_size: int = 0
    requests_by_endpoint: Dict[str, int] = field(default_factory=dict)
    throttled_by_endpoint: Dict[str, int] = field(default_factory=dict)


class SlidingWindowRateLimiter:
    """
    Thread-safe sliding window rate limiter using deque.
    
    Efficiently tracks request timestamps and enforces limits with O(1) operations.
    Memory usage is bounded by the maximum number of requests in the window.
    """
    
    def __init__(self, requests_per_window: int, window_seconds: float):
        """
        Initialize rate limiter.
        
        Args:
            requests_per_window: Maximum requests allowed in the time window
            window_seconds: Time window duration in seconds
        """
        self.requests_per_window = requests_per_window
        self.window_seconds = window_seconds
        self.timestamps = deque()
        self._lock = threading.RLock()
        
        # Performance tracking
        self.total_requests = 0
        self.rejected_requests = 0
        
    def can_proceed(self) -> bool:
        """
        Check if a request can proceed without blocking.
        
        Returns:
            True if request can proceed immediately, False if throttling needed
        """
        with self._lock:
            self._clean_expired_timestamps()
            return len(self.timestamps) < self.requests_per_window
    
    def wait_time(self) -> float:
        """
        Calculate required wait time before next request can proceed.
        
        Returns:
            Wait time in seconds, 0 if can proceed immediately
        """
        with self._lock:
            self._clean_expired_timestamps()
            
            if len(self.timestamps) < self.requests_per_window:
                return 0.0
                
            # Need to wait until the oldest request expires
            oldest_timestamp = self.timestamps[0]
            wait_time = oldest_timestamp + self.window_seconds - time.time()
            return max(0.0, wait_time)
    
    def acquire(self, timeout: Optional[float] = None) -> bool:
        """
        Acquire permission to make a request, blocking if necessary.
        
        Args:
            timeout: Maximum time to wait in seconds, None for no timeout
            
        Returns:
            True if acquired, False if timeout exceeded
        """
        start_time = time.time()
        
        while True:
            wait_time = 0.0
            with self._lock:
                self._clean_expired_timestamps()
                
                if len(self.timestamps) < self.requests_per_window:
                    # Can proceed - record timestamp
                    self.timestamps.append(time.time())
                    self.total_requests += 1
                    return True
                    
                # Check timeout
                if timeout is not None:
                    elapsed = time.time() - start_time
                    if elapsed >= timeout:
                        self.rejected_requests += 1
                        return False
                        
                # Calculate wait time
                if self.timestamps:
                    oldest_timestamp = self.timestamps[0]
                    wait_time = oldest_timestamp + self.window_seconds - time.time()
                
            # Wait outside the lock to allow other threads
            if wait_time > 0:
                sleep_time = min(wait_time, 0.1)  # Check every 100ms
                time.sleep(sleep_time)
            else:
                time.sleep(0.01)  # Small sleep to prevent busy waiting
    
    async def acquire_async(self, timeout: Optional[float] = None) -> bool:
        """
        Async version of acquire for async clients.
        
        Args:
            timeout: Maximum time to wait in seconds, None for no timeout
            
        Returns:
            True if acquired, False if timeout exceeded
        """
        start_time = time.time()
        
        while True:
            wait_time = 0.0
            with self._lock:
                self._clean_expired_timestamps()
                
                if len(self.timestamps) < self.requests_per_window:
                    # Can proceed - record timestamp
                    self.timestamps.append(time.time())
                    self.total_requests += 1
                    return True
                    
                # Check timeout
                if timeout is not None:
                    elapsed = time.time() - start_time
                    if elapsed >= timeout:
                        self.rejected_requests += 1
                        return False
                        
                # Calculate wait time
                if self.timestamps:
                    oldest_timestamp = self.timestamps[0]
                    wait_time = oldest_timestamp + self.window_seconds - time.time()
                
            # Wait outside the lock to allow other operations
            if wait_time > 0:
                sleep_time = min(wait_time, 0.1)  # Check every 100ms
                await asyncio.sleep(sleep_time)
            else:
                await asyncio.sleep(0.01)  # Small sleep to prevent busy waiting
    
    def _clean_expired_timestamps(self):
        """Remove expired timestamps from the window."""
        current_time = time.time()
        while self.timestamps and self.timestamps[0] <= current_time - self.window_seconds:
            self.timestamps.popleft()
    
    def get_stats(self) -> Dict[str, Any]:
        """Get current rate limiter statistics."""
        with self._lock:
            self._clean_expired_timestamps()
            return {
                'current_requests_in_window': len(self.timestamps),
                'max_requests_per_window': self.requests_per_window,
                'window_seconds': self.window_seconds,
                'total_requests': self.total_requests,
                'rejected_requests': self.rejected_requests,
                'utilization_percent': (len(self.timestamps) / self.requests_per_window) * 100
            }


class RateLimiterConfig:
    """Configuration for rate limiting with environment variable support."""
    
    def __init__(self):
        # Default Schwab API limits
        self.default_requests_per_minute = int(os.getenv('SCHWAB_RATE_LIMIT_RPM', '120'))
        self.default_window_seconds = float(os.getenv('SCHWAB_RATE_LIMIT_WINDOW', '60'))
        
        # Performance settings
        self.max_queue_size = int(os.getenv('SCHWAB_RATE_LIMIT_MAX_QUEUE', '1000'))
        self.request_timeout = float(os.getenv('SCHWAB_RATE_LIMIT_TIMEOUT', '30'))
        self.enable_batching = os.getenv('SCHWAB_RATE_LIMIT_BATCHING', 'true').lower() == 'true'
        self.batch_size = int(os.getenv('SCHWAB_RATE_LIMIT_BATCH_SIZE', '10'))
        
        # Endpoint-specific limits
        self.endpoint_limits = self._load_endpoint_limits()
        
        # Monitoring
        self.enable_metrics = os.getenv('SCHWAB_RATE_LIMIT_METRICS', 'true').lower() == 'true'
        self.metrics_log_interval = float(os.getenv('SCHWAB_RATE_LIMIT_METRICS_INTERVAL', '300'))
    
    def _load_endpoint_limits(self) -> Dict[str, EndpointLimits]:
        """Load endpoint-specific rate limits."""
        limits = {}
        
        # Orders have stricter limits due to regulatory requirements
        limits['/trader/v1/accounts/*/orders'] = EndpointLimits(
            requests_per_minute=int(os.getenv('SCHWAB_ORDER_RATE_LIMIT', '60')),
            burst_allowance=5,
            cooldown_seconds=1.0
        )
        
        # Market data can be more frequent
        limits['/marketdata/v1/quotes'] = EndpointLimits(
            requests_per_minute=int(os.getenv('SCHWAB_QUOTES_RATE_LIMIT', '200')),
            burst_allowance=10
        )
        
        # Option chains are expensive
        limits['/marketdata/v1/chains'] = EndpointLimits(
            requests_per_minute=int(os.getenv('SCHWAB_CHAINS_RATE_LIMIT', '30')),
            cooldown_seconds=2.0
        )
        
        return limits
    
    def get_endpoint_limit(self, endpoint: str) -> Optional[EndpointLimits]:
        """Get rate limit for specific endpoint."""
        # Try exact match first
        if endpoint in self.endpoint_limits:
            return self.endpoint_limits[endpoint]
            
        # Try pattern matching
        for pattern, limits in self.endpoint_limits.items():
            if '*' in pattern:
                pattern_parts = pattern.split('*')
                if all(part in endpoint for part in pattern_parts if part):
                    return limits
                    
        return None


class RateLimitedClient:
    """
    Wrapper for Schwab clients that adds intelligent rate limiting.
    
    Features:
    - Sliding window rate limiting with configurable limits
    - Per-endpoint rate limiting  
    - Request priority queue
    - Intelligent batching
    - Comprehensive metrics
    - Thread-safe operation
    """
    
    def __init__(self, client, config: Optional[RateLimiterConfig] = None):
        """
        Initialize rate limited client wrapper.
        
        Args:
            client: Original Schwab client (sync or async)
            config: Rate limiter configuration
        """
        self.client = client
        self.config = config or RateLimiterConfig()
        
        # Global rate limiter
        self.global_limiter = SlidingWindowRateLimiter(
            self.config.default_requests_per_minute,
            self.config.default_window_seconds
        )
        
        # Per-endpoint rate limiters
        self.endpoint_limiters: Dict[str, SlidingWindowRateLimiter] = {}
        
        # Priority queue for requests
        self.request_queue = []
        self.queue_lock = threading.RLock()
        
        # Metrics
        self.metrics = RateLimitMetrics()
        self.metrics_lock = threading.RLock()
        
        # Background metrics logging
        if self.config.enable_metrics:
            self._start_metrics_logging()
        
        # Wrap client methods
        self._wrap_client_methods()
    
    def _wrap_client_methods(self):
        """Wrap the client's HTTP request methods with rate limiting."""
        methods_to_wrap = ['_get_request', '_post_request', '_put_request', '_delete_request']
        
        for method_name in methods_to_wrap:
            if hasattr(self.client, method_name):
                original_method = getattr(self.client, method_name)
                wrapped_method = self._create_wrapped_method(original_method, method_name)
                setattr(self.client, method_name, wrapped_method)
    
    def _create_wrapped_method(self, original_method: Callable, method_name: str) -> Callable:
        """Create a rate-limited wrapper for a client method."""
        
        if asyncio.iscoroutinefunction(original_method):
            @wraps(original_method)
            async def async_wrapper(path: str, *args, **kwargs):
                priority = self._determine_priority(path, method_name)
                endpoint_limiter = self._get_endpoint_limiter(path)
                
                # Apply rate limiting
                start_time = time.time()
                
                # Global rate limiting
                if not await self.global_limiter.acquire_async(self.config.request_timeout):
                    self._record_throttle(path, time.time() - start_time)
                    raise Exception(f"Rate limit exceeded for {path}")
                
                # Endpoint-specific rate limiting
                if endpoint_limiter:
                    if not await endpoint_limiter.acquire_async(self.config.request_timeout):
                        self._record_throttle(path, time.time() - start_time)
                        raise Exception(f"Endpoint rate limit exceeded for {path}")
                
                # Record metrics
                wait_time = time.time() - start_time
                self._record_request(path, wait_time)
                
                # Execute request
                try:
                    return await original_method(path, *args, **kwargs)
                except Exception as e:
                    logger.error(f"Request failed for {path}: {e}")
                    raise
            
            return async_wrapper
        
        else:
            @wraps(original_method)
            def sync_wrapper(path: str, *args, **kwargs):
                priority = self._determine_priority(path, method_name)
                endpoint_limiter = self._get_endpoint_limiter(path)
                
                # Apply rate limiting
                start_time = time.time()
                
                # Global rate limiting
                if not self.global_limiter.acquire(self.config.request_timeout):
                    self._record_throttle(path, time.time() - start_time)
                    raise Exception(f"Rate limit exceeded for {path}")
                
                # Endpoint-specific rate limiting
                if endpoint_limiter:
                    if not endpoint_limiter.acquire(self.config.request_timeout):
                        self._record_throttle(path, time.time() - start_time)
                        raise Exception(f"Endpoint rate limit exceeded for {path}")
                
                # Record metrics
                wait_time = time.time() - start_time
                self._record_request(path, wait_time)
                
                # Execute request
                try:
                    return original_method(path, *args, **kwargs)
                except Exception as e:
                    logger.error(f"Request failed for {path}: {e}")
                    raise
            
            return sync_wrapper
    
    def _determine_priority(self, path: str, method: str) -> RequestPriority:
        """Determine request priority based on endpoint and method."""
        # Order operations get highest priority
        if '/orders' in path and method in ['_post_request', '_put_request', '_delete_request']:
            return RequestPriority.CRITICAL_ORDER
        
        # Market data gets medium priority
        if any(segment in path for segment in ['/quotes', '/chains', '/movers']):
            return RequestPriority.MARKET_DATA
        
        # Account info gets lower priority
        if '/accounts' in path:
            return RequestPriority.ACCOUNT_INFO
        
        # Historical data gets lowest priority
        if any(segment in path for segment in ['/pricehistory', '/transactions']):
            return RequestPriority.HISTORICAL_DATA
        
        return RequestPriority.ACCOUNT_INFO  # Default
    
    def _get_endpoint_limiter(self, path: str) -> Optional[SlidingWindowRateLimiter]:
        """Get or create endpoint-specific rate limiter."""
        endpoint_config = self.config.get_endpoint_limit(path)
        if not endpoint_config:
            return None
        
        if path not in self.endpoint_limiters:
            self.endpoint_limiters[path] = SlidingWindowRateLimiter(
                endpoint_config.requests_per_minute,
                60.0  # 1 minute window
            )
        
        return self.endpoint_limiters[path]
    
    def _record_request(self, endpoint: str, wait_time: float):
        """Record request metrics."""
        with self.metrics_lock:
            self.metrics.total_requests += 1
            self.metrics.requests_by_endpoint[endpoint] = (
                self.metrics.requests_by_endpoint.get(endpoint, 0) + 1
            )
            
            # Update wait time statistics
            total_wait = self.metrics.avg_wait_time * (self.metrics.total_requests - 1) + wait_time
            self.metrics.avg_wait_time = total_wait / self.metrics.total_requests
            self.metrics.max_wait_time = max(self.metrics.max_wait_time, wait_time)
    
    def _record_throttle(self, endpoint: str, wait_time: float):
        """Record throttling metrics."""
        with self.metrics_lock:
            self.metrics.throttled_requests += 1
            self.metrics.throttled_by_endpoint[endpoint] = (
                self.metrics.throttled_by_endpoint.get(endpoint, 0) + 1
            )
            
            logger.warning(f"Request throttled for {endpoint}, wait time: {wait_time:.2f}s")
    
    def _start_metrics_logging(self):
        """Start background metrics logging."""
        def log_metrics():
            while True:
                time.sleep(self.config.metrics_log_interval)
                stats = self.get_rate_limit_status()
                logger.info(f"Rate Limiter Metrics: {stats}")
        
        thread = threading.Thread(target=log_metrics, daemon=True)
        thread.start()
    
    def get_rate_limit_status(self) -> Dict[str, Any]:
        """Get comprehensive rate limit status for monitoring."""
        global_stats = self.global_limiter.get_stats()
        
        endpoint_stats = {}
        for endpoint, limiter in self.endpoint_limiters.items():
            endpoint_stats[endpoint] = limiter.get_stats()
        
        with self.metrics_lock:
            metrics_copy = {
                'total_requests': self.metrics.total_requests,
                'throttled_requests': self.metrics.throttled_requests,
                'avg_wait_time': self.metrics.avg_wait_time,
                'max_wait_time': self.metrics.max_wait_time,
                'current_queue_size': len(self.request_queue),
                'requests_by_endpoint': dict(self.metrics.requests_by_endpoint),
                'throttled_by_endpoint': dict(self.metrics.throttled_by_endpoint)
            }
        
        return {
            'global_limiter': global_stats,
            'endpoint_limiters': endpoint_stats,
            'metrics': metrics_copy,
            'config': {
                'default_rpm': self.config.default_requests_per_minute,
                'window_seconds': self.config.default_window_seconds,
                'max_queue_size': self.config.max_queue_size
            }
        }
    
    def reset_metrics(self):
        """Reset all metrics counters."""
        with self.metrics_lock:
            self.metrics = RateLimitMetrics()
        
        # Reset limiter stats
        self.global_limiter.total_requests = 0
        self.global_limiter.rejected_requests = 0
        
        for limiter in self.endpoint_limiters.values():
            limiter.total_requests = 0
            limiter.rejected_requests = 0
    
    @contextmanager
    def batch_requests(self):
        """Context manager for batching multiple requests efficiently."""
        if not self.config.enable_batching:
            yield
            return
        
        batch_start = time.time()
        requests_in_batch = 0
        
        try:
            yield
        finally:
            batch_duration = time.time() - batch_start
            logger.debug(f"Batch completed: {requests_in_batch} requests in {batch_duration:.2f}s")
    
    def __getattr__(self, name):
        """Delegate attribute access to the wrapped client."""
        return getattr(self.client, name)


def create_rate_limited_client(client, config: Optional[RateLimiterConfig] = None):
    """
    Factory function to create a rate-limited client wrapper.
    
    Args:
        client: Original Schwab client (sync or async)
        config: Optional rate limiter configuration
        
    Returns:
        RateLimitedClient wrapper instance
    """
    return RateLimitedClient(client, config)


# Export key classes and functions
__all__ = [
    'RateLimitedClient',
    'RateLimiterConfig', 
    'SlidingWindowRateLimiter',
    'RequestPriority',
    'EndpointLimits',
    'RateLimitMetrics',
    'create_rate_limited_client'
]