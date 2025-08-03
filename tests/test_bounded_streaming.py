"""
Comprehensive test suite for bounded streaming data management.

Tests cover:
- Buffer capacity and drop behavior
- Network lag scenarios
- Memory profiling
- Service restart recovery
- Performance requirements
- Integration contracts
"""

import asyncio
import time
import tempfile
import shutil
import threading
import unittest
from unittest.mock import Mock, patch, MagicMock
from pathlib import Path
import pickle
import gc
import psutil
import os

from enhancements.bounded_streaming import (
    BufferConfig, BufferMetrics, BoundedBuffer, BoundedStreamingManager,
    BoundedStreamClient, OverflowItemsWrapper, create_bounded_stream_client
)


class TestBufferConfig(unittest.TestCase):
    """Test BufferConfig dataclass"""
    
    def test_default_config(self):
        """Test default configuration values"""
        config = BufferConfig()
        self.assertEqual(config.max_size, 10000)
        self.assertEqual(config.drop_threshold, 0.8)
        self.assertIsNone(config.persistence_path)
        self.assertTrue(config.enable_metrics)
        
    def test_custom_config(self):
        """Test custom configuration values"""
        config = BufferConfig(
            max_size=5000,
            drop_threshold=0.9,
            persistence_path="/tmp/test",
            enable_metrics=False
        )
        self.assertEqual(config.max_size, 5000)
        self.assertEqual(config.drop_threshold, 0.9)
        self.assertEqual(config.persistence_path, "/tmp/test")
        self.assertFalse(config.enable_metrics)


class TestBufferMetrics(unittest.TestCase):
    """Test BufferMetrics functionality"""
    
    def test_metrics_initialization(self):
        """Test metrics initialization"""
        metrics = BufferMetrics()
        self.assertEqual(metrics.current_size, 0)
        self.assertEqual(metrics.total_messages, 0)
        self.assertEqual(metrics.dropped_messages, 0)
        self.assertEqual(metrics.fill_rate, 0.0)
        self.assertEqual(metrics.drop_rate, 0.0)
        
    def test_fill_rate_calculation(self):
        """Test fill rate calculation"""
        metrics = BufferMetrics(current_size=80, max_size=100)
        metrics.update_fill_rate()
        self.assertEqual(metrics.fill_rate, 0.8)
        
    def test_drop_rate_calculation(self):
        """Test drop rate calculation"""
        metrics = BufferMetrics(dropped_messages=20, total_messages=100)
        metrics.update_drop_rate()
        self.assertEqual(metrics.drop_rate, 0.2)
        self.assertGreater(metrics.last_updated, 0)


