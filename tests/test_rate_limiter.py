"""
Comprehensive test suite for the intelligent API rate limiting system.

Tests cover:
- Sliding window rate limiting behavior
- Concurrent access safety
- Priority queue ordering
- Per-endpoint rate limiting
- Configuration and environment variables
- Metrics and monitoring
- Integration with Schwab clients
"""

import asyncio
import os
import pytest
import threading
import time
import unittest.mock as mock
from collections import deque
from concurrent.futures import ThreadPoolExecutor, as_completed
from unittest.mock import MagicMock, patch

import sys
sys.path.append('.')

from enhancements.rate_limiter import (
    SlidingWindowRateLimiter,
    RateLimitedClient,
    RateLimiterConfig,
    RequestPriority,
    EndpointLimits,
    RateLimitMetrics,
    create_rate_limited_client
)


class TestSlidingWindowRateLimiter:
    """Test the core sliding window rate limiter."""
    
    def test_basic_rate_limiting(self):
        """Test basic rate limiting functionality."""
        limiter = SlidingWindowRateLimiter(requests_per_window=3, window_seconds=1.0)
        
        # First 3 requests should pass immediately
        assert limiter.acquire(timeout=0.1) is True
        assert limiter.acquire(timeout=0.1) is True
        assert limiter.acquire(timeout=0.1) is True
        
        # 4th request should be blocked
        assert limiter.acquire(timeout=0.1) is False
        
        # After waiting for window to expire, should work again
        time.sleep(1.1)
        assert limiter.acquire(timeout=0.1) is True
    
    def test_sliding_window_behavior(self):
        """Test that the sliding window slides correctly."""
        limiter = SlidingWindowRateLimiter(requests_per_window=2, window_seconds=1.0)
        
        # Make 2 requests at time 0
        start_time = time.time()
        assert limiter.acquire(timeout=0.1) is True
        assert limiter.acquire(timeout=0.1) is True
        
        # Should be blocked now
        assert limiter.can_proceed() is False
        
        # Wait 0.6 seconds and should still be blocked
        time.sleep(0.6)
        assert limiter.can_proceed() is False
        
        # Wait another 0.5 seconds (total 1.1s) and should be free
        time.sleep(0.5)
        assert limiter.can_proceed() is True
        assert limiter.acquire(timeout=0.1) is True
    
    def test_can_proceed_method(self):
        """Test the can_proceed method for quick checks."""
        limiter = SlidingWindowRateLimiter(requests_per_window=2, window_seconds=1.0)
        
        assert limiter.can_proceed() is True
        limiter.acquire()
        assert limiter.can_proceed() is True
        limiter.acquire()
        assert limiter.can_proceed() is False
    
    def test_wait_time_calculation(self):
        """Test wait time calculation accuracy."""
        limiter = SlidingWindowRateLimiter(requests_per_window=2, window_seconds=1.0)
        
        # Fill up the limiter
        start_time = time.time()
        limiter.acquire()
        limiter.acquire()
        
        # Check wait time is approximately 1 second
        wait_time = limiter.wait_time()
        assert 0.9 <= wait_time <= 1.1
        
        # Wait a bit and check that wait time decreases
        time.sleep(0.3)
        new_wait_time = limiter.wait_time()
        assert new_wait_time < wait_time
        assert 0.6 <= new_wait_time <= 0.8
    
    def test_stats_collection(self):
        """Test statistics collection."""
        limiter = SlidingWindowRateLimiter(requests_per_window=3, window_seconds=1.0)
        
        # Make some requests
        limiter.acquire()
        limiter.acquire()
        
        stats = limiter.get_stats()
        assert stats['current_requests_in_window'] == 2
        assert stats['max_requests_per_window'] == 3
        assert stats['window_seconds'] == 1.0
        assert stats['total_requests'] == 2
        assert stats['rejected_requests'] == 0
        assert stats['utilization_percent'] == (2/3) * 100
        
        # Try to exceed limit
        limiter.acquire()  # This should work
        assert limiter.acquire(timeout=0.1) is False  # This should fail
        
        stats = limiter.get_stats()
        assert stats['total_requests'] == 3
        assert stats['rejected_requests'] == 1
    
    def test_thread_safety(self):
        """Test thread safety with concurrent access."""
        limiter = SlidingWindowRateLimiter(requests_per_window=10, window_seconds=1.0)
        results = []
        
        def make_requests(thread_id):
            thread_results = []
            for i in range(5):
                success = limiter.acquire(timeout=2.0)
                thread_results.append(success)
                time.sleep(0.05)  # Small delay between requests
            return thread_results
        
        # Run multiple threads concurrently
        with ThreadPoolExecutor(max_workers=4) as executor:
            futures = [executor.submit(make_requests, i) for i in range(4)]
            for future in as_completed(futures):
                results.extend(future.result())
        
        # Should have exactly 10 successful requests (the limit)
        successful_requests = sum(results)
        assert successful_requests == 10
        assert len(results) == 20  # 4 threads * 5 requests each
        
        # Verify stats are consistent
        stats = limiter.get_stats()
        assert stats['total_requests'] == 10
        assert stats['rejected_requests'] == 10
    
    @pytest.mark.asyncio
    async def test_async_acquire(self):
        """Test async acquire method."""
        limiter = SlidingWindowRateLimiter(requests_per_window=2, window_seconds=1.0)
        
        # First 2 should succeed
        assert await limiter.acquire_async(timeout=0.1) is True
        assert await limiter.acquire_async(timeout=0.1) is True
        
        # Third should fail
        assert await limiter.acquire_async(timeout=0.1) is False
        
        # After window expires, should work again
        await asyncio.sleep(1.1)
        assert await limiter.acquire_async(timeout=0.1) is True
    
    @pytest.mark.asyncio
    async def test_async_concurrency(self):
        """Test async concurrency handling."""
        limiter = SlidingWindowRateLimiter(requests_per_window=5, window_seconds=1.0)
        
        async def make_request():
            return await limiter.acquire_async(timeout=1.0)
        
        # Launch 10 concurrent requests
        tasks = [make_request() for _ in range(10)]
        results = await asyncio.gather(*tasks)
        
        # Should have exactly 5 successful requests
        successful_requests = sum(results)
        assert successful_requests == 5
        assert len(results) == 10


