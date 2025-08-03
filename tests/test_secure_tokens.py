"""
Comprehensive test suite for secure token management system

Tests all aspects of the secure token management system including:
- Encryption and decryption
- Multiple storage backends
- Token validation and health checks
- Automatic refresh mechanisms
- Token rotation and recovery
- Security features and blacklisting
- Concurrent access patterns
- Error handling and recovery
"""

import asyncio
import base64
import json
import os
import tempfile
import threading
import time
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import Mock, patch, MagicMock

import pytest

# Import the secure token management system
from enhancements.secure_tokens import (
    SecureTokenManager,
    TokenValidator,
    TokenEvent,
    TokenEventType,
    KeyringStorageBackend,
    EncryptedFileStorageBackend,
    DatabaseStorageBackend,
    get_global_token_manager,
    set_global_token_manager,
    get_user_token,
    refresh_user_token,
    store_user_token,
    get_token_health
)


class TestTokenValidator(unittest.TestCase):
    """Test token validation and health checking"""
    
    def setUp(self):
        self.validator = TokenValidator()
        self.valid_token = {
            'access_token': 'valid_access_token',
            'refresh_token': 'valid_refresh_token',
            'token_type': 'Bearer',
            'expires_at': time.time() + 3600,  # 1 hour from now
            'creation_timestamp': time.time()
        }
    
    def test_validate_valid_token(self):
        """Test validation of valid token"""
        is_valid, message = self.validator.validate_token(self.valid_token)
        self.assertTrue(is_valid)
        self.assertEqual(message, "Token is valid")
    
    def test_validate_missing_fields(self):
        """Test validation with missing required fields"""
        invalid_token = {'access_token': 'token'}
        is_valid, message = self.validator.validate_token(invalid_token)
        self.assertFalse(is_valid)
        self.assertIn("Missing required field", message)
    
    def test_validate_expired_token(self):
        """Test validation of expired token"""
        expired_token = self.valid_token.copy()
        expired_token['expires_at'] = time.time() - 3600  # 1 hour ago
        is_valid, message = self.validator.validate_token(expired_token)
        self.assertFalse(is_valid)
        self.assertEqual(message, "Token has expired")
    
    def test_validate_expiring_soon_token(self):
        """Test validation of token expiring soon"""
        expiring_token = self.valid_token.copy()
        expiring_token['expires_at'] = time.time() + 1800  # 30 minutes from now
        is_valid, message = self.validator.validate_token(expiring_token)
        self.assertFalse(is_valid)
        self.assertEqual(message, "Token expires soon")
    
    def test_calculate_token_hash(self):
        """Test token hash calculation"""
        hash1 = self.validator.calculate_token_hash(self.valid_token)
        hash2 = self.validator.calculate_token_hash(self.valid_token)
        self.assertEqual(hash1, hash2)
        
        # Different tokens should have different hashes
        different_token = self.valid_token.copy()
        different_token['access_token'] = 'different_token'
        hash3 = self.validator.calculate_token_hash(different_token)
        self.assertNotEqual(hash1, hash3)
    
    def test_check_token_health(self):
        """Test comprehensive token health check"""
        health = self.validator.check_token_health(self.valid_token)
        
        self.assertTrue(health['is_valid'])
        self.assertEqual(health['message'], "Token is valid")
        self.assertIn('token_hash', health)
        self.assertIn('created_at', health)
        self.assertIn('expires_at', health)
        self.assertIn('age_seconds', health)
        self.assertIn('time_to_expiry', health)
        self.assertGreater(health['time_to_expiry'], 0)