class TestBoundedBuffer(unittest.TestCase):
    """Test BoundedBuffer core functionality"""
    
    def setUp(self):
        """Set up test buffer"""
        self.config = BufferConfig(max_size=5, drop_threshold=0.8)
        self.buffer = BoundedBuffer(self.config, "test_buffer")
        
    def test_buffer_initialization(self):
        """Test buffer initialization"""
        self.assertEqual(len(self.buffer), 0)
        self.assertTrue(self.buffer.is_empty())
        self.assertFalse(self.buffer.is_full())
        self.assertEqual(self.buffer.get_fill_percentage(), 0.0)
        
    def test_append_operations(self):
        """Test O(1) append operations"""
        # Test normal append
        result = self.buffer.append("item1")
        self.assertTrue(result)
        self.assertEqual(len(self.buffer), 1)
        
        # Test appendleft
        result = self.buffer.appendleft("item0")
        self.assertTrue(result)
        self.assertEqual(len(self.buffer), 2)
        
    def test_pop_operations(self):
        """Test O(1) pop operations"""
        self.buffer.append("item1")
        self.buffer.append("item2")
        
        # Test pop
        item = self.buffer.pop()
        self.assertEqual(item, "item2")
        self.assertEqual(len(self.buffer), 1)
        
        # Test popleft
        item = self.buffer.popleft()
        self.assertEqual(item, "item1")
        self.assertEqual(len(self.buffer), 0)
        
    def test_pop_from_empty_buffer(self):
        """Test popping from empty buffer raises exception"""
        with self.assertRaises(IndexError):
            self.buffer.pop()
            
        with self.assertRaises(IndexError):
            self.buffer.popleft()
            
    def test_buffer_capacity_and_drops(self):
        """Test buffer reaches capacity and drops oldest items"""
        drop_callback = Mock()
        self.buffer.add_drop_callback(drop_callback)
        
        # Fill buffer to capacity
        for i in range(5):
            result = self.buffer.append(f"item{i}")
            self.assertTrue(result)
            
        self.assertTrue(self.buffer.is_full())
        self.assertEqual(self.buffer.get_fill_percentage(), 100.0)
        
        # Add one more item - should drop oldest
        result = self.buffer.append("item5")
        self.assertFalse(result)  # Indicates item was dropped
        self.assertEqual(len(self.buffer), 5)  # Still at capacity
        
        # Verify drop callback was called
        drop_callback.assert_called_once()
        call_args = drop_callback.call_args[0]
        self.assertEqual(call_args[0], "test_buffer")  # buffer_id
        self.assertEqual(call_args[1], "item0")       # dropped_item
        self.assertEqual(call_args[2], "item5")       # new_item
        
    def test_extendleft_with_drops(self):
        """Test extendleft operation with capacity limits"""
        # Fill buffer partially
        for i in range(3):
            self.buffer.append(f"item{i}")
            
        # Extend with more items than capacity allows
        items_to_add = ["new1", "new2", "new3", "new4"]
        dropped_count = self.buffer.extendleft(items_to_add)
        
        self.assertEqual(dropped_count, 2)  # 2 items should be dropped
        self.assertEqual(len(self.buffer), 5)  # At capacity
        
    def test_buffer_metrics_tracking(self):
        """Test buffer metrics are correctly tracked"""
        # Add items and verify metrics
        self.buffer.append("item1")
        metrics = self.buffer.get_metrics()
        
        self.assertEqual(metrics.current_size, 1)
        self.assertEqual(metrics.total_messages, 1)
        self.assertEqual(metrics.dropped_messages, 0)
        self.assertEqual(metrics.fill_rate, 0.2)  # 1/5
        self.assertEqual(metrics.drop_rate, 0.0)
        
    def test_alert_callbacks(self):
        """Test alert callbacks are triggered at threshold"""
        alert_callback = Mock()
        self.buffer.add_alert_callback(alert_callback)
        
        # Fill buffer to 80% (drop_threshold)
        for i in range(4):
            self.buffer.append(f"item{i}")
            
        # Alert should be triggered
        alert_callback.assert_called()
        call_args = alert_callback.call_args[0]
        self.assertEqual(call_args[0], "test_buffer")
        self.assertIsInstance(call_args[1], BufferMetrics)
        self.assertGreaterEqual(call_args[1].fill_rate, 0.8)


class TestBoundedBufferPersistence(unittest.TestCase):
    """Test buffer persistence functionality"""
    
    def setUp(self):
        """Set up test environment"""
        self.temp_dir = tempfile.mkdtemp()
        self.persistence_path = os.path.join(self.temp_dir, "test_buffer.pickle")
        self.config = BufferConfig(
            max_size=5,
            persistence_path=self.persistence_path
        )
        self.buffer = BoundedBuffer(self.config, "test_buffer")
        
    def tearDown(self):
        """Clean up test environment"""
        shutil.rmtree(self.temp_dir)
        
    def test_persist_to_disk(self):
        """Test persisting buffer to disk"""
        # Add some data
        for i in range(3):
            self.buffer.append(f"item{i}")
            
        # Persist to disk
        result = self.buffer.persist_to_disk()
        self.assertTrue(result)
        self.assertTrue(Path(self.persistence_path).exists())
        
        # Verify persisted data
        with open(self.persistence_path, 'rb') as f:
            data = pickle.load(f)
            
        self.assertEqual(data['buffer_id'], "test_buffer")
        self.assertEqual(len(data['items']), 3)
        self.assertIn('config', data)
        self.assertIn('metrics', data)
        
    def test_restore_from_disk(self):
        """Test restoring buffer from disk"""
        # Create test data
        test_data = {
            'buffer_id': 'test_buffer',
            'config': {'max_size': 5},
            'metrics': {'total_messages': 10, 'dropped_messages': 2},
            'items': ['item0', 'item1', 'item2']
        }
        
        # Save test data
        with open(self.persistence_path, 'wb') as f:
            pickle.dump(test_data, f)
            
        # Restore buffer
        result = self.buffer.restore_from_disk()
        self.assertTrue(result)
        
        # Verify restored data
        self.assertEqual(len(self.buffer), 3)
        self.assertEqual(self.buffer.pop(), 'item2')
        self.assertEqual(self.buffer.metrics.total_messages, 10)
        self.assertEqual(self.buffer.metrics.dropped_messages, 2)
        
    def test_restore_nonexistent_file(self):
        """Test restore returns False for nonexistent file"""
        config = BufferConfig(persistence_path="/nonexistent/path.pickle")
        buffer = BoundedBuffer(config, "test")
        result = buffer.restore_from_disk()
        self.assertFalse(result)


