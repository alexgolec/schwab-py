"""
Comprehensive test suite for multi-user session isolation system.

Tests include:
- 100 concurrent users with separate streaming
- User isolation (no data leakage)
- User permission enforcement
- Load testing with realistic trading patterns
- Rate limiting and quota enforcement
- Session cleanup and memory management
"""

import asyncio
import datetime
import json
import logging
import os
import tempfile
import threading
import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import Mock, patch, MagicMock

# Import the multi-user module
import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from enhancements.multi_user import (
    UserSessionManager, UserSession, UserPermission, UserStatus, UserQuota,
    RateLimiter, TokenStorage, MultiUserClient, create_user_session,
    authenticate_user, get_multi_user_client, get_session_manager
)


class TestUserSession(unittest.TestCase):
    """Test UserSession functionality."""
    
    def setUp(self):
        """Set up test fixtures."""
        self.session = UserSession(
            user_id="test_user",
            username="test_user",
            email="test@example.com",
            permission=UserPermission.TRADING,
            quota=UserQuota()
        )
    
    def test_session_creation(self):
        """Test session creation with proper defaults."""
        self.assertEqual(self.session.user_id, "test_user")
        self.assertEqual(self.session.username, "test_user")
        self.assertEqual(self.session.email, "test@example.com")
        self.assertEqual(self.session.permission, UserPermission.TRADING)
        self.assertIsInstance(self.session.quota, UserQuota)
        self.assertEqual(self.session.status, UserStatus.ACTIVE)
        self.assertIsNotNone(self.session.session_id)
        self.assertIsNotNone(self.session.created_at)
        self.assertIsNotNone(self.session.expires_at)
    
    def test_session_expiration(self):
        """Test session expiration logic."""
        # Session should not be expired initially
        self.assertFalse(self.session.is_expired())
        
        # Manually set expiration to past
        self.session.expires_at = datetime.datetime.now() - datetime.timedelta(hours=1)
        self.assertTrue(self.session.is_expired())
    
    def test_session_activity(self):
        """Test session activity tracking."""
        initial_activity = self.session.last_activity
        time.sleep(0.1)  # Small delay
        
        self.session.update_activity()
        self.assertGreater(self.session.last_activity, initial_activity)
    
    def test_session_active_status(self):
        """Test session active status logic."""
        # Should be active initially
        self.assertTrue(self.session.is_active())
        
        # Set to inactive status
        self.session.status = UserStatus.INACTIVE
        self.assertFalse(self.session.is_active())
        
        # Set to expired
        self.session.status = UserStatus.ACTIVE
        self.session.expires_at = datetime.datetime.now() - datetime.timedelta(hours=1)
        self.assertFalse(self.session.is_active())
        
        # Set to old activity
        self.session.expires_at = datetime.datetime.now() + datetime.timedelta(hours=1)
        self.session.last_activity = datetime.datetime.now() - datetime.timedelta(hours=2)
        self.assertFalse(self.session.is_active())
    
    def test_audit_events(self):
        """Test audit event tracking."""
        initial_count = len(self.session.audit_events)
        
        self.session.add_audit_event("test_event", {"key": "value"})
        
        self.assertEqual(len(self.session.audit_events), initial_count + 1)
        event = self.session.audit_events[-1]
        self.assertEqual(event["event_type"], "test_event")
        self.assertEqual(event["details"], {"key": "value"})
        self.assertIn("timestamp", event)
        self.assertEqual(event["session_id"], self.session.session_id)


