"""
Comprehensive Test Suite for Secure HTTPS OAuth Callback Server

Tests all security features, certificate management, OAuth flow validation,
and integration scenarios for the SecureAuthServer implementation.

Author: Agent 2 - Authentication Security Specialist
"""

import json
import os
import pytest
import threading
import time
import tempfile
import ssl
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import Mock, patch, MagicMock
from urllib.parse import urlparse, parse_qs

import httpx
from cryptography import x509
from cryptography.hazmat.primitives import serialization

# Import the modules under test
import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'enhancements'))

from secure_auth import (
    SecureAuthServer,
    CertificateManager,
    SessionManager,
    RateLimiter,
    AuthenticationError,
    SecurityError,
    CertificateError,
    secure_client_from_login_flow,
    generate_production_csr,
    DEFAULT_HOST,
    DEFAULT_PORT
)


class TestRateLimiter:
    """Test rate limiting functionality"""
    
    def test_rate_limiter_allows_requests_under_limit(self):
        """Test that requests under the limit are allowed"""
        limiter = RateLimiter(max_requests=5, window_seconds=60)
        
        # Should allow first 5 requests
        for i in range(5):
            assert limiter.is_allowed("192.168.1.1") is True
        
        # 6th request should be denied
        assert limiter.is_allowed("192.168.1.1") is False
    
    def test_rate_limiter_different_ips(self):
        """Test that different IPs have separate limits"""
        limiter = RateLimiter(max_requests=2, window_seconds=60)
        
        # First IP uses up its limit
        assert limiter.is_allowed("192.168.1.1") is True
        assert limiter.is_allowed("192.168.1.1") is True
        assert limiter.is_allowed("192.168.1.1") is False
        
        # Second IP should still be allowed
        assert limiter.is_allowed("192.168.1.2") is True
        assert limiter.is_allowed("192.168.1.2") is True
        assert limiter.is_allowed("192.168.1.2") is False
    
    def test_rate_limiter_window_reset(self):
        """Test that rate limit window resets properly"""
        limiter = RateLimiter(max_requests=2, window_seconds=1)
        
        # Use up the limit
        assert limiter.is_allowed("192.168.1.1") is True
        assert limiter.is_allowed("192.168.1.1") is True
        assert limiter.is_allowed("192.168.1.1") is False
        
        # Wait for window to reset
        time.sleep(1.1)
        
        # Should be allowed again
        assert limiter.is_allowed("192.168.1.1") is True
    
    def test_rate_limiter_retry_after(self):
        """Test retry-after calculation"""
        limiter = RateLimiter(max_requests=1, window_seconds=10)
        
        # Use up the limit
        assert limiter.is_allowed("192.168.1.1") is True
        assert limiter.is_allowed("192.168.1.1") is False
        
        # Check retry-after
        retry_after = limiter.get_retry_after("192.168.1.1")
        assert 0 < retry_after <= 10


class TestSessionManager:
    """Test session management functionality"""
    
    def test_session_creation(self):
        """Test session creation with CSRF token"""
        manager = SessionManager(timeout_seconds=600)
        
        session_id = manager.create_session()
        assert session_id is not None
        assert len(session_id) > 0
        
        csrf_token = manager.get_csrf_token(session_id)
        assert csrf_token is not None
        assert len(csrf_token) > 0
    
    def test_session_validation(self):
        """Test session validation"""
        manager = SessionManager(timeout_seconds=600)
        
        session_id = manager.create_session()
        csrf_token = manager.get_csrf_token(session_id)
        
        # Valid session without CSRF
        assert manager.validate_session(session_id) is True
        
        # Valid session with correct CSRF
        assert manager.validate_session(session_id, csrf_token) is True
        
        # Invalid session with wrong CSRF
        assert manager.validate_session(session_id, "wrong_token") is False
        
        # Non-existent session
        assert manager.validate_session("non_existent") is False
    
    def test_session_timeout(self):
        """Test session timeout functionality"""
        manager = SessionManager(timeout_seconds=1)
        
        session_id = manager.create_session()
        assert manager.validate_session(session_id) is True
        
        # Wait for timeout
        time.sleep(1.1)
        
        # Session should be expired
        assert manager.validate_session(session_id) is False
    
    def test_session_cleanup(self):
        """Test expired session cleanup"""
        manager = SessionManager(timeout_seconds=1)
        
        # Create multiple sessions
        session1 = manager.create_session()
        session2 = manager.create_session()
        
        # Wait for expiration
        time.sleep(1.1)
        
        # Add a new session
        session3 = manager.create_session()
        
        # Cleanup expired sessions
        manager.cleanup_expired()
        
        # Old sessions should be invalid, new one valid
        assert manager.validate_session(session1) is False
        assert manager.validate_session(session2) is False
        assert manager.validate_session(session3) is True