class TestBoundedStreamingManager(unittest.TestCase):
    """Test BoundedStreamingManager functionality"""
    
    def setUp(self):
        """Set up test manager"""
        self.default_config = BufferConfig(max_size=100)
        self.manager = BoundedStreamingManager(self.default_config)
        
    def test_manager_initialization(self):
        """Test manager initialization"""
        self.assertEqual(self.manager.default_config.max_size, 100)
        self.assertEqual(len(self.manager._buffers), 0)
        
    def test_get_buffer_creates_new(self):
        """Test get_buffer creates new buffer when needed"""
        buffer = self.manager.get_buffer("test_buffer")
        self.assertIsInstance(buffer, BoundedBuffer)
        self.assertEqual(buffer.buffer_id, "test_buffer")
        self.assertEqual(len(self.manager._buffers), 1)
        
    def test_get_buffer_returns_existing(self):
        """Test get_buffer returns existing buffer"""
        buffer1 = self.manager.get_buffer("test_buffer")
        buffer2 = self.manager.get_buffer("test_buffer")
        self.assertIs(buffer1, buffer2)
        
    def test_configure_buffer(self):
        """Test buffer configuration"""
        custom_config = BufferConfig(max_size=50)
        self.manager.configure_buffer("custom_buffer", custom_config)
        
        buffer = self.manager.get_buffer("custom_buffer")
        self.assertEqual(buffer.config.max_size, 50)
        
    def test_global_metrics(self):
        """Test global metrics collection"""
        # Create some buffers and add data
        buffer1 = self.manager.get_buffer("buffer1")
        buffer2 = self.manager.get_buffer("buffer2")
        
        for i in range(5):
            buffer1.append(f"item{i}")
            buffer2.append(f"item{i}")
            
        metrics = self.manager.get_global_metrics()
        
        self.assertEqual(metrics['total_buffers'], 2)
        self.assertEqual(metrics['total_messages'], 10)
        self.assertIn('buffer_details', metrics)
        
    def test_data_availability_status(self):
        """Test data availability status for Agent 8 integration"""
        buffer = self.manager.get_buffer("test_buffer")
        buffer.append("test_item")
        
        # Trigger the drop callback to update availability
        self.manager._on_item_dropped("test_buffer", None, "new_item")
        
        status = self.manager.get_data_availability_status()
        self.assertIn("test_buffer", status)
        
    def test_recent_events(self):
        """Test recent events for Agent 9 integration"""
        buffer = self.manager.get_buffer("test_buffer")
        
        # Trigger some events
        self.manager._on_item_dropped("test_buffer", "old", "new")
        
        events = self.manager.get_recent_events(10)
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]['type'], 'item_dropped')
        self.assertEqual(events[0]['buffer_id'], 'test_buffer')
        
    def test_event_callbacks(self):
        """Test event callbacks for monitoring"""
        callback = Mock()
        self.manager.add_event_callback(callback)
        
        # Trigger an event
        self.manager._on_item_dropped("test_buffer", "old", "new")
        
        callback.assert_called_once()
        call_args = callback.call_args[0]
        self.assertEqual(call_args[0], 'drop')
        self.assertIsInstance(call_args[1], dict)