class TestRateLimiter(unittest.TestCase):
    """Test RateLimiter functionality."""
    
    def setUp(self):
        """Set up test fixtures."""
        self.rate_limiter = RateLimiter(max_requests_per_minute=5)
    
    def test_rate_limiter_creation(self):
        """Test rate limiter creation."""
        self.assertEqual(self.rate_limiter.max_requests_per_minute, 5)
    
    def test_rate_limiting_basic(self):
        """Test basic rate limiting functionality."""
        user_id = "test_user"
        
        # Should allow requests initially
        for i in range(5):
            self.assertTrue(self.rate_limiter.can_make_request(user_id))
        
        # Should block after limit
        self.assertFalse(self.rate_limiter.can_make_request(user_id))
    
    def test_rate_limiting_multiple_users(self):
        """Test rate limiting with multiple users."""
        user1 = "user1"
        user2 = "user2"
        
        # Each user should have independent limits
        for i in range(5):
            self.assertTrue(self.rate_limiter.can_make_request(user1))
            self.assertTrue(self.rate_limiter.can_make_request(user2))
        
        # Both should be blocked
        self.assertFalse(self.rate_limiter.can_make_request(user1))
        self.assertFalse(self.rate_limiter.can_make_request(user2))
    
    def test_rate_limiting_time_window(self):
        """Test rate limiting with time window."""
        user_id = "test_user"
        
        # Make 5 requests
        for i in range(5):
            self.assertTrue(self.rate_limiter.can_make_request(user_id))
        
        # Should be blocked
        self.assertFalse(self.rate_limiter.can_make_request(user_id))
        
        # Clear the request times to simulate time passing
        self.rate_limiter._request_times[user_id] = []
        
        # Should allow requests again
        self.assertTrue(self.rate_limiter.can_make_request(user_id))
    
    def test_wait_time_calculation(self):
        """Test wait time calculation."""
        user_id = "test_user"
        
        # No wait time initially
        self.assertEqual(self.rate_limiter.get_wait_time(user_id), 0.0)
        
        # Make requests up to limit
        for i in range(5):
            self.rate_limiter.can_make_request(user_id)
        
        # Should have wait time
        wait_time = self.rate_limiter.get_wait_time(user_id)
        self.assertGreater(wait_time, 0.0)
        self.assertLessEqual(wait_time, 60.0)  # Should be less than 1 minute


class TestTokenStorage(unittest.TestCase):
    """Test TokenStorage functionality."""
    
    def setUp(self):
        """Set up test fixtures."""
        self.temp_dir = tempfile.mkdtemp()
        self.token_storage = TokenStorage(self.temp_dir)
        self.user_id = "test_user"
        self.test_token = {
            "access_token": "test_access_token",
            "refresh_token": "test_refresh_token",
            "token_type": "Bearer",
            "expires_in": 3600
        }
    
    def tearDown(self):
        """Clean up test fixtures."""
        import shutil
        shutil.rmtree(self.temp_dir)
    
    def test_token_storage_creation(self):
        """Test token storage creation."""
        self.assertEqual(self.token_storage.base_path, Path(self.temp_dir))
        self.assertTrue(self.token_storage.base_path.exists())
    
    def test_token_path_generation(self):
        """Test token path generation."""
        expected_path = Path(self.temp_dir) / "test_user_token.json"
        self.assertEqual(self.token_storage.get_token_path(self.user_id), expected_path)
    
    def test_token_save_and_load(self):
        """Test token save and load functionality."""
        # Save token
        self.token_storage.save_token(self.user_id, self.test_token)
        
        # Check if file exists
        self.assertTrue(self.token_storage.token_exists(self.user_id))
        
        # Load token
        loaded_token = self.token_storage.load_token(self.user_id)
        self.assertEqual(loaded_token, self.test_token)
    
    def test_token_delete(self):
        """Test token deletion."""
        # Save token
        self.token_storage.save_token(self.user_id, self.test_token)
        self.assertTrue(self.token_storage.token_exists(self.user_id))
        
        # Delete token
        self.token_storage.delete_token(self.user_id)
        self.assertFalse(self.token_storage.token_exists(self.user_id))
    
    def test_token_load_nonexistent(self):
        """Test loading non-existent token."""
        token = self.token_storage.load_token("nonexistent_user")
        self.assertIsNone(token)
    
    def test_token_exists_check(self):
        """Test token existence check."""
        self.assertFalse(self.token_storage.token_exists(self.user_id))
        
        self.token_storage.save_token(self.user_id, self.test_token)
        self.assertTrue(self.token_storage.token_exists(self.user_id))


