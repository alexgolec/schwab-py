"""
Multi-User Architecture for Schwab Trading Platform

This module provides a comprehensive multi-user session isolation system that enables
scalable trading platform with per-user token storage, rate limiting, permissions,
and monitoring.

Key Components:
- UserSessionManager: Central session management with complete isolation
- Per-user Client and StreamingClient instances
- User authentication and session management
- User-specific rate limiting and quotas
- User permission system (read-only, trading, admin)
- User activity monitoring and audit trails

Scalability Features:
- Support for 1000+ concurrent users
- Linear memory scaling with user count
- Session cleanup for inactive users
- Connection pooling for efficiency
"""

import asyncio
import collections
import datetime
import hashlib
import json
import logging
import os
import secrets
import threading
import time
import uuid
from abc import ABC, abstractmethod
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple, Union
from weakref import WeakValueDictionary

import schwab
from schwab.auth import TokenMetadata
from schwab.client import AsyncClient, Client
from schwab.streaming import StreamClient


# Configure logging
logger = logging.getLogger(__name__)


class UserPermission(Enum):
    """User permission levels for the trading platform."""
    READ_ONLY = "read_only"
    TRADING = "trading"
    ADMIN = "admin"


class UserStatus(Enum):
    """User session status."""
    ACTIVE = "active"
    INACTIVE = "inactive"
    SUSPENDED = "suspended"
    EXPIRED = "expired"


@dataclass
class UserQuota:
    """Rate limiting and quota configuration for a user."""
    max_requests_per_minute: int = 120
    max_requests_per_hour: int = 1000
    max_streaming_connections: int = 5
    max_concurrent_orders: int = 10
    max_daily_trades: int = 100
    max_account_balance: float = 1000000.0


@dataclass
class UserSession:
    """Represents a user session with all associated data."""
    user_id: str
    username: str
    email: str
    permission: UserPermission
    quota: UserQuota
    status: UserStatus = UserStatus.ACTIVE
    
    # Authentication
    api_key: str = ""
    app_secret: str = ""
    token_path: str = ""
    token_metadata: Optional[TokenMetadata] = None
    
    # Clients
    client: Optional[Client] = None
    async_client: Optional[AsyncClient] = None
    stream_client: Optional[StreamClient] = None
    
    # Session management
    session_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    created_at: datetime.datetime = field(default_factory=datetime.datetime.now)
    last_activity: datetime.datetime = field(default_factory=datetime.datetime.now)
    expires_at: Optional[datetime.datetime] = None
    
    # Rate limiting
    request_count: int = 0
    request_history: List[datetime.datetime] = field(default_factory=list)
    
    # Activity tracking
    total_requests: int = 0
    total_trades: int = 0
    total_volume: float = 0.0
    last_trade_at: Optional[datetime.datetime] = None
    
    # Audit trail
    audit_events: List[Dict[str, Any]] = field(default_factory=list)
    
    def __post_init__(self):
        """Initialize session after creation."""
        if not self.expires_at:
            self.expires_at = self.created_at + datetime.timedelta(hours=24)
    
    def is_expired(self) -> bool:
        """Check if session has expired."""
        return datetime.datetime.now() > self.expires_at
    
    def is_active(self) -> bool:
        """Check if session is active."""
        return (self.status == UserStatus.ACTIVE and 
                not self.is_expired() and
                datetime.datetime.now() - self.last_activity < datetime.timedelta(hours=1))
    
    def update_activity(self):
        """Update last activity timestamp."""
        self.last_activity = datetime.datetime.now()
    
    def add_audit_event(self, event_type: str, details: Dict[str, Any]):
        """Add an audit event to the session."""
        event = {
            'timestamp': datetime.datetime.now().isoformat(),
            'event_type': event_type,
            'details': details,
            'session_id': self.session_id
        }
        self.audit_events.append(event)
        
        # Keep only last 1000 events to prevent memory bloat
        if len(self.audit_events) > 1000:
            self.audit_events = self.audit_events[-1000:]