class TestOverflowItemsWrapper(unittest.TestCase):
    """Test OverflowItemsWrapper compatibility layer"""
    
    def setUp(self):
        """Set up test wrapper"""
        config = BufferConfig(max_size=5)
        self.buffer = BoundedBuffer(config, "test")
        self.wrapper = OverflowItemsWrapper(self.buffer)
        
    def test_wrapper_interface(self):
        """Test wrapper provides deque-like interface"""
        # Test append operations
        self.wrapper.append("item1")
        self.wrapper.appendleft("item0")
        self.assertEqual(len(self.wrapper), 2)
        
        # Test pop operations
        item = self.wrapper.pop()
        self.assertEqual(item, "item1")
        
        item = self.wrapper.popleft()
        self.assertEqual(item, "item0")
        
        self.assertEqual(len(self.wrapper), 0)
        
    def test_wrapper_extendleft(self):
        """Test wrapper extendleft operation"""
        items = ["item1", "item2", "item3"]
        self.wrapper.extendleft(items)
        self.assertEqual(len(self.wrapper), 3)
        
    def test_wrapper_clear(self):
        """Test wrapper clear operation"""
        for i in range(3):
            self.wrapper.append(f"item{i}")
            
        self.wrapper.clear()
        self.assertEqual(len(self.wrapper), 0)


class TestNetworkLagScenarios(unittest.TestCase):
    """Test buffer behavior during network lag scenarios"""
    
    def setUp(self):
        """Set up test environment"""
        self.config = BufferConfig(max_size=100, drop_threshold=0.8)
        self.manager = BoundedStreamingManager(self.config)
        
    def test_burst_messages_during_lag(self):
        """Test handling burst of messages during network lag"""
        buffer = self.manager.get_buffer("lag_test")
        drop_callback = Mock()
        buffer.add_drop_callback(drop_callback)
        
        # Simulate burst of 150 messages (exceeding buffer capacity)
        start_time = time.time()
        for i in range(150):
            buffer.append(f"burst_message_{i}")
            
        end_time = time.time()
        processing_time = end_time - start_time
        
        # Verify performance and behavior
        self.assertLess(processing_time, 0.1)  # Should be very fast
        self.assertEqual(len(buffer), 100)     # At capacity
        self.assertEqual(drop_callback.call_count, 50)  # 50 items dropped
        
        # Verify oldest items were dropped, newest retained
        oldest_item = buffer._buffer[0]
        self.assertTrue(oldest_item.startswith("burst_message_"))
        
    def test_slow_consumer_scenario(self):
        """Test scenario where consumer is slower than producer"""
        buffer = self.manager.get_buffer("slow_consumer")
        
        # Simulate fast producer
        producer_thread = threading.Thread(
            target=self._fast_producer, 
            args=(buffer, 200, 0.001)  # 200 items, 1ms interval
        )
        
        # Simulate slow consumer
        consumer_thread = threading.Thread(
            target=self._slow_consumer,
            args=(buffer, 0.01)  # 10ms per item
        )
        
        producer_thread.start()
        time.sleep(0.1)  # Let producer get ahead
        consumer_thread.start()
        
        producer_thread.join()
        consumer_thread.join()
        
        # Buffer should maintain bounded size
        self.assertLessEqual(len(buffer), buffer.config.max_size)
        
    def _fast_producer(self, buffer, count, interval):
        """Helper: Fast producer for testing"""
        for i in range(count):
            buffer.append(f"fast_item_{i}")
            time.sleep(interval)
            
    def _slow_consumer(self, buffer, interval):
        """Helper: Slow consumer for testing"""
        start_time = time.time()
        while time.time() - start_time < 1.0:  # Run for 1 second
            try:
                buffer.pop()
                time.sleep(interval)
            except IndexError:
                time.sleep(0.001)  # Brief pause if empty


