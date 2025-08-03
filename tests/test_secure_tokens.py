"""
Comprehensive test suite for secure token management system

Tests all aspects of the SecureTokenManager including:
- Token validation and health checking
- Multiple storage backends
- Security features and encryption
- Performance and stress testing
- Error handling and recovery
"""

import json
import os
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import pytest

from enhancements.secure_tokens import (
    DatabaseStorageBackend,
    EncryptedFileStorageBackend,
    KeyringStorageBackend,
    SecureTokenManager,
    TokenEvent,
    TokenEventType,
    TokenValidator,
    get_global_token_manager,
    get_token_health,
    get_user_token,
    refresh_user_token,
    set_global_token_manager,
    store_user_token,
)


class TestTokenValidator(unittest.TestCase):
    """Test token validation functionality"""
    
    def setUp(self):
        self.validator = TokenValidator()
    
    def test_validate_token_valid(self):
        """Test validation of valid token"""
        token_data = {
            'access_token': 'test_access_token',
            'refresh_token': 'test_refresh_token',
            'token_type': 'Bearer',
            'expires_at': time.time() + 7200,  # 2 hours from now
            'creation_timestamp': time.time()
        }
        
        is_valid, message = self.validator.validate_token(token_data)
        self.assertTrue(is_valid)
        self.assertEqual(message, "Token is valid")
    
    def test_validate_token_missing_fields(self):
        """Test validation with missing required fields"""
        token_data = {
            'access_token': 'test_access_token',
            # Missing refresh_token and token_type
            'expires_at': time.time() + 7200
        }
        
        is_valid, message = self.validator.validate_token(token_data)
        self.assertFalse(is_valid)
        self.assertIn("Missing required field", message)
    
    def test_validate_token_expired(self):
        """Test validation of expired token"""
        token_data = {
            'access_token': 'test_access_token',
            'refresh_token': 'test_refresh_token',
            'token_type': 'Bearer',
            'expires_at': time.time() - 3600,  # 1 hour ago
            'creation_timestamp': time.time() - 7200
        }
        
        is_valid, message = self.validator.validate_token(token_data)
        self.assertFalse(is_valid)
        self.assertEqual(message, "Token has expired")
    
    def test_validate_token_expiring_soon(self):
        """Test validation of token expiring soon"""
        token_data = {
            'access_token': 'test_access_token',
            'refresh_token': 'test_refresh_token',
            'token_type': 'Bearer',
            'expires_at': time.time() + 1800,  # 30 minutes from now
            'creation_timestamp': time.time()
        }
        
        is_valid, message = self.validator.validate_token(token_data)
        self.assertFalse(is_valid)
        self.assertEqual(message, "Token expires soon")
    
    def test_calculate_token_hash(self):
        """Test token hash calculation"""
        token_data = {
            'access_token': 'test_access_token',
            'refresh_token': 'test_refresh_token',
            'token_type': 'Bearer'
        }
        
        hash1 = self.validator.calculate_token_hash(token_data)
        hash2 = self.validator.calculate_token_hash(token_data)
        
        # Same token should produce same hash
        self.assertEqual(hash1, hash2)
        
        # Different token should produce different hash
        token_data2 = token_data.copy()
        token_data2['access_token'] = 'different_token'
        hash3 = self.validator.calculate_token_hash(token_data2)
        
        self.assertNotEqual(hash1, hash3)
    
    def test_check_token_health(self):
        """Test comprehensive token health check"""
        token_data = {
            'access_token': 'test_access_token',
            'refresh_token': 'test_refresh_token',
            'token_type': 'Bearer',
            'expires_at': time.time() + 7200,
            'creation_timestamp': time.time()
        }
        
        health = self.validator.check_token_health(token_data)
        
        self.assertTrue(health['is_valid'])
        self.assertEqual(health['message'], "Token is valid")
        self.assertIn('token_hash', health)
        self.assertIn('created_at', health)
        self.assertIn('expires_at', health)
        self.assertIn('age_seconds', health)
        self.assertIn('time_to_expiry', health)


