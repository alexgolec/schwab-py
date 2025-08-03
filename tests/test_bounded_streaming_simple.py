"""
Simplified test suite for bounded streaming (no external dependencies)
"""

import unittest
import time
import tempfile
import shutil
import threading
import os
import pickle
from pathlib import Path
from unittest.mock import Mock

from enhancements.bounded_streaming import (
    BufferConfig, BufferMetrics, BoundedBuffer, BoundedStreamingManager,
    OverflowItemsWrapper
)


class TestBoundedBufferCore(unittest.TestCase):
    """Core functionality tests"""
    
    def setUp(self):
        self.config = BufferConfig(max_size=5, drop_threshold=0.8)
        self.buffer = BoundedBuffer(self.config, "test_buffer")
        
    def test_buffer_capacity_enforcement(self):
        """REQUIREMENT: Fill buffer to capacity + 1, verify oldest dropped"""
        drop_callback = Mock()
        self.buffer.add_drop_callback(drop_callback)
        
        # Fill buffer to capacity
        for i in range(5):
            result = self.buffer.append(f"item{i}")
            self.assertTrue(result)
            
        self.assertTrue(self.buffer.is_full())
        
        # Add one more - should drop oldest
        result = self.buffer.append("item5")
        self.assertFalse(result)  # Indicates drop occurred
        self.assertEqual(len(self.buffer), 5)  # Still at capacity
        
        # Verify oldest was dropped
        drop_callback.assert_called_once()
        dropped_item = drop_callback.call_args[0][1]
        self.assertEqual(dropped_item, "item0")
        
    def test_o1_performance(self):
        """REQUIREMENT: Buffer operations must be O(1)"""
        config = BufferConfig(max_size=1000)
        buffer = BoundedBuffer(config, "perf_test")
        
        # Test that operation time doesn't increase significantly with size
        small_buffer_times = []
        large_buffer_times = []
        
        # Small buffer (100 items)
        for i in range(100):
            buffer.append(f"item{i}")
            
        for _ in range(10):
            start = time.perf_counter()
            buffer.append("test")
            buffer.pop()
            end = time.perf_counter()
            small_buffer_times.append(end - start)
            
        # Large buffer (900 items)
        for i in range(800):
            buffer.append(f"item{i}")
            
        for _ in range(10):
            start = time.perf_counter()
            buffer.append("test")
            buffer.pop()
            end = time.perf_counter()
            large_buffer_times.append(end - start)
            
        avg_small = sum(small_buffer_times) / len(small_buffer_times)
        avg_large = sum(large_buffer_times) / len(large_buffer_times)
        
        # Should not increase by more than 3x (allowing for variance)
        self.assertLess(avg_large / avg_small, 3.0)
        
    def test_high_frequency_messages(self):
        """REQUIREMENT: Support 10,000+ messages per second without drops"""
        config = BufferConfig(max_size=20000)  # Large enough buffer
        buffer = BoundedBuffer(config, "high_freq_test")
        
        message_count = 15000
        start_time = time.time()
        
        for i in range(message_count):
            result = buffer.append(f"msg_{i}")
            self.assertTrue(result, f"Message {i} was unexpectedly dropped")
            
        end_time = time.time()
        duration = end_time - start_time
        
        if duration > 0:
            messages_per_second = message_count / duration
            self.assertGreater(messages_per_second, 10000)
            
    def test_buffer_metrics(self):
        """Test buffer health metrics"""
        # Add some items
        for i in range(3):
            self.buffer.append(f"item{i}")
            
        metrics = self.buffer.get_metrics()
        self.assertEqual(metrics.current_size, 3)
        self.assertEqual(metrics.total_messages, 3)
        self.assertEqual(metrics.dropped_messages, 0)
        self.assertEqual(metrics.fill_rate, 0.6)  # 3/5
        
    def test_drop_monitoring(self):
        """Test data drop monitoring and alerting"""
        drop_events = []
        alert_events = []
        
        def drop_callback(buffer_id, dropped, new):
            drop_events.append((buffer_id, dropped, new))
            
        def alert_callback(buffer_id, metrics):
            alert_events.append((buffer_id, metrics.fill_rate))
            
        self.buffer.add_drop_callback(drop_callback)
        self.buffer.add_alert_callback(alert_callback)
        
        # Fill to threshold (80%)
        for i in range(4):
            self.buffer.append(f"item{i}")
            
        # Should trigger alert
        self.assertEqual(len(alert_events), 1)
        self.assertGreaterEqual(alert_events[0][1], 0.8)
        
        # Fill to capacity and beyond
        self.buffer.append("item4")  # Fill to capacity
        self.buffer.append("item5")  # Trigger drop
        
        # Should trigger drop event
        self.assertEqual(len(drop_events), 1)
        self.assertEqual(drop_events[0][1], "item0")  # Oldest dropped