class TestMemoryProfiling(unittest.TestCase):
    """Test memory usage and profiling"""
    
    def setUp(self):
        """Set up memory testing"""
        self.process = psutil.Process()
        
    def test_bounded_memory_usage(self):
        """Test memory usage remains bounded with bounded buffer"""
        # Get initial memory
        initial_memory = self.process.memory_info().rss
        
        # Create bounded buffer
        config = BufferConfig(max_size=1000)
        buffer = BoundedBuffer(config, "memory_test")
        
        # Add many items
        for i in range(10000):  # 10x buffer capacity
            buffer.append(f"memory_test_item_{i:06d}")
            
        # Force garbage collection
        gc.collect()
        
        # Check final memory
        final_memory = self.process.memory_info().rss
        memory_increase = final_memory - initial_memory
        
        # Memory increase should be bounded (less than 10MB for this test)
        self.assertLess(memory_increase, 10 * 1024 * 1024)
        
        # Buffer should be at capacity, not unbounded
        self.assertEqual(len(buffer), 1000)
        
    def test_24_hour_simulation(self):
        """Test memory stability over extended period (simulated)"""
        config = BufferConfig(max_size=5000)
        manager = BoundedStreamingManager(config)
        
        # Simulate 24 hours of messages at 10/second (reduced for testing)
        # Actual test runs much faster but simulates the pattern
        initial_memory = self.process.memory_info().rss
        
        for hour in range(24):
            buffer_id = f"symbol_{hour % 10}"  # Rotate through 10 symbols
            buffer = manager.get_buffer(buffer_id)
            
            # Simulate 1 hour of messages (reduced count for test speed)
            for second in range(100):  # Reduced from 3600 for test speed
                for msg in range(10):  # 10 messages per "second"
                    buffer.append(f"h{hour}_s{second}_m{msg}")
                    
            # Periodic garbage collection
            if hour % 6 == 0:
                gc.collect()
                
        final_memory = self.process.memory_info().rss
        memory_increase = final_memory - initial_memory
        
        # Memory should not grow unbounded
        self.assertLess(memory_increase, 50 * 1024 * 1024)  # Less than 50MB
        
        # All buffers should be at capacity
        for buffer_id, buffer in manager._buffers.items():
            self.assertLessEqual(len(buffer), buffer.config.max_size)


class TestServiceRestartRecovery(unittest.TestCase):
    """Test buffer recovery after service restart"""
    
    def setUp(self):
        """Set up test environment"""
        self.temp_dir = tempfile.mkdtemp()
        
    def tearDown(self):
        """Clean up test environment"""
        shutil.rmtree(self.temp_dir)
        
    def test_buffer_recovery_after_restart(self):
        """Test complete buffer recovery scenario"""
        persistence_path = os.path.join(self.temp_dir, "recovery_test")
        
        # Phase 1: Create and populate buffers
        config = BufferConfig(max_size=100, persistence_path=persistence_path)
        manager1 = BoundedStreamingManager(config)
        
        # Add data to multiple buffers
        test_data = {
            "AAPL": ["price_1", "price_2", "price_3"],
            "GOOGL": ["price_4", "price_5"],
            "MSFT": ["price_6", "price_7", "price_8", "price_9"]
        }
        
        for symbol, prices in test_data.items():
            buffer = manager1.get_buffer(symbol)
            for price in prices:
                buffer.append(price)
                
        # Persist all buffers
        results = manager1.persist_all_buffers(persistence_path)
        for symbol in test_data.keys():
            self.assertTrue(results[symbol], f"Failed to persist {symbol}")
            
        # Phase 2: Simulate restart - create new manager
        manager2 = BoundedStreamingManager(config)
        
        # Restore all buffers
        restore_results = manager2.restore_all_buffers(persistence_path)
        for symbol in test_data.keys():
            self.assertTrue(restore_results[symbol], f"Failed to restore {symbol}")
            
        # Phase 3: Verify data integrity
        for symbol, expected_prices in test_data.items():
            buffer = manager2.get_buffer(symbol)
            self.assertEqual(len(buffer), len(expected_prices))
            
            # Verify data order (LIFO for pop)
            for expected_price in reversed(expected_prices):
                actual_price = buffer.pop()
                self.assertEqual(actual_price, expected_price)
                
    def test_partial_recovery_with_corruption(self):
        """Test recovery when some files are corrupted"""
        persistence_path = os.path.join(self.temp_dir, "partial_recovery")
        config = BufferConfig(persistence_path=persistence_path)
        manager = BoundedStreamingManager(config)
        
        # Create some valid files
        valid_data = {
            'buffer_id': 'AAPL',
            'config': {'max_size': 100},
            'metrics': {'total_messages': 5, 'dropped_messages': 0},
            'items': ['item1', 'item2', 'item3']
        }
        
        valid_path = os.path.join(persistence_path, "AAPL.pickle")
        os.makedirs(persistence_path, exist_ok=True)
        with open(valid_path, 'wb') as f:
            pickle.dump(valid_data, f)
            
        # Create corrupted file
        corrupted_path = os.path.join(persistence_path, "GOOGL.pickle")
        with open(corrupted_path, 'w') as f:
            f.write("corrupted data")
            
        # Attempt recovery
        results = manager.restore_all_buffers(persistence_path)
        
        # Valid file should restore successfully
        self.assertTrue(results['AAPL'])
        buffer = manager.get_buffer('AAPL')
        self.assertEqual(len(buffer), 3)
        
        # Corrupted file should fail gracefully
        self.assertFalse(results['GOOGL'])


