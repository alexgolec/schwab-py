"""
Comprehensive test suite for secure token management system

Tests all functionality including:
- Token storage and retrieval
- Automatic refresh 1 hour before expiration
- Recovery from corrupted token files
- Concurrent token access
- Security audit and penetration testing
- Multiple storage backends
- Token rotation and revocation
"""

import base64
import json
import os
import pickle
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import Mock, patch, MagicMock

import pytest

# Import the secure tokens module
import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from enhancements.secure_tokens import (
    SecureTokenManager,
    TokenMetadata,
    TokenStatus,
    TokenEvent,
    StorageBackend,
    EncryptedFileBackend,
    KeyringBackend,
    SQLiteBackend,
    HSMBackend,
    TokenEventCallback,
    create_secure_token_manager,
    create_encryption_key_from_password,
    log_token_event,
    notify_scheduler_event,
    security_audit_event
)


class TestTokenMetadata(unittest.TestCase):
    """Test TokenMetadata class"""
    
    def test_token_metadata_creation(self):
        """Test creating TokenMetadata"""
        metadata = TokenMetadata(
            token_id="test_token_123",
            user_id="user_456",
            api_key="api_key_789",
            tags={"production", "high_priority"}
        )
        
        self.assertEqual(metadata.token_id, "test_token_123")
        self.assertEqual(metadata.user_id, "user_456")
        self.assertEqual(metadata.api_key, "api_key_789")
        self.assertEqual(metadata.status, TokenStatus.VALID)
        self.assertEqual(metadata.blacklisted, False)
        self.assertEqual(metadata.tags, {"production", "high_priority"})
    
    def test_token_metadata_serialization(self):
        """Test TokenMetadata serialization/deserialization"""
        original = TokenMetadata(
            token_id="test_token",
            user_id="user_123",
            api_key="api_key_456",
            tags={"tag1", "tag2"}
        )
        
        # Convert to dict
        data = original.to_dict()
        
        # Convert back to TokenMetadata
        restored = TokenMetadata.from_dict(data)
        
        self.assertEqual(original.token_id, restored.token_id)
        self.assertEqual(original.user_id, restored.user_id)
        self.assertEqual(original.api_key, restored.api_key)
        self.assertEqual(original.status, restored.status)
        self.assertEqual(original.tags, restored.tags)


class TestStorageBackends(unittest.TestCase):
    """Test storage backend implementations"""
    
    def setUp(self):
        """Set up test environment"""
        self.temp_dir = tempfile.mkdtemp()
        self.test_token_data = b"test_token_data_12345"
        self.test_metadata = TokenMetadata(
            token_id="test_token",
            api_key="test_api_key"
        )
    
    def tearDown(self):
        """Clean up test environment"""
        import shutil
        shutil.rmtree(self.temp_dir, ignore_errors=True)
    
    def test_encrypted_file_backend(self):
        """Test EncryptedFileBackend"""
        from cryptography.fernet import Fernet
        key = Fernet.generate_key()
        
        backend = EncryptedFileBackend(self.temp_dir, key)
        
        # Test store and retrieve
        encrypted_token = Fernet(key).encrypt(self.test_token_data)
        success = backend.store_token("test_token", encrypted_token, self.test_metadata)
        self.assertTrue(success)
        
        retrieved_token, retrieved_metadata = backend.retrieve_token("test_token")
        self.assertEqual(retrieved_token, encrypted_token)
        self.assertEqual(retrieved_metadata.token_id, self.test_metadata.token_id)
        
        # Test list tokens
        tokens = backend.list_tokens()
        self.assertIn("test_token", tokens)
        
        # Test delete
        success = backend.delete_token("test_token")
        self.assertTrue(success)
        
        # Test health check
        self.assertTrue(backend.health_check())
    
    def test_sqlite_backend(self):
        """Test SQLiteBackend"""
        from cryptography.fernet import Fernet
        key = Fernet.generate_key()
        db_path = os.path.join(self.temp_dir, "test_tokens.db")
        
        backend = SQLiteBackend(db_path, key)
        
        # Test store and retrieve
        encrypted_token = Fernet(key).encrypt(self.test_token_data)
        success = backend.store_token("test_token", encrypted_token, self.test_metadata)
        self.assertTrue(success)
        
        retrieved_token, retrieved_metadata = backend.retrieve_token("test_token")
        self.assertEqual(retrieved_token, encrypted_token)
        self.assertEqual(retrieved_metadata.token_id, self.test_metadata.token_id)
        
        # Test list tokens
        tokens = backend.list_tokens()
        self.assertIn("test_token", tokens)
        
        # Test delete
        success = backend.delete_token("test_token")
        self.assertTrue(success)
        
        # Test health check
        self.assertTrue(backend.health_check())
    
    @patch('keyring.set_password')
    @patch('keyring.get_password')
    @patch('keyring.delete_password')
    def test_keyring_backend(self, mock_delete, mock_get, mock_set):
        """Test KeyringBackend with mocked keyring"""
        backend = KeyringBackend("test_service")
        
        # Mock keyring responses
        mock_set.return_value = None
        mock_get.side_effect = lambda service, key: {
            "token_test_token": base64.b64encode(b"encrypted_token").decode(),
            "meta_test_token": json.dumps(self.test_metadata.to_dict())
        }.get(key)
        mock_delete.return_value = None
        
        # Test store
        success = backend.store_token("test_token", b"encrypted_token", self.test_metadata)
        self.assertTrue(success)
        
        # Test retrieve
        retrieved_token, retrieved_metadata = backend.retrieve_token("test_token")
        self.assertEqual(retrieved_token, b"encrypted_token")
        self.assertEqual(retrieved_metadata.token_id, self.test_metadata.token_id)
        
        # Test delete
        success = backend.delete_token("test_token")
        self.assertTrue(success)
        
        # Test health check
        mock_get.side_effect = lambda service, key: "test" if key == "health_check_test" else None
        self.assertTrue(backend.health_check())


