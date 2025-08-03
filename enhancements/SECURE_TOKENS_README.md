# Secure Token Management System

**Agent 6: Security & Token Specialist**

Bulletproof OAuth token lifecycle management system for high-availability trading services.

## 🚀 Features

### 🔐 Security
- **Encrypted Storage**: All tokens encrypted at rest using Fernet (AES-128-CBC)
- **Memory Safety**: Token decryption only in memory, never logged
- **HSM Integration**: Support for Hardware Security Modules in production
- **Token Blacklisting**: Comprehensive token revocation and blacklisting
- **Environment Key Support**: Secure key management via environment variables

### 🔄 Lifecycle Management
- **Automatic Refresh**: Tokens refreshed 24 hours before expiration
- **Zero-Downtime Rotation**: Seamless token rotation without service interruption
- **Background Processing**: Non-blocking token refresh in background threads
- **Retry Logic**: Exponential backoff for failed refresh attempts

### 💾 Storage Backends
- **Keyring**: System-level secure credential storage (macOS Keychain, Windows Credential Manager, Linux Secret Service)
- **Encrypted Files**: Local encrypted JSON files with metadata
- **SQLite Database**: Relational storage with event tracking
- **Extensible**: Easy to add new storage backends

### 🛠️ Recovery & Monitoring
- **Corruption Recovery**: Automatic recovery from corrupted storage
- **Health Checks**: Comprehensive system health monitoring
- **Event System**: Rich event system for Agent 9 (scheduler) integration
- **Backup Tokens**: In-memory backup for critical recovery scenarios

## 📦 Installation

```bash
# Install dependencies
pip install -r enhancements/requirements_secure_tokens.txt

# Set encryption key (optional)
export SCHWAB_ENCRYPTION_KEY="your_base64_encoded_key_here"
```

## 🚀 Quick Start

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
    'expires_at': time.time() + 3600,  # 1 hour from now
    'creation_timestamp': time.time()
}

success = manager.store_token('user123', token_data)

# Retrieve token
token = manager.get_token('user123')

# Refresh token
manager.refresh_token('user123')

# Check token health
health = manager.get_token_health('user123')
print(f"Token valid: {health['is_valid']}")
print(f"Time to expiry: {health['time_to_expiry']} seconds")
```

### Global Manager

```python
from enhancements.secure_tokens import (
    get_global_token_manager,
    get_user_token,
    store_user_token,
    refresh_user_token
)

# Use global manager (automatically created)
manager = get_global_token_manager()

# Convenience functions for other agents
store_user_token('user123', token_data)
token = get_user_token('user123')
refresh_user_token('user123')
```

## 💾 Storage Backends

### Keyring Storage (Default)

```python
from enhancements.secure_tokens import KeyringStorageBackend

backend = KeyringStorageBackend(service_name="my_app_tokens")
manager = SecureTokenManager(storage_backend=backend)
```

**Features:**
- Uses system keychain (macOS Keychain, Windows Credential Manager, Linux Secret Service)
- No files created on disk
- Automatic credential management
- Limited listing capabilities

### Encrypted File Storage

```python
from enhancements.secure_tokens import EncryptedFileStorageBackend

backend = EncryptedFileStorageBackend(storage_dir="./secure_tokens")
manager = SecureTokenManager(storage_backend=backend)
```

**Features:**
- Local encrypted JSON files
- Full user listing support
- File-based backup and recovery
- Human-readable metadata

### Database Storage

```python
from enhancements.secure_tokens import DatabaseStorageBackend

backend = DatabaseStorageBackend(db_path="./tokens.db")
manager = SecureTokenManager(storage_backend=backend)
```

**Features:**
- SQLite database with event tracking
- Transaction support
- Token revocation tracking
- Rich metadata storage

## 📡 Event System

The system emits rich events for integration with Agent 9 (scheduler):

```python
from enhancements.secure_tokens import TokenEvent, TokenEventType

def token_event_callback(event: TokenEvent):
    print(f"Token event: {event.event_type.value}")
    print(f"User: {event.user_id}")
    print(f"Timestamp: {event.timestamp}")
    print(f"Metadata: {event.metadata}")

# Register callback
manager = SecureTokenManager(event_callbacks=[token_event_callback])
```

**Event Types:**
- `TOKEN_CREATED`: New token stored
- `TOKEN_REFRESHED`: Token refreshed
- `TOKEN_EXPIRED`: Token expired
- `TOKEN_REVOKED`: Token revoked
- `TOKEN_ROTATED`: Token rotated
- `TOKEN_CORRUPTED`: Token corruption detected
- `TOKEN_RECOVERED`: Token recovered from backup
- `STORAGE_ERROR`: Storage backend error
- `REFRESH_FAILED`: Token refresh failed

## 🔧 Security Configuration

### Environment Variables

```bash
# Set encryption key (base64 encoded)
export SCHWAB_ENCRYPTION_KEY="your_32_byte_base64_encoded_key"