class TestStorageBackends(unittest.TestCase):
    """Test storage backend implementations"""
    
    def test_keyring_storage_backend(self):
        """Test keyring storage backend"""
        backend = KeyringStorageBackend("test_service")
        
        # Test health check
        self.assertTrue(backend.health_check())
        
        # Test store and retrieve
        user_id = "test_user"
        token_data = {'test': 'data'}
        encrypted_data = b"encrypted_test_data"
        
        # Store token
        success = backend.store_token(user_id, token_data, encrypted_data)
        self.assertTrue(success)
        
        # Retrieve token
        retrieved = backend.retrieve_token(user_id)
        self.assertEqual(retrieved, encrypted_data)
        
        # Delete token
        success = backend.delete_token(user_id)
        self.assertTrue(success)
        
        # Verify deletion
        retrieved = backend.retrieve_token(user_id)
        self.assertIsNone(retrieved)
    
    def test_encrypted_file_storage_backend(self):
        """Test encrypted file storage backend"""
        with tempfile.TemporaryDirectory() as temp_dir:
            backend = EncryptedFileStorageBackend(temp_dir)
            
            # Test health check
            self.assertTrue(backend.health_check())
            
            # Test store and retrieve
            user_id = "test_user"
            token_data = {'test': 'data'}
            encrypted_data = b"encrypted_test_data"
            
            # Store token
            success = backend.store_token(user_id, token_data, encrypted_data)
            self.assertTrue(success)
            
            # Verify file was created
            token_file = Path(temp_dir) / f"{user_id}.token"
            self.assertTrue(token_file.exists())
            
            # Retrieve token
            retrieved = backend.retrieve_token(user_id)
            self.assertEqual(retrieved, encrypted_data)
            
            # Test list users
            users = backend.list_users()
            self.assertIn(user_id, users)
            
            # Delete token
            success = backend.delete_token(user_id)
            self.assertTrue(success)
            
            # Verify deletion
            retrieved = backend.retrieve_token(user_id)
            self.assertIsNone(retrieved)
    
    def test_database_storage_backend(self):
        """Test database storage backend"""
        with tempfile.NamedTemporaryFile(suffix='.db', delete=False) as temp_file:
            db_path = temp_file.name
        
        try:
            backend = DatabaseStorageBackend(db_path)
            
            # Test health check
            self.assertTrue(backend.health_check())
            
            # Test store and retrieve
            user_id = "test_user"
            token_data = {'test': 'data', 'expires_at': time.time() + 3600}
            encrypted_data = b"encrypted_test_data"
            
            # Store token
            success = backend.store_token(user_id, token_data, encrypted_data)
            self.assertTrue(success)
            
            # Retrieve token
            retrieved = backend.retrieve_token(user_id)
            self.assertEqual(retrieved, encrypted_data)
            
            # Test list users
            users = backend.list_users()
            self.assertIn(user_id, users)
            
            # Delete token
            success = backend.delete_token(user_id)
            self.assertTrue(success)
            
            # Verify deletion
            retrieved = backend.retrieve_token(user_id)
            self.assertIsNone(retrieved)
            
        finally:
            # Clean up
            if os.path.exists(db_path):
                os.unlink(db_path)