class TestRateLimiterConfig:
    """Test configuration system."""
    
    def test_default_configuration(self):
        """Test default configuration values."""
        config = RateLimiterConfig()
        
        assert config.default_requests_per_minute == 120
        assert config.default_window_seconds == 60.0
        assert config.max_queue_size == 1000
        assert config.request_timeout == 30.0
        assert config.enable_batching is True
        assert config.batch_size == 10
        assert config.enable_metrics is True
        assert config.metrics_log_interval == 300.0
    
    @patch.dict(os.environ, {
        'SCHWAB_RATE_LIMIT_RPM': '240',
        'SCHWAB_RATE_LIMIT_WINDOW': '120',
        'SCHWAB_RATE_LIMIT_MAX_QUEUE': '2000',
        'SCHWAB_RATE_LIMIT_TIMEOUT': '60',
        'SCHWAB_RATE_LIMIT_BATCHING': 'false',
        'SCHWAB_RATE_LIMIT_BATCH_SIZE': '20',
        'SCHWAB_ORDER_RATE_LIMIT': '30',
        'SCHWAB_QUOTES_RATE_LIMIT': '400'
    })
    def test_environment_variable_configuration(self):
        """Test configuration from environment variables."""
        config = RateLimiterConfig()
        
        assert config.default_requests_per_minute == 240
        assert config.default_window_seconds == 120.0
        assert config.max_queue_size == 2000
        assert config.request_timeout == 60.0
        assert config.enable_batching is False
        assert config.batch_size == 20
        
        # Test endpoint-specific limits
        order_limits = config.get_endpoint_limit('/trader/v1/accounts/123/orders')
        assert order_limits is not None
        assert order_limits.requests_per_minute == 30
        
        quotes_limits = config.get_endpoint_limit('/marketdata/v1/quotes')
        assert quotes_limits is not None
        assert quotes_limits.requests_per_minute == 400
    
    def test_endpoint_limit_matching(self):
        """Test endpoint limit pattern matching."""
        config = RateLimiterConfig()
        
        # Test exact match
        quotes_limits = config.get_endpoint_limit('/marketdata/v1/quotes')
        assert quotes_limits is not None
        assert quotes_limits.requests_per_minute == 200
        
        # Test wildcard pattern matching
        order_limits = config.get_endpoint_limit('/trader/v1/accounts/12345/orders')
        assert order_limits is not None
        assert order_limits.requests_per_minute == 60
        
        # Test unknown endpoint
        unknown_limits = config.get_endpoint_limit('/unknown/endpoint')
        assert unknown_limits is None


