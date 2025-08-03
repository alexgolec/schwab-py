"""
Bounded Streaming Data Management for High-Availability Trading Service

This module implements bounded deque functionality for streaming data to prevent
memory bloat in high-frequency streaming scenarios while maintaining O(1) performance.

Key Features:
- Configurable buffer sizes per symbol/data type
- Data drop monitoring and alerting
- Buffer health metrics (fill rate, drop rate)
- Buffer persistence for service restart recovery
- Integration with Agent 1's resilient streaming
- Interface for Agent 8 signal processing and Agent 9 scheduler monitoring
"""

import asyncio
import json
import logging
import time
import pickle
from collections import deque, defaultdict
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any, Dict, Optional, Set, Callable, List
from threading import Lock
import weakref

logger = logging.getLogger(__name__)


@dataclass
class BufferConfig:
    """Configuration for bounded buffer behavior"""
    max_size: int = 10000
    drop_threshold: float = 0.8  # Start alerting when 80% full
    persistence_path: Optional[str] = None
    enable_metrics: bool = True


@dataclass 
class BufferMetrics:
    """Buffer health metrics"""
    current_size: int = 0
    max_size: int = 0
    total_messages: int = 0
    dropped_messages: int = 0
    fill_rate: float = 0.0
    drop_rate: float = 0.0
    last_updated: float = 0.0
    
    def update_fill_rate(self):
        """Calculate current fill rate"""
        self.fill_rate = self.current_size / self.max_size if self.max_size > 0 else 0.0
        
    def update_drop_rate(self):
        """Calculate drop rate"""
        self.drop_rate = self.dropped_messages / self.total_messages if self.total_messages > 0 else 0.0
        self.last_updated = time.time()