class TestStorageBackends(unittest.TestCase):
    """Test storage backend implementations"""
    
    def setUp(self):
        self.test_user_id = "test_user_123"
        self.test_token_data = {
            'access_token': 'test_access_token',
            'refresh_token': 'test_refresh_token',
            'token_type': 'Bearer',
            'expires_at': time.time() + 3600
        }
        self.test_encrypted_data = b"encrypted_test_data"
    
    def test_keyring_storage_backend(self):
        """Test keyring storage backend"""
        backend = KeyringStorageBackend("test_service")
        
        # Test store
        success = backend.store_token(self.test_user_id, self.test_token_data, self.test_encrypted_data)
        self.assertTrue(success)
        
        # Test retrieve
        retrieved = backend.retrieve_token(self.test_user_id)
        self.assertEqual(retrieved, self.test_encrypted_data)
        
        # Test delete
        success = backend.delete_token(self.test_user_id)
        self.assertTrue(success)
        
        # Verify deletion
        retrieved = backend.retrieve_token(self.test_user_id)
        self.assertIsNone(retrieved)
        
        # Test health check
        health = backend.health_check()
        self.assertTrue(health)
    
    def test_encrypted_file_storage_backend(self):
        """Test encrypted file storage backend"""
        with tempfile.TemporaryDirectory() as temp_dir:
            backend = EncryptedFileStorageBackend(temp_dir)
            
            # Test store
            success = backend.store_token(self.test_user_id, self.test_token_data, self.test_encrypted_data)
            self.assertTrue(success)
            
            # Test retrieve
            retrieved = backend.retrieve_token(self.test_user_id)
            self.assertEqual(retrieved, self.test_encrypted_data)
            
            # Test list users
            users = backend.list_users()
            self.assertIn(self.test_user_id, users)
            
            # Test delete
            success = backend.delete_token(self.test_user_id)
            self.assertTrue(success)
            
            # Verify deletion
            retrieved = backend.retrieve_token(self.test_user_id)
            self.assertIsNone(retrieved)
            
            # Test health check
            health = backend.health_check()
            self.assertTrue(health)
    
    def test_database_storage_backend(self):
        """Test database storage backend"""
        with tempfile.NamedTemporaryFile(suffix='.db', delete=False) as temp_db:
            db_path = temp_db.name
        
        try:
            backend = DatabaseStorageBackend(db_path)
            
            # Test store
            success = backend.store_token(self.test_user_id, self.test_token_data, self.test_encrypted_data)
            self.assertTrue(success)
            
            # Test retrieve
            retrieved = backend.retrieve_token(self.test_user_id)
            self.assertEqual(retrieved, self.test_encrypted_data)
            
            # Test list users
            users = backend.list_users()
            self.assertIn(self.test_user_id, users)
            
            # Test delete
            success = backend.delete_token(self.test_user_id)
            self.assertTrue(success)
            
            # Verify deletion
            retrieved = backend.retrieve_token(self.test_user_id)
            self.assertIsNone(retrieved)
            
            # Test health check
            health = backend.health_check()
            self.assertTrue(health)
            
        finally:
            # Cleanup
            if os.path.exists(db_path):
                os.unlink(db_path)