# Optional: Custom storage configuration
export SCHWAB_TOKEN_STORAGE_DIR="./secure_tokens"
export SCHWAB_TOKEN_DB_PATH="./tokens.db"
```

### HSM Integration (Production)

```python
# For production environments with HSM
from enhancements.secure_tokens import SecureTokenManager

# Configure HSM integration
hsm_config = {
    'hsm_type': 'pkcs11',
    'hsm_library': '/usr/lib/libpkcs11.so',
    'slot_id': 0,
    'key_id': 'token_encryption_key'
}

manager = SecureTokenManager(
    encryption_key=hsm_key,  # Key from HSM
    hsm_config=hsm_config
)
```

## 🔍 Token Validation

The system includes comprehensive token validation:

```python
from enhancements.secure_tokens import TokenValidator

validator = TokenValidator()

# Validate token structure
is_valid, message = validator.validate_token(token_data)

# Check token health
health = validator.check_token_health(token_data)
print(f"Valid: {health['is_valid']}")
print(f"Time to expiry: {health['time_to_expiry']} seconds")
print(f"Token hash: {health['token_hash']}")
```

**Validation Checks:**
- Required fields present (`access_token`, `refresh_token`, `token_type`)
- Token not expired
- Token not expiring soon (within 1 hour)
- Valid token structure

## 🚀 Advanced Features

### Token Rotation

```python
# Rotate token with zero downtime
success = manager.rotate_token('user123')
if success:
    print("Token rotated successfully")
```

### Token Revocation

```python
# Revoke and blacklist token
success = manager.revoke_token('user123')
if success:
    print("Token revoked and blacklisted")
```

### Health Monitoring

```python
# Comprehensive health check
health = manager.health_check()
print(f"Storage healthy: {health['storage_backend_healthy']}")
print(f"Refresh thread alive: {health['refresh_thread_alive']}")
print(f"Blacklisted tokens: {health['blacklisted_tokens_count']}")
print(f"Cached tokens: {health['cached_tokens_count']}")
```

### Recovery Mechanisms

```python
# Enable/disable corruption recovery
manager._corruption_recovery_enabled = True

# Manual recovery (if needed)
recovered_token = manager._recover_token('user123')
if recovered_token:
    print("Token recovered from backup")
```

## 🔗 Integration with Other Agents

### Agent 2 (Secure Authentication)

```python
# The secure token manager integrates with Agent 2's auth system
# Token refresh calls would use Agent 2's OAuth refresh endpoints
def _simulate_token_refresh(self, current_token):
    # In real implementation, this would call Agent 2's refresh method
    # return agent2.refresh_oauth_token(current_token['refresh_token'])
    pass
```

### Agent 7 (Multi-User Support)

```python
# Per-user token isolation is built-in
manager.store_token('user1', token_data_1)
manager.store_token('user2', token_data_2)

# Each user's tokens are completely isolated
token1 = manager.get_token('user1')  # Only user1's token
token2 = manager.get_token('user2')  # Only user2's token
```

### Agent 9 (System Scheduler)

```python
# Rich event system for scheduler integration
def scheduler_event_handler(event: TokenEvent):
    if event.event_type == TokenEventType.TOKEN_EXPIRED:
        # Schedule immediate refresh
        scheduler.schedule_refresh(event.user_id)
    elif event.event_type == TokenEventType.TOKEN_REFRESHED:
        # Update scheduler state
        scheduler.update_token_status(event.user_id, 'refreshed')

manager = SecureTokenManager(event_callbacks=[scheduler_event_handler])
```

## 🧪 Testing

### Run Tests

```bash
# Run all tests
python -m pytest tests/test_secure_tokens.py -v

# Run specific test categories
python -m pytest tests/test_secure_tokens.py::TestTokenValidator -v
python -m pytest tests/test_secure_tokens.py::TestSecureTokenManager -v
python -m pytest tests/test_secure_tokens.py::TestSecurityFeatures -v
```

### Test Coverage

```bash
# Run with coverage
python -m pytest tests/test_secure_tokens.py --cov=enhancements.secure_tokens --cov-report=html
```

### Security Testing

```bash
# Test encryption at rest
python -m pytest tests/test_secure_tokens.py::TestSecurityFeatures::test_encryption_at_rest -v

# Test token blacklisting
python -m pytest tests/test_secure_tokens.py::TestSecurityFeatures::test_token_blacklisting -v
```

## 🚀 Production Deployment

### 1. Environment Setup

```bash
# Set production encryption key
export SCHWAB_ENCRYPTION_KEY="$(openssl rand -base64 32)"