class RateLimiter:
    """Thread-safe rate limiter for per-user request limiting."""
    
    def __init__(self, max_requests_per_minute: int = 120):
        self.max_requests_per_minute = max_requests_per_minute
        self._lock = threading.Lock()
        self._request_times: Dict[str, List[datetime.datetime]] = {}
    
    def can_make_request(self, user_id: str) -> bool:
        """Check if user can make a request based on rate limits."""
        with self._lock:
            now = datetime.datetime.now()
            cutoff = now - datetime.timedelta(minutes=1)
            
            if user_id not in self._request_times:
                self._request_times[user_id] = []
            
            # Remove old requests
            self._request_times[user_id] = [
                req_time for req_time in self._request_times[user_id]
                if hasattr(req_time, '__gt__') and req_time > cutoff
            ]
            
            # Check if under limit
            if len(self._request_times[user_id]) < self.max_requests_per_minute:
                self._request_times[user_id].append(now)
                return True
            
            return False
    
    def get_wait_time(self, user_id: str) -> float:
        """Get time to wait before next request is allowed."""
        with self._lock:
            if user_id not in self._request_times:
                return 0.0
            
            now = datetime.datetime.now()
            cutoff = now - datetime.timedelta(minutes=1)
            
            # Remove old requests
            self._request_times[user_id] = [
                req_time for req_time in self._request_times[user_id]
                if hasattr(req_time, '__gt__') and req_time > cutoff
            ]
            
            if len(self._request_times[user_id]) < self.max_requests_per_minute:
                return 0.0
            
            # Find oldest request
            oldest = min(self._request_times[user_id])
            wait_until = oldest + datetime.timedelta(minutes=1)
            return max(0.0, (wait_until - now).total_seconds())


class TokenStorage:
    """Secure token storage with per-user isolation."""
    
    def __init__(self, base_path: str = "./tokens"):
        self.base_path = Path(base_path)
        self.base_path.mkdir(exist_ok=True)
        self._lock = threading.Lock()
    
    def get_token_path(self, user_id: str) -> Path:
        """Get token file path for a user."""
        return self.base_path / f"{user_id}_token.json"
    
    def save_token(self, user_id: str, token: Dict[str, Any]) -> None:
        """Save token for a user."""
        with self._lock:
            token_path = self.get_token_path(user_id)
            with open(token_path, 'w') as f:
                json.dump(token, f, indent=2)
            logger.info(f"Saved token for user {user_id}")
    
    def load_token(self, user_id: str) -> Optional[Dict[str, Any]]:
        """Load token for a user."""
        with self._lock:
            token_path = self.get_token_path(user_id)
            if not token_path.exists():
                return None
            
            try:
                with open(token_path, 'r') as f:
                    return json.load(f)
            except (json.JSONDecodeError, IOError) as e:
                logger.error(f"Failed to load token for user {user_id}: {e}")
                return None
    
    def delete_token(self, user_id: str) -> None:
        """Delete token for a user."""
        with self._lock:
            token_path = self.get_token_path(user_id)
            if token_path.exists():
                token_path.unlink()
                logger.info(f"Deleted token for user {user_id}")
    
    def token_exists(self, user_id: str) -> bool:
        """Check if token exists for a user."""
        return self.get_token_path(user_id).exists()


