"""
Moving Average Signal Processor Extension

This extension demonstrates a signal processor that generates buy/sell signals
based on moving average crossovers. It extends Agent 8's signal processing capabilities.

Author: Agent 10 - Extensibility Architect
"""

import logging
from typing import Dict, List, Optional, Any
from collections import deque
import time

from enhancements.extension_framework import (
    ExtensionBase, ExtensionAPI, ExtensionType, extension
)


@extension(ExtensionType.SIGNAL_PROCESSOR, name="Moving Average Signal Processor")
class MovingAverageSignalProcessor(ExtensionBase):
    """
    Signal processor that generates trading signals based on moving average crossovers.
    
    This extension demonstrates:
    - Real-time market data processing
    - Technical indicator calculation
    - Signal generation and publishing
    - Configuration management
    - Event-driven architecture
    """
    
    def __init__(self, api: ExtensionAPI):
        super().__init__(api)
        self.logger = logging.getLogger(__name__)
        
        # Configuration
        self.short_period = self.api.get_config('short_period', 10)
        self.long_period = self.api.get_config('long_period', 20)
        self.symbols = self.api.get_config('symbols', ['AAPL', 'MSFT', 'GOOGL'])
        
        # Data storage
        self.price_history: Dict[str, deque] = {}
        self.short_ma: Dict[str, deque] = {}
        self.long_ma: Dict[str, deque] = {}
        self.last_signals: Dict[str, str] = {}
        
        # Event handlers
        self._market_data_handler = None
        self._active = False
    
    def initialize(self) -> None:
        """Initialize the signal processor"""
        self.logger.info("Initializing Moving Average Signal Processor")
        
        # Initialize data structures for each symbol
        for symbol in self.symbols:
            self.price_history[symbol] = deque(maxlen=max(self.short_period, self.long_period))
            self.short_ma[symbol] = deque(maxlen=1)
            self.long_ma[symbol] = deque(maxlen=1)
            self.last_signals[symbol] = 'none'
        
        # Subscribe to market data events
        self._market_data_handler = self._handle_market_data
        self.api.context.event_bus.subscribe('market_data_update', self._market_data_handler)
        
        self.logger.info(f"Initialized for symbols: {self.symbols}")
    
    def activate(self) -> None:
        """Activate the signal processor"""
        self.logger.info("Activating Moving Average Signal Processor")
        self._active = True
        
        # Publish activation event
        self.api.publish_event('signal_processor_activated', {
            'processor_type': 'moving_average',
            'symbols': self.symbols,
            'parameters': {
                'short_period': self.short_period,
                'long_period': self.long_period
            }
        })
    
    def deactivate(self) -> None:
        """Deactivate the signal processor"""
        self.logger.info("Deactivating Moving Average Signal Processor")
        self._active = False
        
        # Publish deactivation event
        self.api.publish_event('signal_processor_deactivated', {
            'processor_type': 'moving_average'
        })
    
    def cleanup(self) -> None:
        """Clean up resources"""
        self.logger.info("Cleaning up Moving Average Signal Processor")
        
        # Unsubscribe from events
        if self._market_data_handler:
            self.api.context.event_bus.unsubscribe('market_data_update', self._market_data_handler)
        
        # Clear data structures
        self.price_history.clear()
        self.short_ma.clear()
        self.long_ma.clear()
        self.last_signals.clear()
    
    def _handle_market_data(self, event_type: str, data: Dict[str, Any]) -> None:
        """Handle incoming market data updates"""
        if not self._active:
            return
        
        try:
            symbol = data.get('symbol')
            price = data.get('price')
            timestamp = data.get('timestamp', time.time())
            
            if not symbol or not price or symbol not in self.symbols:
                return
            
            # Update price history
            self.price_history[symbol].append(price)
            
            # Calculate moving averages if we have enough data
            if len(self.price_history[symbol]) >= max(self.short_period, self.long_period):
                self._calculate_moving_averages(symbol)
                self._generate_signals(symbol, timestamp)
        
        except Exception as e:
            self.logger.error(f"Error processing market data: {e}")
    
    def _calculate_moving_averages(self, symbol: str) -> None:
        """Calculate short and long moving averages"""
        prices = list(self.price_history[symbol])
        
        # Calculate short moving average
        if len(prices) >= self.short_period:
            short_ma = sum(prices[-self.short_period:]) / self.short_period
            self.short_ma[symbol].append(short_ma)
        
        # Calculate long moving average
        if len(prices) >= self.long_period:
            long_ma = sum(prices[-self.long_period:]) / self.long_period
            self.long_ma[symbol].append(long_ma)
    
    def _generate_signals(self, symbol: str, timestamp: float) -> None:
        """Generate trading signals based on moving average crossovers"""
        if not self.short_ma[symbol] or not self.long_ma[symbol]:
            return
        
        short_ma = self.short_ma[symbol][-1]
        long_ma = self.long_ma[symbol][-1]
        
        # Determine signal
        current_signal = 'none'
        if short_ma > long_ma:
            current_signal = 'buy'
        elif short_ma < long_ma:
            current_signal = 'sell'
        
        # Check if signal changed
        if current_signal != self.last_signals[symbol]:
            self.last_signals[symbol] = current_signal
            
            if current_signal != 'none':
                signal_data = {
                    'symbol': symbol,
                    'signal': current_signal,
                    'timestamp': timestamp,
                    'short_ma': short_ma,
                    'long_ma': long_ma,
                    'price': self.price_history[symbol][-1],
                    'processor_type': 'moving_average',
                    'parameters': {
                        'short_period': self.short_period,
                        'long_period': self.long_period
                    }
                }
                
                # Publish signal event
                self.api.publish_event('trading_signal', signal_data)
                
                # Log signal
                self.logger.info(f"Generated {current_signal.upper()} signal for {symbol}: "
                               f"Short MA: {short_ma:.2f}, Long MA: {long_ma:.2f}")
    
    def update_config(self, config: Dict[str, Any]) -> None:
        """Update configuration parameters"""
        if 'short_period' in config:
            self.short_period = config['short_period']
            self.api.set_config('short_period', self.short_period)
        
        if 'long_period' in config:
            self.long_period = config['long_period']
            self.api.set_config('long_period', self.long_period)
        
        if 'symbols' in config:
            self.symbols = config['symbols']
            self.api.set_config('symbols', self.symbols)
            
            # Reinitialize data structures for new symbols
            for symbol in self.symbols:
                if symbol not in self.price_history:
                    self.price_history[symbol] = deque(maxlen=max(self.short_period, self.long_period))
                    self.short_ma[symbol] = deque(maxlen=1)
                    self.long_ma[symbol] = deque(maxlen=1)
                    self.last_signals[symbol] = 'none'
        
        self.logger.info("Configuration updated")
    
    def get_status(self) -> Dict[str, Any]:
        """Get current status of the signal processor"""
        return {
            'active': self._active,
            'symbols': self.symbols,
            'parameters': {
                'short_period': self.short_period,
                'long_period': self.long_period
            },
            'last_signals': self.last_signals.copy(),
            'data_points': {
                symbol: len(self.price_history[symbol]) 
                for symbol in self.symbols
            }
        } 