class TestRequestPriority:
    """Test request priority system."""
    
    def test_priority_ordering(self):
        """Test that priorities are ordered correctly."""
        priorities = [
            RequestPriority.CRITICAL_ORDER,
            RequestPriority.MARKET_DATA,
            RequestPriority.ACCOUNT_INFO,
            RequestPriority.HISTORICAL_DATA
        ]
        
        # Test enum values are in correct order
        assert RequestPriority.CRITICAL_ORDER.value == 1
        assert RequestPriority.MARKET_DATA.value == 2
        assert RequestPriority.ACCOUNT_INFO.value == 3
        assert RequestPriority.HISTORICAL_DATA.value == 4
        
        # Test sorting works correctly
        from enhancements.rate_limiter import RequestInfo
        import time
        
        requests = [
            RequestInfo(RequestPriority.HISTORICAL_DATA, time.time(), "/history", "GET", (), {}),
            RequestInfo(RequestPriority.CRITICAL_ORDER, time.time(), "/orders", "POST", (), {}),
            RequestInfo(RequestPriority.MARKET_DATA, time.time(), "/quotes", "GET", (), {}),
            RequestInfo(RequestPriority.ACCOUNT_INFO, time.time(), "/accounts", "GET", (), {})
        ]
        
        sorted_requests = sorted(requests)
        assert sorted_requests[0].priority == RequestPriority.CRITICAL_ORDER
        assert sorted_requests[1].priority == RequestPriority.MARKET_DATA
        assert sorted_requests[2].priority == RequestPriority.ACCOUNT_INFO
        assert sorted_requests[3].priority == RequestPriority.HISTORICAL_DATA


