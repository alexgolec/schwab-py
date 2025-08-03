"""
Agent 8: SMA Crossover Signal Processing System

This module implements a high-performance SMA crossover signal processing system
for real-time trading signal generation and order execution.

Key Components:
- SignalProcessor: Core SMA crossover logic with configurable parameters
- StreamingDataIntegration: Integration with Agent 5's bounded deque
- SignalBacktesting: Historical data validation framework
- RiskManagement: Position sizing and risk controls
- PerformanceMetrics: Signal accuracy and performance reporting

Performance Requirements:
- Signal calculation <100ms
- Support 500+ symbols simultaneously
- Handle 1000+ price updates per second
- Maintain signal state across restarts

Interface Contracts:
- Consumes data from Agent 5's streaming buffer
- Uses Agent 3's reliable order placement
- Respects Agent 7's per-user signal isolation
- Emits signals for Agent 9's monitoring
"""

import asyncio
import collections
import datetime
import json
import logging
import math
import os
import pickle
import statistics
import threading
import time
from abc import ABC, abstractmethod
from collections import defaultdict, deque
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple, Union
from weakref import WeakValueDictionary

import numpy as np
import pandas as pd
from schwab.client import Client
from schwab.streaming import StreamClient


# Configure logging
logger = logging.getLogger(__name__)


class SignalType(Enum):
    """Signal types for SMA crossover strategy."""
    BUY = "buy"
    SELL = "sell"
    HOLD = "hold"


class SignalStrength(Enum):
    """Signal strength levels."""
    WEAK = "weak"
    MODERATE = "moderate"
    STRONG = "strong"


@dataclass
class SignalConfig:
    """Configuration for SMA crossover signal processing."""
    # SMA periods
    short_sma_period: int = 10
    long_sma_period: int = 50
    
    # Signal thresholds
    crossover_threshold: float = 0.001  # Minimum price change for signal
    volume_threshold: float = 1.5  # Minimum volume increase for confirmation
    
    # Risk management
    max_position_size: float = 0.1  # Max 10% of portfolio per position
    stop_loss_pct: float = 0.05  # 5% stop loss
    take_profit_pct: float = 0.15  # 15% take profit
    
    # Performance settings
    min_signal_interval: float = 60.0  # Minimum seconds between signals
    max_symbols: int = 500
    max_updates_per_second: int = 1000
    
    # Backtesting
    backtest_lookback_days: int = 365
    min_backtest_accuracy: float = 0.6
    
    # Persistence
    state_file: str = "signal_processor_state.pkl"
    metrics_file: str = "signal_metrics.json"


@dataclass
class SignalMetrics:
    """Performance metrics for signal processing."""
    total_signals: int = 0
    successful_signals: int = 0
    failed_signals: int = 0
    total_pnl: float = 0.0
    max_drawdown: float = 0.0
    sharpe_ratio: float = 0.0
    win_rate: float = 0.0
    avg_win: float = 0.0
    avg_loss: float = 0.0
    signal_accuracy: float = 0.0
    
    # Timing metrics
    avg_signal_time_ms: float = 0.0
    max_signal_time_ms: float = 0.0
    total_processing_time_ms: float = 0.0
    
    # Volume metrics
    total_volume_processed: int = 0
    avg_updates_per_second: float = 0.0
    peak_updates_per_second: float = 0.0


@dataclass
class SignalState:
    """State for a single symbol's signal processing."""
    symbol: str
    short_sma: deque = field(default_factory=lambda: deque(maxlen=50))
    long_sma: deque = field(default_factory=lambda: deque(maxlen=100))
    last_signal: Optional[SignalType] = None
    last_signal_time: Optional[datetime.datetime] = None
    last_price: Optional[float] = None
    position_size: float = 0.0
    entry_price: Optional[float] = None
    stop_loss_price: Optional[float] = None
    take_profit_price: Optional[float] = None
    
    # Performance tracking
    signals_generated: int = 0
    signals_successful: int = 0
    total_pnl: float = 0.0
    
    def update_sma(self, price: float, short_period: int, long_period: int):
        """Update SMA values with new price."""
        self.short_sma.append(price)
        self.long_sma.append(price)
        
        if len(self.short_sma) >= short_period:
            short_avg = sum(list(self.short_sma)[-short_period:]) / short_period
        else:
            short_avg = None
            
        if len(self.long_sma) >= long_period:
            long_avg = sum(list(self.long_sma)[-long_period:]) / long_period
        else:
            long_avg = None
            
        return short_avg, long_avg