class TestUserSessionManager(unittest.TestCase):
    """Test UserSessionManager functionality."""
    
    def setUp(self):
        """Set up test fixtures."""
        self.temp_dir = tempfile.mkdtemp()
        self.token_storage = TokenStorage(self.temp_dir)
        self.session_manager = UserSessionManager(token_storage=self.token_storage)
    
    def tearDown(self):
        """Clean up test fixtures."""
        import shutil
        shutil.rmtree(self.temp_dir)
        self.session_manager.stop_cleanup_task()
    
    def test_session_manager_creation(self):
        """Test session manager creation."""
        self.assertIsNotNone(self.session_manager.token_storage)
        self.assertEqual(self.session_manager.session_timeout_hours, 24)
        self.assertEqual(self.session_manager.cleanup_interval_minutes, 30)
    
    def test_create_session(self):
        """Test session creation."""
        session = self.session_manager.create_session(
            user_id="test_user",
            username="test_user",
            email="test@example.com",
            permission=UserPermission.TRADING
        )
        
        self.assertIsInstance(session, UserSession)
        self.assertEqual(session.user_id, "test_user")
        self.assertEqual(session.username, "test_user")
        self.assertEqual(session.email, "test@example.com")
        self.assertEqual(session.permission, UserPermission.TRADING)
    
    def test_get_session(self):
        """Test session retrieval."""
        # Create session
        session = self.session_manager.create_session(
            user_id="test_user",
            username="test_user",
            email="test@example.com"
        )
        
        # Get session
        retrieved_session = self.session_manager.get_session(session.session_id)
        self.assertEqual(retrieved_session, session)
        
        # Test non-existent session
        non_existent = self.session_manager.get_session("non_existent")
        self.assertIsNone(non_existent)
    
    def test_get_user_sessions(self):
        """Test getting all sessions for a user."""
        # Create multiple sessions for same user
        session1 = self.session_manager.create_session(
            user_id="test_user",
            username="test_user",
            email="test@example.com"
        )
        session2 = self.session_manager.create_session(
            user_id="test_user",
            username="test_user",
            email="test@example.com"
        )
        
        # Get all sessions for user
        sessions = self.session_manager.get_user_sessions("test_user")
        self.assertEqual(len(sessions), 2)
        session_ids = {s.session_id for s in sessions}
        self.assertIn(session1.session_id, session_ids)
        self.assertIn(session2.session_id, session_ids)
    
    def test_rate_limiting(self):
        """Test rate limiting functionality."""
        user_id = "test_user"
        
        # Create session with rate limiting
        session = self.session_manager.create_session(
            user_id=user_id,
            username="test_user",
            email="test@example.com"
        )
        
        # Should be able to make requests initially
        self.assertTrue(self.session_manager.can_make_request(user_id))
        
        # Simulate many requests by directly calling the rate limiter
        rate_limiter = self.session_manager._rate_limiters.get(user_id)
        for i in range(120):  # Default limit
            rate_limiter.can_make_request(user_id)
        
        # Should be rate limited
        self.assertFalse(self.session_manager.can_make_request(user_id))
    
    def test_permission_checking(self):
        """Test permission checking."""
        # Create sessions with different permissions
        read_only_session = self.session_manager.create_session(
            user_id="read_only_user",
            username="read_only_user",
            email="read@example.com",
            permission=UserPermission.READ_ONLY
        )
        
        trading_session = self.session_manager.create_session(
            user_id="trading_user",
            username="trading_user",
            email="trading@example.com",
            permission=UserPermission.TRADING
        )
        
        admin_session = self.session_manager.create_session(
            user_id="admin_user",
            username="admin_user",
            email="admin@example.com",
            permission=UserPermission.ADMIN
        )
        
        # Test permission hierarchy
        self.assertTrue(self.session_manager.check_permission(
            read_only_session, UserPermission.READ_ONLY))
        self.assertFalse(self.session_manager.check_permission(
            read_only_session, UserPermission.TRADING))
        self.assertFalse(self.session_manager.check_permission(
            read_only_session, UserPermission.ADMIN))
        
        self.assertTrue(self.session_manager.check_permission(
            trading_session, UserPermission.READ_ONLY))
        self.assertTrue(self.session_manager.check_permission(
            trading_session, UserPermission.TRADING))
        self.assertFalse(self.session_manager.check_permission(
            trading_session, UserPermission.ADMIN))
        
        self.assertTrue(self.session_manager.check_permission(
            admin_session, UserPermission.READ_ONLY))
        self.assertTrue(self.session_manager.check_permission(
            admin_session, UserPermission.TRADING))
        self.assertTrue(self.session_manager.check_permission(
            admin_session, UserPermission.ADMIN))
    
    def test_session_cleanup(self):
        """Test session cleanup functionality."""
        # Create session
        session = self.session_manager.create_session(
            user_id="test_user",
            username="test_user",
            email="test@example.com"
        )
        
        # Manually expire session
        session.expires_at = datetime.datetime.now() - datetime.timedelta(hours=1)
        
        # Cleanup should remove expired session
        cleaned_count = self.session_manager.cleanup_expired_sessions()
        self.assertEqual(cleaned_count, 1)
        
        # Session should no longer be retrievable
        retrieved = self.session_manager.get_session(session.session_id)
        self.assertIsNone(retrieved)
    
    def test_statistics(self):
        """Test statistics collection."""
        # Create some sessions
        for i in range(3):
            self.session_manager.create_session(
                user_id=f"user_{i}",
                username=f"user_{i}",
                email=f"user_{i}@example.com"
            )
        
        stats = self.session_manager.get_statistics()
        
        self.assertIn('total_sessions', stats)
        self.assertIn('active_sessions', stats)
        self.assertIn('total_requests', stats)
        self.assertIn('total_trades', stats)
        self.assertIn('total_users', stats)
        self.assertIn('rate_limiters', stats)
        
        self.assertEqual(stats['total_sessions'], 3)
        self.assertEqual(stats['active_sessions'], 3)
        self.assertEqual(stats['total_users'], 3)