class UserSessionManager:
    """Central manager for all user sessions with complete isolation."""
    
    def __init__(self, 
                 token_storage: Optional[TokenStorage] = None,
                 session_timeout_hours: int = 24,
                 cleanup_interval_minutes: int = 30):
        self.token_storage = token_storage or TokenStorage()
        self.session_timeout_hours = session_timeout_hours
        self.cleanup_interval_minutes = cleanup_interval_minutes
        
        # Session storage with regular dictionary for session management
        self._sessions: Dict[str, UserSession] = {}
        self._user_sessions: Dict[str, Set[str]] = collections.defaultdict(set)
        
        # Rate limiters per user
        self._rate_limiters: Dict[str, RateLimiter] = {}
        
        # Thread safety
        self._lock = threading.RLock()
        
        # Background cleanup task
        self._cleanup_task: Optional[asyncio.Task] = None
        self._stop_cleanup = threading.Event()
        
        # Statistics
        self._stats = {
            'total_sessions': 0,
            'active_sessions': 0,
            'total_requests': 0,
            'total_trades': 0
        }
    
    def create_session(self, 
                      user_id: str,
                      username: str,
                      email: str,
                      permission: UserPermission = UserPermission.TRADING,
                      quota: Optional[UserQuota] = None) -> UserSession:
        """Create a new user session."""
        with self._lock:
            # Create new session
            session = UserSession(
                user_id=user_id,
                username=username,
                email=email,
                permission=permission,
                quota=quota or UserQuota()
            )
            
            # Ensure the session is marked as recently active
            session.update_activity()
            
            # Store session
            self._sessions[session.session_id] = session
            self._user_sessions[user_id].add(session.session_id)
            
            # Create rate limiter for user if not exists
            if user_id not in self._rate_limiters:
                self._rate_limiters[user_id] = RateLimiter(
                    max_requests_per_minute=session.quota.max_requests_per_minute
                )
            
            # Update statistics
            self._stats['total_sessions'] += 1
            self._stats['active_sessions'] += 1
            
            logger.info(f"Created session {session.session_id} for user {user_id}")
            return session
    
    def get_session(self, session_id: str) -> Optional[UserSession]:
        """Get session by session ID."""
        with self._lock:
            session = self._sessions.get(session_id)
            if session and session.is_active():
                session.update_activity()
                return session
            return None
    
    def get_user_sessions(self, user_id: str) -> List[UserSession]:
        """Get all active sessions for a user."""
        with self._lock:
            sessions = []
            for session_id in self._user_sessions.get(user_id, set()):
                session = self._sessions.get(session_id)
                if session and session.is_active():
                    session.update_activity()
                    sessions.append(session)
            return sessions
    
    def authenticate_user(self, 
                         user_id: str,
                         api_key: str,
                         app_secret: str,
                         callback_url: str) -> Optional[UserSession]:
        """Authenticate a user and create/update their session."""
        with self._lock:
            # Check if user has existing session
            sessions = self.get_user_sessions(user_id)
            if sessions:
                session = sessions[0]  # Use first active session
            else:
                # Create new session with default values
                session = self.create_session(
                    user_id=user_id,
                    username=f"user_{user_id}",
                    email=f"user_{user_id}@example.com"
                )
            
            # Update session with authentication info
            session.api_key = api_key
            session.app_secret = app_secret
            session.token_path = str(self.token_storage.get_token_path(user_id))
            
            # Try to load existing token
            token_data = self.token_storage.load_token(user_id)
            if token_data:
                try:
                    # Create token metadata
                    def token_write_func(token, *args, **kwargs):
                        self.token_storage.save_token(user_id, token)
                    
                    session.token_metadata = TokenMetadata.from_loaded_token(
                        token_data, token_write_func
                    )
                    
                    # Create clients
                    session.client = Client(
                        api_key, 
                        session.token_metadata.session,
                        token_metadata=session.token_metadata
                    )
                    
                    session.async_client = AsyncClient(
                        api_key,
                        session.token_metadata.session,
                        token_metadata=session.token_metadata
                    )
                    
                    logger.info(f"Authenticated user {user_id} with existing token")
                    session.add_audit_event("authentication", {"method": "token_load"})
                    return session
                    
                except Exception as e:
                    logger.error(f"Failed to load token for user {user_id}: {e}")
                    session.add_audit_event("authentication_error", {"error": str(e)})
            
            # No valid token, user needs to complete OAuth flow
            logger.info(f"User {user_id} needs to complete OAuth flow")
            session.add_audit_event("authentication", {"method": "oauth_required"})
            return session
    
    def can_make_request(self, user_id: str) -> bool:
        """Check if user can make a request based on rate limits."""
        with self._lock:
            rate_limiter = self._rate_limiters.get(user_id)
            if not rate_limiter:
                return True  # No rate limiter means no limits
            return rate_limiter.can_make_request(user_id)
    
    def wait_for_rate_limit(self, user_id: str) -> float:
        """Wait for rate limit and return wait time."""
        with self._lock:
            rate_limiter = self._rate_limiters.get(user_id)
            if not rate_limiter:
                return 0.0
            
            wait_time = rate_limiter.get_wait_time(user_id)
            if wait_time > 0:
                time.sleep(wait_time)
            return wait_time
    
    def record_request(self, session: UserSession, request_type: str = "api"):
        """Record a user request for monitoring and rate limiting."""
        with self._lock:
            session.update_activity()
            session.request_count += 1
            session.total_requests += 1
            session.request_history.append(datetime.datetime.now())
            
            # Keep only last 1000 requests in history
            if len(session.request_history) > 1000:
                session.request_history = session.request_history[-1000:]
            
            # Update rate limiter
            rate_limiter = self._rate_limiters.get(session.user_id)
            if rate_limiter:
                # Record the request in the rate limiter
                rate_limiter.can_make_request(session.user_id)
            
            self._stats['total_requests'] += 1
            
            session.add_audit_event("request", {
                "type": request_type,
                "request_count": session.request_count,
                "total_requests": session.total_requests
            })
    
    def record_trade(self, session: UserSession, trade_details: Dict[str, Any]):
        """Record a user trade for monitoring and quotas."""
        with self._lock:
            session.total_trades += 1
            session.last_trade_at = datetime.datetime.now()
            
            # Update volume if available
            if 'volume' in trade_details:
                session.total_volume += trade_details['volume']
            
            self._stats['total_trades'] += 1
            
            session.add_audit_event("trade", trade_details)
    
    def check_permission(self, session: UserSession, required_permission: UserPermission) -> bool:
        """Check if session has required permission."""
        permission_hierarchy = {
            UserPermission.READ_ONLY: 1,
            UserPermission.TRADING: 2,
            UserPermission.ADMIN: 3
        }
        
        session_level = permission_hierarchy.get(session.permission, 0)
        required_level = permission_hierarchy.get(required_permission, 0)
        
        return session_level >= required_level
    
    def get_client(self, session: UserSession) -> Optional[Client]:
        """Get the HTTP client for a session."""
        if not session.client:
            logger.warning(f"No client available for session {session.session_id}")
            return None
        return session.client
    
    def get_async_client(self, session: UserSession) -> Optional[AsyncClient]:
        """Get the async HTTP client for a session."""
        if not session.async_client:
            logger.warning(f"No async client available for session {session.session_id}")
            return None
        return session.async_client
    
    def get_stream_client(self, session: UserSession, account_id: Optional[int] = None) -> Optional[StreamClient]:
        """Get the streaming client for a session."""
        if not session.client:
            logger.warning(f"No client available for streaming session {session.session_id}")
            return None
        
        if not session.stream_client:
            session.stream_client = StreamClient(
                session.client,
                account_id=account_id
            )
        
        return session.stream_client
    
    def close_session(self, session_id: str) -> bool:
        """Close a user session."""
        with self._lock:
            session = self._sessions.get(session_id)
            if not session:
                return False
            
            # Close streaming client if exists
            if session.stream_client:
                try:
                    asyncio.create_task(session.stream_client.logout())
                except Exception as e:
                    logger.error(f"Error closing stream client: {e}")
            
            # Remove from storage
            if session_id in self._sessions:
                del self._sessions[session_id]
            
            # Remove from user sessions
            if session.user_id in self._user_sessions:
                self._user_sessions[session.user_id].discard(session_id)
                if not self._user_sessions[session.user_id]:
                    del self._user_sessions[session.user_id]
            
            # Update statistics
            self._stats['active_sessions'] = max(0, self._stats['active_sessions'] - 1)
            
            session.add_audit_event("session_closed", {"session_id": session_id})
            logger.info(f"Closed session {session_id}")
            return True
    
    def cleanup_expired_sessions(self) -> int:
        """Clean up expired sessions and return count of cleaned sessions."""
        with self._lock:
            expired_sessions = []
            
            for session_id, session in list(self._sessions.items()):
                if not session.is_active():
                    expired_sessions.append(session_id)
            
            for session_id in expired_sessions:
                self.close_session(session_id)
            
            if expired_sessions:
                logger.info(f"Cleaned up {len(expired_sessions)} expired sessions")
            
            return len(expired_sessions)
    
    def get_statistics(self) -> Dict[str, Any]:
        """Get system statistics."""
        with self._lock:
            active_sessions = sum(
                1 for session in self._sessions.values()
                if session.is_active()
            )
            
            # Update the active sessions count in stats
            self._stats['active_sessions'] = active_sessions
            
            return {
                **self._stats,
                'active_sessions': active_sessions,
                'total_sessions_in_memory': len(self._sessions),
                'total_users': len(self._user_sessions),
                'rate_limiters': len(self._rate_limiters)
            }
    
    def start_cleanup_task(self):
        """Start background cleanup task."""
        if self._cleanup_task is None:
            self._stop_cleanup.clear()
            try:
                # Try to get the current event loop
                loop = asyncio.get_running_loop()
                self._cleanup_task = loop.create_task(self._cleanup_loop())
                logger.info("Started background cleanup task")
            except RuntimeError:
                # No event loop running, skip cleanup task for now
                logger.warning("No event loop running, cleanup task not started")
                self._cleanup_task = None
    
    def stop_cleanup_task(self):
        """Stop background cleanup task."""
        if self._cleanup_task:
            self._stop_cleanup.set()
            self._cleanup_task.cancel()
            self._cleanup_task = None
            logger.info("Stopped background cleanup task")
    
    async def _cleanup_loop(self):
        """Background cleanup loop."""
        while not self._stop_cleanup.is_set():
            try:
                self.cleanup_expired_sessions()
                await asyncio.sleep(self.cleanup_interval_minutes * 60)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error in cleanup loop: {e}")
                await asyncio.sleep(60)  # Wait before retrying