# Set secure storage directory
export SCHWAB_TOKEN_STORAGE_DIR="/secure/tokens"

# Set database path
export SCHWAB_TOKEN_DB_PATH="/secure/tokens.db"
```

### 2. HSM Configuration (Recommended)

```python
# Configure HSM for production
hsm_config = {
    'hsm_type': 'pkcs11',
    'hsm_library': '/usr/lib/libpkcs11.so',
    'slot_id': 0,
    'key_id': 'production_token_key',
    'pin': 'your_hsm_pin'
}

manager = SecureTokenManager(
    storage_backend=DatabaseStorageBackend('/secure/tokens.db'),
    hsm_config=hsm_config
)
```

### 3. Monitoring Setup

```python
# Set up monitoring callbacks
def monitoring_callback(event: TokenEvent):
    # Send to monitoring system
    monitoring.send_metric('token_event', {
        'event_type': event.event_type.value,
        'user_id': event.user_id,
        'timestamp': event.timestamp
    })

manager = SecureTokenManager(event_callbacks=[monitoring_callback])
```

### 4. Health Checks

```python
# Regular health checks
health = manager.health_check()
if not health['storage_backend_healthy']:
    alert("Token storage backend unhealthy")

if not health['refresh_thread_alive']:
    alert("Token refresh thread died")
```

## 🔧 Troubleshooting

### Common Issues

**1. Keyring Access Denied**
```bash
# On macOS, grant keychain access
security unlock-keychain login.keychain
```

**2. Encryption Key Issues**
```bash
# Generate new encryption key
python -c "import base64, secrets; print(base64.b64encode(secrets.token_bytes(32)).decode())"
```

**3. Storage Backend Failures**
```python
# Check storage backend health
health = manager.health_check()
print(f"Storage healthy: {health['storage_backend_healthy']}")

# Try alternative backend
fallback_backend = EncryptedFileStorageBackend('./backup_tokens')
manager = SecureTokenManager(storage_backend=fallback_backend)
```

**4. Token Recovery**
```python
# Enable recovery mode
manager._corruption_recovery_enabled = True

# Manual recovery
recovered = manager._recover_token('user123')
if recovered:
    print("Token recovered successfully")
```

### Debug Mode

```python
import logging

# Enable debug logging
logging.basicConfig(level=logging.DEBUG)

# Create manager with debug
manager = SecureTokenManager()
```

## 📚 API Reference

### SecureTokenManager

**Constructor:**
```python
SecureTokenManager(
    storage_backend: StorageBackend = None,
    encryption_key: bytes = None,
    refresh_threshold_hours: int = 24,
    max_retry_attempts: int = 3,
    event_callbacks: List[Callable] = None
)
```

**Methods:**
- `store_token(user_id: str, token_data: Dict[str, Any]) -> bool`
- `get_token(user_id: str) -> Optional[Dict[str, Any]]`
- `refresh_token(user_id: str) -> bool`
- `rotate_token(user_id: str) -> bool`
- `revoke_token(user_id: str) -> bool`
- `get_token_health(user_id: str) -> Dict[str, Any]`
- `list_users() -> List[str]`
- `health_check() -> Dict[str, Any]`
- `shutdown()`

### StorageBackend

**Abstract base class for storage backends:**
- `store_token(user_id: str, token_data: Dict[str, Any], encrypted_data: bytes) -> bool`
- `retrieve_token(user_id: str) -> Optional[bytes]`
- `delete_token(user_id: str) -> bool`
- `list_users() -> List[str]`
- `health_check() -> bool`

### TokenValidator

**Token validation and health checking:**
- `validate_token(token_data: Dict[str, Any]) -> Tuple[bool, str]`
- `calculate_token_hash(token_data: Dict[str, Any]) -> str`
- `check_token_health(token_data: Dict[str, Any]) -> Dict[str, Any]`

## 📄 License

This project is licensed under the MIT License - see the LICENSE file for details.

## 🤝 Contributing

1. Fork the repository
2. Create a feature branch
3. Make your changes
4. Add tests for new functionality
5. Run the test suite
6. Submit a pull request

### Development Setup

```bash
# Install development dependencies
pip install -r enhancements/requirements_secure_tokens.txt

# Install pre-commit hooks
pre-commit install

# Run tests
python -m pytest tests/test_secure_tokens.py -v

# Run linting
black enhancements/secure_tokens.py
flake8 enhancements/secure_tokens.py
mypy enhancements/secure_tokens.py
```

---

**Agent 6: Security & Token Specialist** - Bulletproof token lifecycle management for high-availability trading services. 