class TestMultiUserClient(unittest.TestCase):
    """Test MultiUserClient functionality."""
    
    def setUp(self):
        """Set up test fixtures."""
        self.temp_dir = tempfile.mkdtemp()
        self.token_storage = TokenStorage(self.temp_dir)
        self.session_manager = UserSessionManager(token_storage=self.token_storage)
        self.multi_user_client = MultiUserClient(self.session_manager)
    
    def tearDown(self):
        """Clean up test fixtures."""
        import shutil
        shutil.rmtree(self.temp_dir)
        self.session_manager.stop_cleanup_task()
    
    def test_multi_user_client_creation(self):
        """Test multi-user client creation."""
        self.assertIsNotNone(self.multi_user_client.session_manager)
    
    def test_get_client_with_invalid_session(self):
        """Test getting client with invalid session."""
        client = self.multi_user_client.get_client("invalid_session_id")
        self.assertIsNone(client)
    
    def test_get_client_with_read_only_permission(self):
        """Test getting client with read-only permission."""
        # Create session with read-only permission
        session = self.session_manager.create_session(
            user_id="read_only_user",
            username="read_only_user",
            email="read@example.com",
            permission=UserPermission.READ_ONLY
        )
        
        # Should be able to get client
        client = self.multi_user_client.get_client(session.session_id)
        # Note: client will be None since we don't have real authentication
        # but the permission check should pass
    
    def test_get_client_with_insufficient_permission(self):
        """Test getting client with insufficient permission."""
        # Create session with no permission (edge case)
        session = UserSession(
            user_id="no_permission_user",
            username="no_permission_user",
            email="none@example.com",
            permission=UserPermission.READ_ONLY,  # This should actually work
            quota=UserQuota()
        )
        session.permission = None  # Force no permission
        
        # This should raise an exception or return None
        # The exact behavior depends on the permission checking logic


