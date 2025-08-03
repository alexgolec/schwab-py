# Secure Token Management System

**Agent 6: Security & Token Specialist**

A bulletproof OAuth token lifecycle management system for high-availability trading services.

## Features

### 🔐 Security Features
- **Encrypted Storage**: All tokens encrypted at rest using Fernet (AES-256)
- **Memory Protection**: Token decryption only in memory, never logged
- **HSM Integration**: Hardware Security Module support for production
- **Token Blacklisting**: Revocation and blacklisting capabilities
- **Zero-Downtime Rotation**: Seamless token rotation without service interruption

### 🔄 Lifecycle Management
- **Automatic Refresh**: Proactive refresh 24 hours before expiration
- **Health Monitoring**: Comprehensive health checks and monitoring
- **Recovery Mechanisms**: Corrupted storage recovery capabilities
- **Multi-User Support**: Per-user token isolation

### 💾 Storage Backends
- **Encrypted Files**: File-based encrypted storage
- **Keyring**: System keyring integration
- **SQLite Database**: Encrypted database storage
- **HSM**: Hardware Security Module (placeholder for production)

### 🔌 Integration Features
- **Event System**: Token lifecycle events for other agents
- **Scheduler Integration**: Agent 9 (scheduler) event notifications
- **Multi-Agent Support**: Works with all other agents transparently
- **API Compatibility**: Drop-in replacement for existing token systems

## Quick Start

### Basic Usage

```python
from enhancements.secure_tokens import SecureTokenManager, StorageBackend

# Create token manager
token_manager = SecureTokenManager(
    storage_backend=StorageBackend.ENCRYPTED_FILE,
    storage_config={'storage_dir': './secure_tokens'},
    enable_auto_refresh=True
)

# Store a token
token_id = token_manager.store_token(
    token_data=b"your_oauth_token_data",
    api_key="your_api_key",
    user_id="user_123"
)

# Retrieve a token
token_data = token_manager.retrieve_token(token_id)

# Clean up
token_manager.shutdown()
```

### Advanced Configuration

```python
from enhancements.secure_tokens import (
    SecureTokenManager, 
    StorageBackend,
    TokenEventCallback,
    log_token_event
)

# Create with custom configuration
token_manager = SecureTokenManager(
    storage_backend=StorageBackend.SQLITE,
    storage_config={'db_path': './tokens.db'},
    refresh_threshold_hours=12,  # Refresh 12 hours before expiry
    max_concurrent_refreshes=10,
    enable_auto_refresh=True,
    event_callbacks=[TokenEventCallback(log_token_event)]
)

# Store with tags
token_id = token_manager.store_token(
    token_data=b"token_data",
    api_key="api_key",
    user_id="user_123",
    tags={"production", "high_priority"}
)
```

## Storage Backends

### Encrypted File Backend
```python
# File-based encrypted storage
token_manager = SecureTokenManager(
    storage_backend=StorageBackend.ENCRYPTED_FILE,
    storage_config={'storage_dir': './secure_tokens'}
)
```

### Keyring Backend
```python
# System keyring storage
token_manager = SecureTokenManager(
    storage_backend=StorageBackend.KEYRING,
    storage_config={'service_name': 'schwab_secure_tokens'}
)
```

### SQLite Backend
```python
# Encrypted database storage
token_manager = SecureTokenManager(
    storage_backend=StorageBackend.SQLITE,
    storage_config={'db_path': './tokens.db'}
)
```

### HSM Backend (Production)
```python
# Hardware Security Module (placeholder)
token_manager = SecureTokenManager(
    storage_backend=StorageBackend.HSM,
    storage_config={'hsm_config': {
        'provider': 'your_hsm_provider',
        'key_id': 'your_key_id'
    }}
)
```

## Token Operations

### Store Token
```python
# Basic storage
token_id = token_manager.store_token(
    token_data=b"oauth_token_data",
    api_key="api_key_123",
    user_id="user_456"
)

# With custom token ID
token_id = token_manager.store_token(
    token_data=b"token_data",
    api_key="api_key",
    user_id="user_123",
    token_id="custom_token_id",
    tags={"production", "trading"}
)
```

### Retrieve Token
```python
# Retrieve token data
token_data = token_manager.retrieve_token(token_id)

# Get metadata
metadata = token_manager.get_token_metadata(token_id)
print(f"Token age: {metadata.token_age()} seconds")
print(f"Refresh count: {metadata.refresh_count}")
print(f"Status: {metadata.status}")
```

### Token Rotation
```python
# Zero-downtime token rotation
new_token_data = b"new_oauth_token_data"
success = token_manager.rotate_token(token_id, new_token_data)

if success:
    print("Token rotated successfully")
else:
    print("Token rotation failed")
```

### Token Revocation
```python
# Revoke and blacklist token
success = token_manager.revoke_token(
    token_id, 
    reason="Security breach detected"
)

if success:
    print("Token revoked and blacklisted")
```

### Token Recovery
```python
# Recover from corrupted storage
backup_token_data = b"backup_token_data"
success = token_manager.recover_corrupted_token(
    token_id, 
    backup_token_data
)

if success:
    print("Token recovered successfully")
```