class TestSecureTokenManager(unittest.TestCase):
    """Test SecureTokenManager functionality"""
    
    def setUp(self):
        # Use temporary directory for file storage
        self.temp_dir = tempfile.mkdtemp()
        self.storage_backend = EncryptedFileStorageBackend(self.temp_dir)
        self.manager = SecureTokenManager(
            storage_backend=self.storage_backend,
            refresh_threshold_hours=1  # Use 1 hour for testing
        )
    
    def tearDown(self):
        self.manager.shutdown()
        # Clean up temporary directory
        import shutil
        shutil.rmtree(self.temp_dir, ignore_errors=True)
    
    def test_store_and_retrieve_token(self):
        """Test basic token storage and retrieval"""
        user_id = "test_user"
        token_data = {
            'access_token': 'test_access_token',
            'refresh_token': 'test_refresh_token',
            'token_type': 'Bearer',
            'expires_at': time.time() + 7200,  # 2 hours from now
            'creation_timestamp': time.time()
        }
        
        # Store token
        success = self.manager.store_token(user_id, token_data)
        self.assertTrue(success)
        
        # Retrieve token
        retrieved = self.manager.get_token(user_id)
        self.assertIsNotNone(retrieved)
        self.assertEqual(retrieved['access_token'], token_data['access_token'])
        self.assertEqual(retrieved['refresh_token'], token_data['refresh_token'])
    
    def test_token_validation_on_store(self):
        """Test that invalid tokens are rejected on store"""
        user_id = "test_user"
        invalid_token = {
            'access_token': 'test_access_token',
            # Missing required fields
            'expires_at': time.time() + 7200
        }
        
        # Attempt to store invalid token
        success = self.manager.store_token(user_id, invalid_token)
        self.assertFalse(success)
        
        # Verify token was not stored
        retrieved = self.manager.get_token(user_id)
        self.assertIsNone(retrieved)
    
    def test_token_health_check(self):
        """Test token health checking"""
        user_id = "test_user"
        token_data = {
            'access_token': 'test_access_token',
            'refresh_token': 'test_refresh_token',
            'token_type': 'Bearer',
            'expires_at': time.time() + 7200,
            'creation_timestamp': time.time()
        }
        
        # Store token
        self.manager.store_token(user_id, token_data)
        
        # Check health
        health = self.manager.get_token_health(user_id)
        self.assertTrue(health['is_valid'])
        self.assertEqual(health['message'], "Token is valid")
    
    def test_token_refresh(self):
        """Test token refresh functionality"""
        user_id = "test_user"
        token_data = {
            'access_token': 'test_access_token',
            'refresh_token': 'test_refresh_token',
            'token_type': 'Bearer',
            'expires_at': time.time() + 7200,
            'creation_timestamp': time.time()
        }
        
        # Store token
        self.manager.store_token(user_id, token_data)
        
        # Refresh token
        success = self.manager.refresh_token(user_id)
        self.assertTrue(success)
        
        # Verify token was refreshed
        refreshed = self.manager.get_token(user_id)
        self.assertIsNotNone(refreshed)
        self.assertNotEqual(refreshed['access_token'], token_data['access_token'])
    
    def test_token_rotation(self):
        """Test token rotation with zero downtime"""
        user_id = "test_user"
        token_data = {
            'access_token': 'test_access_token',
            'refresh_token': 'test_refresh_token',
            'token_type': 'Bearer',
            'expires_at': time.time() + 7200,
            'creation_timestamp': time.time()
        }
        
        # Store token
        self.manager.store_token(user_id, token_data)
        
        # Rotate token
        success = self.manager.rotate_token(user_id)
        self.assertTrue(success)
        
        # Verify token was rotated
        rotated = self.manager.get_token(user_id)
        self.assertIsNotNone(rotated)
        self.assertNotEqual(rotated['access_token'], token_data['access_token'])
    
    def test_token_revocation_and_blacklisting(self):
        """Test token revocation and blacklisting"""
        user_id = "test_user"
        token_data = {
            'access_token': 'test_access_token',
            'refresh_token': 'test_refresh_token',
            'token_type': 'Bearer',
            'expires_at': time.time() + 7200,
            'creation_timestamp': time.time()
        }
        
        # Store token
        self.manager.store_token(user_id, token_data)
        
        # Get token hash for blacklisting
        health = self.manager.get_token_health(user_id)
        token_hash = health['token_hash']
        
        # Revoke token
        success = self.manager.revoke_token(user_id)
        self.assertTrue(success)
        
        # Verify token is blacklisted
        self.assertTrue(self.manager.is_token_blacklisted(token_hash))
        
        # Verify token is no longer retrievable
        retrieved = self.manager.get_token(user_id)
        self.assertIsNone(retrieved)
    
    def test_concurrent_token_access(self):
        """Test concurrent access to tokens"""
        user_id = "test_user"
        token_data = {
            'access_token': 'test_access_token',
            'refresh_token': 'test_refresh_token',
            'token_type': 'Bearer',
            'expires_at': time.time() + 7200,
            'creation_timestamp': time.time()
        }
        
        # Store token
        self.manager.store_token(user_id, token_data)
        
        # Test concurrent access
        results = []
        errors = []
        
        def access_token():
            try:
                token = self.manager.get_token(user_id)
                results.append(token is not None)
            except Exception as e:
                errors.append(e)
        
        # Create multiple threads
        threads = []
        for _ in range(10):
            thread = threading.Thread(target=access_token)
            threads.append(thread)
            thread.start()
        
        # Wait for all threads to complete
        for thread in threads:
            thread.join()
        
        # Verify all accesses were successful
        self.assertEqual(len(results), 10)
        self.assertTrue(all(results))
        self.assertEqual(len(errors), 0)
    
    def test_corrupted_token_recovery(self):
        """Test recovery from corrupted token storage"""
        user_id = "test_user"
        token_data = {
            'access_token': 'test_access_token',
            'refresh_token': 'test_refresh_token',
            'token_type': 'Bearer',
            'expires_at': time.time() + 7200,
            'creation_timestamp': time.time()
        }
        
        # Store token
        self.manager.store_token(user_id, token_data)
        
        # Manually corrupt the token file
        token_file = Path(self.temp_dir) / f"{user_id}.token"
        with open(token_file, 'w') as f:
            f.write("corrupted_data")
        
        # Try to retrieve token (should trigger recovery)
        retrieved = self.manager.get_token(user_id)
        
        # Should recover from backup
        self.assertIsNotNone(retrieved)
        self.assertEqual(retrieved['access_token'], token_data['access_token'])
    
    def test_background_refresh(self):
        """Test background token refresh"""
        user_id = "test_user"
        token_data = {
            'access_token': 'test_access_token',
            'refresh_token': 'test_refresh_token',
            'token_type': 'Bearer',
            'expires_at': time.time() + 1800,  # 30 minutes (within 1 hour threshold)
            'creation_timestamp': time.time()
        }
        
        # Store token
        self.manager.store_token(user_id, token_data)
        
        # Wait a bit for background refresh to potentially trigger
        time.sleep(2)
        
        # Verify token is still accessible
        retrieved = self.manager.get_token(user_id)
        self.assertIsNotNone(retrieved)
    
    def test_manager_health_check(self):
        """Test manager health check"""
        health = self.manager.health_check()
        
        self.assertIn('storage_backend_healthy', health)
        self.assertIn('refresh_thread_alive', health)
        self.assertIn('blacklisted_tokens_count', health)
        self.assertIn('cached_tokens_count', health)
        self.assertIn('backup_tokens_count', health)
        
        self.assertTrue(health['storage_backend_healthy'])


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
        user_id = "test_user"
        token_data = {
            'access_token': 'test_access_token',
            'refresh_token': 'test_refresh_token',
            'token_type': 'Bearer',
            'expires_at': time.time() + 7200,
            'creation_timestamp': time.time()
        }
        
        # Test store_user_token
        success = store_user_token(user_id, token_data)
        self.assertTrue(success)
        
        # Test get_user_token
        retrieved = get_user_token(user_id)
        self.assertIsNotNone(retrieved)
        self.assertEqual(retrieved['access_token'], token_data['access_token'])
        
        # Test get_token_health
        health = get_token_health(user_id)
        self.assertTrue(health['is_valid'])
        
        # Test refresh_user_token
        success = refresh_user_token(user_id)
        self.assertTrue(success)