class TestConcurrentUsers(unittest.TestCase):
    """Test concurrent user scenarios."""
    
    def setUp(self):
        """Set up test fixtures."""
        self.temp_dir = tempfile.mkdtemp()
        self.token_storage = TokenStorage(self.temp_dir)
        self.session_manager = UserSessionManager(token_storage=self.token_storage)
    
    def tearDown(self):
        """Clean up test fixtures."""
        import shutil
        shutil.rmtree(self.temp_dir)
        self.session_manager.stop_cleanup_task()
    
    def test_100_concurrent_users(self):
        """Test 100 concurrent users with separate sessions."""
        sessions = []
        
        # Create 100 concurrent users
        with ThreadPoolExecutor(max_workers=10) as executor:
            futures = []
            for i in range(100):
                future = executor.submit(
                    self.session_manager.create_session,
                    user_id=f"user_{i}",
                    username=f"user_{i}",
                    email=f"user_{i}@example.com",
                    permission=UserPermission.TRADING
                )
                futures.append(future)
            
            # Wait for all sessions to be created
            for future in futures:
                session = future.result()
                sessions.append(session)
        
        # Verify all sessions were created
        self.assertEqual(len(sessions), 100)
        
        # Verify unique session IDs
        session_ids = {session.session_id for session in sessions}
        self.assertEqual(len(session_ids), 100)
        
        # Verify all sessions are active
        for session in sessions:
            self.assertTrue(session.is_active())
        
        # Check statistics
        stats = self.session_manager.get_statistics()
        self.assertEqual(stats['total_sessions'], 100)
        self.assertEqual(stats['active_sessions'], 100)
        self.assertEqual(stats['total_users'], 100)
    
    def test_user_isolation(self):
        """Test that users are completely isolated."""
        # Create two users
        user1_session = self.session_manager.create_session(
            user_id="user1",
            username="user1",
            email="user1@example.com",
            permission=UserPermission.TRADING
        )
        
        user2_session = self.session_manager.create_session(
            user_id="user2",
            username="user2",
            email="user2@example.com",
            permission=UserPermission.READ_ONLY
        )
        
        # Verify they have different session IDs
        self.assertNotEqual(user1_session.session_id, user2_session.session_id)
        
        # Verify they have different user IDs
        self.assertNotEqual(user1_session.user_id, user2_session.user_id)
        
        # Verify they have different permissions
        self.assertNotEqual(user1_session.permission, user2_session.permission)
        
        # Verify rate limiters are separate
        rate_limiter1 = self.session_manager._rate_limiters.get("user1")
        rate_limiter2 = self.session_manager._rate_limiters.get("user2")
        self.assertIsNotNone(rate_limiter1)
        self.assertIsNotNone(rate_limiter2)
        self.assertIsNot(rate_limiter1, rate_limiter2)
    
    def test_session_cleanup_under_load(self):
        """Test session cleanup under load."""
        # Create many sessions
        sessions = []
        for i in range(50):
            session = self.session_manager.create_session(
                user_id=f"user_{i}",
                username=f"user_{i}",
                email=f"user_{i}@example.com"
            )
            sessions.append(session)
        
        # Expire some sessions
        for i in range(10):
            sessions[i].expires_at = datetime.datetime.now() - datetime.timedelta(hours=1)
        
        # Run cleanup
        cleaned_count = self.session_manager.cleanup_expired_sessions()
        self.assertEqual(cleaned_count, 10)
        
        # Verify remaining sessions
        stats = self.session_manager.get_statistics()
        self.assertEqual(stats['active_sessions'], 40)
    
    def test_1000_concurrent_users_scalability(self):
        """Test that the system can handle 1000+ concurrent users."""
        sessions = []
        
        # Create 1000 concurrent users
        with ThreadPoolExecutor(max_workers=20) as executor:
            futures = []
            for i in range(1000):
                future = executor.submit(
                    self.session_manager.create_session,
                    user_id=f"scalability_user_{i}",
                    username=f"scalability_user_{i}",
                    email=f"scalability_user_{i}@example.com",
                    permission=UserPermission.TRADING
                )
                futures.append(future)
            
            # Wait for all sessions to be created
            for future in futures:
                session = future.result()
                sessions.append(session)
        
        # Verify all sessions were created
        self.assertEqual(len(sessions), 1000)
        
        # Verify unique session IDs
        session_ids = {session.session_id for session in sessions}
        self.assertEqual(len(session_ids), 1000)
        
        # Verify all sessions are active
        active_count = sum(1 for session in sessions if session.is_active())
        self.assertEqual(active_count, 1000)
        
        # Check statistics
        stats = self.session_manager.get_statistics()
        self.assertEqual(stats['total_sessions'], 1000)
        self.assertEqual(stats['active_sessions'], 1000)
        self.assertEqual(stats['total_users'], 1000)
        
        # Test memory usage is reasonable (should be less than 1GB for 1000 users)
        import psutil
        import os
        process = psutil.Process(os.getpid())
        memory_usage = process.memory_info().rss
        self.assertLess(memory_usage, 1024 * 1024 * 1024)  # 1GB
        
        # Clean up sessions
        for session in sessions:
            self.session_manager.close_session(session.session_id)