class TestRateLimitedClient:
    """Test the rate limited client wrapper."""
    
    def setup_method(self):
        """Set up test fixtures."""
        self.mock_client = MagicMock()
        self.mock_client._get_request = MagicMock(return_value="GET response")
        self.mock_client._post_request = MagicMock(return_value="POST response")
        self.mock_client._put_request = MagicMock(return_value="PUT response")
        self.mock_client._delete_request = MagicMock(return_value="DELETE response")
        
        # Configure for quick testing
        self.config = RateLimiterConfig()
        self.config.default_requests_per_minute = 5  # Low limit for testing
        self.config.default_window_seconds = 1.0
        self.config.request_timeout = 0.5
        self.config.enable_metrics = False  # Disable background logging
    
    def test_client_method_wrapping(self):
        """Test that client methods are properly wrapped."""
        rate_limited_client = RateLimitedClient(self.mock_client, self.config)
        
        # Make a request
        result = rate_limited_client.client._get_request('/test/path', {'param': 'value'})
        
        # Verify the original method was called
        self.mock_client._get_request.assert_called_once_with('/test/path', {'param': 'value'})
        assert result == "GET response"
    
    def test_rate_limiting_enforcement(self):
        """Test that rate limiting is actually enforced."""
        rate_limited_client = RateLimitedClient(self.mock_client, self.config)
        
        # Make requests up to the limit
        for i in range(5):
            result = rate_limited_client.client._get_request(f'/test/path/{i}')
            assert result == "GET response"
        
        # Next request should be rate limited
        with pytest.raises(Exception, match="Rate limit exceeded"):
            rate_limited_client.client._get_request('/test/path/overflow')
    
    def test_priority_determination(self):
        """Test request priority determination."""
        rate_limited_client = RateLimitedClient(self.mock_client, self.config)
        
        # Test order operations get highest priority
        priority = rate_limited_client._determine_priority('/trader/v1/accounts/123/orders', '_post_request')
        assert priority == RequestPriority.CRITICAL_ORDER
        
        priority = rate_limited_client._determine_priority('/trader/v1/accounts/123/orders/456', '_delete_request')
        assert priority == RequestPriority.CRITICAL_ORDER
        
        # Test market data gets medium priority
        priority = rate_limited_client._determine_priority('/marketdata/v1/quotes', '_get_request')
        assert priority == RequestPriority.MARKET_DATA
        
        priority = rate_limited_client._determine_priority('/marketdata/v1/chains', '_get_request')
        assert priority == RequestPriority.MARKET_DATA
        
        # Test account info gets lower priority
        priority = rate_limited_client._determine_priority('/trader/v1/accounts/123', '_get_request')
        assert priority == RequestPriority.ACCOUNT_INFO
        
        # Test historical data gets lowest priority
        priority = rate_limited_client._determine_priority('/marketdata/v1/pricehistory', '_get_request')
        assert priority == RequestPriority.HISTORICAL_DATA
        
        priority = rate_limited_client._determine_priority('/trader/v1/accounts/123/transactions', '_get_request')
        assert priority == RequestPriority.HISTORICAL_DATA
    
    def test_endpoint_specific_limiting(self):
        """Test per-endpoint rate limiting."""
        # Configure strict order limits
        self.config.endpoint_limits['/trader/v1/accounts/*/orders'] = EndpointLimits(
            requests_per_minute=2, burst_allowance=0
        )
        
        rate_limited_client = RateLimitedClient(self.mock_client, self.config)
        
        # Should be able to make 2 order requests
        rate_limited_client.client._post_request('/trader/v1/accounts/123/orders', {})
        rate_limited_client.client._post_request('/trader/v1/accounts/123/orders', {})
        
        # Third order request should fail
        with pytest.raises(Exception, match="Endpoint rate limit exceeded"):
            rate_limited_client.client._post_request('/trader/v1/accounts/123/orders', {})
        
        # But other endpoints should still work (if global limit allows)
        rate_limited_client.client._get_request('/trader/v1/accounts/123')
    
    def test_metrics_collection(self):
        """Test metrics collection and reporting."""
        self.config.enable_metrics = True
        rate_limited_client = RateLimitedClient(self.mock_client, self.config)
        
        # Make some requests
        rate_limited_client.client._get_request('/test/path1')
        rate_limited_client.client._post_request('/test/path2', {})
        
        # Check metrics
        status = rate_limited_client.get_rate_limit_status()
        
        assert status['metrics']['total_requests'] == 2
        assert status['metrics']['throttled_requests'] == 0
        assert '/test/path1' in status['metrics']['requests_by_endpoint']
        assert '/test/path2' in status['metrics']['requests_by_endpoint']
        assert status['metrics']['requests_by_endpoint']['/test/path1'] == 1
        assert status['metrics']['requests_by_endpoint']['/test/path2'] == 1
        
        # Test global limiter stats
        assert 'global_limiter' in status
        assert status['global_limiter']['total_requests'] == 2
        assert status['global_limiter']['current_requests_in_window'] == 2
    
    def test_metrics_reset(self):
        """Test metrics reset functionality."""
        rate_limited_client = RateLimitedClient(self.mock_client, self.config)
        
        # Make some requests
        rate_limited_client.client._get_request('/test/path1')
        rate_limited_client.client._get_request('/test/path2')
        
        # Verify metrics exist
        status = rate_limited_client.get_rate_limit_status()
        assert status['metrics']['total_requests'] == 2
        
        # Reset metrics
        rate_limited_client.reset_metrics()
        
        # Verify metrics are reset
        status = rate_limited_client.get_rate_limit_status()
        assert status['metrics']['total_requests'] == 0
        assert status['metrics']['throttled_requests'] == 0
        assert len(status['metrics']['requests_by_endpoint']) == 0
    
    def test_attribute_delegation(self):
        """Test that client attributes are properly delegated."""
        self.mock_client.api_key = "test_api_key"
        self.mock_client.session = "test_session"
        self.mock_client.custom_method = MagicMock(return_value="custom_result")
        
        rate_limited_client = RateLimitedClient(self.mock_client, self.config)
        
        # Test attribute access
        assert rate_limited_client.api_key == "test_api_key"
        assert rate_limited_client.session == "test_session"
        
        # Test method delegation
        result = rate_limited_client.custom_method("arg1", kwarg="value")
        self.mock_client.custom_method.assert_called_once_with("arg1", kwarg="value")
        assert result == "custom_result"
    
    def test_batch_context_manager(self):
        """Test batch request context manager."""
        rate_limited_client = RateLimitedClient(self.mock_client, self.config)
        
        with rate_limited_client.batch_requests():
            rate_limited_client.client._get_request('/test/batch1')
            rate_limited_client.client._get_request('/test/batch2')
            rate_limited_client.client._get_request('/test/batch3')
        
        # All requests should have been executed
        assert self.mock_client._get_request.call_count == 3