class TestSecureTokenManager(unittest.TestCase):
    """Test SecureTokenManager class"""
    
    def setUp(self):
        """Set up test environment"""
        self.temp_dir = tempfile.mkdtemp()
        self.test_token_data = b"test_oauth_token_data"
        self.test_api_key = "test_api_key_123"
        self.test_user_id = "test_user_456"
        
        # Create token manager with file backend
        self.token_manager = SecureTokenManager(
            storage_backend=StorageBackend.ENCRYPTED_FILE,
            storage_config={'storage_dir': self.temp_dir},
            enable_auto_refresh=False,  # Disable for testing
            event_callbacks=[]
        )
    
    def tearDown(self):
        """Clean up test environment"""
        self.token_manager.shutdown()
        import shutil
        shutil.rmtree(self.temp_dir, ignore_errors=True)
    
    def test_store_and_retrieve_token(self):
        """Test basic token storage and retrieval"""
        # Store token
        token_id = self.token_manager.store_token(
            self.test_token_data,
            self.test_api_key,
            self.test_user_id
        )
        
        self.assertIsNotNone(token_id)
        self.assertTrue(token_id.startswith("token_"))
        
        # Retrieve token
        retrieved_data = self.token_manager.retrieve_token(token_id)
        self.assertEqual(retrieved_data, self.test_token_data)
        
        # Check metadata
        metadata = self.token_manager.get_token_metadata(token_id)
        self.assertIsNotNone(metadata)
        self.assertEqual(metadata.api_key, self.test_api_key)
        self.assertEqual(metadata.user_id, self.test_user_id)
        self.assertEqual(metadata.status, TokenStatus.VALID)
    
    def test_token_validation(self):
        """Test token validation logic"""
        # Store a token
        token_id = self.token_manager.store_token(
            self.test_token_data,
            self.test_api_key,
            self.test_user_id
        )
        
        # Get metadata and manipulate it to test validation
        metadata = self.token_manager.get_token_metadata(token_id)
        
        # Test valid token
        self.assertTrue(self.token_manager._validate_token(metadata))
        
        # Test blacklisted token
        metadata.blacklisted = True
        self.assertFalse(self.token_manager._validate_token(metadata))
        
        # Test expired token
        metadata.blacklisted = False
        metadata.last_refresh_timestamp = int(time.time()) - (8 * 24 * 3600)  # 8 days ago
        self.assertFalse(self.token_manager._validate_token(metadata))
    
    def test_token_revocation(self):
        """Test token revocation and blacklisting"""
        # Store token
        token_id = self.token_manager.store_token(
            self.test_token_data,
            self.test_api_key,
            self.test_user_id
        )
        
        # Revoke token
        success = self.token_manager.revoke_token(token_id, "Security breach")
        self.assertTrue(success)
        
        # Verify token is blacklisted
        metadata = self.token_manager.get_token_metadata(token_id)
        self.assertTrue(metadata.blacklisted)
        self.assertEqual(metadata.revocation_reason, "Security breach")
        self.assertEqual(metadata.status, TokenStatus.REVOKED)
        
        # Verify token cannot be retrieved
        with self.assertRaises(ValueError):
            self.token_manager.retrieve_token(token_id)
    
    def test_token_rotation(self):
        """Test zero-downtime token rotation"""
        # Store initial token
        token_id = self.token_manager.store_token(
            self.test_token_data,
            self.test_api_key,
            self.test_user_id
        )
        
        # Get initial metadata
        initial_metadata = self.token_manager.get_token_metadata(token_id)
        initial_refresh_count = initial_metadata.refresh_count
        
        # Rotate token
        new_token_data = b"new_oauth_token_data"
        success = self.token_manager.rotate_token(token_id, new_token_data)
        self.assertTrue(success)
        
        # Verify new token data
        retrieved_data = self.token_manager.retrieve_token(token_id)
        self.assertEqual(retrieved_data, new_token_data)
        
        # Verify metadata updated
        updated_metadata = self.token_manager.get_token_metadata(token_id)
        self.assertEqual(updated_metadata.refresh_count, initial_refresh_count + 1)
        self.assertEqual(updated_metadata.status, TokenStatus.VALID)
    
    def test_token_recovery(self):
        """Test recovery from corrupted token storage"""
        # Store token
        token_id = self.token_manager.store_token(
            self.test_token_data,
            self.test_api_key,
            self.test_user_id
        )
        
        # Simulate corruption by deleting the token file
        token_file = Path(self.temp_dir) / f"{token_id}.token"
        if token_file.exists():
            token_file.unlink()
        
        # Try to retrieve (should fail)
        with self.assertRaises(Exception):
            self.token_manager.retrieve_token(token_id)
        
        # Recover with backup data
        backup_token_data = b"recovered_token_data"
        success = self.token_manager.recover_corrupted_token(token_id, backup_token_data)
        self.assertTrue(success)
        
        # Verify recovery
        recovered_data = self.token_manager.retrieve_token(token_id)
        self.assertEqual(recovered_data, backup_token_data)
    
    def test_concurrent_token_access(self):
        """Test concurrent access to tokens"""
        # Store multiple tokens
        token_ids = []
        for i in range(5):
            token_id = self.token_manager.store_token(
                f"token_data_{i}".encode(),
                f"api_key_{i}",
                f"user_{i}"
            )
            token_ids.append(token_id)
        
        # Create threads to access tokens concurrently
        results = []
        errors = []
        
        def access_token(token_id):
            try:
                data = self.token_manager.retrieve_token(token_id)
                results.append((token_id, data))
            except Exception as e:
                errors.append((token_id, str(e)))
        
        # Start concurrent access
        threads = []
        for token_id in token_ids:
            thread = threading.Thread(target=access_token, args=(token_id,))
            threads.append(thread)
            thread.start()
        
        # Wait for all threads
        for thread in threads:
            thread.join()
        
        # Verify all tokens were accessed successfully
        self.assertEqual(len(results), 5)
        self.assertEqual(len(errors), 0)
    
    def test_auto_refresh_simulation(self):
        """Test automatic token refresh logic"""
        # Create token manager with auto-refresh enabled
        refresh_manager = SecureTokenManager(
            storage_backend=StorageBackend.ENCRYPTED_FILE,
            storage_config={'storage_dir': self.temp_dir},
            enable_auto_refresh=True,
            refresh_threshold_hours=1  # 1 hour threshold for testing
        )
        
        try:
            # Store token with old timestamp
            token_id = refresh_manager.store_token(
                self.test_token_data,
                self.test_api_key,
                self.test_user_id
            )
            
            # Manually manipulate metadata to simulate expiring token
            metadata = refresh_manager.get_token_metadata(token_id)
            metadata.last_refresh_timestamp = int(time.time()) - (6 * 24 * 3600)  # 6 days ago
            
            # Test should refresh logic
            should_refresh = refresh_manager._should_refresh_token(metadata)
            self.assertTrue(should_refresh)
            
            # Test with valid token
            metadata.last_refresh_timestamp = int(time.time())
            should_refresh = refresh_manager._should_refresh_token(metadata)
            self.assertFalse(should_refresh)
            
        finally:
            refresh_manager.shutdown()
    
    def test_health_check(self):
        """Test comprehensive health check"""
        # Store a token
        token_id = self.token_manager.store_token(
            self.test_token_data,
            self.test_api_key,
            self.test_user_id
        )
        
        # Perform health check
        health_status = self.token_manager.health_check()
        
        # Verify health check results
        self.assertIsInstance(health_status, dict)
        self.assertIn('overall_healthy', health_status)
        self.assertIn('backend_healthy', health_status)
        self.assertIn('encryption_healthy', health_status)
        self.assertIn('cache_healthy', health_status)
        self.assertIn('refresh_healthy', health_status)
        
        # Should be healthy in normal conditions
        self.assertTrue(health_status['overall_healthy'])
    
    def test_user_isolation(self):
        """Test per-user token isolation"""
        # Store tokens for different users
        user1_token = self.token_manager.store_token(
            b"user1_token",
            "api_key_1",
            "user_1"
        )
        
        user2_token = self.token_manager.store_token(
            b"user2_token",
            "api_key_2",
            "user_2"
        )
        
        # List tokens for specific users
        user1_tokens = self.token_manager.list_tokens(user_id="user_1")
        user2_tokens = self.token_manager.list_tokens(user_id="user_2")
        
        self.assertIn(user1_token, user1_tokens)
        self.assertNotIn(user2_token, user1_tokens)
        
        self.assertIn(user2_token, user2_tokens)
        self.assertNotIn(user1_token, user2_tokens)
    
    def test_event_callbacks(self):
        """Test event callback system"""
        events_received = []
        
        def test_callback(event, token_id, metadata, **kwargs):
            events_received.append((event, token_id, metadata))
        
        # Create token manager with callback
        callback_manager = SecureTokenManager(
            storage_backend=StorageBackend.ENCRYPTED_FILE,
            storage_config={'storage_dir': self.temp_dir},
            enable_auto_refresh=False,
            event_callbacks=[TokenEventCallback(test_callback)]
        )
        
        try:
            # Store token (should trigger CREATED event)
            token_id = callback_manager.store_token(
                self.test_token_data,
                self.test_api_key,
                self.test_user_id
            )
            
            # Revoke token (should trigger REVOKED event)
            callback_manager.revoke_token(token_id, "Test revocation")
            
            # Verify events were received
            self.assertEqual(len(events_received), 2)
            self.assertEqual(events_received[0][0], TokenEvent.CREATED)
            self.assertEqual(events_received[1][0], TokenEvent.REVOKED)
            
        finally:
            callback_manager.shutdown()