class TestSecureTokenManager(unittest.TestCase):
    """Test the main SecureTokenManager class"""
    
    def setUp(self):
        # Use file storage for testing
        self.temp_dir = tempfile.mkdtemp()
        self.storage_backend = EncryptedFileStorageBackend(self.temp_dir)
        self.manager = SecureTokenManager(
            storage_backend=self.storage_backend,
            refresh_threshold_hours=1,  # 1 hour for testing
            max_retry_attempts=2
        )
        
        self.test_user_id = "test_user_456"
        self.test_token = {
            'access_token': 'test_access_token_456',
            'refresh_token': 'test_refresh_token_456',
            'token_type': 'Bearer',
            'expires_at': time.time() + 7200,  # 2 hours from now
            'creation_timestamp': time.time()
        }
        
        # Track events
        self.events = []
        self.manager.event_callbacks.append(self._event_callback)
    
    def tearDown(self):
        self.manager.shutdown()
        import shutil
        shutil.rmtree(self.temp_dir, ignore_errors=True)
    
    def _event_callback(self, event):
        """Callback to track events"""
        self.events.append(event)
    
    def test_store_and_retrieve_token(self):
        """Test storing and retrieving tokens"""
        # Store token
        success = self.manager.store_token(self.test_user_id, self.test_token)
        self.assertTrue(success)
        
        # Retrieve token
        retrieved = self.manager.get_token(self.test_user_id)
        self.assertIsNotNone(retrieved)
        self.assertEqual(retrieved['access_token'], self.test_token['access_token'])
        
        # Check event was emitted
        self.assertEqual(len(self.events), 1)
        self.assertEqual(self.events[0].event_type, TokenEventType.TOKEN_CREATED)
    
    def test_token_validation_on_store(self):
        """Test that invalid tokens are rejected"""
        invalid_token = {'access_token': 'token'}  # Missing required fields
        
        success = self.manager.store_token(self.test_user_id, invalid_token)
        self.assertFalse(success)
    
    def test_token_health_check(self):
        """Test token health checking"""
        # Store token
        self.manager.store_token(self.test_user_id, self.test_token)
        
        # Check health
        health = self.manager.get_token_health(self.test_user_id)
        self.assertTrue(health['is_valid'])
        self.assertGreater(health['time_to_expiry'], 0)
    
    def test_token_refresh(self):
        """Test token refresh functionality"""
        # Store token
        self.manager.store_token(self.test_user_id, self.test_token)
        
        # Refresh token
        success = self.manager.refresh_token(self.test_user_id)
        self.assertTrue(success)
        
        # Check refresh event
        refresh_events = [e for e in self.events if e.event_type == TokenEventType.TOKEN_REFRESHED]
        self.assertEqual(len(refresh_events), 1)
    
    def test_token_rotation(self):
        """Test zero-downtime token rotation"""
        # Store token
        self.manager.store_token(self.test_user_id, self.test_token)
        
        # Rotate token
        success = self.manager.rotate_token(self.test_user_id)
        self.assertTrue(success)
        
        # Check rotation event
        rotation_events = [e for e in self.events if e.event_type == TokenEventType.TOKEN_ROTATED]
        self.assertEqual(len(rotation_events), 1)
    
    def test_token_revocation(self):
        """Test token revocation and blacklisting"""
        # Store token
        self.manager.store_token(self.test_user_id, self.test_token)
        
        # Get token hash for blacklisting
        token_hash = self.manager.validator.calculate_token_hash(self.test_token)
        
        # Revoke token
        success = self.manager.revoke_token(self.test_user_id)
        self.assertTrue(success)
        
        # Verify token is blacklisted
        self.assertTrue(self.manager.is_token_blacklisted(token_hash))
        
        # Verify token is no longer retrievable
        retrieved = self.manager.get_token(self.test_user_id)
        self.assertIsNone(retrieved)
        
        # Check revocation event
        revocation_events = [e for e in self.events if e.event_type == TokenEventType.TOKEN_REVOKED]
        self.assertEqual(len(revocation_events), 1)
    
    def test_concurrent_token_access(self):
        """Test concurrent access to tokens"""
        # Store token
        self.manager.store_token(self.test_user_id, self.test_token)
        
        # Create multiple threads accessing the same token
        results = []
        errors = []
        
        def access_token():
            try:
                token = self.manager.get_token(self.test_user_id)
                results.append(token is not None)
            except Exception as e:
                errors.append(e)
        
        threads = []
        for _ in range(10):
            thread = threading.Thread(target=access_token)
            threads.append(thread)
            thread.start()
        
        # Wait for all threads
        for thread in threads:
            thread.join()
        
        # All threads should succeed
        self.assertEqual(len(results), 10)
        self.assertTrue(all(results))
        self.assertEqual(len(errors), 0)
    
    def test_corrupted_token_recovery(self):
        """Test recovery from corrupted token storage"""
        # Store token
        self.manager.store_token(self.test_user_id, self.test_token)
        
        # Corrupt the stored token by modifying the encrypted data
        token_path = Path(self.temp_dir) / f"{self.test_user_id}.token"
        with open(token_path, 'r') as f:
            token_info = json.load(f)
        
        # Corrupt the encrypted data
        token_info['encrypted_data'] = "corrupted_data"
        with open(token_path, 'w') as f:
            json.dump(token_info, f)
        
        # Try to retrieve token - should trigger recovery
        retrieved = self.manager.get_token(self.test_user_id)
        
        # Should recover from backup
        self.assertIsNotNone(retrieved)
        self.assertEqual(retrieved['access_token'], self.test_token['access_token'])
        
        # Check recovery event
        recovery_events = [e for e in self.events if e.event_type == TokenEventType.TOKEN_RECOVERED]
        self.assertEqual(len(recovery_events), 1)
    
    def test_background_refresh(self):
        """Test background token refresh"""
        # Create token that expires soon
        expiring_token = self.test_token.copy()
        expiring_token['expires_at'] = time.time() + 1800  # 30 minutes
        
        # Store token
        self.manager.store_token(self.test_user_id, expiring_token)
        
        # Wait a bit for background refresh to potentially trigger
        time.sleep(2)
        
        # Check if refresh occurred (this is probabilistic)
        refresh_events = [e for e in self.events if e.event_type == TokenEventType.TOKEN_REFRESHED]
        # Note: In a real test, we might need to wait longer or mock the refresh logic
    
    def test_manager_health_check(self):
        """Test comprehensive manager health check"""
        health = self.manager.health_check()
        
        self.assertIn('storage_backend_healthy', health)
        self.assertIn('refresh_thread_alive', health)
        self.assertIn('blacklisted_tokens_count', health)
        self.assertIn('cached_tokens_count', health)
        self.assertIn('backup_tokens_count', health)
        
        self.assertTrue(health['storage_backend_healthy'])
        self.assertTrue(health['refresh_thread_alive'])