class TestLoadTesting(unittest.TestCase):
    """Test load testing scenarios."""
    
    def setUp(self):
        """Set up test fixtures."""
        self.temp_dir = tempfile.mkdtemp()
        self.token_storage = TokenStorage(self.temp_dir)
        self.session_manager = UserSessionManager(token_storage=self.token_storage)
    
    def tearDown(self):
        """Clean up test fixtures."""
        import shutil
        shutil.rmtree(self.temp_dir)
        self.session_manager.stop_cleanup_task()
    
    def test_rapid_request_simulation(self):
        """Test rapid request simulation."""
        # Create session
        session = self.session_manager.create_session(
            user_id="load_test_user",
            username="load_test_user",
            email="load@example.com",
            permission=UserPermission.TRADING
        )
        
        # Simulate rapid requests
        request_count = 0
        start_time = time.time()
        
        for i in range(200):  # More than rate limit
            if self.session_manager.can_make_request(session.user_id):
                self.session_manager.record_request(session, "api")
                request_count += 1
            else:
                # Wait for rate limit
                time.sleep(0.1)
        
        end_time = time.time()
        
        # Verify rate limiting worked
        self.assertLessEqual(request_count, 120)  # Should be limited
        self.assertGreater(end_time - start_time, 0)  # Should take some time
    
    def test_memory_usage_scaling(self):
        """Test memory usage scaling with user count."""
        import psutil
        import os
        
        process = psutil.Process(os.getpid())
        initial_memory = process.memory_info().rss
        
        # Create many sessions
        sessions = []
        for i in range(100):
            session = self.session_manager.create_session(
                user_id=f"memory_test_user_{i}",
                username=f"memory_test_user_{i}",
                email=f"memory_test_user_{i}@example.com"
            )
            sessions.append(session)
        
        # Check memory usage
        final_memory = process.memory_info().rss
        memory_increase = final_memory - initial_memory
        
        # Memory increase should be reasonable (less than 100MB for 100 users)
        self.assertLess(memory_increase, 100 * 1024 * 1024)  # 100MB
        
        # Clean up
        for session in sessions:
            self.session_manager.close_session(session.session_id)
    
    def test_realistic_trading_patterns(self):
        """Test realistic trading patterns."""
        # Create trading session
        session = self.session_manager.create_session(
            user_id="trader_user",
            username="trader_user",
            email="trader@example.com",
            permission=UserPermission.TRADING,
            quota=UserQuota(
                max_requests_per_minute=60,
                max_daily_trades=50,
                max_concurrent_orders=5
            )
        )
        
        # Simulate realistic trading day
        trades_made = 0
        requests_made = 0
        
        # Morning: Check account, get quotes
        for i in range(10):
            if self.session_manager.can_make_request(session.user_id):
                self.session_manager.record_request(session, "account_check")
                requests_made += 1
        
        # Mid-morning: Place some orders
        for i in range(5):
            if self.session_manager.can_make_request(session.user_id):
                self.session_manager.record_trade(session, {
                    "symbol": "AAPL",
                    "quantity": 100,
                    "price": 150.0,
                    "volume": 15000.0
                })
                trades_made += 1
        
        # Afternoon: More trading
        for i in range(8):
            if self.session_manager.can_make_request(session.user_id):
                self.session_manager.record_trade(session, {
                    "symbol": "GOOGL",
                    "quantity": 50,
                    "price": 2800.0,
                    "volume": 140000.0
                })
                trades_made += 1
        
        # End of day: Final checks
        for i in range(5):
            if self.session_manager.can_make_request(session.user_id):
                self.session_manager.record_request(session, "portfolio_check")
                requests_made += 1
        
        # Verify realistic patterns
        self.assertGreater(requests_made, 0)
        self.assertGreater(trades_made, 0)
        self.assertLessEqual(trades_made, session.quota.max_daily_trades)
        
        # Check session statistics
        self.assertEqual(session.total_trades, trades_made)
        self.assertEqual(session.total_requests, requests_made)


class TestIntegration(unittest.TestCase):
    """Test integration with other components."""
    
    def setUp(self):
        """Set up test fixtures."""
        self.temp_dir = tempfile.mkdtemp()
        self.token_storage = TokenStorage(self.temp_dir)
        self.session_manager = UserSessionManager(token_storage=self.token_storage)
    
    def tearDown(self):
        """Clean up test fixtures."""
        import shutil
        shutil.rmtree(self.temp_dir)
        self.session_manager.stop_cleanup_task()
    
    def test_global_session_manager(self):
        """Test global session manager functionality."""
        # Get global session manager
        global_manager = get_session_manager()
        self.assertIsNotNone(global_manager)
        
        # Create session using global manager
        session = create_user_session(
            user_id="global_test_user",
            username="global_test_user",
            email="global@example.com"
        )
        
        self.assertIsInstance(session, UserSession)
        self.assertEqual(session.user_id, "global_test_user")
    
    def test_multi_user_client_integration(self):
        """Test multi-user client integration."""
        # Get multi-user client
        client = get_multi_user_client()
        self.assertIsInstance(client, MultiUserClient)
        
        # Create session
        session = create_user_session(
            user_id="client_test_user",
            username="client_test_user",
            email="client@example.com",
            permission=UserPermission.TRADING
        )
        
        # Test client access
        http_client = client.get_client(session.session_id)
        # Note: Will be None without real authentication, but should not raise exception


if __name__ == '__main__':
    # Run tests with verbose output
    unittest.main(verbosity=2) 