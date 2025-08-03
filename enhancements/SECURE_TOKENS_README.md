# Secure Token Management System

**Agent 6: Security & Token Specialist**

A bulletproof OAuth token lifecycle management system for the Schwab API with enterprise-grade security features.

## Features

### 🔐 Security Features
- **Encrypted Storage**: All tokens encrypted at rest using Fernet (AES-128-CBC)
- **Memory-Only Decryption**: Tokens only decrypted in memory, never logged
- **HSM Integration**: Support for Hardware Security Modules in production
- **Token Blacklisting**: Revoked tokens are blacklisted and tracked
- **Environment Key Support**: Encryption keys can be provided via environment variables

### 🔄 Lifecycle Management
- **Automatic Refresh**: Tokens refreshed 24 hours before expiration
- **Zero-Downtime Rotation**: Seamless token rotation without service interruption
- **Background Processing**: Non-blocking token refresh in background threads
- **Retry Logic**: Exponential backoff for failed refresh attempts

### 💾 Storage Backends
- **Keyring**: System keychain integration (macOS Keychain, Windows Credential Manager, Linux Secret Service)
- **Encrypted Files**: File-based storage with encryption
- **SQLite Database**: Lightweight database storage with revocation tracking
- **Extensible**: Easy to add new storage backends

### 🛡️ Recovery & Resilience
- **Corruption Recovery**: Automatic recovery from corrupted token storage
- **Backup Tokens**: In-memory backup of recent tokens
- **Health Checks**: Comprehensive system health monitoring
- **Error Handling**: Graceful handling of storage and encryption failures

### 🔍 Monitoring & Events
- **Token Events**: Rich event system for monitoring and integration
- **Health Metrics**: Detailed token health information
- **Audit Trail**: Complete token lifecycle tracking
- **Agent Integration**: Events for Agent 9 (scheduler) integration

## Installation

```bash
# Install dependencies
pip install -r enhancements/requirements_secure_tokens.txt

# For development
pip install -r enhancements/requirements_secure_tokens.txt[dev]
```

## Quick Start

### Basic Usage

```python
from enhancements.secure_tokens import SecureTokenManager, KeyringStorageBackend

# Create manager with keyring storage
manager = SecureTokenManager(
    storage_backend=KeyringStorageBackend(),
    refresh_threshold_hours=24
)

# Store a token
token_data = {
    'access_token': 'your_access_token',
    'refresh_token': 'your_refresh_token',
    'token_type': 'Bearer',
    'expires_at': time.time() + 3600,
    'creation_timestamp': time.time()
}

success = manager.store_token('user123', token_data)

# Retrieve token
token = manager.get_token('user123')

# Check token health
health = manager.get_token_health('user123')
print(f"Token valid: {health['is_valid']}")
print(f"Time to expiry: {health['time_to_expiry']} seconds")
```

### Global Manager (Recommended)

```python
from enhancements.secure_tokens import (
    get_user_token, store_user_token, refresh_user_token, get_token_health
)

# Store token
store_user_token('user123', token_data)

# Get token
token = get_user_token('user123')

# Refresh token
refresh_user_token('user123')

# Check health
health = get_token_health('user123')
```

## Storage Backends

### Keyring Storage (Default)

```python
from enhancements.secure_tokens import KeyringStorageBackend

backend = KeyringStorageBackend(service_name="my_app_tokens")
manager = SecureTokenManager(storage_backend=backend)
```

### Encrypted File Storage

```python
from enhancements.secure_tokens import EncryptedFileStorageBackend

backend = EncryptedFileStorageBackend(storage_dir="/secure/tokens")
manager = SecureTokenManager(storage_backend=backend)
```

### Database Storage

```python
from enhancements.secure_tokens import DatabaseStorageBackend

backend = DatabaseStorageBackend(db_path="/secure/tokens.db")
manager = SecureTokenManager(storage_backend=backend)
```

## Event System

The system emits events for monitoring and integration:

```python
def token_event_callback(event):
    print(f"Token event: {event.event_type.value}")
    print(f"User: {event.user_id}")
    print(f"Timestamp: {event.timestamp}")

manager = SecureTokenManager(event_callbacks=[token_event_callback])
```

### Event Types

- `TOKEN_CREATED`: New token stored
- `TOKEN_REFRESHED`: Token refreshed
- `TOKEN_EXPIRED`: Token expired
- `TOKEN_REVOKED`: Token revoked
- `TOKEN_ROTATED`: Token rotated
- `TOKEN_CORRUPTED`: Token storage corrupted
- `TOKEN_RECOVERED`: Token recovered from backup
- `STORAGE_ERROR`: Storage backend error
- `REFRESH_FAILED`: Token refresh failed

## Security Configuration

### Environment Variables

```bash
# Set encryption key (base64 encoded)
export SCHWAB_ENCRYPTION_KEY="your_base64_encoded_32_byte_key"

# For production, use a strong key
python -c "import base64, secrets; print(base64.b64encode(secrets.token_bytes(32)).decode())"
```

### HSM Integration (Production)

```python
# Example HSM integration (requires pypkcs11)
class HSMEncryption:
    def __init__(self, hsm_config):
        self.hsm = pypkcs11.PyPKCS11Lib()
        self.hsm.load(hsm_config)
    
    def encrypt(self, data):
        # Use HSM for encryption
        pass
    
    def decrypt(self, encrypted_data):
        # Use HSM for decryption
        pass

# Use with SecureTokenManager
manager = SecureTokenManager(encryption_provider=HSMEncryption(hsm_config))
```

## Token Validation

The system validates tokens before storage:

```python
from enhancements.secure_tokens import TokenValidator

validator = TokenValidator()

# Validate token
is_valid, message = validator.validate_token(token_data)

# Check comprehensive health
health = validator.check_token_health(token_data)
```

### Validation Rules

- All required fields present (`access_token`, `refresh_token`, `token_type`)
- Token not expired
- Token not expiring soon (< 1 hour)
- Valid token structure

## Advanced Features

### Token Rotation

```python
# Rotate token with zero downtime
success = manager.rotate_token('user123')
```

### Token Revocation

```python
# Revoke and blacklist token
success = manager.revoke_token('user123')

# Check if token is blacklisted
token_hash = validator.calculate_token_hash(token_data)
is_blacklisted = manager.is_token_blacklisted(token_hash)
```

### Recovery Mechanisms

```python
# Enable/disable corruption recovery
manager._corruption_recovery_enabled = True

# Manual recovery
recovered_token = manager._recover_token('user123')
```

### Health Monitoring

```python
# System health check
health = manager.health_check()
print(f"Storage healthy: {health['storage_backend_healthy']}")
print(f"Refresh thread alive: {health['refresh_thread_alive']}")
print(f"Blacklisted tokens: {health['blacklisted_tokens_count']}")
```

## Integration with Other Agents

### Agent 2 (Secure Authentication)

```python
# The secure token manager integrates with Agent 2's auth system
# Token refresh calls Agent 2's OAuth refresh endpoints
```

### Agent 7 (Multi-User Support)

```python
# Per-user token isolation is built-in
manager.store_token('user1', token1)
manager.store_token('user2', token2)
# Tokens are completely isolated
```

### Agent 9 (Scheduler)

```python
# Events are emitted for Agent 9 to schedule operations
def scheduler_callback(event):
    if event.event_type == TokenEventType.TOKEN_REFRESHED:
        # Schedule follow-up operations
        pass

manager = SecureTokenManager(event_callbacks=[scheduler_callback])
```

## Testing

Run the comprehensive test suite:

```bash
# Run all tests
python -m pytest tests/test_secure_tokens.py -v

# Run specific test categories
python -m pytest tests/test_secure_tokens.py::TestSecurityFeatures -v
python -m pytest tests/test_secure_tokens.py::TestPerformanceAndStress -v

# Run with coverage
python -m pytest tests/test_secure_tokens.py --cov=enhancements.secure_tokens
```

### Test Categories

- **TokenValidator**: Token validation and health checking
- **StorageBackends**: All storage backend implementations
- **SecureTokenManager**: Core manager functionality
- **GlobalTokenManager**: Global singleton and convenience functions
- **SecurityFeatures**: Encryption and security features
- **ErrorHandling**: Error handling and recovery
- **PerformanceAndStress**: Performance and stress testing

## Production Deployment

### Security Checklist

- [ ] Use environment-provided encryption keys
- [ ] Enable HSM integration for production
- [ ] Configure secure storage backends
- [ ] Set up monitoring for token events
- [ ] Implement token revocation procedures
- [ ] Test recovery mechanisms
- [ ] Configure appropriate refresh thresholds
- [ ] Set up health monitoring

### Performance Considerations

- **Caching**: Tokens are cached in memory for fast access
- **Background Processing**: Refresh operations don't block main operations
- **Concurrent Access**: Thread-safe operations with proper locking
- **Storage Optimization**: Efficient storage backends for your use case

### Monitoring

```python
# Monitor token events
def monitor_tokens(event):
    if event.event_type == TokenEventType.REFRESH_FAILED:
        # Alert on refresh failures
        send_alert(f"Token refresh failed for user {event.user_id}")
    elif event.event_type == TokenEventType.TOKEN_CORRUPTED:
        # Alert on corruption
        send_alert(f"Token corrupted for user {event.user_id}")

manager = SecureTokenManager(event_callbacks=[monitor_tokens])
```

## Troubleshooting

### Common Issues

1. **Keyring not available**: Install keyring backend for your platform
2. **Encryption errors**: Check encryption key format and length
3. **Storage failures**: Verify storage backend permissions and configuration
4. **Refresh failures**: Check network connectivity and OAuth configuration

### Debug Mode

```python
import logging
logging.basicConfig(level=logging.DEBUG)

# Enable debug logging for the secure token system
logging.getLogger('enhancements.secure_tokens').setLevel(logging.DEBUG)
```

## API Reference

### SecureTokenManager

Main class for token management.

#### Methods

- `store_token(user_id, token_data)`: Store encrypted token
- `get_token(user_id)`: Retrieve decrypted token
- `refresh_token(user_id)`: Manually refresh token
- `rotate_token(user_id)`: Rotate token with zero downtime
- `revoke_token(user_id)`: Revoke and blacklist token
- `get_token_health(user_id)`: Get comprehensive health info
- `health_check()`: System health check
- `shutdown()`: Graceful shutdown

### StorageBackend

Abstract base class for storage backends.

#### Implementations

- `KeyringStorageBackend`: System keychain integration
- `EncryptedFileStorageBackend`: Encrypted file storage
- `DatabaseStorageBackend`: SQLite database storage

### TokenValidator

Token validation and health checking.

#### Methods

- `validate_token(token_data)`: Validate token structure
- `calculate_token_hash(token_data)`: Calculate token hash
- `check_token_health(token_data)`: Comprehensive health check

## License

This secure token management system is part of the Schwab API client library and follows the same license terms.

## Contributing

See the main project's CONTRIBUTING.md for contribution guidelines. Security-related contributions are especially welcome.

---

**Agent 6: Security & Token Specialist** - Bulletproof token lifecycle management for high-availability trading services. 