class TestAsyncRateLimitedClient:
    """Test rate limited client with async client."""
    
    def setup_method(self):
        """Set up async test fixtures."""
        self.mock_async_client = MagicMock()
        
        # Create async mock methods
        async def mock_get(path, *args, **kwargs):
            return f"GET {path}"
        
        async def mock_post(path, *args, **kwargs):
            return f"POST {path}"
        
        self.mock_async_client._get_request = mock_get
        self.mock_async_client._post_request = mock_post
        
        # Configure for quick testing
        self.config = RateLimiterConfig()
        self.config.default_requests_per_minute = 5
        self.config.default_window_seconds = 1.0
        self.config.request_timeout = 0.5
        self.config.enable_metrics = False
    
    @pytest.mark.asyncio
    async def test_async_rate_limiting(self):
        """Test rate limiting with async client."""
        rate_limited_client = RateLimitedClient(self.mock_async_client, self.config)
        
        # Make requests up to the limit
        for i in range(5):
            result = await rate_limited_client.client._get_request(f'/test/path/{i}')
            assert result == f"GET /test/path/{i}"
        
        # Next request should be rate limited
        with pytest.raises(Exception, match="Rate limit exceeded"):
            await rate_limited_client.client._get_request('/test/path/overflow')
    
    @pytest.mark.asyncio
    async def test_async_concurrent_requests(self):
        """Test concurrent async requests."""
        rate_limited_client = RateLimitedClient(self.mock_async_client, self.config)
        
        async def make_request(path):
            try:
                return await rate_limited_client.client._get_request(path)
            except Exception:
                return None
        
        # Launch 10 concurrent requests
        tasks = [make_request(f'/test/path/{i}') for i in range(10)]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        # Should have exactly 5 successful requests due to rate limiting
        successful_results = [r for r in results if r is not None and not isinstance(r, Exception)]
        assert len(successful_results) == 5