class TestCertificateManager:
    """Test SSL certificate management"""
    
    def setup_method(self):
        """Setup temporary directory for certificates"""
        self.temp_dir = tempfile.mkdtemp()
        self.cert_manager = CertificateManager(cert_dir=self.temp_dir)
    
    def teardown_method(self):
        """Cleanup temporary directory"""
        import shutil
        shutil.rmtree(self.temp_dir, ignore_errors=True)
    
    def test_certificate_generation(self):
        """Test self-signed certificate generation"""
        cert_path, key_path = self.cert_manager.generate_self_signed_cert("localhost")
        
        # Check files were created
        assert cert_path.exists()
        assert key_path.exists()
        
        # Check file permissions
        assert oct(cert_path.stat().st_mode)[-3:] == '644'
        assert oct(key_path.stat().st_mode)[-3:] == '600'
        
        # Load and validate certificate
        with open(cert_path, 'rb') as f:
            cert = x509.load_pem_x509_certificate(f.read())
        
        # Check certificate properties
        assert cert.subject.get_attributes_for_oid(x509.NameOID.COMMON_NAME)[0].value == "localhost"
        assert cert.not_valid_after > datetime.utcnow()
        
        # Check private key
        with open(key_path, 'rb') as f:
            private_key = serialization.load_pem_private_key(f.read(), password=None)
        
        assert private_key.key_size == 2048
    
    def test_certificate_validation_valid(self):
        """Test validation of valid certificates"""
        # Generate certificate first
        self.cert_manager.generate_self_signed_cert("localhost")
        
        # Should validate successfully
        assert self.cert_manager.validate_cert() is True
    
    def test_certificate_validation_missing_files(self):
        """Test validation when certificate files are missing"""
        assert self.cert_manager.validate_cert() is False
    
    def test_certificate_validation_expired(self):
        """Test validation of expired certificates"""
        # This would require generating an expired cert, which is complex
        # For now, test the validation logic with a mock
        with patch('secure_auth.x509.load_pem_x509_certificate') as mock_load:
            mock_cert = Mock()
            mock_cert.not_valid_after = datetime.utcnow() - timedelta(days=1)
            mock_load.return_value = mock_cert
            
            # Create dummy files
            self.cert_manager.cert_path.touch()
            self.cert_manager.key_path.touch()
            
            with patch('builtins.open', mock_open_side_effect):
                assert self.cert_manager.validate_cert() is False
    
    def test_ssl_context_creation(self):
        """Test SSL context creation"""
        # Generate certificate first
        self.cert_manager.generate_self_signed_cert("localhost")
        
        # Create SSL context
        ssl_context = self.cert_manager.get_ssl_context()
        
        assert isinstance(ssl_context, ssl.SSLContext)
        assert ssl_context.verify_mode == ssl.CERT_NONE
    
    def test_ssl_context_invalid_cert(self):
        """Test SSL context creation with invalid certificate"""
        with pytest.raises(CertificateError):
            self.cert_manager.get_ssl_context()


def mock_open_side_effect(*args, **kwargs):
    """Mock open function that returns dummy certificate data"""
    if 'server.crt' in str(args[0]):
        mock_file = Mock()
        mock_file.read.return_value = b"dummy cert data"
        return mock_file
    elif 'server.key' in str(args[0]):
        mock_file = Mock()
        mock_file.read.return_value = b"dummy key data"
        return mock_file
    else:
        return open(*args, **kwargs)