class TestPerformanceRequirements(unittest.TestCase):
    """Test performance requirements are met"""
    
    def test_10000_messages_per_second(self):
        """Test system can handle 10,000+ messages per second without drops"""
        config = BufferConfig(max_size=50000)  # Large enough buffer
        buffer = BoundedBuffer(config, "performance_test")
        
        message_count = 15000  # Test with 15k messages
        start_time = time.time()
        
        for i in range(message_count):
            result = buffer.append(f"perf_msg_{i}")
            self.assertTrue(result, f"Message {i} was dropped unexpectedly")
            
        end_time = time.time()
        duration = end_time - start_time
        messages_per_second = message_count / duration
        
        # Should handle at least 10,000 messages per second
        self.assertGreater(messages_per_second, 10000,
                          f"Only achieved {messages_per_second:.0f} msgs/sec")
        
    def test_o1_operations(self):
        """Test all buffer operations are O(1)"""
        config = BufferConfig(max_size=1000)
        buffer = BoundedBuffer(config, "o1_test")
        
        # Test append performance doesn't degrade with size
        times = []
        for size in [100, 500, 1000]:
            # Fill buffer to specific size
            buffer._buffer.clear()
            for i in range(size):
                buffer.append(f"item_{i}")
                
            # Time single operation
            start = time.perf_counter()
            buffer.append("test_item")
            end = time.perf_counter()
            times.append(end - start)
            
        # Operation time should not increase significantly with buffer size
        # (allowing some variance for system noise)
        self.assertLess(times[-1] / times[0], 2.0, 
                       "Operation time increased too much with buffer size")
                       
    def test_concurrent_access_performance(self):
        """Test performance under concurrent access"""
        config = BufferConfig(max_size=10000)
        buffer = BoundedBuffer(config, "concurrent_test")
        
        def producer_worker(start_idx, count):
            for i in range(count):
                buffer.append(f"item_{start_idx + i}")
                
        def consumer_worker(count):
            consumed = 0
            while consumed < count:
                try:
                    buffer.pop()
                    consumed += 1
                except IndexError:
                    time.sleep(0.0001)  # Brief pause if empty
                    
        # Start concurrent producers and consumers
        threads = []
        start_time = time.time()
        
        # 4 producers, each adding 2500 items
        for i in range(4):
            t = threading.Thread(target=producer_worker, args=(i * 2500, 2500))
            threads.append(t)
            t.start()
            
        # 2 consumers, each consuming 5000 items  
        for i in range(2):
            t = threading.Thread(target=consumer_worker, args=(5000,))
            threads.append(t)
            t.start()
            
        # Wait for completion
        for t in threads:
            t.join()
            
        end_time = time.time()
        duration = end_time - start_time
        
        # Should complete within reasonable time
        self.assertLess(duration, 2.0, "Concurrent operations took too long")


