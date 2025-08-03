"""
Position Size Risk Manager Extension

This extension demonstrates a risk management module that enforces position size limits
and stop-loss rules. It extends the trading system's risk management capabilities.

Author: Agent 10 - Extensibility Architect
"""

import logging
from typing import Dict, List, Optional, Any
from decimal import Decimal
import time

from enhancements.extension_framework import (
    ExtensionBase, ExtensionAPI, ExtensionType, extension
)


@extension(ExtensionType.RISK_MANAGEMENT, name="Position Size Risk Manager")
class PositionSizeRiskManager(ExtensionBase):
    """
    Risk management extension that enforces position size limits and stop-loss rules.
    
    This extension demonstrates:
    - Position size calculation based on account value
    - Stop-loss enforcement
    - Risk per trade limits
    - Order validation and modification
    - Account monitoring
    """
    
    def __init__(self, api: ExtensionAPI):
        super().__init__(api)
        self.logger = logging.getLogger(__name__)
        
        # Configuration
        self.max_risk_per_trade = self.api.get_config('max_risk_per_trade', 0.02)  # 2% of account
        self.max_position_size = self.api.get_config('max_position_size', 0.10)  # 10% of account
        self.stop_loss_percentage = self.api.get_config('stop_loss_percentage', 0.05)  # 5%
        self.max_daily_loss = self.api.get_config('max_daily_loss', 0.05)  # 5% daily loss limit
        
        # State tracking
        self.positions: Dict[str, Dict[str, Any]] = {}
        self.daily_pnl = 0.0
        self.account_value = 0.0
        self.last_account_update = 0
        
        # Event handlers
        self._order_handler = None
        self._account_handler = None
        self._position_handler = None
        self._active = False
    
    def initialize(self) -> None:
        """Initialize the risk manager"""
        self.logger.info("Initializing Position Size Risk Manager")
        
        # Subscribe to relevant events
        self._order_handler = self._handle_order_request
        self._account_handler = self._handle_account_update
        self._position_handler = self._handle_position_update
        
        self.api.context.event_bus.subscribe('order_request', self._order_handler)
        self.api.context.event_bus.subscribe('account_update', self._account_handler)
        self.api.context.event_bus.subscribe('position_update', self._position_handler)
        
        # Load initial account data
        self._update_account_data()
        
        self.logger.info("Risk manager initialized")
    
    def activate(self) -> None:
        """Activate the risk manager"""
        self.logger.info("Activating Position Size Risk Manager")
        self._active = True
        
        # Publish activation event
        self.api.publish_event('risk_manager_activated', {
            'manager_type': 'position_size',
            'parameters': {
                'max_risk_per_trade': self.max_risk_per_trade,
                'max_position_size': self.max_position_size,
                'stop_loss_percentage': self.stop_loss_percentage,
                'max_daily_loss': self.max_daily_loss
            }
        })
    
    def deactivate(self) -> None:
        """Deactivate the risk manager"""
        self.logger.info("Deactivating Position Size Risk Manager")
        self._active = False
        
        # Publish deactivation event
        self.api.publish_event('risk_manager_deactivated', {
            'manager_type': 'position_size'
        })
    
    def cleanup(self) -> None:
        """Clean up resources"""
        self.logger.info("Cleaning up Position Size Risk Manager")
        
        # Unsubscribe from events
        if self._order_handler:
            self.api.context.event_bus.unsubscribe('order_request', self._order_handler)
        if self._account_handler:
            self.api.context.event_bus.unsubscribe('account_update', self._account_handler)
        if self._position_handler:
            self.api.context.event_bus.unsubscribe('position_update', self._position_handler)
        
        # Clear state
        self.positions.clear()
        self.daily_pnl = 0.0
        self.account_value = 0.0
    
    def _handle_order_request(self, event_type: str, data: Dict[str, Any]) -> None:
        """Handle incoming order requests"""
        if not self._active:
            return
        
        try:
            order = data.get('order', {})
            symbol = order.get('symbol')
            quantity = order.get('quantity', 0)
            price = order.get('price', 0)
            side = order.get('side', 'buy')
            
            if not symbol or not quantity or not price:
                return
            
            # Validate order against risk rules
            validation_result = self._validate_order(symbol, quantity, price, side)
            
            if validation_result['valid']:
                # Order is valid, allow it to proceed
                self.api.publish_event('order_validated', {
                    'order_id': data.get('order_id'),
                    'validation_result': validation_result
                })
            else:
                # Order violates risk rules, reject it
                self.api.publish_event('order_rejected', {
                    'order_id': data.get('order_id'),
                    'reason': validation_result['reason'],
                    'validation_result': validation_result
                })
                
                self.logger.warning(f"Order rejected for {symbol}: {validation_result['reason']}")
        
        except Exception as e:
            self.logger.error(f"Error processing order request: {e}")
    
    def _handle_account_update(self, event_type: str, data: Dict[str, Any]) -> None:
        """Handle account updates"""
        if not self._active:
            return
        
        try:
            self._update_account_data()
            
            # Check daily loss limit
            if self.daily_pnl < -(self.account_value * self.max_daily_loss):
                self.api.publish_event('daily_loss_limit_reached', {
                    'daily_pnl': self.daily_pnl,
                    'account_value': self.account_value,
                    'limit': self.max_daily_loss
                })
                
                self.logger.warning(f"Daily loss limit reached: ${self.daily_pnl:.2f}")
        
        except Exception as e:
            self.logger.error(f"Error processing account update: {e}")
    
    def _handle_position_update(self, event_type: str, data: Dict[str, Any]) -> None:
        """Handle position updates"""
        if not self._active:
            return
        
        try:
            symbol = data.get('symbol')
            quantity = data.get('quantity', 0)
            avg_price = data.get('avg_price', 0)
            current_price = data.get('current_price', 0)
            
            if not symbol:
                return
            
            # Update position tracking
            self.positions[symbol] = {
                'quantity': quantity,
                'avg_price': avg_price,
                'current_price': current_price,
                'last_update': time.time()
            }
            
            # Check stop-loss
            if quantity > 0 and current_price > 0:
                loss_percentage = (avg_price - current_price) / avg_price
                
                if loss_percentage >= self.stop_loss_percentage:
                    self.api.publish_event('stop_loss_triggered', {
                        'symbol': symbol,
                        'quantity': quantity,
                        'avg_price': avg_price,
                        'current_price': current_price,
                        'loss_percentage': loss_percentage
                    })
                    
                    self.logger.warning(f"Stop-loss triggered for {symbol}: {loss_percentage:.2%}")
        
        except Exception as e:
            self.logger.error(f"Error processing position update: {e}")
    
    def _validate_order(self, symbol: str, quantity: int, price: float, side: str) -> Dict[str, Any]:
        """Validate order against risk rules"""
        result = {
            'valid': True,
            'reason': '',
            'suggested_quantity': quantity,
            'suggested_price': price
        }
        
        # Calculate order value
        order_value = abs(quantity * price)
        
        # Check maximum position size
        max_position_value = self.account_value * self.max_position_size
        if order_value > max_position_value:
            result['valid'] = False
            result['reason'] = f"Order value ${order_value:.2f} exceeds maximum position size ${max_position_value:.2f}"
            result['suggested_quantity'] = int(max_position_value / price)
        
        # Check maximum risk per trade
        max_risk_value = self.account_value * self.max_risk_per_trade
        if order_value > max_risk_value:
            result['valid'] = False
            result['reason'] = f"Order value ${order_value:.2f} exceeds maximum risk per trade ${max_risk_value:.2f}"
            result['suggested_quantity'] = int(max_risk_value / price)
        
        # Check daily loss limit
        if self.daily_pnl < -(self.account_value * self.max_daily_loss):
            result['valid'] = False
            result['reason'] = "Daily loss limit reached"
        
        return result
    
    def _update_account_data(self) -> None:
        """Update account data from API client"""
        try:
            # This would typically call the Schwab API to get account information
            # For this sample, we'll use mock data
            client = self.api.get_api_client()
            
            # Mock account data - in real implementation, this would come from API
            self.account_value = 100000.0  # $100k account
            self.last_account_update = time.time()
            
        except Exception as e:
            self.logger.error(f"Error updating account data: {e}")
    
    def calculate_position_size(self, symbol: str, price: float, risk_amount: float = None) -> int:
        """Calculate recommended position size based on risk parameters"""
        if risk_amount is None:
            risk_amount = self.account_value * self.max_risk_per_trade
        
        # Calculate position size based on risk amount
        position_size = int(risk_amount / price)
        
        # Ensure it doesn't exceed maximum position size
        max_position_value = self.account_value * self.max_position_size
        max_position_size = int(max_position_value / price)
        
        return min(position_size, max_position_size)
    
    def update_config(self, config: Dict[str, Any]) -> None:
        """Update risk management configuration"""
        if 'max_risk_per_trade' in config:
            self.max_risk_per_trade = config['max_risk_per_trade']
            self.api.set_config('max_risk_per_trade', self.max_risk_per_trade)
        
        if 'max_position_size' in config:
            self.max_position_size = config['max_position_size']
            self.api.set_config('max_position_size', self.max_position_size)
        
        if 'stop_loss_percentage' in config:
            self.stop_loss_percentage = config['stop_loss_percentage']
            self.api.set_config('stop_loss_percentage', self.stop_loss_percentage)
        
        if 'max_daily_loss' in config:
            self.max_daily_loss = config['max_daily_loss']
            self.api.set_config('max_daily_loss', self.max_daily_loss)
        
        self.logger.info("Risk management configuration updated")
    
    def get_status(self) -> Dict[str, Any]:
        """Get current status of the risk manager"""
        return {
            'active': self._active,
            'account_value': self.account_value,
            'daily_pnl': self.daily_pnl,
            'positions': len(self.positions),
            'parameters': {
                'max_risk_per_trade': self.max_risk_per_trade,
                'max_position_size': self.max_position_size,
                'stop_loss_percentage': self.stop_loss_percentage,
                'max_daily_loss': self.max_daily_loss
            },
            'limits': {
                'max_risk_per_trade': self.account_value * self.max_risk_per_trade,
                'max_position_size': self.account_value * self.max_position_size,
                'daily_loss_limit': self.account_value * self.max_daily_loss
            }
        } 