## Event System

### Event Callbacks
```python
def my_token_event_callback(event, token_id, metadata, **kwargs):
    print(f"Token event: {event.value} for {token_id}")
    if event == TokenEvent.REFRESHED:
        print(f"Token {token_id} was refreshed")
    elif event == TokenEvent.REVOKED:
        print(f"Token {token_id} was revoked: {kwargs.get('reason')}")

# Create token manager with callback
token_manager = SecureTokenManager(
    storage_backend=StorageBackend.ENCRYPTED_FILE,
    storage_config={'storage_dir': './tokens'},
    event_callbacks=[TokenEventCallback(my_token_event_callback)]
)
```

### Built-in Event Callbacks
```python
from enhancements.secure_tokens import (
    log_token_event,
    notify_scheduler_event,
    security_audit_event
)

# Multiple callbacks
token_manager = SecureTokenManager(
    storage_backend=StorageBackend.ENCRYPTED_FILE,
    storage_config={'storage_dir': './tokens'},
    event_callbacks=[
        TokenEventCallback(log_token_event),
        TokenEventCallback(notify_scheduler_event),
        TokenEventCallback(security_audit_event)
    ]
)
```

## Multi-User Support

### User Isolation
```python
# Store tokens for different users
user1_token = token_manager.store_token(
    b"user1_token_data",
    "api_key_1",
    "user_1"
)

user2_token = token_manager.store_token(
    b"user2_token_data", 
    "api_key_2",
    "user_2"
)

# List tokens for specific user
user1_tokens = token_manager.list_tokens(user_id="user_1")
user2_tokens = token_manager.list_tokens(user_id="user_2")

print(f"User 1 tokens: {user1_tokens}")
print(f"User 2 tokens: {user2_tokens}")
```

## Health Monitoring

### Health Check
```python
# Comprehensive health check
health_status = token_manager.health_check()

print(f"Overall healthy: {health_status['overall_healthy']}")
print(f"Backend healthy: {health_status['backend_healthy']}")
print(f"Encryption healthy: {health_status['encryption_healthy']}")
print(f"Cache size: {health_status['cache_size']}")
print(f"Blacklist size: {health_status['blacklist_size']}")
print(f"Active refreshes: {health_status['active_refreshes']}")
```

### Background Monitoring
```python
# Token manager automatically performs health checks
# and monitors token expiration in the background

# Health checks every 5 minutes
# Auto-refresh checks every hour
# Background threads handle all monitoring
```

## Security Considerations

### Encryption
- All tokens encrypted at rest using Fernet (AES-256)
- Encryption keys never logged or stored in plain text
- Support for password-based key derivation (PBKDF2)
- HSM integration for production environments

### Access Control
- Token blacklisting for revocation
- Per-user token isolation
- Concurrent access protection
- Memory-only token decryption

### Audit Trail
- Comprehensive event logging
- Token lifecycle tracking
- Security event notifications
- Audit callback system

## Integration with Other Agents

### Agent 2 (Secure Authentication)
```python
# Works seamlessly with Agent 2's secure authentication
# Tokens are automatically managed and refreshed
# No changes needed to existing authentication flow
```

### Agent 7 (Per-User Isolation)
```python
# Supports Agent 7's per-user token isolation
# Each user's tokens are completely isolated
# User-specific token listing and management
```

### Agent 9 (Scheduler)
```python
# Emits events for Agent 9 (scheduler)
# Automatic refresh scheduling
# Token lifecycle event notifications
```

## Testing

### Run Tests
```bash
# Run comprehensive test suite
python -m pytest tests/test_secure_tokens.py -v

# Run with coverage
python -m pytest tests/test_secure_tokens.py --cov=enhancements.secure_tokens

# Run specific test categories
python -m pytest tests/test_secure_tokens.py::TestSecurityFeatures -v
```

### Test Categories
- **TokenMetadata**: Metadata creation and serialization
- **StorageBackends**: All storage backend implementations
- **SecureTokenManager**: Core token management functionality
- **SecurityFeatures**: Security and penetration testing
- **IntegrationFeatures**: Multi-agent integration
- **ErrorHandling**: Error handling and edge cases

## Performance Considerations

### Caching
- In-memory token cache for performance
- Configurable cache size limits
- Automatic cache cleanup

### Concurrency
- Thread-safe operations
- Configurable concurrent refresh limits
- Background monitoring threads

### Storage Optimization
- Efficient encrypted storage
- Minimal metadata overhead
- Configurable storage backends

## Production Deployment

### Environment Setup
```bash
# Install dependencies
pip install -r enhancements/requirements_secure_tokens.txt

# Set up storage directory
mkdir -p /var/secure/tokens
chmod 700 /var/secure/tokens

# Configure logging
export LOG_LEVEL=INFO
```

### Configuration
```python
# Production configuration
token_manager = SecureTokenManager(
    storage_backend=StorageBackend.HSM,  # Use HSM in production
    storage_config={'hsm_config': {
        'provider': 'your_hsm_provider',
        'key_id': 'production_key_id'
    }},
    refresh_threshold_hours=24,
    max_concurrent_refreshes=20,
    enable_auto_refresh=True,
    event_callbacks=[
        TokenEventCallback(log_token_event),
        TokenEventCallback(security_audit_event)
    ]
)
```