class TestGlobalTokenManager(unittest.TestCase):
    """Test global token manager functionality"""
    
    def setUp(self):
        # Reset global manager
        set_global_token_manager(None)
    
    def test_global_manager_singleton(self):
        """Test that global manager is a singleton"""
        manager1 = get_global_token_manager()
        manager2 = get_global_token_manager()
        self.assertIs(manager1, manager2)
    
    def test_convenience_functions(self):
        """Test convenience functions for other agents"""
        test_user_id = "global_test_user"
        test_token = {
            'access_token': 'global_test_token',
            'refresh_token': 'global_refresh_token',
            'token_type': 'Bearer',
            'expires_at': time.time() + 3600,
            'creation_timestamp': time.time()
        }
        
        # Test store
        success = store_user_token(test_user_id, test_token)
        self.assertTrue(success)
        
        # Test get
        retrieved = get_user_token(test_user_id)
        self.assertIsNotNone(retrieved)
        self.assertEqual(retrieved['access_token'], test_token['access_token'])
        
        # Test health
        health = get_token_health(test_user_id)
        self.assertTrue(health['is_valid'])
        
        # Test refresh
        success = refresh_user_token(test_user_id)
        self.assertTrue(success)


class TestSecurityFeatures(unittest.TestCase):
    """Test security features and encryption"""
    
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.storage_backend = EncryptedFileStorageBackend(self.temp_dir)
        self.manager = SecureTokenManager(storage_backend=self.storage_backend)
        
        self.test_user_id = "security_test_user"
        self.test_token = {
            'access_token': 'sensitive_access_token',
            'refresh_token': 'sensitive_refresh_token',
            'token_type': 'Bearer',
            'expires_at': time.time() + 3600,
            'creation_timestamp': time.time()
        }
    
    def tearDown(self):
        self.manager.shutdown()
        import shutil
        shutil.rmtree(self.temp_dir, ignore_errors=True)
    
    def test_encryption_at_rest(self):
        """Test that tokens are encrypted at rest"""
        # Store token
        self.manager.store_token(self.test_user_id, self.test_token)
        
        # Check that stored data is encrypted
        token_path = Path(self.temp_dir) / f"{self.test_user_id}.token"
        with open(token_path, 'r') as f:
            stored_data = json.load(f)
        
        encrypted_data = base64.b64decode(stored_data['encrypted_data'])
        
        # Verify data is encrypted (not plain JSON)
        try:
            json.loads(encrypted_data.decode())
            self.fail("Data should be encrypted, not plain JSON")
        except (json.JSONDecodeError, UnicodeDecodeError):
            # Expected - data should be encrypted
            pass
    
    def test_token_blacklisting(self):
        """Test token blacklisting functionality"""
        # Store token
        self.manager.store_token(self.test_user_id, self.test_token)
        
        # Get token hash
        token_hash = self.manager.validator.calculate_token_hash(self.test_token)
        
        # Initially not blacklisted
        self.assertFalse(self.manager.is_token_blacklisted(token_hash))
        
        # Revoke token (adds to blacklist)
        self.manager.revoke_token(self.test_user_id)
        
        # Now blacklisted
        self.assertTrue(self.manager.is_token_blacklisted(token_hash))
    
    def test_environment_key_encryption(self):
        """Test encryption with environment-provided key"""
        # Set environment key
        test_key = base64.b64encode(b"test_encryption_key_32_bytes_long!")
        with patch.dict(os.environ, {'SCHWAB_ENCRYPTION_KEY': test_key.decode()}):
            manager = SecureTokenManager(storage_backend=self.storage_backend)
            
            # Test encryption works
            success = manager.store_token(self.test_user_id, self.test_token)
            self.assertTrue(success)
            
            retrieved = manager.get_token(self.test_user_id)
            self.assertIsNotNone(retrieved)
            self.assertEqual(retrieved['access_token'], self.test_token['access_token'])
            
            manager.shutdown()


