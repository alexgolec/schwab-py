"""
Test suite for ReliableOrderClient with comprehensive coverage.

Tests include:
- Mock various Schwab order status responses
- Timeout scenarios and retry logic
- Bulk operations with partial failures
- Load test: 100 concurrent cancellations
"""

import asyncio
import datetime
import json
import logging
import threading
import time
import unittest
from concurrent.futures import ThreadPoolExecutor, as_completed
from unittest.mock import Mock, MagicMock, patch, call

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from enhancements.reliable_orders import (
    ReliableOrderClient,
    CancellationTimeoutError,
    CancellationFailedError,
    BulkCancellationError,
    OrderState,
    OrderEvent,
    OrderAuditTrail
)


class MockResponse:
    """Mock response object for testing"""
    
    def __init__(self, status_code: int, json_data: dict = None):
        self.status_code = status_code
        self._json_data = json_data or {}
    
    def json(self):
        return self._json_data


class TestReliableOrderClient(unittest.TestCase):
    """Test suite for ReliableOrderClient"""
    
    def setUp(self):
        """Set up test fixtures"""
        # Create mock session and API key
        self.mock_session = Mock()
        self.api_key = "test_api_key"
        
        # Create client instance
        self.client = ReliableOrderClient(
            api_key=self.api_key,
            session=self.mock_session
        )
        
        # Test data
        self.order_id = "12345"
        self.account_hash = "test_account_hash"
        self.user_id = "test_user"
        
        # Configure shorter timeouts for testing
        self.client.poll_interval = 0.1  # 100ms for faster tests
        self.client.max_poll_duration = 1.0  # 1 second max
        self.client._min_request_interval = 0.01  # 10ms for faster tests
    
    def test_order_state_tracking(self):
        """Test order state creation and updates"""
        # Test state creation
        state = self.client._update_order_state(
            self.order_id, self.account_hash, "WORKING", self.user_id
        )
        
        self.assertEqual(state.order_id, self.order_id)
        self.assertEqual(state.account_hash, self.account_hash)
        self.assertEqual(state.status, "WORKING")
        self.assertEqual(state.user_id, self.user_id)
        self.assertEqual(state.cancellation_attempts, 0)
        
        # Test state update
        updated_state = self.client._update_order_state(
            self.order_id, self.account_hash, "CANCELED"
        )
        
        self.assertEqual(updated_state.status, "CANCELED")
        self.assertEqual(updated_state.order_id, self.order_id)
        # User ID should remain
        self.assertEqual(updated_state.user_id, self.user_id)
    
    def test_user_isolation(self):
        """Test Agent 7 per-user order isolation"""
        # Associate orders with different users
        user1_orders = [("order1", "account1"), ("order2", "account1")]
        user2_orders = [("order3", "account2")]
        
        for order_id, account_hash in user1_orders:
            self.client.set_user_context("user1", order_id, account_hash)
            self.client._update_order_state(order_id, account_hash, "WORKING", "user1")
        
        for order_id, account_hash in user2_orders:
            self.client.set_user_context("user2", order_id, account_hash)
            self.client._update_order_state(order_id, account_hash, "WORKING", "user2")
        
        # Test user-specific order retrieval
        user1_states = self.client.get_user_orders("user1")
        user2_states = self.client.get_user_orders("user2")
        
        self.assertEqual(len(user1_states), 2)
        self.assertEqual(len(user2_states), 1)
        
        user1_order_ids = {state.order_id for state in user1_states}
        user2_order_ids = {state.order_id for state in user2_states}
        
        self.assertEqual(user1_order_ids, {"order1", "order2"})
        self.assertEqual(user2_order_ids, {"order3"})
    
    def test_event_emission(self):
        """Test Agent 8 event emission integration"""
        events_captured = []
        
        def event_handler(event: OrderEvent):
            events_captured.append(event)
        
        self.client.register_event_handler(event_handler)
        
        # Emit test event
        test_event = OrderEvent(
            event_type='test_event',
            order_id=self.order_id,
            account_hash=self.account_hash,
            status='TESTING'
        )
        
        self.client._emit_event(test_event)
        
        # Verify event was captured
        self.assertEqual(len(events_captured), 1)
        self.assertEqual(events_captured[0].event_type, 'test_event')
        self.assertEqual(events_captured[0].order_id, self.order_id)
    
    def test_rate_limiting(self):
        """Test Agent 4 rate limiting integration"""
        start_time = time.time()
        
        # Make multiple rate-limited calls
        for _ in range(3):
            self.client._respect_rate_limit()
        
        elapsed = time.time() - start_time
        
        # Should take at least 2 * min_request_interval (3 calls = 2 intervals)
        expected_min_time = 2 * self.client._min_request_interval
        self.assertGreaterEqual(elapsed, expected_min_time * 0.8)  # Allow some tolerance
    
    @patch('enhancements.reliable_orders.ReliableOrderClient.get_order')
    def test_get_order_status_success(self, mock_get_order):
        """Test successful order status retrieval"""
        # Mock successful response
        mock_response = MockResponse(200, {'status': 'WORKING'})
        mock_get_order.return_value = mock_response
        
        status = self.client._get_order_status(self.order_id, self.account_hash)
        
        self.assertEqual(status, 'WORKING')
        mock_get_order.assert_called_once_with(self.order_id, self.account_hash)
    
    @patch('enhancements.reliable_orders.ReliableOrderClient.get_order')
    def test_get_order_status_not_found(self, mock_get_order):
        """Test order status retrieval when order not found"""
        # Mock 404 response
        mock_response = MockResponse(404)
        mock_get_order.return_value = mock_response
        
        status = self.client._get_order_status(self.order_id, self.account_hash)
        
        self.assertIsNone(status)
    
    @patch('enhancements.reliable_orders.ReliableOrderClient.get_order')
    def test_get_order_status_error(self, mock_get_order):
        """Test order status retrieval with API error"""
        # Mock exception
        mock_get_order.side_effect = Exception("API Error")
        
        status = self.client._get_order_status(self.order_id, self.account_hash)
        
        self.assertIsNone(status)
    
    @patch('enhancements.reliable_orders.ReliableOrderClient._get_order_status')
    def test_cancel_order_and_verify_already_canceled(self, mock_get_status):
        """Test cancellation when order is already canceled"""
        # Order is already canceled
        mock_get_status.return_value = 'CANCELED'
        
        result = self.client.cancel_order_and_verify(
            self.order_id, self.account_hash, self.user_id
        )
        
        self.assertTrue(result)
        # Should only check status once
        self.assertEqual(mock_get_status.call_count, 1)
    
    @patch('enhancements.reliable_orders.ReliableOrderClient.cancel_order')
    @patch('enhancements.reliable_orders.ReliableOrderClient._get_order_status')
    def test_cancel_order_and_verify_success(self, mock_get_status, mock_cancel):
        """Test successful order cancellation with verification"""
        # First call: WORKING, second call: CANCELED
        mock_get_status.side_effect = ['WORKING', 'CANCELED']
        mock_cancel.return_value = MockResponse(200)
        
        result = self.client.cancel_order_and_verify(
            self.order_id, self.account_hash, self.user_id
        )
        
        self.assertTrue(result)
        # Should check status twice and cancel once
        self.assertEqual(mock_get_status.call_count, 2)
        mock_cancel.assert_called_once_with(self.order_id, self.account_hash)
    
    @patch('enhancements.reliable_orders.ReliableOrderClient.cancel_order')
    @patch('enhancements.reliable_orders.ReliableOrderClient._get_order_status')
    def test_cancel_order_and_verify_retry_logic(self, mock_get_status, mock_cancel):
        """Test retry logic when order remains WORKING"""
        # Always return WORKING to trigger retries
        mock_get_status.return_value = 'WORKING'
        mock_cancel.return_value = MockResponse(200)
        
        with self.assertRaises(CancellationTimeoutError):
            self.client.cancel_order_and_verify(
                self.order_id, self.account_hash, self.user_id
            )
        
        # Should retry up to max_cancellation_retries times
        self.assertEqual(mock_cancel.call_count, self.client.max_cancellation_retries)
    
    @patch('enhancements.reliable_orders.ReliableOrderClient._get_order_status')
    def test_cancel_order_and_verify_order_not_found(self, mock_get_status):
        """Test cancellation when order is not found"""
        mock_get_status.return_value = None
        
        with self.assertRaises(CancellationFailedError) as context:
            self.client.cancel_order_and_verify(
                self.order_id, self.account_hash, self.user_id
            )
        
        self.assertIn("Order not found", str(context.exception))
    
    @patch('enhancements.reliable_orders.ReliableOrderClient.cancel_order')
    @patch('enhancements.reliable_orders.ReliableOrderClient._get_order_status')
    def test_cancel_order_and_verify_timeout(self, mock_get_status, mock_cancel):
        """Test cancellation timeout scenario"""
        # Always return WORKING to trigger timeout
        mock_get_status.return_value = 'WORKING'
        mock_cancel.return_value = MockResponse(200)
        
        with self.assertRaises(CancellationTimeoutError) as context:
            self.client.cancel_order_and_verify(
                self.order_id, self.account_hash, self.user_id
            )
        
        exception = context.exception
        self.assertEqual(exception.order_id, self.order_id)
        self.assertEqual(exception.account_hash, self.account_hash)
        self.assertEqual(exception.timeout_seconds, self.client.max_poll_duration)
    
    @patch('enhancements.reliable_orders.ReliableOrderClient.cancel_order_and_verify')
    def test_bulk_cancel_orders_success(self, mock_cancel_verify):
        """Test successful bulk cancellation"""
        orders = [
            ("order1", "account1"),
            ("order2", "account1"),
            ("order3", "account2")
        ]
        
        # All cancellations succeed
        mock_cancel_verify.return_value = True
        
        result = self.client.bulk_cancel_orders(orders, self.user_id)
        
        self.assertEqual(len(result['successful']), 3)
        self.assertEqual(len(result['failed']), 0)
        self.assertEqual(len(result['rolled_back']), 0)
        self.assertEqual(mock_cancel_verify.call_count, 3)
    
    @patch('enhancements.reliable_orders.ReliableOrderClient.cancel_order_and_verify')
    def test_bulk_cancel_orders_partial_failure(self, mock_cancel_verify):
        """Test bulk cancellation with partial failures"""
        orders = [
            ("order1", "account1"),  # Success
            ("order2", "account1"),  # Failure
            ("order3", "account2")   # Success
        ]
        
        # Mock mixed results
        def side_effect(order_id, account_hash, user_id):
            if order_id == "order2":
                raise CancellationFailedError(order_id, account_hash, "Test failure", 1)
            return True
        
        mock_cancel_verify.side_effect = side_effect
        
        with self.assertRaises(BulkCancellationError) as context:
            self.client.bulk_cancel_orders(orders, self.user_id)
        
        exception = context.exception
        self.assertEqual(len(exception.successful), 2)
        self.assertEqual(len(exception.failed), 1)
        self.assertIn("order2", exception.failed)
        # Should have rolled back successful orders
        self.assertEqual(len(exception.rolled_back), 2)
    
    @patch('enhancements.reliable_orders.ReliableOrderClient.cancel_order_and_verify')
    def test_bulk_cancel_orders_no_rollback(self, mock_cancel_verify):
        """Test bulk cancellation without rollback on failure"""
        orders = [
            ("order1", "account1"),  # Success
            ("order2", "account1")   # Failure
        ]
        
        def side_effect(order_id, account_hash, user_id):
            if order_id == "order2":
                raise CancellationFailedError(order_id, account_hash, "Test failure", 1)
            return True
        
        mock_cancel_verify.side_effect = side_effect
        
        with self.assertRaises(BulkCancellationError) as context:
            self.client.bulk_cancel_orders(orders, self.user_id, rollback_on_failure=False)
        
        exception = context.exception
        self.assertEqual(len(exception.successful), 1)
        self.assertEqual(len(exception.failed), 1)
        self.assertEqual(len(exception.rolled_back), 0)  # No rollback
    
    def test_audit_trail(self):
        """Test order audit trail functionality"""
        # Log some events
        self.client.audit_trail.log_event(
            self.order_id, self.account_hash, 'test_event',
            {'detail': 'test'}, self.user_id
        )
        
        self.client.audit_trail.log_event(
            "other_order", self.account_hash, 'other_event',
            {'detail': 'other'}, self.user_id
        )
        
        # Test order-specific trail
        order_trail = self.client.audit_trail.get_trail_for_order(self.order_id)
        self.assertEqual(len(order_trail), 1)
        self.assertEqual(order_trail[0]['event'], 'test_event')
        
        # Test user-specific trail
        user_trail = self.client.audit_trail.get_trail_for_user(self.user_id)
        self.assertEqual(len(user_trail), 2)
    
    def test_order_recovery_after_restart(self):
        """Test order state recovery after service restart"""
        # Add some orders to state
        orders = [
            ("order1", "account1", "WORKING"),
            ("order2", "account1", "CANCELED"),
            ("order3", "account2", "WORKING")
        ]
        
        for order_id, account_hash, status in orders:
            self.client._update_order_state(order_id, account_hash, status, self.user_id)
        
        # Test recovery
        recovered_orders = self.client.recover_orders_after_restart()
        self.assertEqual(len(recovered_orders), 3)
        
        # Test user-specific recovery
        user_orders = self.client.recover_orders_after_restart(self.user_id)
        self.assertEqual(len(user_orders), 3)
    
    def test_cleanup_old_states(self):
        """Test cleanup of old order states"""
        # Add orders with different ages
        old_time = datetime.datetime.utcnow() - datetime.timedelta(hours=25)
        recent_time = datetime.datetime.utcnow() - datetime.timedelta(hours=1)
        
        # Mock the update to set specific timestamps
        with patch('datetime.datetime') as mock_datetime:
            # Old order
            mock_datetime.utcnow.return_value = old_time
            self.client._update_order_state("old_order", self.account_hash, "WORKING")
            
            # Recent order
            mock_datetime.utcnow.return_value = recent_time
            self.client._update_order_state("recent_order", self.account_hash, "WORKING")
        
        # Verify both orders exist
        self.assertEqual(len(self.client._order_states), 2)
        
        # Cleanup old states (max age 24 hours)
        self.client.cleanup_old_states(max_age_hours=24)
        
        # Only recent order should remain
        self.assertEqual(len(self.client._order_states), 1)
        self.assertIn(("recent_order", self.account_hash), self.client._order_states)
    
    @patch('enhancements.reliable_orders.ReliableOrderClient.cancel_order_and_verify')
    def test_load_test_concurrent_cancellations(self, mock_cancel_verify):
        """Load test: 100 concurrent cancellations"""
        # Configure mock to simulate success with small delay
        def mock_cancel(order_id, account_hash, user_id):
            time.sleep(0.01)  # Small delay to simulate processing
            return True
        
        mock_cancel_verify.side_effect = mock_cancel
        
        # Generate 100 orders
        orders = [(f"order_{i}", f"account_{i % 5}") for i in range(100)]
        
        start_time = time.time()
        
        # Execute concurrent cancellations
        with ThreadPoolExecutor(max_workers=20) as executor:
            futures = []
            for order_id, account_hash in orders:
                future = executor.submit(
                    self.client.cancel_order_and_verify,
                    order_id, account_hash, f"user_{hash(order_id) % 10}"
                )
                futures.append(future)
            
            # Collect results
            results = []
            for future in as_completed(futures):
                try:
                    result = future.result()
                    results.append(result)
                except Exception as e:
                    results.append(e)
        
        elapsed_time = time.time() - start_time
        
        # Verify all completed
        self.assertEqual(len(results), 100)
        
        # Count successes
        successes = sum(1 for r in results if r is True)
        self.assertEqual(successes, 100)
        
        # Should complete in reasonable time (much less than sequential)
        # Sequential would take at least 100 * 0.01 = 1 second
        self.assertLess(elapsed_time, 0.5)  # Should be much faster with concurrency
        
        print(f"Load test completed: 100 cancellations in {elapsed_time:.3f}s")
    
    def test_network_timeout_handling(self):
        """Test handling of network timeouts during verification"""
        with patch('enhancements.reliable_orders.ReliableOrderClient._get_order_status') as mock_get_status:
            # First call times out, second succeeds
            mock_get_status.side_effect = [None, 'CANCELED']
            
            result = self.client.cancel_order_and_verify(
                self.order_id, self.account_hash, self.user_id
            )
            
            # Should handle timeout and retry
            self.assertTrue(result)
    
    def test_error_handling_during_cancellation(self):
        """Test error handling during cancellation attempts"""
        with patch('enhancements.reliable_orders.ReliableOrderClient._get_order_status') as mock_get_status:
            with patch('enhancements.reliable_orders.ReliableOrderClient.cancel_order') as mock_cancel:
                mock_get_status.return_value = 'WORKING'
                mock_cancel.side_effect = Exception("Network error")
                
                with self.assertRaises(CancellationTimeoutError):
                    self.client.cancel_order_and_verify(
                        self.order_id, self.account_hash, self.user_id
                    )
                
                # Should have attempted retries despite errors
                self.assertEqual(mock_cancel.call_count, self.client.max_cancellation_retries)


class TestOrderAuditTrail(unittest.TestCase):
    """Test audit trail functionality"""
    
    def setUp(self):
        self.audit_trail = OrderAuditTrail()
    
    def test_concurrent_audit_logging(self):
        """Test thread-safe audit logging"""
        def log_events(thread_id):
            for i in range(10):
                self.audit_trail.log_event(
                    f"order_{thread_id}_{i}",
                    "account_hash",
                    "test_event",
                    {"thread_id": thread_id, "event_num": i}
                )
        
        # Run concurrent logging
        threads = []
        for i in range(5):
            thread = threading.Thread(target=log_events, args=(i,))
            threads.append(thread)
            thread.start()
        
        for thread in threads:
            thread.join()
        
        # Should have 50 total events (5 threads * 10 events each)
        self.assertEqual(len(self.audit_trail._trail), 50)


if __name__ == '__main__':
    # Set up logging for tests
    logging.basicConfig(level=logging.DEBUG)
    
    # Run tests
    unittest.main(verbosity=2)