class TestSecurityFeatures(unittest.TestCase):
    """Test security features"""
    
    def test_encryption_at_rest(self):
        """Test that tokens are encrypted at rest"""
        with tempfile.TemporaryDirectory() as temp_dir:
            backend = EncryptedFileStorageBackend(temp_dir)
            manager = SecureTokenManager(storage_backend=backend)
            
            user_id = "test_user"
            token_data = {
                'access_token': 'test_access_token',
                'refresh_token': 'test_refresh_token',
                'token_type': 'Bearer',
                'expires_at': time.time() + 7200,
                'creation_timestamp': time.time()
            }
            
            # Store token
            manager.store_token(user_id, token_data)
            
            # Read raw file content
            token_file = Path(temp_dir) / f"{user_id}.token"
            with open(token_file, 'r') as f:
                stored_data = json.load(f)
            
            # Verify stored data is not plain JSON
            encrypted_str = stored_data['encrypted_data']
            self.assertNotIn('test_access_token', encrypted_str)
            self.assertNotIn('test_refresh_token', encrypted_str)
            
            manager.shutdown()
    
    def test_token_blacklisting(self):
        """Test token blacklisting functionality"""
        manager = SecureTokenManager()
        
        user_id = "test_user"
        token_data = {
            'access_token': 'test_access_token',
            'refresh_token': 'test_refresh_token',
            'token_type': 'Bearer',
            'expires_at': time.time() + 7200,
            'creation_timestamp': time.time()
        }
        
        # Store token
        manager.store_token(user_id, token_data)
        
        # Get token hash
        health = manager.get_token_health(user_id)
        token_hash = health['token_hash']
        
        # Check that token is not blacklisted initially
        self.assertFalse(manager.is_token_blacklisted(token_hash))
        
        # Revoke token
        manager.revoke_token(user_id)
        
        # Check that token is now blacklisted
        self.assertTrue(manager.is_token_blacklisted(token_hash))
        
        manager.shutdown()
    
    def test_environment_key_encryption(self):
        """Test encryption with environment key"""
        # Set environment variable
        test_key = "test_encryption_key_32_bytes_long!"
        os.environ['SCHWAB_ENCRYPTION_KEY'] = test_key
        
        try:
            manager = SecureTokenManager()
            
            # Test that manager was created successfully
            self.assertIsNotNone(manager)
            
            manager.shutdown()
        finally:
            # Clean up environment
            if 'SCHWAB_ENCRYPTION_KEY' in os.environ:
                del os.environ['SCHWAB_ENCRYPTION_KEY']