class BoundedBuffer:
    """
    A bounded deque with monitoring and persistence capabilities.
    Provides O(1) operations while preventing memory bloat.
    """
    
    def __init__(self, config: BufferConfig, buffer_id: str):
        self.config = config
        self.buffer_id = buffer_id
        self._buffer = deque(maxlen=config.max_size)
        self._lock = Lock()
        self.metrics = BufferMetrics(max_size=config.max_size)
        self._drop_callbacks: List[Callable] = []
        self._alert_callbacks: List[Callable] = []
        
    def append(self, item: Any) -> bool:
        """
        Append item to buffer. Returns True if added, False if dropped.
        O(1) operation.
        """
        with self._lock:
            was_full = len(self._buffer) >= self.config.max_size
            
            if was_full and self.config.max_size > 0:
                # Item will be dropped (oldest removed automatically)
                self.metrics.dropped_messages += 1
                dropped_item = self._buffer[0] if self._buffer else None
                self._buffer.append(item)
                
                # Trigger drop callbacks
                for callback in self._drop_callbacks:
                    try:
                        callback(self.buffer_id, dropped_item, item)
                    except Exception as e:
                        logger.error(f"Error in drop callback: {e}")
                        
                self._update_metrics()
                return False
            else:
                self._buffer.append(item)
                self._update_metrics()
                return True
                
    def appendleft(self, item: Any) -> bool:
        """
        Append item to left of buffer. Returns True if added, False if dropped.
        O(1) operation.
        """
        with self._lock:
            was_full = len(self._buffer) >= self.config.max_size
            
            if was_full and self.config.max_size > 0:
                # Item will be dropped (rightmost removed automatically)
                self.metrics.dropped_messages += 1
                dropped_item = self._buffer[-1] if self._buffer else None
                self._buffer.appendleft(item)
                
                # Trigger drop callbacks
                for callback in self._drop_callbacks:
                    try:
                        callback(self.buffer_id, dropped_item, item)
                    except Exception as e:
                        logger.error(f"Error in drop callback: {e}")
                        
                self._update_metrics()
                return False
            else:
                self._buffer.appendleft(item)
                self._update_metrics()
                return True
    
    def pop(self) -> Any:
        """Remove and return item from right. O(1) operation."""
        with self._lock:
            try:
                item = self._buffer.pop()
                self._update_metrics()
                return item
            except IndexError:
                raise IndexError("pop from empty buffer")
    
    def popleft(self) -> Any:
        """Remove and return item from left. O(1) operation."""
        with self._lock:
            try:
                item = self._buffer.popleft()
                self._update_metrics()
                return item
            except IndexError:
                raise IndexError("popleft from empty buffer")
                
    def extendleft(self, items: List[Any]) -> int:
        """
        Extend buffer with items from left. Returns number of dropped items.
        O(n) where n is number of items.
        """
        dropped_count = 0
        for item in items:
            if not self.appendleft(item):
                dropped_count += 1
        return dropped_count
    
    def __len__(self) -> int:
        """Return current buffer size. O(1) operation."""
        return len(self._buffer)
        
    def is_empty(self) -> bool:
        """Check if buffer is empty. O(1) operation."""
        return len(self._buffer) == 0
        
    def is_full(self) -> bool:
        """Check if buffer is full. O(1) operation."""
        return len(self._buffer) >= self.config.max_size
        
    def get_fill_percentage(self) -> float:
        """Get current fill percentage. O(1) operation."""
        return (len(self._buffer) / self.config.max_size) * 100 if self.config.max_size > 0 else 0.0
        
    def _update_metrics(self):
        """Update buffer metrics"""
        if self.config.enable_metrics:
            self.metrics.current_size = len(self._buffer)
            self.metrics.total_messages += 1
            self.metrics.update_fill_rate()
            self.metrics.update_drop_rate()
            
            # Check for alerts
            if self.metrics.fill_rate >= self.config.drop_threshold:
                for callback in self._alert_callbacks:
                    try:
                        callback(self.buffer_id, self.metrics)
                    except Exception as e:
                        logger.error(f"Error in alert callback: {e}")
    
    def add_drop_callback(self, callback: Callable):
        """Add callback for when items are dropped"""
        self._drop_callbacks.append(callback)
        
    def add_alert_callback(self, callback: Callable):
        """Add callback for buffer alerts"""
        self._alert_callbacks.append(callback)
        
    def get_metrics(self) -> BufferMetrics:
        """Get current buffer metrics"""
        with self._lock:
            return BufferMetrics(**asdict(self.metrics))
            
    def persist_to_disk(self, path: Optional[str] = None) -> bool:
        """Persist buffer contents to disk for recovery"""
        if not path:
            path = self.config.persistence_path
            
        if not path:
            return False
            
        try:
            with self._lock:
                data = {
                    'buffer_id': self.buffer_id,
                    'config': asdict(self.config),
                    'metrics': asdict(self.metrics),
                    'items': list(self._buffer)
                }
                
                Path(path).parent.mkdir(parents=True, exist_ok=True)
                with open(path, 'wb') as f:
                    pickle.dump(data, f)
                    
                logger.info(f"Persisted buffer {self.buffer_id} to {path}")
                return True
                
        except Exception as e:
            logger.error(f"Failed to persist buffer {self.buffer_id}: {e}")
            return False
            
    def restore_from_disk(self, path: Optional[str] = None) -> bool:
        """Restore buffer contents from disk"""
        if not path:
            path = self.config.persistence_path
            
        if not path or not Path(path).exists():
            return False
            
        try:
            with open(path, 'rb') as f:
                data = pickle.load(f)
                
            with self._lock:
                # Restore items
                self._buffer.clear()
                for item in data.get('items', []):
                    if len(self._buffer) < self.config.max_size:
                        self._buffer.append(item)
                        
                # Restore metrics
                if 'metrics' in data:
                    metrics_data = data['metrics']
                    self.metrics.total_messages = metrics_data.get('total_messages', 0)
                    self.metrics.dropped_messages = metrics_data.get('dropped_messages', 0)
                    self._update_metrics()
                    
                logger.info(f"Restored buffer {self.buffer_id} from {path}")
                return True
                
        except Exception as e:
            logger.error(f"Failed to restore buffer {self.buffer_id}: {e}")
            return False