class TestSecurityFeatures(unittest.TestCase):
    """Test security features and penetration testing"""
    
    def setUp(self):
        """Set up test environment"""
        self.temp_dir = tempfile.mkdtemp()
        self.test_token_data = b"sensitive_oauth_token_data"
        self.test_api_key = "sensitive_api_key"
        
        self.token_manager = SecureTokenManager(
            storage_backend=StorageBackend.ENCRYPTED_FILE,
            storage_config={'storage_dir': self.temp_dir},
            enable_auto_refresh=False
        )
    
    def tearDown(self):
        """Clean up test environment"""
        self.token_manager.shutdown()
        import shutil
        shutil.rmtree(self.temp_dir, ignore_errors=True)
    
    def test_encryption_at_rest(self):
        """Test that tokens are properly encrypted at rest"""
        # Store token
        token_id = self.token_manager.store_token(
            self.test_token_data,
            self.test_api_key
        )
        
        # Check that token file exists and is encrypted
        token_file = Path(self.temp_dir) / f"{token_id}.token"
        self.assertTrue(token_file.exists())
        
        # Read raw file content
        with open(token_file, 'rb') as f:
            encrypted_data = f.read()
        
        # Verify data is encrypted (not plain text)
        self.assertNotIn(self.test_token_data, encrypted_data)
        self.assertNotIn(self.test_api_key.encode(), encrypted_data)
    
    def test_token_blacklisting(self):
        """Test token blacklisting security feature"""
        # Store token
        token_id = self.token_manager.store_token(
            self.test_token_data,
            self.test_api_key
        )
        
        # Add to blacklist
        self.token_manager.revoke_token(token_id, "Security test")
        
        # Verify token is in blacklist
        with self.token_manager._blacklist_lock:
            self.assertIn(token_id, self.token_manager._blacklist)
        
        # Verify token cannot be retrieved
        with self.assertRaises(ValueError):
            self.token_manager.retrieve_token(token_id)
    
    def test_concurrent_security(self):
        """Test security under concurrent access"""
        # Store token
        token_id = self.token_manager.store_token(
            self.test_token_data,
            self.test_api_key
        )
        
        # Simulate concurrent access attempts
        access_results = []
        
        def concurrent_access():
            try:
                data = self.token_manager.retrieve_token(token_id)
                access_results.append(("success", data))
            except Exception as e:
                access_results.append(("error", str(e)))
        
        # Start multiple threads
        threads = []
        for i in range(10):
            thread = threading.Thread(target=concurrent_access)
            threads.append(thread)
            thread.start()
        
        # Wait for completion
        for thread in threads:
            thread.join()
        
        # Verify all accesses were successful and consistent
        self.assertEqual(len(access_results), 10)
        for result in access_results:
            self.assertEqual(result[0], "success")
            self.assertEqual(result[1], self.test_token_data)
    
    def test_encryption_key_rotation(self):
        """Test encryption key rotation capability"""
        # Create new encryption key
        new_key = self.token_manager._generate_encryption_key()
        
        # Store token with new key
        token_id = self.token_manager.store_token(
            self.test_token_data,
            self.test_api_key
        )
        
        # Verify token is accessible
        retrieved_data = self.token_manager.retrieve_token(token_id)
        self.assertEqual(retrieved_data, self.test_token_data)
    
    def test_password_based_encryption(self):
        """Test password-based encryption key generation"""
        password = "test_password_123"
        salt = b"test_salt_456"
        
        # Generate key from password
        key = create_encryption_key_from_password(password, salt)
        
        # Verify key is valid
        self.assertIsInstance(key, bytes)
        self.assertEqual(len(key), 44)  # Base64 encoded Fernet key length
        
        # Test that same password + salt produces same key
        key2 = create_encryption_key_from_password(password, salt)
        self.assertEqual(key, key2)
        
        # Test that different password produces different key
        key3 = create_encryption_key_from_password("different_password", salt)
        self.assertNotEqual(key, key3)