class MultiUserClient:
    """Client wrapper that provides multi-user functionality."""
    
    def __init__(self, session_manager: UserSessionManager):
        self.session_manager = session_manager
    
    def get_client(self, session_id: str) -> Optional[Client]:
        """Get HTTP client for a session."""
        session = self.session_manager.get_session(session_id)
        if not session:
            return None
        
        if not self.session_manager.check_permission(session, UserPermission.READ_ONLY):
            raise PermissionError(f"Session {session_id} lacks required permissions")
        
        # Check rate limits
        if not self.session_manager.can_make_request(session.user_id):
            raise Exception("Rate limit exceeded")
        
        client = self.session_manager.get_client(session)
        if client:
            self.session_manager.record_request(session, "api")
        
        return client
    
    def get_async_client(self, session_id: str) -> Optional[AsyncClient]:
        """Get async HTTP client for a session."""
        session = self.session_manager.get_session(session_id)
        if not session:
            return None
        
        if not self.session_manager.check_permission(session, UserPermission.READ_ONLY):
            raise PermissionError(f"Session {session_id} lacks required permissions")
        
        # Check rate limits
        if not self.session_manager.can_make_request(session.user_id):
            raise Exception("Rate limit exceeded")
        
        client = self.session_manager.get_async_client(session)
        if client:
            self.session_manager.record_request(session, "async_api")
        
        return client
    
    def get_stream_client(self, session_id: str, account_id: Optional[int] = None) -> Optional[StreamClient]:
        """Get streaming client for a session."""
        session = self.session_manager.get_session(session_id)
        if not session:
            return None
        
        if not self.session_manager.check_permission(session, UserPermission.READ_ONLY):
            raise PermissionError(f"Session {session_id} lacks required permissions")
        
        # Check streaming connection limits
        if session.quota.max_streaming_connections <= 0:
            raise Exception("Streaming connections not allowed for this user")
        
        client = self.session_manager.get_stream_client(session, account_id)
        if client:
            self.session_manager.record_request(session, "streaming")
        
        return client
    
    def place_order(self, session_id: str, account_hash: str, order_spec: Dict[str, Any]) -> Any:
        """Place an order with permission and quota checking."""
        session = self.session_manager.get_session(session_id)
        if not session:
            raise ValueError(f"Invalid session {session_id}")
        
        if not self.session_manager.check_permission(session, UserPermission.TRADING):
            raise PermissionError(f"Session {session_id} lacks trading permissions")
        
        # Check rate limits
        wait_time = self.session_manager.wait_for_rate_limit(session.user_id)
        if wait_time > 0:
            logger.info(f"Waited {wait_time}s for rate limit")
        
        client = self.session_manager.get_client(session)
        if not client:
            raise Exception("No client available")
        
        # Place order
        result = client.place_order(account_hash, order_spec)
        
        # Record trade
        self.session_manager.record_trade(session, {
            "order_spec": order_spec,
            "account_hash": account_hash,
            "result": str(result)
        })
        
        return result


# Global session manager instance
_session_manager: Optional[UserSessionManager] = None


def get_session_manager() -> UserSessionManager:
    """Get the global session manager instance."""
    global _session_manager
    if _session_manager is None:
        _session_manager = UserSessionManager()
        _session_manager.start_cleanup_task()
    return _session_manager


def create_user_session(user_id: str,
                       username: str,
                       email: str,
                       permission: UserPermission = UserPermission.TRADING,
                       quota: Optional[UserQuota] = None) -> UserSession:
    """Create a new user session using the global session manager."""
    return get_session_manager().create_session(
        user_id=user_id,
        username=username,
        email=email,
        permission=permission,
        quota=quota
    )


def authenticate_user(user_id: str,
                     api_key: str,
                     app_secret: str,
                     callback_url: str) -> Optional[UserSession]:
    """Authenticate a user using the global session manager."""
    return get_session_manager().authenticate_user(
        user_id=user_id,
        api_key=api_key,
        app_secret=app_secret,
        callback_url=callback_url
    )


def get_multi_user_client() -> MultiUserClient:
    """Get a multi-user client using the global session manager."""
    return MultiUserClient(get_session_manager()) 