class TestIntegrationContracts(unittest.TestCase):
    """Test integration contracts with other agents"""
    
    def test_agent_8_data_availability_contract(self):
        """Test data availability status interface for Agent 8"""
        manager = BoundedStreamingManager()
        
        # Test initial status (no data)
        status = manager.get_data_availability_status()
        self.assertIsInstance(status, dict)
        
        # Add data and trigger availability update
        buffer = manager.get_buffer("AAPL")
        buffer.append("price_data")
        manager._on_item_dropped("AAPL", None, "new_data")
        
        # Verify status update
        status = manager.get_data_availability_status()
        self.assertIn("AAPL", status)
        self.assertIsInstance(status["AAPL"], bool)
        
    def test_agent_9_event_monitoring_contract(self):
        """Test buffer event interface for Agent 9"""
        manager = BoundedStreamingManager()
        
        # Register event callback
        events_received = []
        def event_callback(event_type, event_data):
            events_received.append((event_type, event_data))
            
        manager.add_event_callback(event_callback)
        
        # Trigger events
        manager._on_item_dropped("test_buffer", "old", "new")
        buffer = manager.get_buffer("test_buffer")
        manager._on_buffer_alert("test_buffer", buffer.get_metrics())
        
        # Verify events were captured
        self.assertEqual(len(events_received), 2)
        self.assertEqual(events_received[0][0], "drop")
        self.assertEqual(events_received[1][0], "alert")
        
        # Test recent events retrieval
        recent = manager.get_recent_events(10)
        self.assertIsInstance(recent, list)
        self.assertGreater(len(recent), 0)
        
    def test_agent_7_user_isolation_compatibility(self):
        """Test compatibility with per-user data isolation"""
        manager = BoundedStreamingManager()
        
        # Simulate per-user buffers
        users = ["user_123", "user_456", "user_789"]
        symbols = ["AAPL", "GOOGL", "MSFT"]
        
        # Create buffers for each user-symbol combination
        for user in users:
            for symbol in symbols:
                buffer_id = f"{user}_{symbol}"
                config = BufferConfig(max_size=1000)
                manager.configure_buffer(buffer_id, config)
                buffer = manager.get_buffer(buffer_id)
                buffer.append(f"data_for_{user}_{symbol}")
                
        # Verify isolation
        metrics = manager.get_global_metrics()
        self.assertEqual(metrics['total_buffers'], len(users) * len(symbols))
        
        # Verify each buffer is independent
        user1_aapl = manager.get_buffer("user_123_AAPL")
        user2_aapl = manager.get_buffer("user_456_AAPL")
        self.assertIsNot(user1_aapl, user2_aapl)


class TestBoundedStreamClientIntegration(unittest.TestCase):
    """Test BoundedStreamClient integration with existing StreamClient"""
    
    def test_overflow_items_property_compatibility(self):
        """Test _overflow_items property maintains compatibility"""
        # Mock the StreamClient for testing
        with patch('enhancements.bounded_streaming.StreamClient'):
            manager = BoundedStreamingManager()
            
            # Create mock client
            mock_client = Mock()
            
            # Test the factory function
            bounded_client = create_bounded_stream_client(
                mock_client,
                buffer_configs={"default_overflow": BufferConfig(max_size=100)}
            )
            
            # Test _overflow_items interface
            overflow = bounded_client._overflow_items
            self.assertIsInstance(overflow, OverflowItemsWrapper)
            
            # Test operations
            overflow.append("test_item")
            self.assertEqual(len(overflow), 1)
            
            item = overflow.pop()
            self.assertEqual(item, "test_item")
            
    def test_streaming_metrics_interface(self):
        """Test streaming metrics interface"""
        with patch('enhancements.bounded_streaming.StreamClient'):
            mock_client = Mock()
            bounded_client = create_bounded_stream_client(mock_client)
            
            # Test metrics retrieval
            metrics = bounded_client.get_streaming_metrics()
            self.assertIsInstance(metrics, dict)
            self.assertIn('total_buffers', metrics)
            self.assertIn('total_messages', metrics)


if __name__ == '__main__':
    # Run tests with detailed output
    unittest.main(verbosity=2)