class TestBoundedStreamingManager(unittest.TestCase):
    """Test streaming manager functionality"""
    
    def setUp(self):
        self.manager = BoundedStreamingManager()
        
    def test_configurable_buffer_sizes(self):
        """REQUIREMENT: Configurable buffer sizes per symbol/data type"""
        # Configure different buffer sizes
        configs = {
            "AAPL": BufferConfig(max_size=1000),
            "GOOGL": BufferConfig(max_size=2000),
            "MSFT": BufferConfig(max_size=500)
        }
        
        for symbol, config in configs.items():
            self.manager.configure_buffer(symbol, config)
            
        # Verify buffers have correct sizes
        for symbol, config in configs.items():
            buffer = self.manager.get_buffer(symbol)
            self.assertEqual(buffer.config.max_size, config.max_size)
            
    def test_global_metrics(self):
        """Test global metrics collection"""
        # Create buffers and add data
        symbols = ["AAPL", "GOOGL", "MSFT"]
        for symbol in symbols:
            buffer = self.manager.get_buffer(symbol)
            for i in range(10):
                buffer.append(f"{symbol}_price_{i}")
                
        metrics = self.manager.get_global_metrics()
        
        self.assertEqual(metrics['total_buffers'], 3)
        self.assertEqual(metrics['total_messages'], 30)
        self.assertIn('buffer_details', metrics)
        
    def test_agent_integration_interfaces(self):
        """Test interfaces for Agent 8 and Agent 9 integration"""
        buffer = self.manager.get_buffer("test_symbol")
        buffer.append("test_data")
        
        # Trigger events
        self.manager._on_item_dropped("test_symbol", "old", "new")
        
        # Test Agent 8 interface (data availability)
        availability = self.manager.get_data_availability_status()
        self.assertIsInstance(availability, dict)
        
        # Test Agent 9 interface (recent events)
        events = self.manager.get_recent_events(10)
        self.assertIsInstance(events, list)
        self.assertGreater(len(events), 0)
        
        # Test event callbacks
        callback_called = []
        def event_callback(event_type, event_data):
            callback_called.append((event_type, event_data))
            
        self.manager.add_event_callback(event_callback)
        self.manager._on_item_dropped("test", "old", "new")
        
        self.assertEqual(len(callback_called), 1)


class TestBufferPersistence(unittest.TestCase):
    """Test buffer persistence for service restart recovery"""
    
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        
    def tearDown(self):
        shutil.rmtree(self.temp_dir)
        
    def test_service_restart_recovery(self):
        """REQUIREMENT: Test buffer recovery after restart"""
        persistence_path = os.path.join(self.temp_dir, "recovery_test")
        
        # Phase 1: Create and populate manager
        config = BufferConfig(max_size=100)
        manager1 = BoundedStreamingManager(config)
        
        test_data = {
            "AAPL": ["price_1", "price_2", "price_3"],
            "GOOGL": ["price_4", "price_5"]
        }
        
        for symbol, prices in test_data.items():
            buffer = manager1.get_buffer(symbol)
            for price in prices:
                buffer.append(price)
                
        # Persist all buffers
        results = manager1.persist_all_buffers(persistence_path)
        for symbol in test_data.keys():
            self.assertTrue(results[symbol])
            
        # Phase 2: Simulate restart
        manager2 = BoundedStreamingManager(config)
        
        # Restore buffers
        restore_results = manager2.restore_all_buffers(persistence_path)
        for symbol in test_data.keys():
            self.assertTrue(restore_results[symbol])
            
        # Phase 3: Verify data integrity
        for symbol, expected_prices in test_data.items():
            buffer = manager2.get_buffer(symbol)
            self.assertEqual(len(buffer), len(expected_prices))
            
            # Verify data (LIFO order)
            for expected in reversed(expected_prices):
                actual = buffer.pop()
                self.assertEqual(actual, expected)


class TestNetworkLagScenarios(unittest.TestCase):
    """Test buffer during network lag scenarios"""
    
    def test_burst_handling(self):
        """REQUIREMENT: Test buffer during network lag scenarios"""
        config = BufferConfig(max_size=100)
        manager = BoundedStreamingManager(config)
        buffer = manager.get_buffer("lag_test")
        
        drop_callback = Mock()
        buffer.add_drop_callback(drop_callback)
        
        # Simulate burst of messages exceeding capacity
        burst_size = 150
        start_time = time.time()
        
        for i in range(burst_size):
            buffer.append(f"burst_msg_{i}")
            
        end_time = time.time()
        
        # Should complete quickly (< 100ms)
        self.assertLess(end_time - start_time, 0.1)
        
        # Buffer should be at capacity
        self.assertEqual(len(buffer), 100)
        
        # Should have dropped 50 messages
        self.assertEqual(drop_callback.call_count, 50)
        
    def test_concurrent_producer_consumer(self):
        """Test concurrent access scenarios"""
        config = BufferConfig(max_size=1000)
        buffer = BoundedBuffer(config, "concurrent_test")
        
        def producer(count):
            for i in range(count):
                buffer.append(f"item_{i}")
                
        def consumer(count):
            consumed = 0
            while consumed < count:
                try:
                    buffer.pop()
                    consumed += 1
                except IndexError:
                    pass
                    
        # Start threads
        producer_thread = threading.Thread(target=producer, args=(500,))
        consumer_thread = threading.Thread(target=consumer, args=(500,))
        
        start_time = time.time()
        producer_thread.start()
        consumer_thread.start()
        
        producer_thread.join()
        consumer_thread.join()
        end_time = time.time()
        
        # Should complete within reasonable time
        self.assertLess(end_time - start_time, 2.0)
        
        # Buffer should maintain bounded size
        self.assertLessEqual(len(buffer), buffer.config.max_size)


class TestOverflowItemsWrapper(unittest.TestCase):
    """Test compatibility wrapper"""
    
    def test_deque_interface_compatibility(self):
        """Test wrapper maintains deque interface"""
        config = BufferConfig(max_size=10)
        buffer = BoundedBuffer(config, "test")
        wrapper = OverflowItemsWrapper(buffer)
        
        # Test all required operations
        wrapper.append("item1")
        wrapper.appendleft("item0") 
        self.assertEqual(len(wrapper), 2)
        
        item = wrapper.pop()
        self.assertEqual(item, "item1")
        
        item = wrapper.popleft()
        self.assertEqual(item, "item0")
        
        # Test extendleft
        wrapper.extendleft(["a", "b", "c"])
        self.assertEqual(len(wrapper), 3)
        
        # Test clear
        wrapper.clear()
        self.assertEqual(len(wrapper), 0)


if __name__ == '__main__':
    # Run tests
    unittest.main(verbosity=2)