### Monitoring
```python
# Regular health checks
health = token_manager.health_check()
if not health['overall_healthy']:
    # Alert monitoring system
    alert_monitoring_system(health)

# Event monitoring
def production_event_callback(event, token_id, metadata, **kwargs):
    # Send to monitoring system
    send_to_monitoring_system(event, token_id, metadata)
```

## Troubleshooting

### Common Issues

#### Token Retrieval Fails
```python
# Check if token is blacklisted
metadata = token_manager.get_token_metadata(token_id)
if metadata and metadata.blacklisted:
    print(f"Token {token_id} is blacklisted: {metadata.revocation_reason}")

# Check token age
if metadata:
    age_hours = metadata.token_age() / 3600
    print(f"Token age: {age_hours:.1f} hours")
```

#### Health Check Failures
```python
# Check health status
health = token_manager.health_check()
print(f"Health status: {health}")

# Check storage backend
if not health['backend_healthy']:
    print("Storage backend is unhealthy")

# Check encryption
if not health['encryption_healthy']:
    print("Encryption system is unhealthy")
```

#### Auto-Refresh Issues
```python
# Check refresh configuration
print(f"Auto-refresh enabled: {token_manager.enable_auto_refresh}")
print(f"Refresh threshold: {token_manager.refresh_threshold_hours} hours")
print(f"Max concurrent refreshes: {token_manager.max_concurrent_refreshes}")

# Check active refreshes
health = token_manager.health_check()
print(f"Active refreshes: {health['active_refreshes']}")
```

### Recovery Procedures

#### Corrupted Token Recovery
```python
# Recover from backup
backup_data = get_backup_token_data(token_id)
success = token_manager.recover_corrupted_token(token_id, backup_data)

if success:
    print("Token recovered successfully")
else:
    print("Token recovery failed")
```

#### Storage Backend Migration
```python
# Migrate between storage backends
old_manager = SecureTokenManager(
    storage_backend=StorageBackend.ENCRYPTED_FILE,
    storage_config={'storage_dir': './old_tokens'}
)

new_manager = SecureTokenManager(
    storage_backend=StorageBackend.SQLITE,
    storage_config={'db_path': './new_tokens.db'}
)

# Migrate tokens
for token_id in old_manager.list_tokens():
    try:
        token_data = old_manager.retrieve_token(token_id)
        metadata = old_manager.get_token_metadata(token_id)
        
        new_manager.store_token(
            token_data,
            metadata.api_key,
            metadata.user_id,
            token_id,
            metadata.tags
        )
    except Exception as e:
        print(f"Failed to migrate token {token_id}: {e}")
```

## API Reference

### SecureTokenManager

#### Constructor
```python
SecureTokenManager(
    storage_backend=StorageBackend.ENCRYPTED_FILE,
    storage_config=None,
    encryption_key=None,
    refresh_threshold_hours=24,
    max_concurrent_refreshes=5,
    enable_auto_refresh=True,
    event_callbacks=None
)
```

#### Methods
- `store_token(token_data, api_key, user_id=None, token_id=None, tags=None) -> str`
- `retrieve_token(token_id) -> bytes`
- `delete_token(token_id) -> bool`
- `revoke_token(token_id, reason=None) -> bool`
- `rotate_token(token_id, new_token_data) -> bool`
- `recover_corrupted_token(token_id, backup_token_data) -> bool`
- `get_token_metadata(token_id) -> Optional[TokenMetadata]`
- `list_tokens(user_id=None) -> List[str]`
- `health_check() -> Dict[str, Any]`
- `shutdown()`

### TokenMetadata

#### Attributes
- `token_id: str`
- `user_id: Optional[str]`
- `api_key: str`
- `creation_timestamp: int`
- `last_refresh_timestamp: int`
- `refresh_count: int`
- `status: TokenStatus`
- `storage_backend: StorageBackend`
- `blacklisted: bool`
- `revocation_reason: Optional[str]`
- `tags: Set[str]`

### TokenEvent

#### Events
- `CREATED`: Token created
- `REFRESHED`: Token refreshed
- `EXPIRED`: Token expired
- `REVOKED`: Token revoked
- `ROTATED`: Token rotated
- `RECOVERED`: Token recovered
- `CORRUPTED`: Token corrupted

### StorageBackend

#### Backends
- `ENCRYPTED_FILE`: File-based encrypted storage
- `KEYRING`: System keyring storage
- `SQLITE`: SQLite database storage
- `HSM`: Hardware Security Module

## License

This secure token management system is part of the Schwab Python API project and follows the same licensing terms.

## Contributing

See the main project CONTRIBUTING.md for guidelines on contributing to this secure token management system.

## Security

For security issues, please contact the development team through the project's security contact channels.

---

**Agent 6: Security & Token Specialist**  
*Bulletproof OAuth token lifecycle management for high-availability trading services* 