class BoundedStreamingManager:
    """
    Manager for bounded streaming buffers with per-symbol/data-type configuration.
    Integrates with StreamClient to provide bounded overflow buffer functionality.
    """
    
    def __init__(self, default_config: Optional[BufferConfig] = None):
        self.default_config = default_config or BufferConfig()
        self._buffers: Dict[str, BoundedBuffer] = {}
        self._configs: Dict[str, BufferConfig] = {}
        self._global_metrics = {
            'total_buffers': 0,
            'total_messages': 0,
            'total_drops': 0,
            'active_alerts': set()
        }
        self._event_callbacks: List[Callable] = []
        self._lock = Lock()
        
        # For Agent 8 integration (signal processing)
        self._data_availability_status = defaultdict(bool)
        
        # For Agent 9 integration (scheduler monitoring)  
        self._buffer_events = deque(maxlen=1000)  # Recent events for monitoring
        
    def configure_buffer(self, buffer_id: str, config: BufferConfig):
        """Configure buffer for specific symbol/data type"""
        with self._lock:
            self._configs[buffer_id] = config
            if buffer_id in self._buffers:
                # Update existing buffer
                old_buffer = self._buffers[buffer_id]
                self._buffers[buffer_id] = BoundedBuffer(config, buffer_id)
                
                # Migrate data if possible
                with old_buffer._lock:
                    items_to_migrate = list(old_buffer._buffer)
                    
                for item in items_to_migrate:
                    if len(self._buffers[buffer_id]) < config.max_size:
                        self._buffers[buffer_id]._buffer.append(item)
                        
    def get_buffer(self, buffer_id: str) -> BoundedBuffer:
        """Get or create buffer for given ID"""
        if buffer_id not in self._buffers:
            with self._lock:
                if buffer_id not in self._buffers:  # Double-check locking
                    config = self._configs.get(buffer_id, self.default_config)
                    buffer = BoundedBuffer(config, buffer_id)
                    
                    # Add default callbacks
                    buffer.add_drop_callback(self._on_item_dropped)
                    buffer.add_alert_callback(self._on_buffer_alert)
                    
                    self._buffers[buffer_id] = buffer
                    self._global_metrics['total_buffers'] += 1
                    
        return self._buffers[buffer_id]
        
    def _on_item_dropped(self, buffer_id: str, dropped_item: Any, new_item: Any):
        """Handle item drop events"""
        self._global_metrics['total_drops'] += 1
        
        # Create event for Agent 9 monitoring
        event = {
            'type': 'item_dropped',
            'buffer_id': buffer_id,
            'timestamp': time.time(),
            'dropped_item_type': type(dropped_item).__name__ if dropped_item else None,
            'new_item_type': type(new_item).__name__
        }
        self._buffer_events.append(event)
        
        # Update data availability for Agent 8
        if buffer_id in self._buffers:
            self._data_availability_status[buffer_id] = len(self._buffers[buffer_id]) > 0
        
        # Trigger callbacks
        for callback in self._event_callbacks:
            try:
                callback('drop', event)
            except Exception as e:
                logger.error(f"Error in event callback: {e}")
                
        logger.warning(f"Buffer {buffer_id} dropped item due to capacity limit")
        
    def _on_buffer_alert(self, buffer_id: str, metrics: BufferMetrics):
        """Handle buffer alert events"""
        self._global_metrics['active_alerts'].add(buffer_id)
        
        # Create event for Agent 9 monitoring
        event = {
            'type': 'buffer_alert',
            'buffer_id': buffer_id,
            'timestamp': time.time(),
            'fill_rate': metrics.fill_rate,
            'drop_rate': metrics.drop_rate,
            'current_size': metrics.current_size
        }
        self._buffer_events.append(event)
        
        # Trigger callbacks
        for callback in self._event_callbacks:
            try:
                callback('alert', event)
            except Exception as e:
                logger.error(f"Error in event callback: {e}")
                
        logger.warning(f"Buffer {buffer_id} alert: {metrics.fill_rate:.1%} full")
        
    def add_event_callback(self, callback: Callable):
        """Add callback for buffer events (for Agent 9 integration)"""
        self._event_callbacks.append(callback)
        
    def get_data_availability_status(self) -> Dict[str, bool]:
        """Get data availability status for Agent 8 integration"""
        return dict(self._data_availability_status)
        
    def get_recent_events(self, count: int = 100) -> List[Dict]:
        """Get recent buffer events for Agent 9 integration"""
        return list(self._buffer_events)[-count:]
        
    def get_global_metrics(self) -> Dict:
        """Get global metrics across all buffers"""
        with self._lock:
            total_messages = sum(buf.metrics.total_messages for buf in self._buffers.values())
            total_drops = sum(buf.metrics.dropped_messages for buf in self._buffers.values())
            
            return {
                'total_buffers': len(self._buffers),
                'total_messages': total_messages,
                'total_drops': total_drops,
                'global_drop_rate': total_drops / total_messages if total_messages > 0 else 0.0,
                'active_alerts': list(self._global_metrics['active_alerts']),
                'buffer_details': {
                    buf_id: buf.get_metrics() for buf_id, buf in self._buffers.items()
                }
            }
            
    def persist_all_buffers(self, base_path: str) -> Dict[str, bool]:
        """Persist all buffers to disk"""
        results = {}
        base_path = Path(base_path)
        base_path.mkdir(parents=True, exist_ok=True)
        
        for buffer_id, buffer in self._buffers.items():
            path = base_path / f"{buffer_id}.pickle"
            results[buffer_id] = buffer.persist_to_disk(str(path))
            
        return results
        
    def restore_all_buffers(self, base_path: str) -> Dict[str, bool]:
        """Restore all buffers from disk"""
        results = {}
        base_path = Path(base_path)
        
        if not base_path.exists():
            return results
            
        for pickle_file in base_path.glob("*.pickle"):
            buffer_id = pickle_file.stem
            try:
                # Create buffer if it doesn't exist
                buffer = self.get_buffer(buffer_id)
                results[buffer_id] = buffer.restore_from_disk(str(pickle_file))
            except Exception as e:
                logger.error(f"Failed to restore buffer {buffer_id}: {e}")
                results[buffer_id] = False
                
        return results