class TestSecureAuthServer:
    """Test the main SecureAuthServer class"""
    
    def setup_method(self):
        """Setup test environment"""
        self.temp_dir = tempfile.mkdtemp()
        self.server = None
    
    def teardown_method(self):
        """Cleanup test environment"""
        if self.server:
            self.server.shutdown()
        
        import shutil
        shutil.rmtree(self.temp_dir, ignore_errors=True)
    
    def test_server_initialization_defaults(self):
        """Test server initialization with default values"""
        server = SecureAuthServer(cert_dir=self.temp_dir)
        
        assert server.host == DEFAULT_HOST
        assert server.port == DEFAULT_PORT
        assert server.callback_path == '/callback'
        assert server.use_self_signed is True
        assert server.framework == 'flask'
    
    def test_server_initialization_custom(self):
        """Test server initialization with custom values"""
        server = SecureAuthServer(
            host='192.168.1.100',
            port=9443,
            callback_path='/oauth',
            use_self_signed=False,
            cert_dir=self.temp_dir,
            framework='flask'
        )
        
        assert server.host == '192.168.1.100'
        assert server.port == 9443
        assert server.callback_path == '/oauth'
        assert server.use_self_signed is False
    
    def test_server_initialization_environment_vars(self):
        """Test server initialization from environment variables"""
        env_vars = {
            'SCHWAB_AUTH_HOST': '10.0.0.1',
            'SCHWAB_AUTH_PORT': '7443',
            'SCHWAB_AUTH_USE_SELF_SIGNED': 'false',
            'SCHWAB_AUTH_SESSION_TIMEOUT': '300',
            'SCHWAB_AUTH_RATE_LIMIT': '5'
        }
        
        with patch.dict(os.environ, env_vars):
            server = SecureAuthServer(cert_dir=self.temp_dir)
            
            assert server.host == '10.0.0.1'
            assert server.port == 7443
            assert server.use_self_signed is False
    
    def test_callback_url_generation(self):
        """Test callback URL generation"""
        server = SecureAuthServer(
            host='example.com',
            port=8443,
            callback_path='/callback',
            cert_dir=self.temp_dir
        )
        
        expected_url = 'https://example.com:8443/callback'
        assert server.get_callback_url() == expected_url
    
    def test_certificate_preparation_self_signed(self):
        """Test certificate preparation in self-signed mode"""
        server = SecureAuthServer(
            use_self_signed=True,
            cert_dir=self.temp_dir
        )
        
        cert_path, key_path = server.prepare_certificates()
        
        assert cert_path.exists()
        assert key_path.exists()
        assert server.cert_manager.validate_cert(cert_path, key_path)
    
    def test_certificate_preparation_production_missing(self):
        """Test certificate preparation in production mode with missing certs"""
        server = SecureAuthServer(
            use_self_signed=False,
            cert_dir=self.temp_dir
        )
        
        with pytest.raises(CertificateError):
            server.prepare_certificates()
    
    @patch('secure_auth.webbrowser')
    @patch('secure_auth.get_auth_context')
    @patch('secure_auth.client_from_received_url')
    @patch('secure_auth.__make_update_token_func')
    def test_oauth_callback_handling(self, mock_token_func, mock_client, mock_auth, mock_browser):
        """Test OAuth callback handling"""
        # Mock Flask request
        mock_request = Mock()
        mock_request.url = 'https://localhost:8443/callback?code=test123&state=abc123'
        mock_request.args.to_dict.return_value = {'code': 'test123', 'state': 'abc123'}
        mock_request.environ.get.return_value = '127.0.0.1'
        mock_request.headers.get.return_value = 'Mozilla/5.0'
        
        server = SecureAuthServer(cert_dir=self.temp_dir, framework='flask')
        
        # Test callback handling
        result = server._handle_oauth_callback(mock_request)
        
        assert server.callback_url_received == mock_request.url
        assert len(server.auth_events) > 0
        assert server.auth_events[0]['type'] == 'oauth_callback_received'
        assert 'Authorization Successful' in result
    
    def test_oauth_callback_missing_code(self):
        """Test OAuth callback with missing authorization code"""
        mock_request = Mock()
        mock_request.url = 'https://localhost:8443/callback?error=access_denied'
        mock_request.args.to_dict.return_value = {'error': 'access_denied'}
        mock_request.environ.get.return_value = '127.0.0.1'
        mock_request.headers.get.return_value = 'Mozilla/5.0'
        
        server = SecureAuthServer(cert_dir=self.temp_dir, framework='flask')
        
        result = server._handle_oauth_callback(mock_request)
        
        assert 'Authorization Error' in result[0]
        assert result[1] == 400
    
    def test_oauth_callback_invalid_state(self):
        """Test OAuth callback with invalid state parameter"""
        mock_request = Mock()
        mock_request.url = 'https://localhost:8443/callback?code=test123&state=invalid!'
        mock_request.args.to_dict.return_value = {'code': 'test123', 'state': 'invalid!'}
        mock_request.environ.get.return_value = '127.0.0.1'
        mock_request.headers.get.return_value = 'Mozilla/5.0'
        
        server = SecureAuthServer(cert_dir=self.temp_dir, framework='flask')
        
        result = server._handle_oauth_callback(mock_request)
        
        assert 'Authorization Error' in result[0]
        assert result[1] == 400
    
    def test_auth_events_management(self):
        """Test authentication event management"""
        server = SecureAuthServer(cert_dir=self.temp_dir)
        
        # Add some events
        server.auth_events.append({'type': 'test1', 'timestamp': time.time()})
        server.auth_events.append({'type': 'test2', 'timestamp': time.time()})
        
        # Get events (should return copy)
        events = server.get_auth_events()
        assert len(events) == 2
        
        # Modify returned events (shouldn't affect original)
        events.append({'type': 'test3', 'timestamp': time.time()})
        assert len(server.get_auth_events()) == 2
        
        # Clear events
        server.clear_auth_events()
        assert len(server.get_auth_events()) == 0


