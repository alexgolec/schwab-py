"""
Multi-Channel Notification System Extension

This extension demonstrates a notification system that sends alerts via email, SMS, and webhook.
It extends the trading system's notification capabilities.

Author: Agent 10 - Extensibility Architect
"""

import logging
import json
import time
from typing import Dict, List, Optional, Any
from datetime import datetime
import smtplib
import requests
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

from enhancements.extension_framework import (
    ExtensionBase, ExtensionAPI, ExtensionType, extension
)


@extension(ExtensionType.NOTIFICATION, name="Multi-Channel Notification System")
class MultiChannelNotificationSystem(ExtensionBase):
    """
    Notification system that sends alerts via multiple channels.
    
    This extension demonstrates:
    - Multi-channel notification delivery
    - Event-driven notification triggers
    - Template-based message formatting
    - Notification history tracking
    - Rate limiting and throttling
    """
    
    def __init__(self, api: ExtensionAPI):
        super().__init__(api)
        self.logger = logging.getLogger(__name__)
        
        # Configuration
        self.email_enabled = self.api.get_config('email_enabled', True)
        self.sms_enabled = self.api.get_config('sms_enabled', False)
        self.webhook_enabled = self.api.get_config('webhook_enabled', True)
        
        # Email configuration
        self.smtp_server = self.api.get_config('smtp_server', 'smtp.gmail.com')
        self.smtp_port = self.api.get_config('smtp_port', 587)
        self.email_username = self.api.get_config('email_username', '')
        self.email_password = self.api.get_config('email_password', '')
        self.recipient_emails = self.api.get_config('recipient_emails', [])
        
        # SMS configuration
        self.sms_api_key = self.api.get_config('sms_api_key', '')
        self.sms_api_secret = self.api.get_config('sms_api_secret', '')
        self.recipient_phones = self.api.get_config('recipient_phones', [])
        
        # Webhook configuration
        self.webhook_url = self.api.get_config('webhook_url', '')
        self.webhook_headers = self.api.get_config('webhook_headers', {})
        
        # Notification settings
        self.notification_types = self.api.get_config('notification_types', [
            'trading_signal', 'order_executed', 'risk_alert', 'system_error'
        ])
        self.rate_limit = self.api.get_config('rate_limit', 60)  # seconds between notifications
        
        # State tracking
        self.notification_history: List[Dict[str, Any]] = []
        self.last_notification_time = 0
        self.event_handlers = {}
        self._active = False
    
    def initialize(self) -> None:
        """Initialize the notification system"""
        self.logger.info("Initializing Multi-Channel Notification System")
        
        # Subscribe to notification events
        for event_type in self.notification_types:
            handler = self._create_event_handler(event_type)
            self.event_handlers[event_type] = handler
            self.api.context.event_bus.subscribe(event_type, handler)
        
        # Subscribe to system events
        self.api.context.event_bus.subscribe('system_error', self._handle_system_error)
        self.api.context.event_bus.subscribe('risk_alert', self._handle_risk_alert)
        
        self.logger.info(f"Notification system initialized for events: {self.notification_types}")
    
    def activate(self) -> None:
        """Activate the notification system"""
        self.logger.info("Activating Multi-Channel Notification System")
        self._active = True
        
        # Publish activation event
        self.api.publish_event('notification_system_activated', {
            'system_type': 'multi_channel',
            'channels': {
                'email': self.email_enabled,
                'sms': self.sms_enabled,
                'webhook': self.webhook_enabled
            }
        })
    
    def deactivate(self) -> None:
        """Deactivate the notification system"""
        self.logger.info("Deactivating Multi-Channel Notification System")
        self._active = False
        
        # Publish deactivation event
        self.api.publish_event('notification_system_deactivated', {
            'system_type': 'multi_channel'
        })
    
    def cleanup(self) -> None:
        """Clean up resources"""
        self.logger.info("Cleaning up Multi-Channel Notification System")
        
        # Unsubscribe from events
        for event_type, handler in self.event_handlers.items():
            self.api.context.event_bus.unsubscribe(event_type, handler)
        
        self.api.context.event_bus.unsubscribe('system_error', self._handle_system_error)
        self.api.context.event_bus.unsubscribe('risk_alert', self._handle_risk_alert)
        
        # Clear state
        self.notification_history.clear()
        self.event_handlers.clear()
    
    def _create_event_handler(self, event_type: str):
        """Create an event handler for a specific event type"""
        def handler(event_type: str, data: Dict[str, Any]):
            if not self._active:
                return
            
            try:
                # Check rate limiting
                if not self._check_rate_limit():
                    return
                
                # Format message based on event type
                message = self._format_message(event_type, data)
                
                # Send notifications
                self._send_notifications(event_type, message, data)
                
                # Log notification
                self._log_notification(event_type, message, data)
                
            except Exception as e:
                self.logger.error(f"Error handling {event_type} event: {e}")
        
        return handler
    
    def _handle_system_error(self, event_type: str, data: Dict[str, Any]) -> None:
        """Handle system error events"""
        if not self._active:
            return
        
        try:
            error_message = f"SYSTEM ERROR: {data.get('error', 'Unknown error')}"
            self._send_notifications('system_error', error_message, data)
        except Exception as e:
            self.logger.error(f"Error handling system error: {e}")
    
    def _handle_risk_alert(self, event_type: str, data: Dict[str, Any]) -> None:
        """Handle risk alert events"""
        if not self._active:
            return
        
        try:
            alert_message = f"RISK ALERT: {data.get('message', 'Risk threshold exceeded')}"
            self._send_notifications('risk_alert', alert_message, data)
        except Exception as e:
            self.logger.error(f"Error handling risk alert: {e}")
    
    def _format_message(self, event_type: str, data: Dict[str, Any]) -> str:
        """Format notification message based on event type"""
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        
        if event_type == 'trading_signal':
            symbol = data.get('symbol', 'Unknown')
            signal = data.get('signal', 'Unknown')
            price = data.get('price', 0)
            return f"[{timestamp}] TRADING SIGNAL: {signal.upper()} {symbol} @ ${price:.2f}"
        
        elif event_type == 'order_executed':
            symbol = data.get('symbol', 'Unknown')
            side = data.get('side', 'Unknown')
            quantity = data.get('quantity', 0)
            price = data.get('price', 0)
            return f"[{timestamp}] ORDER EXECUTED: {side.upper()} {quantity} {symbol} @ ${price:.2f}"
        
        elif event_type == 'risk_alert':
            message = data.get('message', 'Risk threshold exceeded')
            return f"[{timestamp}] RISK ALERT: {message}"
        
        elif event_type == 'system_error':
            error = data.get('error', 'Unknown error')
            return f"[{timestamp}] SYSTEM ERROR: {error}"
        
        else:
            return f"[{timestamp}] {event_type.upper()}: {json.dumps(data, indent=2)}"
    
    def _send_notifications(self, event_type: str, message: str, data: Dict[str, Any]) -> None:
        """Send notifications through all enabled channels"""
        notification_data = {
            'event_type': event_type,
            'message': message,
            'data': data,
            'timestamp': time.time()
        }
        
        # Send email notification
        if self.email_enabled:
            self._send_email_notification(notification_data)
        
        # Send SMS notification
        if self.sms_enabled:
            self._send_sms_notification(notification_data)
        
        # Send webhook notification
        if self.webhook_enabled:
            self._send_webhook_notification(notification_data)
    
    def _send_email_notification(self, notification_data: Dict[str, Any]) -> None:
        """Send email notification"""
        try:
            if not self.email_username or not self.email_password or not self.recipient_emails:
                self.logger.warning("Email configuration incomplete")
                return
            
            # Create email message
            msg = MIMEMultipart()
            msg['From'] = self.email_username
            msg['To'] = ', '.join(self.recipient_emails)
            msg['Subject'] = f"Trading Alert: {notification_data['event_type']}"
            
            body = f"""
            Trading System Alert
            
            {notification_data['message']}
            
            Event Type: {notification_data['event_type']}
            Timestamp: {datetime.fromtimestamp(notification_data['timestamp'])}
            
            Additional Data:
            {json.dumps(notification_data['data'], indent=2)}
            """
            
            msg.attach(MIMEText(body, 'plain'))
            
            # Send email
            with smtplib.SMTP(self.smtp_server, self.smtp_port) as server:
                server.starttls()
                server.login(self.email_username, self.email_password)
                server.send_message(msg)
            
            self.logger.info(f"Email notification sent to {len(self.recipient_emails)} recipients")
            
        except Exception as e:
            self.logger.error(f"Error sending email notification: {e}")
    
    def _send_sms_notification(self, notification_data: Dict[str, Any]) -> None:
        """Send SMS notification"""
        try:
            if not self.sms_api_key or not self.sms_api_secret or not self.recipient_phones:
                self.logger.warning("SMS configuration incomplete")
                return
            
            # This is a mock implementation - in real usage, you'd use a service like Twilio
            message = notification_data['message']
            
            for phone in self.recipient_phones:
                # Mock SMS sending
                self.logger.info(f"SMS notification sent to {phone}: {message[:50]}...")
            
        except Exception as e:
            self.logger.error(f"Error sending SMS notification: {e}")
    
    def _send_webhook_notification(self, notification_data: Dict[str, Any]) -> None:
        """Send webhook notification"""
        try:
            if not self.webhook_url:
                self.logger.warning("Webhook URL not configured")
                return
            
            # Prepare webhook payload
            payload = {
                'event_type': notification_data['event_type'],
                'message': notification_data['message'],
                'timestamp': notification_data['timestamp'],
                'data': notification_data['data']
            }
            
            # Send webhook
            response = requests.post(
                self.webhook_url,
                json=payload,
                headers=self.webhook_headers,
                timeout=10
            )
            
            if response.status_code == 200:
                self.logger.info("Webhook notification sent successfully")
            else:
                self.logger.warning(f"Webhook notification failed: {response.status_code}")
            
        except Exception as e:
            self.logger.error(f"Error sending webhook notification: {e}")
    
    def _check_rate_limit(self) -> bool:
        """Check if we're within rate limits"""
        current_time = time.time()
        if current_time - self.last_notification_time < self.rate_limit:
            return False
        
        self.last_notification_time = current_time
        return True
    
    def _log_notification(self, event_type: str, message: str, data: Dict[str, Any]) -> None:
        """Log notification for history tracking"""
        notification_record = {
            'event_type': event_type,
            'message': message,
            'data': data,
            'timestamp': time.time(),
            'channels_sent': {
                'email': self.email_enabled,
                'sms': self.sms_enabled,
                'webhook': self.webhook_enabled
            }
        }
        
        self.notification_history.append(notification_record)
        
        # Keep only last 100 notifications
        if len(self.notification_history) > 100:
            self.notification_history = self.notification_history[-100:]
    
    def send_custom_notification(self, message: str, channels: List[str] = None) -> bool:
        """Send a custom notification"""
        if not self._active:
            return False
        
        try:
            if channels is None:
                channels = ['email', 'sms', 'webhook']
            
            notification_data = {
                'event_type': 'custom',
                'message': message,
                'data': {},
                'timestamp': time.time()
            }
            
            if 'email' in channels and self.email_enabled:
                self._send_email_notification(notification_data)
            
            if 'sms' in channels and self.sms_enabled:
                self._send_sms_notification(notification_data)
            
            if 'webhook' in channels and self.webhook_enabled:
                self._send_webhook_notification(notification_data)
            
            self._log_notification('custom', message, {})
            return True
            
        except Exception as e:
            self.logger.error(f"Error sending custom notification: {e}")
            return False
    
    def update_config(self, config: Dict[str, Any]) -> None:
        """Update notification configuration"""
        if 'email_enabled' in config:
            self.email_enabled = config['email_enabled']
            self.api.set_config('email_enabled', self.email_enabled)
        
        if 'sms_enabled' in config:
            self.sms_enabled = config['sms_enabled']
            self.api.set_config('sms_enabled', self.sms_enabled)
        
        if 'webhook_enabled' in config:
            self.webhook_enabled = config['webhook_enabled']
            self.api.set_config('webhook_enabled', self.webhook_enabled)
        
        if 'notification_types' in config:
            self.notification_types = config['notification_types']
            self.api.set_config('notification_types', self.notification_types)
        
        if 'rate_limit' in config:
            self.rate_limit = config['rate_limit']
            self.api.set_config('rate_limit', self.rate_limit)
        
        self.logger.info("Notification configuration updated")
    
    def get_status(self) -> Dict[str, Any]:
        """Get current status of the notification system"""
        return {
            'active': self._active,
            'channels': {
                'email': self.email_enabled,
                'sms': self.sms_enabled,
                'webhook': self.webhook_enabled
            },
            'notification_types': self.notification_types,
            'rate_limit': self.rate_limit,
            'history_count': len(self.notification_history),
            'last_notification': self.last_notification_time
        }
    
    def get_notification_history(self, limit: int = 10) -> List[Dict[str, Any]]:
        """Get recent notification history"""
        return self.notification_history[-limit:] 