class TestIntegrationRequirements:
    """Test specific requirements from the task specification."""
    
    def test_120_requests_in_59_seconds_should_pass(self):
        """Test that 120 requests in 59 seconds should pass."""
        # Use a mock time to control timing precisely
        with patch('time.time') as mock_time:
            current_time = 1000.0
            mock_time.return_value = current_time
            
            limiter = SlidingWindowRateLimiter(requests_per_window=120, window_seconds=60.0)
            
            # Make 120 requests over 59 seconds
            for i in range(120):
                mock_time.return_value = current_time + (i * 59.0 / 119)  # Spread over 59 seconds
                success = limiter.acquire(timeout=0.1)
                assert success, f"Request {i+1} should have succeeded"
            
            stats = limiter.get_stats()
            assert stats['total_requests'] == 120
            assert stats['rejected_requests'] == 0
    
    def test_121_requests_in_60_seconds_should_throttle(self):
        """Test that 121 requests in 60 seconds should throttle."""
        with patch('time.time') as mock_time:
            current_time = 1000.0
            mock_time.return_value = current_time
            
            limiter = SlidingWindowRateLimiter(requests_per_window=120, window_seconds=60.0)
            
            # Make 120 requests - all should succeed
            for i in range(120):
                mock_time.return_value = current_time + (i * 59.0 / 119)
                success = limiter.acquire(timeout=0.1)
                assert success, f"Request {i+1} should have succeeded"
            
            # 121st request should fail
            mock_time.return_value = current_time + 59.5
            success = limiter.acquire(timeout=0.1)
            assert not success, "121st request should have been throttled"
            
            stats = limiter.get_stats()
            assert stats['total_requests'] == 120
            assert stats['rejected_requests'] == 1
    
    def test_rate_check_performance(self):
        """Test that rate check completes in <1ms."""
        limiter = SlidingWindowRateLimiter(requests_per_window=120, window_seconds=60.0)
        
        # Fill up some of the window
        for _ in range(60):
            limiter.acquire()
        
        # Time multiple can_proceed calls
        times = []
        for _ in range(100):
            start = time.perf_counter()
            limiter.can_proceed()
            end = time.perf_counter()
            times.append((end - start) * 1000)  # Convert to milliseconds
        
        avg_time = sum(times) / len(times)
        max_time = max(times)
        
        assert avg_time < 1.0, f"Average rate check time {avg_time:.3f}ms exceeds 1ms"
        assert max_time < 2.0, f"Max rate check time {max_time:.3f}ms exceeds 2ms threshold"
    
    def test_memory_usage_bounded(self):
        """Test that memory usage is bounded for timestamp storage."""
        limiter = SlidingWindowRateLimiter(requests_per_window=120, window_seconds=60.0)
        
        # Fill the entire window
        for _ in range(120):
            limiter.acquire()
        
        # Verify timestamp storage is bounded
        assert len(limiter.timestamps) == 120
        
        # Wait for window to expire and make new requests
        time.sleep(61)
        for _ in range(120):
            limiter.acquire()
        
        # Should still be bounded at 120
        assert len(limiter.timestamps) <= 120
    
    def test_concurrent_thread_safety(self):
        """Test thread safety for concurrent operations."""
        limiter = SlidingWindowRateLimiter(requests_per_window=100, window_seconds=1.0)
        results = []
        errors = []
        
        def thread_worker(thread_id, num_requests):
            thread_results = []
            try:
                for i in range(num_requests):
                    success = limiter.acquire(timeout=2.0)
                    thread_results.append(success)
                    time.sleep(0.001)  # Small delay
            except Exception as e:
                errors.append(e)
            return thread_results
        
        # Run 10 threads with 15 requests each (150 total, but limit is 100)
        with ThreadPoolExecutor(max_workers=10) as executor:
            futures = [executor.submit(thread_worker, i, 15) for i in range(10)]
            for future in as_completed(futures):
                results.extend(future.result())
        
        # Should have no exceptions
        assert len(errors) == 0
        
        # Should have exactly 100 successful requests
        successful = sum(results)
        assert successful == 100
        assert len(results) == 150  # 10 threads * 15 requests
        
        # Verify final state is consistent
        stats = limiter.get_stats()
        assert stats['total_requests'] == 100
        assert stats['rejected_requests'] == 50


class TestFactoryFunction:
    """Test the factory function."""
    
    def test_create_rate_limited_client(self):
        """Test the factory function creates proper wrapper."""
        mock_client = MagicMock()
        config = RateLimiterConfig()
        
        rate_limited_client = create_rate_limited_client(mock_client, config)
        
        assert isinstance(rate_limited_client, RateLimitedClient)
        assert rate_limited_client.client is mock_client
        assert rate_limited_client.config is config
    
    def test_create_with_default_config(self):
        """Test factory function with default config."""
        mock_client = MagicMock()
        
        rate_limited_client = create_rate_limited_client(mock_client)
        
        assert isinstance(rate_limited_client, RateLimitedClient)
        assert rate_limited_client.client is mock_client
        assert isinstance(rate_limited_client.config, RateLimiterConfig)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])