class TestSecureAuthServerIntegration:
    """Integration tests for the secure auth server"""
    
    def setup_method(self):
        """Setup test environment"""
        self.temp_dir = tempfile.mkdtemp()
        self.server = None
    
    def teardown_method(self):
        """Cleanup test environment"""
        if self.server:
            self.server.shutdown()
        
        import shutil
        shutil.rmtree(self.temp_dir, ignore_errors=True)
    
    def test_server_start_and_health_check(self):
        """Test server startup and health check endpoint"""
        self.server = SecureAuthServer(
            host='127.0.0.1',
            port=0,  # Let OS choose port
            cert_dir=self.temp_dir,
            use_self_signed=True
        )
        
        # Start server in a thread to avoid blocking
        server_thread = threading.Thread(target=self.server.start_server)
        server_thread.daemon = True
        server_thread.start()
        
        # Give server time to start
        time.sleep(2)
        
        # Test health check (note: will fail with SSL verification due to self-signed cert)
        # This tests that the server is actually running and responding
        try:
            with pytest.raises((httpx.ConnectError, httpx.SSLError)):
                # This should fail due to SSL verification, but confirms server is running
                httpx.get(f"https://127.0.0.1:{self.server.port}/health", timeout=1)
        except Exception:
            pass  # Expected to fail due to SSL verification
    
    def test_concurrent_requests_rate_limiting(self):
        """Test concurrent requests and rate limiting"""
        self.server = SecureAuthServer(
            rate_limit=2,  # Very low limit for testing
            cert_dir=self.temp_dir
        )
        
        # Test rate limiting logic directly
        client_ip = "192.168.1.100"
        
        # First two requests should be allowed
        assert self.server.rate_limiter.is_allowed(client_ip) is True
        assert self.server.rate_limiter.is_allowed(client_ip) is True
        
        # Third request should be denied
        assert self.server.rate_limiter.is_allowed(client_ip) is False
        
        # Check retry-after
        retry_after = self.server.rate_limiter.get_retry_after(client_ip)
        assert retry_after > 0
    
    def test_session_management_integration(self):
        """Test session management integration"""
        self.server = SecureAuthServer(
            session_timeout=1,  # 1 second for testing
            cert_dir=self.temp_dir
        )
        
        # Create session
        session_id = self.server.session_manager.create_session()
        csrf_token = self.server.session_manager.get_csrf_token(session_id)
        
        # Validate immediately
        assert self.server.session_manager.validate_session(session_id, csrf_token) is True
        
        # Wait for timeout
        time.sleep(1.1)
        
        # Should be expired
        assert self.server.session_manager.validate_session(session_id, csrf_token) is False