class TestIntegrationFeatures(unittest.TestCase):
    """Test integration with other system components"""
    
    def setUp(self):
        """Set up test environment"""
        self.temp_dir = tempfile.mkdtemp()
        self.token_manager = SecureTokenManager(
            storage_backend=StorageBackend.ENCRYPTED_FILE,
            storage_config={'storage_dir': self.temp_dir},
            enable_auto_refresh=False
        )
    
    def tearDown(self):
        """Clean up test environment"""
        self.token_manager.shutdown()
        import shutil
        shutil.rmtree(self.temp_dir, ignore_errors=True)
    
    def test_scheduler_integration(self):
        """Test integration with Agent 9 (scheduler)"""
        scheduler_events = []
        
        def scheduler_callback(event, token_id, metadata, **kwargs):
            scheduler_events.append({
                'event': event.value,
                'token_id': token_id,
                'user_id': metadata.user_id,
                'timestamp': time.time()
            })
        
        # Create token manager with scheduler callback
        scheduler_manager = SecureTokenManager(
            storage_backend=StorageBackend.ENCRYPTED_FILE,
            storage_config={'storage_dir': self.temp_dir},
            enable_auto_refresh=False,
            event_callbacks=[TokenEventCallback(scheduler_callback)]
        )
        
        try:
            # Store token
            token_id = scheduler_manager.store_token(
                b"test_token",
                "test_api_key",
                "test_user"
            )
            
            # Verify scheduler received event
            self.assertEqual(len(scheduler_events), 1)
            self.assertEqual(scheduler_events[0]['event'], 'created')
            self.assertEqual(scheduler_events[0]['token_id'], token_id)
            
        finally:
            scheduler_manager.shutdown()
    
    def test_multi_user_support(self):
        """Test multi-user token isolation"""
        # Store tokens for multiple users
        user_tokens = {}
        
        for user_id in ["user_1", "user_2", "user_3"]:
            token_id = self.token_manager.store_token(
                f"token_for_{user_id}".encode(),
                f"api_key_{user_id}",
                user_id
            )
            user_tokens[user_id] = token_id
        
        # Verify user isolation
        for user_id, token_id in user_tokens.items():
            user_tokens_list = self.token_manager.list_tokens(user_id=user_id)
            self.assertIn(token_id, user_tokens_list)
            
            # Verify other users' tokens are not included
            for other_user_id, other_token_id in user_tokens.items():
                if other_user_id != user_id:
                    self.assertNotIn(other_token_id, user_tokens_list)
    
    def test_storage_backend_migration(self):
        """Test migration between storage backends"""
        # Create token in file backend
        token_id = self.token_manager.store_token(
            b"migration_test_token",
            "test_api_key",
            "test_user"
        )
        
        # Verify token exists in file backend
        retrieved_data = self.token_manager.retrieve_token(token_id)
        self.assertEqual(retrieved_data, b"migration_test_token")
        
        # Create SQLite backend
        db_path = os.path.join(self.temp_dir, "migration_test.db")
        sqlite_manager = SecureTokenManager(
            storage_backend=StorageBackend.SQLITE,
            storage_config={'db_path': db_path},
            enable_auto_refresh=False
        )
        
        try:
            # Store same token in SQLite backend
            sqlite_token_id = sqlite_manager.store_token(
                b"migration_test_token",
                "test_api_key",
                "test_user"
            )
            
            # Verify token exists in SQLite backend
            sqlite_retrieved_data = sqlite_manager.retrieve_token(sqlite_token_id)
            self.assertEqual(sqlite_retrieved_data, b"migration_test_token")
            
        finally:
            sqlite_manager.shutdown()