class TestErrorHandling(unittest.TestCase):
    """Test error handling and edge cases"""
    
    def test_storage_backend_failure(self):
        """Test handling of storage backend failures"""
        # Create a mock backend that fails
        mock_backend = Mock()
        mock_backend.store_token.return_value = False
        mock_backend.retrieve_token.return_value = None
        mock_backend.health_check.return_value = False
        
        manager = SecureTokenManager(storage_backend=mock_backend)
        
        # Test store failure
        token_data = {
            'access_token': 'test_access_token',
            'refresh_token': 'test_refresh_token',
            'token_type': 'Bearer',
            'expires_at': time.time() + 7200,
            'creation_timestamp': time.time()
        }
        
        success = manager.store_token("test_user", token_data)
        self.assertFalse(success)
        
        manager.shutdown()
    
    def test_encryption_failure(self):
        """Test handling of encryption failures"""
        # Create manager with invalid encryption key
        invalid_key = b"invalid_key"
        
        with self.assertRaises(Exception):
            manager = SecureTokenManager(encryption_key=invalid_key)
    
    def test_token_validation_failure(self):
        """Test handling of token validation failures"""
        manager = SecureTokenManager()
        
        # Test with invalid token
        invalid_token = {
            'access_token': 'test_access_token',
            # Missing required fields
        }
        
        success = manager.store_token("test_user", invalid_token)
        self.assertFalse(success)
        
        manager.shutdown()
    
    def test_refresh_failure(self):
        """Test handling of refresh failures"""
        manager = SecureTokenManager()
        
        # Try to refresh non-existent token
        success = manager.refresh_token("non_existent_user")
        self.assertFalse(success)
        
        manager.shutdown()


class TestPerformanceAndStress(unittest.TestCase):
    """Test performance and stress scenarios"""
    
    def test_multiple_users(self):
        """Test performance with multiple users"""
        manager = SecureTokenManager()
        
        # Create tokens for multiple users
        num_users = 100
        for i in range(num_users):
            user_id = f"user_{i}"
            token_data = {
                'access_token': f'access_token_{i}',
                'refresh_token': f'refresh_token_{i}',
                'token_type': 'Bearer',
                'expires_at': time.time() + 7200,
                'creation_timestamp': time.time()
            }
            
            success = manager.store_token(user_id, token_data)
            self.assertTrue(success)
        
        # Verify all users can retrieve their tokens
        for i in range(num_users):
            user_id = f"user_{i}"
            token = manager.get_token(user_id)
            self.assertIsNotNone(token)
            self.assertEqual(token['access_token'], f'access_token_{i}')
        
        manager.shutdown()
    
    def test_concurrent_stress_test(self):
        """Test concurrent access stress"""
        manager = SecureTokenManager()
        
        def stress_operation():
            for i in range(10):
                user_id = f"stress_user_{threading.current_thread().ident}_{i}"
                token_data = {
                    'access_token': f'stress_token_{i}',
                    'refresh_token': f'stress_refresh_{i}',
                    'token_type': 'Bearer',
                    'expires_at': time.time() + 7200,
                    'creation_timestamp': time.time()
                }
                
                # Store token
                manager.store_token(user_id, token_data)
                
                # Retrieve token
                retrieved = manager.get_token(user_id)
                assert retrieved is not None
                
                # Refresh token
                manager.refresh_token(user_id)
                
                # Revoke token
                manager.revoke_token(user_id)
        
        # Create multiple threads
        threads = []
        for _ in range(5):
            thread = threading.Thread(target=stress_operation)
            threads.append(thread)
            thread.start()
        
        # Wait for all threads to complete
        for thread in threads:
            thread.join()
        
        manager.shutdown()


if __name__ == '__main__':
    # Run tests
    unittest.main() 