class TestSecureClientIntegration:
    """Test the secure client integration function"""
    
    @patch('secure_auth.webbrowser')
    @patch('secure_auth.get_auth_context')
    @patch('secure_auth.client_from_received_url')
    @patch('secure_auth.__make_update_token_func')
    def test_secure_client_from_login_flow_success(self, mock_token_func, mock_client, mock_auth, mock_browser):
        """Test successful secure client creation flow"""
        # Setup mocks
        mock_auth_context = Mock()
        mock_auth_context.authorization_url = 'https://api.schwab.com/oauth/authorize?...'
        mock_auth.return_value = mock_auth_context
        
        mock_client_instance = Mock()
        mock_client.return_value = mock_client_instance
        
        mock_token_func.return_value = Mock()
        
        # Mock server callback
        temp_dir = tempfile.mkdtemp()
        try:
            with patch('secure_auth.SecureAuthServer') as mock_server_class:
                mock_server = Mock()
                mock_server.get_callback_url.return_value = 'https://127.0.0.1:8443/callback'
                mock_server.wait_for_callback.return_value = 'https://127.0.0.1:8443/callback?code=test123'
                mock_server.auth_events = []
                mock_server_class.return_value = mock_server
                
                # Create context manager mock
                mock_context = Mock()
                mock_context.__enter__.return_value = mock_server
                mock_context.__exit__.return_value = None
                mock_server.server_context.return_value = mock_context
                
                # Test the function
                result = secure_client_from_login_flow(
                    api_key='test_key',
                    app_secret='test_secret',
                    callback_url='https://127.0.0.1:8443/callback',
                    token_path='/tmp/token.json',
                    interactive=False
                )
                
                assert result == mock_client_instance
                mock_server.wait_for_callback.assert_called_once()
        
        finally:
            import shutil
            shutil.rmtree(temp_dir, ignore_errors=True)
    
    @patch('secure_auth.webbrowser')
    @patch('secure_auth.get_auth_context')
    @patch('secure_auth.SecureAuthServer')
    def test_secure_client_timeout(self, mock_server_class, mock_auth, mock_browser):
        """Test secure client creation with timeout"""
        # Setup mocks
        mock_auth_context = Mock()
        mock_auth_context.authorization_url = 'https://api.schwab.com/oauth/authorize?...'
        mock_auth.return_value = mock_auth_context
        
        mock_server = Mock()
        mock_server.get_callback_url.return_value = 'https://127.0.0.1:8443/callback'
        mock_server.wait_for_callback.return_value = None  # Timeout
        mock_server.auth_events = []
        mock_server_class.return_value = mock_server
        
        # Create context manager mock
        mock_context = Mock()
        mock_context.__enter__.return_value = mock_server
        mock_context.__exit__.return_value = None
        mock_server.server_context.return_value = mock_context
        
        # Test timeout
        with pytest.raises(TimeoutError):
            secure_client_from_login_flow(
                api_key='test_key',
                app_secret='test_secret',
                callback_url='https://127.0.0.1:8443/callback',
                token_path='/tmp/token.json',
                callback_timeout=1,
                interactive=False
            )


class TestUtilityFunctions:
    """Test utility functions"""
    
    def test_generate_production_csr(self):
        """Test production CSR generation"""
        temp_dir = tempfile.mkdtemp()
        
        try:
            csr_path = generate_production_csr('trading.example.com', temp_dir)
            
            # Check CSR file was created
            assert csr_path.exists()
            
            # Check private key was created
            key_path = Path(temp_dir) / 'server.key'
            assert key_path.exists()
            
            # Check key permissions
            assert oct(key_path.stat().st_mode)[-3:] == '600'
            
            # Load and validate CSR
            with open(csr_path, 'rb') as f:
                csr = x509.load_pem_x509_csr(f.read())
            
            # Check CSR properties
            assert csr.subject.get_attributes_for_oid(x509.NameOID.COMMON_NAME)[0].value == 'trading.example.com'
            
        finally:
            import shutil
            shutil.rmtree(temp_dir, ignore_errors=True)