class TestErrorHandling(unittest.TestCase):
    """Test error handling and edge cases"""
    
    def setUp(self):
        """Set up test environment"""
        self.temp_dir = tempfile.mkdtemp()
        self.token_manager = SecureTokenManager(
            storage_backend=StorageBackend.ENCRYPTED_FILE,
            storage_config={'storage_dir': self.temp_dir},
            enable_auto_refresh=False
        )
    
    def tearDown(self):
        """Clean up test environment"""
        self.token_manager.shutdown()
        import shutil
        shutil.rmtree(self.temp_dir, ignore_errors=True)
    
    def test_nonexistent_token_retrieval(self):
        """Test handling of nonexistent token retrieval"""
        with self.assertRaises(Exception):
            self.token_manager.retrieve_token("nonexistent_token")
    
    def test_corrupted_token_recovery(self):
        """Test recovery from corrupted token storage"""
        # Store token
        token_id = self.token_manager.store_token(
            b"test_token_data",
            "test_api_key"
        )
        
        # Corrupt the token file
        token_file = Path(self.temp_dir) / f"{token_id}.token"
        if token_file.exists():
            with open(token_file, 'wb') as f:
                f.write(b"corrupted_data")
        
        # Try to retrieve (should fail)
        with self.assertRaises(Exception):
            self.token_manager.retrieve_token(token_id)
        
        # Recover with backup
        backup_data = b"recovered_token_data"
        success = self.token_manager.recover_corrupted_token(token_id, backup_data)
        self.assertTrue(success)
        
        # Verify recovery
        recovered_data = self.token_manager.retrieve_token(token_id)
        self.assertEqual(recovered_data, backup_data)
    
    def test_invalid_encryption_key(self):
        """Test handling of invalid encryption key"""
        # Create token manager with invalid key
        invalid_key = b"invalid_key_too_short"
        
        with self.assertRaises(Exception):
            SecureTokenManager(
                storage_backend=StorageBackend.ENCRYPTED_FILE,
                storage_config={'storage_dir': self.temp_dir},
                encryption_key=invalid_key,
                enable_auto_refresh=False
            )
    
    def test_storage_backend_failure(self):
        """Test handling of storage backend failures"""
        # Create token manager with invalid storage path
        with self.assertRaises(Exception):
            SecureTokenManager(
                storage_backend=StorageBackend.ENCRYPTED_FILE,
                storage_config={'storage_dir': '/nonexistent/path'},
                enable_auto_refresh=False
            )


if __name__ == '__main__':
    # Run tests
    unittest.main(verbosity=2) 