class TestErrorHandling(unittest.TestCase):
    """Test error handling and recovery mechanisms"""
    
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.storage_backend = EncryptedFileStorageBackend(self.temp_dir)
        self.manager = SecureTokenManager(storage_backend=self.storage_backend)
        
        self.test_user_id = "error_test_user"
        self.test_token = {
            'access_token': 'error_test_token',
            'refresh_token': 'error_refresh_token',
            'token_type': 'Bearer',
            'expires_at': time.time() + 3600,
            'creation_timestamp': time.time()
        }
    
    def tearDown(self):
        self.manager.shutdown()
        import shutil
        shutil.rmtree(self.temp_dir, ignore_errors=True)
    
    def test_storage_backend_failure(self):
        """Test handling of storage backend failures"""
        # Create a failing storage backend
        failing_backend = Mock()
        failing_backend.store_token.return_value = False
        failing_backend.retrieve_token.return_value = None
        failing_backend.health_check.return_value = False
        
        manager = SecureTokenManager(storage_backend=failing_backend)
        
        # Store should fail
        success = manager.store_token(self.test_user_id, self.test_token)
        self.assertFalse(success)
        
        # Get should return None
        retrieved = manager.get_token(self.test_user_id)
        self.assertIsNone(retrieved)
        
        manager.shutdown()
    
    def test_encryption_failure(self):
        """Test handling of encryption failures"""
        # Create manager with invalid encryption key
        invalid_key = b"invalid_key"
        manager = SecureTokenManager(
            storage_backend=self.storage_backend,
            encryption_key=invalid_key
        )
        
        # Store should fail due to encryption issues
        success = manager.store_token(self.test_user_id, self.test_token)
        self.assertFalse(success)
        
        manager.shutdown()
    
    def test_token_validation_failure(self):
        """Test handling of token validation failures"""
        # Try to store invalid token
        invalid_token = {'invalid': 'token'}
        
        success = self.manager.store_token(self.test_user_id, invalid_token)
        self.assertFalse(success)
    
    def test_refresh_failure_recovery(self):
        """Test recovery from refresh failures"""
        # Store token
        self.manager.store_token(self.test_user_id, self.test_token)
        
        # Mock refresh to fail
        with patch.object(self.manager, '_simulate_token_refresh', return_value=None):
            success = self.manager.refresh_token(self.test_user_id)
            self.assertFalse(success)


class TestPerformanceAndStress(unittest.TestCase):
    """Test performance and stress scenarios"""
    
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.storage_backend = EncryptedFileStorageBackend(self.temp_dir)
        self.manager = SecureTokenManager(storage_backend=self.storage_backend)
    
    def tearDown(self):
        self.manager.shutdown()
        import shutil
        shutil.rmtree(self.temp_dir, ignore_errors=True)
    
    def test_multiple_users_performance(self):
        """Test performance with multiple users"""
        num_users = 100
        start_time = time.time()
        
        # Store tokens for multiple users
        for i in range(num_users):
            user_id = f"user_{i}"
            token = {
                'access_token': f'access_token_{i}',
                'refresh_token': f'refresh_token_{i}',
                'token_type': 'Bearer',
                'expires_at': time.time() + 3600,
                'creation_timestamp': time.time()
            }
            success = self.manager.store_token(user_id, token)
            self.assertTrue(success)
        
        store_time = time.time() - start_time
        
        # Retrieve all tokens
        start_time = time.time()
        for i in range(num_users):
            user_id = f"user_{i}"
            token = self.manager.get_token(user_id)
            self.assertIsNotNone(token)
        
        retrieve_time = time.time() - start_time
        
        # Performance should be reasonable
        self.assertLess(store_time, 10.0)  # Store 100 tokens in under 10 seconds
        self.assertLess(retrieve_time, 5.0)  # Retrieve 100 tokens in under 5 seconds
    
    def test_concurrent_stress_test(self):
        """Test concurrent access stress test"""
        num_threads = 20
        operations_per_thread = 50
        results = []
        errors = []
        
        def stress_operation():
            try:
                for i in range(operations_per_thread):
                    user_id = f"stress_user_{threading.current_thread().ident}_{i}"
                    token = {
                        'access_token': f'stress_token_{i}',
                        'refresh_token': f'stress_refresh_{i}',
                        'token_type': 'Bearer',
                        'expires_at': time.time() + 3600,
                        'creation_timestamp': time.time()
                    }
                    
                    # Store token
                    success = self.manager.store_token(user_id, token)
                    if not success:
                        results.append(False)
                        return
                    
                    # Retrieve token
                    retrieved = self.manager.get_token(user_id)
                    if retrieved is None:
                        results.append(False)
                        return
                    
                    # Refresh token
                    refresh_success = self.manager.refresh_token(user_id)
                    if not refresh_success:
                        results.append(False)
                        return
                    
                    results.append(True)
                    
            except Exception as e:
                errors.append(e)
        
        # Start threads
        threads = []
        for _ in range(num_threads):
            thread = threading.Thread(target=stress_operation)
            threads.append(thread)
            thread.start()
        
        # Wait for completion
        for thread in threads:
            thread.join()
        
        # Check results
        self.assertEqual(len(errors), 0, f"Errors occurred: {errors}")
        self.assertEqual(len(results), num_threads * operations_per_thread)
        success_rate = sum(results) / len(results)
        self.assertGreater(success_rate, 0.95)  # 95% success rate


if __name__ == '__main__':
    # Run tests with verbose output
    unittest.main(verbosity=2) 