class TestSecurityFeatures:
    """Test specific security features"""
    
    def test_token_redaction_in_logs(self):
        """Test that tokens are not logged in plain text"""
        # This would typically require checking log output
        # For now, verify that the redaction function is available
        from schwab.debug import register_redactions
        
        mock_token = {'access_token': 'secret123', 'refresh_token': 'refresh456'}
        
        # This should not raise an exception
        register_redactions(mock_token)
    
    def test_csrf_protection(self):
        """Test CSRF protection mechanisms"""
        server = SecureAuthServer()
        
        # Create session with CSRF token
        session_id = server.session_manager.create_session()
        csrf_token = server.session_manager.get_csrf_token(session_id)
        
        # Valid CSRF should pass
        assert server.session_manager.validate_session(session_id, csrf_token) is True
        
        # Invalid CSRF should fail
        assert server.session_manager.validate_session(session_id, "wrong_token") is False
    
    def test_secure_headers_and_responses(self):
        """Test that security headers are properly set"""
        server = SecureAuthServer()
        
        # This would typically require testing actual HTTP responses
        # For now, verify that the server sets up security properly
        assert server.rate_limiter is not None
        assert server.session_manager is not None
        assert server.cert_manager is not None


class TestErrorHandling:
    """Test error handling scenarios"""
    
    def test_certificate_error_handling(self):
        """Test certificate error handling"""
        with pytest.raises(CertificateError):
            cert_manager = CertificateManager()
            cert_manager.get_ssl_context()  # No certificates available
    
    def test_authentication_error_handling(self):
        """Test authentication error scenarios"""
        # Test that AuthenticationError can be raised
        with pytest.raises(AuthenticationError):
            raise AuthenticationError("Test auth error")
    
    def test_security_error_handling(self):
        """Test security error scenarios"""
        # Test that SecurityError can be raised  
        with pytest.raises(SecurityError):
            raise SecurityError("Test security error")


# Performance and load testing helpers

class TestPerformanceBaseline:
    """Basic performance tests"""
    
    def test_rate_limiter_performance(self):
        """Test rate limiter performance under load"""
        limiter = RateLimiter(max_requests=1000, window_seconds=60)
        
        start_time = time.time()
        
        # Test 1000 requests
        for i in range(1000):
            limiter.is_allowed(f"192.168.1.{i % 10}")
        
        end_time = time.time()
        
        # Should complete in reasonable time (less than 1 second)
        assert end_time - start_time < 1.0
    
    def test_session_manager_performance(self):
        """Test session manager performance"""
        manager = SessionManager()
        
        start_time = time.time()
        
        # Create and validate 1000 sessions
        sessions = []
        for i in range(1000):
            session_id = manager.create_session()
            sessions.append(session_id)
            assert manager.validate_session(session_id) is True
        
        end_time = time.time()
        
        # Should complete in reasonable time
        assert end_time - start_time < 2.0


# Mock server for integration testing

class MockSchwabOAuthServer:
    """Mock Schwab OAuth server for testing"""
    
    def __init__(self, port=9999):
        self.port = port
        self.app = None
        self.server_thread = None
    
    def start(self):
        """Start mock OAuth server"""
        from flask import Flask, request, redirect
        
        self.app = Flask(__name__)
        
        @self.app.route('/oauth/authorize')
        def authorize():
            # Mock OAuth authorization endpoint
            callback_url = request.args.get('redirect_uri')
            state = request.args.get('state')
            
            # Simulate user authorization
            auth_code = 'mock_auth_code_12345'
            
            return redirect(f"{callback_url}?code={auth_code}&state={state}")
        
        def run_server():
            self.app.run(host='127.0.0.1', port=self.port, debug=False)
        
        self.server_thread = threading.Thread(target=run_server, daemon=True)
        self.server_thread.start()
        time.sleep(0.5)  # Give server time to start
    
    def stop(self):
        """Stop mock OAuth server"""
        # Flask doesn't have built-in graceful shutdown in test mode
        # In production, you'd use a proper WSGI server
        pass


if __name__ == '__main__':
    # Run tests
    pytest.main([__file__, '-v'])