class StreamingDataBuffer:
    """Bounded buffer for streaming data integration with Agent 5."""
    
    def __init__(self, max_size: int = 10000, drop_threshold: float = 0.8):
        self.max_size = max_size
        self.drop_threshold = drop_threshold
        self.buffer = deque(maxlen=max_size)
        self.lock = threading.Lock()
        self.metrics = {
            'total_messages': 0,
            'dropped_messages': 0,
            'current_size': 0,
            'fill_rate': 0.0
        }
        self._drop_callbacks = []
        self._alert_callbacks = []
    
    def append(self, message: Dict[str, Any]) -> bool:
        """Append message to buffer, return True if dropped."""
        with self.lock:
            was_full = len(self.buffer) >= self.max_size
            self.buffer.append(message)
            self.metrics['total_messages'] += 1
            self.metrics['current_size'] = len(self.buffer)
            self.metrics['fill_rate'] = len(self.buffer) / self.max_size
            
            if was_full:
                self.metrics['dropped_messages'] += 1
                self._trigger_drop_callbacks(message)
                return True
            return False
    
    def get_latest(self, count: int = 1) -> List[Dict[str, Any]]:
        """Get latest messages from buffer."""
        with self.lock:
            return list(self.buffer)[-count:]
    
    def get_all(self) -> List[Dict[str, Any]]:
        """Get all messages from buffer."""
        with self.lock:
            return list(self.buffer)
    
    def clear(self):
        """Clear the buffer."""
        with self.lock:
            self.buffer.clear()
            self.metrics['current_size'] = 0
            self.metrics['fill_rate'] = 0.0
    
    def add_drop_callback(self, callback):
        """Add callback for when messages are dropped."""
        self._drop_callbacks.append(callback)
    
    def add_alert_callback(self, callback):
        """Add callback for buffer alerts."""
        self._alert_callbacks.append(callback)
    
    def _trigger_drop_callbacks(self, message: Dict[str, Any]):
        """Trigger drop callbacks."""
        for callback in self._drop_callbacks:
            try:
                callback(message)
            except Exception as e:
                logger.error(f"Error in drop callback: {e}")