class BoundedStreamClient:
    """
    Mixin class to add bounded streaming capabilities to StreamClient.
    Overrides _overflow_items behavior with bounded buffers.
    """
    
    def __init__(self, *args, streaming_manager: Optional[BoundedStreamingManager] = None, **kwargs):
        # Initialize the streaming manager
        self.streaming_manager = streaming_manager or BoundedStreamingManager()
        
        # Get the default overflow buffer
        self._overflow_buffer = self.streaming_manager.get_buffer('default_overflow')
        
        # Store original _overflow_items for compatibility
        self._original_overflow_items = deque()
        
        super().__init__(*args, **kwargs)
        
    @property 
    def _overflow_items(self):
        """Property to maintain compatibility with existing StreamClient interface"""
        # Return a deque-like object that wraps our bounded buffer
        return OverflowItemsWrapper(self._overflow_buffer)
        
    @_overflow_items.setter
    def _overflow_items(self, value):
        """Allow setting _overflow_items for compatibility"""
        if hasattr(value, '__iter__'):
            self._overflow_buffer._buffer.clear()
            for item in value:
                self._overflow_buffer.append(item)
                
    def configure_overflow_buffer(self, config: BufferConfig):
        """Configure the overflow buffer"""
        self.streaming_manager.configure_buffer('default_overflow', config)
        self._overflow_buffer = self.streaming_manager.get_buffer('default_overflow')
        
    def get_streaming_metrics(self) -> Dict:
        """Get streaming buffer metrics"""
        return self.streaming_manager.get_global_metrics()


class OverflowItemsWrapper:
    """
    Wrapper class to make BoundedBuffer compatible with deque interface.
    Maintains O(1) performance while providing bounded behavior.
    """
    
    def __init__(self, bounded_buffer: BoundedBuffer):
        self._buffer = bounded_buffer
        
    def __len__(self):
        return len(self._buffer)
        
    def append(self, item):
        self._buffer.append(item)
        
    def appendleft(self, item):
        self._buffer.appendleft(item)
        
    def pop(self):
        return self._buffer.pop()
        
    def popleft(self):
        return self._buffer.popleft()
        
    def extendleft(self, items):
        return self._buffer.extendleft(items)
        
    def clear(self):
        while not self._buffer.is_empty():
            try:
                self._buffer.pop()
            except IndexError:
                break


# Factory function for easy integration
def create_bounded_stream_client(client, buffer_configs: Optional[Dict[str, BufferConfig]] = None, **kwargs):
    """
    Factory function to create a StreamClient with bounded streaming capabilities.
    
    Args:
        client: The base client for authentication
        buffer_configs: Optional dictionary of buffer configurations by buffer_id
        **kwargs: Additional arguments for StreamClient
        
    Returns:
        StreamClient with bounded streaming capabilities
    """
    from schwab.streaming import StreamClient
    
    # Create streaming manager
    manager = BoundedStreamingManager()
    
    # Configure buffers if provided
    if buffer_configs:
        for buffer_id, config in buffer_configs.items():
            manager.configure_buffer(buffer_id, config)
    
    # Create combined class that inherits from both BoundedStreamClient and StreamClient
    class BoundedStreamClientImpl(BoundedStreamClient, StreamClient):
        pass
    
    return BoundedStreamClientImpl(client, streaming_manager=manager, **kwargs)