class SignalProcessor:
    """Core SMA crossover signal processing system."""
    
    def __init__(self, 
                 config: SignalConfig,
                 client: Optional[Client] = None,
                 stream_client: Optional[StreamClient] = None):
        self.config = config
        self.client = client
        self.stream_client = stream_client
        
        # Signal states per symbol
        self.signal_states: Dict[str, SignalState] = {}
        
        # Streaming data buffers per symbol
        self.data_buffers: Dict[str, StreamingDataBuffer] = {}
        
        # Performance metrics
        self.metrics = SignalMetrics()
        
        # Thread safety
        self.lock = threading.RLock()
        
        # Background processing
        self._processing_task: Optional[asyncio.Task] = None
        self._stop_processing = threading.Event()
        
        # Signal callbacks for Agent 9 monitoring
        self._signal_callbacks: List[callable] = []
        
        # Load existing state
        self._load_state()
        
        logger.info(f"SignalProcessor initialized with config: {config}")
    
    def add_signal_callback(self, callback: callable):
        """Add callback for signal events (Agent 9 integration)."""
        self._signal_callbacks.append(callback)
    
    def _trigger_signal_callbacks(self, signal_data: Dict[str, Any]):
        """Trigger signal callbacks for monitoring."""
        for callback in self._signal_callbacks:
            try:
                callback(signal_data)
            except Exception as e:
                logger.error(f"Error in signal callback: {e}")
    
    def add_symbol(self, symbol: str) -> bool:
        """Add a symbol for signal processing."""
        with self.lock:
            if len(self.signal_states) >= self.config.max_symbols:
                logger.warning(f"Max symbols reached ({self.config.max_symbols})")
                return False
            
            if symbol in self.signal_states:
                logger.warning(f"Symbol {symbol} already being processed")
                return False
            
            self.signal_states[symbol] = SignalState(symbol=symbol)
            self.data_buffers[symbol] = StreamingDataBuffer(
                max_size=1000,
                drop_threshold=0.8
            )
            
            logger.info(f"Added symbol {symbol} for signal processing")
            return True
    
    def remove_symbol(self, symbol: str) -> bool:
        """Remove a symbol from signal processing."""
        with self.lock:
            if symbol not in self.signal_states:
                return False
            
            del self.signal_states[symbol]
            del self.data_buffers[symbol]
            
            logger.info(f"Removed symbol {symbol} from signal processing")
            return True
    
    def process_price_update(self, symbol: str, price_data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Process a price update and generate signal if applicable."""
        start_time = time.time()
        
        with self.lock:
            if symbol not in self.signal_states:
                return None
            
            # Add to buffer
            self.data_buffers[symbol].append(price_data)
            
            # Extract price
            price = price_data.get('last_price') or price_data.get('close_price')
            if not price:
                return None
            
            # Update signal state
            state = self.signal_states[symbol]
            state.last_price = price
            
            # Check signal interval
            now = datetime.datetime.now()
            if (state.last_signal_time and 
                (now - state.last_signal_time).total_seconds() < self.config.min_signal_interval):
                return None
            
            # Calculate SMAs
            short_avg, long_avg = state.update_sma(
                price, 
                self.config.short_sma_period, 
                self.config.long_sma_period
            )
            
            if short_avg is None or long_avg is None:
                return None
            
            # Generate signal
            signal = self._generate_sma_crossover_signal(
                symbol, price, short_avg, long_avg, state
            )
            
            if signal:
                # Update metrics
                processing_time = (time.time() - start_time) * 1000
                self.metrics.total_signals += 1
                self.metrics.avg_signal_time_ms = (
                    (self.metrics.avg_signal_time_ms * (self.metrics.total_signals - 1) + processing_time) /
                    self.metrics.total_signals
                )
                self.metrics.max_signal_time_ms = max(
                    self.metrics.max_signal_time_ms, processing_time
                )
                
                # Trigger callbacks
                self._trigger_signal_callbacks(signal)
                
                return signal
        
        return None
    
    def _generate_sma_crossover_signal(self, 
                                     symbol: str, 
                                     price: float, 
                                     short_avg: float, 
                                     long_avg: float, 
                                     state: SignalState) -> Optional[Dict[str, Any]]:
        """Generate SMA crossover signal."""
        # Calculate crossover
        crossover = short_avg - long_avg
        crossover_pct = crossover / long_avg if long_avg > 0 else 0
        
        # Determine signal type
        signal_type = SignalType.HOLD
        signal_strength = SignalStrength.WEAK
        
        if crossover_pct > self.config.crossover_threshold:
            if state.last_signal != SignalType.BUY:
                signal_type = SignalType.BUY
                signal_strength = self._calculate_signal_strength(crossover_pct)
        elif crossover_pct < -self.config.crossover_threshold:
            if state.last_signal != SignalType.SELL:
                signal_type = SignalType.SELL
                signal_strength = self._calculate_signal_strength(abs(crossover_pct))
        
        if signal_type == SignalType.HOLD:
            return None
        
        # Calculate position size
        position_size = self._calculate_position_size(symbol, price, signal_strength)
        
        # Update state
        state.last_signal = signal_type
        state.last_signal_time = datetime.datetime.now()
        state.signals_generated += 1
        
        # Create signal data
        signal_data = {
            'symbol': symbol,
            'signal_type': signal_type.value,
            'signal_strength': signal_strength.value,
            'price': price,
            'short_sma': short_avg,
            'long_sma': long_avg,
            'crossover_pct': crossover_pct,
            'position_size': position_size,
            'timestamp': datetime.datetime.now().isoformat(),
            'state': {
                'entry_price': state.entry_price,
                'stop_loss_price': state.stop_loss_price,
                'take_profit_price': state.take_profit_price,
                'total_pnl': state.total_pnl
            }
        }
        
        logger.info(f"Generated {signal_type.value} signal for {symbol} at {price}")
        return signal_data
    
    def _calculate_signal_strength(self, crossover_pct: float) -> SignalStrength:
        """Calculate signal strength based on crossover percentage."""
        if crossover_pct > 0.05:
            return SignalStrength.STRONG
        elif crossover_pct > 0.02:
            return SignalStrength.MODERATE
        else:
            return SignalStrength.WEAK
    
    def _calculate_position_size(self, symbol: str, price: float, strength: SignalStrength) -> float:
        """Calculate position size based on signal strength and risk management."""
        base_size = self.config.max_position_size
        
        # Adjust based on signal strength
        if strength == SignalStrength.STRONG:
            size_multiplier = 1.0
        elif strength == SignalStrength.MODERATE:
            size_multiplier = 0.7
        else:
            size_multiplier = 0.4
        
        return base_size * size_multiplier
    
    def get_signal_state(self, symbol: str) -> Optional[SignalState]:
        """Get signal state for a symbol."""
        with self.lock:
            return self.signal_states.get(symbol)
    
    def get_metrics(self) -> SignalMetrics:
        """Get current performance metrics."""
        with self.lock:
            return self.metrics
    
    def _load_state(self):
        """Load signal processor state from disk."""
        try:
            state_file = Path(self.config.state_file)
            if state_file.exists():
                with open(state_file, 'rb') as f:
                    data = pickle.load(f)
                    self.signal_states = data.get('signal_states', {})
                    self.metrics = data.get('metrics', SignalMetrics())
                logger.info(f"Loaded state from {state_file}")
        except Exception as e:
            logger.error(f"Error loading state: {e}")
    
    def _save_state(self):
        """Save signal processor state to disk."""
        try:
            state_file = Path(self.config.state_file)
            with open(state_file, 'wb') as f:
                data = {
                    'signal_states': self.signal_states,
                    'metrics': self.metrics
                }
                pickle.dump(data, f)
            logger.info(f"Saved state to {state_file}")
        except Exception as e:
            logger.error(f"Error saving state: {e}")


class SignalBacktester:
    """Backtesting framework for signal validation."""
    
    def __init__(self, config: SignalConfig):
        self.config = config
        self.results = {
            'total_trades': 0,
            'winning_trades': 0,
            'losing_trades': 0,
            'total_pnl': 0.0,
            'max_drawdown': 0.0,
            'sharpe_ratio': 0.0,
            'win_rate': 0.0,
            'avg_win': 0.0,
            'avg_loss': 0.0,
            'signal_accuracy': 0.0
        }
    
    def backtest_symbol(self, symbol: str, historical_data: pd.DataFrame) -> Dict[str, Any]:
        """Backtest a symbol with historical data."""
        if len(historical_data) < self.config.long_sma_period:
            return {'error': 'Insufficient historical data'}
        
        # Calculate SMAs
        historical_data['short_sma'] = historical_data['close'].rolling(
            window=self.config.short_sma_period
        ).mean()
        historical_data['long_sma'] = historical_data['close'].rolling(
            window=self.config.long_sma_period
        ).mean()
        
        # Generate signals
        signals = []
        position = 0
        entry_price = 0
        trades = []
        
        for i in range(len(historical_data)):
            row = historical_data.iloc[i]
            
            if pd.isna(row['short_sma']) or pd.isna(row['long_sma']):
                continue
            
            crossover = row['short_sma'] - row['long_sma']
            crossover_pct = crossover / row['long_sma']
            
            # Generate signal
            signal = None
            if crossover_pct > self.config.crossover_threshold and position <= 0:
                signal = SignalType.BUY
            elif crossover_pct < -self.config.crossover_threshold and position >= 0:
                signal = SignalType.SELL
            
            if signal:
                signals.append({
                    'timestamp': row.name,
                    'signal': signal.value,
                    'price': row['close'],
                    'crossover_pct': crossover_pct
                })
                
                # Execute trade
                if signal == SignalType.BUY and position == 0:
                    position = 1
                    entry_price = row['close']
                elif signal == SignalType.SELL and position == 1:
                    position = 0
                    exit_price = row['close']
                    pnl = (exit_price - entry_price) / entry_price
                    trades.append({
                        'entry_time': entry_price,
                        'exit_time': row.name,
                        'entry_price': entry_price,
                        'exit_price': exit_price,
                        'pnl': pnl
                    })
        
        # Calculate results
        return self._calculate_backtest_results(trades)
    
    def _calculate_backtest_results(self, trades: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Calculate backtest results from trades."""
        if not trades:
            return {'error': 'No trades generated'}
        
        total_trades = len(trades)
        winning_trades = len([t for t in trades if t['pnl'] > 0])
        losing_trades = total_trades - winning_trades
        
        total_pnl = sum(t['pnl'] for t in trades)
        avg_win = statistics.mean([t['pnl'] for t in trades if t['pnl'] > 0]) if winning_trades > 0 else 0
        avg_loss = statistics.mean([t['pnl'] for t in trades if t['pnl'] < 0]) if losing_trades > 0 else 0
        
        win_rate = winning_trades / total_trades if total_trades > 0 else 0
        
        # Calculate Sharpe ratio (simplified)
        returns = [t['pnl'] for t in trades]
        sharpe_ratio = statistics.mean(returns) / statistics.stdev(returns) if len(returns) > 1 else 0
        
        # Calculate max drawdown
        cumulative_returns = []
        cumulative = 0
        for trade in trades:
            cumulative += trade['pnl']
            cumulative_returns.append(cumulative)
        
        max_drawdown = 0
        peak = 0
        for ret in cumulative_returns:
            if ret > peak:
                peak = ret
            drawdown = (peak - ret) / peak if peak > 0 else 0
            max_drawdown = max(max_drawdown, drawdown)
        
        return {
            'total_trades': total_trades,
            'winning_trades': winning_trades,
            'losing_trades': losing_trades,
            'total_pnl': total_pnl,
            'max_drawdown': max_drawdown,
            'sharpe_ratio': sharpe_ratio,
            'win_rate': win_rate,
            'avg_win': avg_win,
            'avg_loss': avg_loss,
            'signal_accuracy': win_rate
        }


class RiskManager:
    """Risk management and position sizing."""
    
    def __init__(self, config: SignalConfig):
        self.config = config
        self.positions: Dict[str, Dict[str, Any]] = {}
    
    def calculate_position_size(self, 
                              symbol: str, 
                              price: float, 
                              account_value: float,
                              signal_strength: SignalStrength) -> float:
        """Calculate position size based on risk management rules."""
        # Base position size
        base_size = self.config.max_position_size
        
        # Adjust for signal strength
        if signal_strength == SignalStrength.STRONG:
            size_multiplier = 1.0
        elif signal_strength == SignalStrength.MODERATE:
            size_multiplier = 0.7
        else:
            size_multiplier = 0.4
        
        # Calculate position value
        position_value = account_value * base_size * size_multiplier
        
        # Calculate shares
        shares = position_value / price if price > 0 else 0
        
        return shares
    
    def calculate_stop_loss(self, entry_price: float, signal_type: SignalType) -> float:
        """Calculate stop loss price."""
        if signal_type == SignalType.BUY:
            return entry_price * (1 - self.config.stop_loss_pct)
        else:
            return entry_price * (1 + self.config.stop_loss_pct)
    
    def calculate_take_profit(self, entry_price: float, signal_type: SignalType) -> float:
        """Calculate take profit price."""
        if signal_type == SignalType.BUY:
            return entry_price * (1 + self.config.take_profit_pct)
        else:
            return entry_price * (1 - self.config.take_profit_pct)
    
    def check_risk_limits(self, symbol: str, position_size: float, account_value: float) -> bool:
        """Check if position meets risk limits."""
        # Check maximum position size
        if position_size > account_value * self.config.max_position_size:
            return False
        
        # Check total exposure
        total_exposure = sum(pos.get('size', 0) for pos in self.positions.values())
        if total_exposure > account_value * 0.5:  # Max 50% total exposure
            return False
        
        return True


class PerformanceReporter:
    """Performance metrics and reporting."""
    
    def __init__(self):
        self.metrics_history: List[Dict[str, Any]] = []
    
    def update_metrics(self, metrics: SignalMetrics):
        """Update performance metrics."""
        self.metrics_history.append({
            'timestamp': datetime.datetime.now().isoformat(),
            'total_signals': metrics.total_signals,
            'successful_signals': metrics.successful_signals,
            'failed_signals': metrics.failed_signals,
            'total_pnl': metrics.total_pnl,
            'win_rate': metrics.win_rate,
            'signal_accuracy': metrics.signal_accuracy,
            'avg_signal_time_ms': metrics.avg_signal_time_ms,
            'avg_updates_per_second': metrics.avg_updates_per_second
        })
    
    def generate_report(self) -> Dict[str, Any]:
        """Generate performance report."""
        if not self.metrics_history:
            return {'error': 'No metrics available'}
        
        latest = self.metrics_history[-1]
        
        # Calculate trends
        if len(self.metrics_history) > 1:
            prev = self.metrics_history[-2]
            signal_growth = latest['total_signals'] - prev['total_signals']
            pnl_growth = latest['total_pnl'] - prev['total_pnl']
        else:
            signal_growth = 0
            pnl_growth = 0
        
        return {
            'current_metrics': latest,
            'trends': {
                'signal_growth': signal_growth,
                'pnl_growth': pnl_growth
            },
            'summary': {
                'total_signals': latest['total_signals'],
                'win_rate': latest['win_rate'],
                'total_pnl': latest['total_pnl'],
                'avg_signal_time_ms': latest['avg_signal_time_ms']
            }
        }
    
    def save_report(self, filename: str):
        """Save performance report to file."""
        report = self.generate_report()
        with open(filename, 'w') as f:
            json.dump(report, f, indent=2)


# Factory function for easy integration
def create_signal_processor(config: SignalConfig = None,
                          client: Optional[Client] = None,
                          stream_client: Optional[StreamClient] = None) -> SignalProcessor:
    """Create a configured signal processor."""
    if config is None:
        config = SignalConfig()
    
    return SignalProcessor(config, client, stream_client) 