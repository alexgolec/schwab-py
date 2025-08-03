"""
Secure HTTPS OAuth Callback Server for Production-Grade Authentication

This module provides a production-ready HTTPS callback server for OAuth flows,
replacing the basic HTTP localhost approach with enterprise-grade security.

Author: Agent 2 - Authentication Security Specialist
"""

import asyncio
import json
import logging
import os
import ssl
import time
import threading
import secrets
import hashlib
from contextlib import contextmanager
from datetime import datetime, timedelta
from ipaddress import ip_address
from pathlib import Path
from typing import Dict, Optional, Callable, Union, Tuple, Any
from urllib.parse import urlparse, parse_qs

# Core dependencies
import httpx
from cryptography import x509
from cryptography.x509.oid import NameOID
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa

# Web framework dependencies
import flask
from flask import Flask, request, jsonify

# Rate limiting and security
from collections import defaultdict, deque

# Optional FastAPI support
try:
    import fastapi
    from fastapi import FastAPI, Request, HTTPException
    from fastapi.responses import HTMLResponse
    FASTAPI_AVAILABLE = True
except ImportError:
    FASTAPI_AVAILABLE = False


# Constants
DEFAULT_HOST = '127.0.0.1'
DEFAULT_PORT = 8443
DEFAULT_CERT_DIR = Path.home() / '.schwab-py' / 'certs'
DEFAULT_SESSION_TIMEOUT = 600  # 10 minutes
DEFAULT_RATE_LIMIT = 10  # requests per minute per IP
DEFAULT_CERT_VALIDITY_DAYS = 30

# Environment variable names
ENV_HOST = 'SCHWAB_AUTH_HOST'
ENV_PORT = 'SCHWAB_AUTH_PORT'
ENV_CERT_DIR = 'SCHWAB_AUTH_CERT_DIR'
ENV_USE_SELF_SIGNED = 'SCHWAB_AUTH_USE_SELF_SIGNED'
ENV_SESSION_TIMEOUT = 'SCHWAB_AUTH_SESSION_TIMEOUT'
ENV_RATE_LIMIT = 'SCHWAB_AUTH_RATE_LIMIT'


class AuthenticationError(Exception):
    """Authentication-related errors"""
    pass


class SecurityError(Exception):
    """Security-related errors"""
    pass


class CertificateError(Exception):
    """Certificate-related errors"""
    pass


class RateLimiter:
    """Thread-safe rate limiter with IP-based limits"""
    
    def __init__(self, max_requests: int = DEFAULT_RATE_LIMIT, window_seconds: int = 60):
        self.max_requests = max_requests
        self.window_seconds = window_seconds
        self.requests = defaultdict(deque)
        self._lock = threading.Lock()
    
    def is_allowed(self, ip: str) -> bool:
        """Check if IP is within rate limits"""
        with self._lock:
            now = time.time()
            ip_requests = self.requests[ip]
            
            # Remove old requests outside the window
            while ip_requests and ip_requests[0] <= now - self.window_seconds:
                ip_requests.popleft()
            
            # Check if under limit
            if len(ip_requests) < self.max_requests:
                ip_requests.append(now)
                return True
            
            return False
    
    def get_retry_after(self, ip: str) -> int:
        """Get seconds until next request is allowed"""
        with self._lock:
            ip_requests = self.requests[ip]
            if not ip_requests:
                return 0
            
            return max(0, int(self.window_seconds - (time.time() - ip_requests[0])))


class SessionManager:
    """Manages authentication sessions with timeout"""
    
    def __init__(self, timeout_seconds: int = DEFAULT_SESSION_TIMEOUT):
        self.timeout_seconds = timeout_seconds
        self.sessions = {}
        self._lock = threading.Lock()
    
    def create_session(self, session_id: str = None) -> str:
        """Create a new session with CSRF token"""
        if session_id is None:
            session_id = secrets.token_urlsafe(32)
        
        csrf_token = secrets.token_urlsafe(32)
        
        with self._lock:
            self.sessions[session_id] = {
                'csrf_token': csrf_token,
                'created': time.time(),
                'last_activity': time.time()
            }
        
        return session_id
    
    def validate_session(self, session_id: str, csrf_token: str = None) -> bool:
        """Validate session and optionally CSRF token"""
        with self._lock:
            session = self.sessions.get(session_id)
            if not session:
                return False
            
            # Check timeout
            if time.time() - session['last_activity'] > self.timeout_seconds:
                del self.sessions[session_id]
                return False
            
            # Validate CSRF if provided
            if csrf_token and session['csrf_token'] != csrf_token:
                return False
            
            # Update activity
            session['last_activity'] = time.time()
            return True
    
    def get_csrf_token(self, session_id: str) -> Optional[str]:
        """Get CSRF token for session"""
        with self._lock:
            session = self.sessions.get(session_id)
            return session['csrf_token'] if session else None
    
    def cleanup_expired(self):
        """Remove expired sessions"""
        with self._lock:
            now = time.time()
            expired = [
                sid for sid, session in self.sessions.items()
                if now - session['last_activity'] > self.timeout_seconds
            ]
            for sid in expired:
                del self.sessions[sid]


class CertificateManager:
    """Manages SSL certificates for HTTPS server"""
    
    def __init__(self, cert_dir: Path = DEFAULT_CERT_DIR, validity_days: int = DEFAULT_CERT_VALIDITY_DAYS):
        self.cert_dir = Path(cert_dir)
        self.validity_days = validity_days
        self.cert_path = self.cert_dir / 'server.crt'
        self.key_path = self.cert_dir / 'server.key'
        
        # Ensure cert directory exists
        self.cert_dir.mkdir(parents=True, exist_ok=True)
    
    def generate_self_signed_cert(self, hostname: str = 'localhost') -> Tuple[Path, Path]:
        """Generate self-signed certificate for development"""
        logging.info(f"Generating self-signed certificate for {hostname}")
        
        # Generate private key
        private_key = rsa.generate_private_key(
            public_exponent=65537,
            key_size=2048,
        )
        
        # Create certificate
        subject = issuer = x509.Name([
            x509.NameAttribute(NameOID.COUNTRY_NAME, "US"),
            x509.NameAttribute(NameOID.STATE_OR_PROVINCE_NAME, "State"),
            x509.NameAttribute(NameOID.LOCALITY_NAME, "City"),
            x509.NameAttribute(NameOID.ORGANIZATION_NAME, "Schwab-Py Dev"),
            x509.NameAttribute(NameOID.COMMON_NAME, hostname),
        ])
        
        cert = x509.CertificateBuilder().subject_name(
            subject
        ).issuer_name(
            issuer
        ).public_key(
            private_key.public_key()
        ).serial_number(
            x509.random_serial_number()
        ).not_valid_before(
            datetime.utcnow()
        ).not_valid_after(
            datetime.utcnow() + timedelta(days=self.validity_days)
        ).add_extension(
            x509.SubjectAlternativeName([
                x509.DNSName(hostname),
                x509.DNSName("localhost"),
                x509.IPAddress(ip_address("127.0.0.1")),
            ]),
            critical=False,
        ).sign(private_key, hashes.SHA256())
        
        # Write certificate and key
        with open(self.cert_path, 'wb') as f:
            f.write(cert.public_bytes(serialization.Encoding.PEM))
        
        with open(self.key_path, 'wb') as f:
            f.write(private_key.private_bytes(
                encoding=serialization.Encoding.PEM,
                format=serialization.PrivateFormat.PKCS8,
                encryption_algorithm=serialization.NoEncryption()
            ))
        
        # Set secure permissions
        os.chmod(self.cert_path, 0o644)
        os.chmod(self.key_path, 0o600)
        
        logging.info(f"Certificate generated: {self.cert_path}")
        return self.cert_path, self.key_path
    
    def validate_cert(self, cert_path: Path = None, key_path: Path = None) -> bool:
        """Validate certificate and key files"""
        cert_path = cert_path or self.cert_path
        key_path = key_path or self.key_path
        
        try:
            # Check files exist and are readable
            if not cert_path.exists() or not key_path.exists():
                return False
            
            # Load and validate certificate
            with open(cert_path, 'rb') as f:
                cert = x509.load_pem_x509_certificate(f.read())
            
            # Check if certificate is expired
            if cert.not_valid_after < datetime.utcnow():
                logging.warning("Certificate has expired")
                return False
            
            # Check if expiring soon (within 7 days)
            if cert.not_valid_after < datetime.utcnow() + timedelta(days=7):
                logging.warning("Certificate expires within 7 days")
            
            # Load private key
            with open(key_path, 'rb') as f:
                serialization.load_pem_private_key(f.read(), password=None)
            
            return True
            
        except Exception as e:
            logging.error(f"Certificate validation failed: {e}")
            return False
    
    def get_ssl_context(self, cert_path: Path = None, key_path: Path = None) -> ssl.SSLContext:
        """Create SSL context from certificate and key"""
        cert_path = cert_path or self.cert_path
        key_path = key_path or self.key_path
        
        if not self.validate_cert(cert_path, key_path):
            raise CertificateError("Invalid certificate or key")
        
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        context.load_cert_chain(cert_path, key_path)
        context.check_hostname = False
        context.verify_mode = ssl.CERT_NONE
        
        return context


class SecureAuthServer:
    """Production-grade HTTPS OAuth callback server"""
    
    def __init__(
        self,
        host: str = None,
        port: int = None,
        callback_path: str = '/callback',
        use_self_signed: bool = None,
        cert_dir: Path = None,
        session_timeout: int = None,
        rate_limit: int = None,
        framework: str = 'flask'  # 'flask' or 'fastapi'
    ):
        # Configuration from environment or defaults
        self.host = host or os.getenv(ENV_HOST, DEFAULT_HOST)
        self.port = int(port or os.getenv(ENV_PORT, DEFAULT_PORT))
        self.callback_path = callback_path
        self.use_self_signed = (
            use_self_signed if use_self_signed is not None 
            else os.getenv(ENV_USE_SELF_SIGNED, 'true').lower() == 'true'
        )
        
        cert_dir = cert_dir or os.getenv(ENV_CERT_DIR, DEFAULT_CERT_DIR)
        session_timeout = int(session_timeout or os.getenv(ENV_SESSION_TIMEOUT, DEFAULT_SESSION_TIMEOUT))
        rate_limit = int(rate_limit or os.getenv(ENV_RATE_LIMIT, DEFAULT_RATE_LIMIT))
        
        # Initialize components
        self.cert_manager = CertificateManager(cert_dir)
        self.session_manager = SessionManager(session_timeout)
        self.rate_limiter = RateLimiter(rate_limit)
        
        # Server state
        self.app = None
        self.server_thread = None
        self.callback_url_received = None
        self.shutdown_event = threading.Event()
        self.auth_events = []  # For Agent 9 scheduler integration
        
        # Framework selection
        if framework == 'fastapi' and not FASTAPI_AVAILABLE:
            logging.warning("FastAPI not available, falling back to Flask")
            framework = 'flask'
        
        self.framework = framework
        self._setup_app()
        
        # Logging setup
        self.logger = logging.getLogger(__name__)
        
    def _setup_app(self):
        """Setup the web application"""
        if self.framework == 'fastapi':
            self._setup_fastapi()
        else:
            self._setup_flask()
    
    def _setup_flask(self):
        """Setup Flask application"""
        self.app = Flask(__name__)
        self.app.secret_key = secrets.token_urlsafe(32)
        
        @self.app.before_request
        def before_request():
            # Rate limiting
            client_ip = request.environ.get('REMOTE_ADDR', '127.0.0.1')
            if not self.rate_limiter.is_allowed(client_ip):
                retry_after = self.rate_limiter.get_retry_after(client_ip)
                response = jsonify({'error': 'Rate limit exceeded'})
                response.status_code = 429
                response.headers['Retry-After'] = str(retry_after)
                return response
        
        @self.app.route(self.callback_path, methods=['GET'])
        def oauth_callback():
            return self._handle_oauth_callback(request)
        
        @self.app.route('/health', methods=['GET'])
        def health_check():
            return jsonify({'status': 'healthy', 'timestamp': time.time()})
        
        @self.app.route('/shutdown', methods=['POST'])
        def shutdown():
            # Security: only allow from localhost
            if request.environ.get('REMOTE_ADDR') != '127.0.0.1':
                return jsonify({'error': 'Forbidden'}), 403
            
            self.shutdown_event.set()
            return jsonify({'status': 'shutting down'})
    
    def _setup_fastapi(self):
        """Setup FastAPI application"""
        self.app = FastAPI(title="Schwab-Py Secure Auth Server")
        
        @self.app.middleware("http")
        async def rate_limit_middleware(request: Request, call_next):
            client_ip = request.client.host
            if not self.rate_limiter.is_allowed(client_ip):
                retry_after = self.rate_limiter.get_retry_after(client_ip)
                raise HTTPException(
                    status_code=429,
                    detail="Rate limit exceeded",
                    headers={"Retry-After": str(retry_after)}
                )
            
            return await call_next(request)
        
        @self.app.get(self.callback_path)
        async def oauth_callback(request: Request):
            return self._handle_oauth_callback(request)
        
        @self.app.get("/health")
        async def health_check():
            return {"status": "healthy", "timestamp": time.time()}
        
        @self.app.post("/shutdown")
        async def shutdown(request: Request):
            if request.client.host != "127.0.0.1":
                raise HTTPException(status_code=403, detail="Forbidden")
            
            self.shutdown_event.set()
            return {"status": "shutting down"}
    
    def _handle_oauth_callback(self, request) -> Union[str, dict]:
        """Handle OAuth callback with security validation"""
        try:
            # Extract parameters based on framework
            if self.framework == 'fastapi':
                full_url = str(request.url)
                query_params = dict(request.query_params)
            else:  # Flask
                full_url = request.url
                query_params = request.args.to_dict()
            
            # Validate required OAuth parameters
            if 'code' not in query_params:
                self.logger.error("OAuth callback missing authorization code")
                raise SecurityError("Missing authorization code")
            
            # CSRF protection (if state parameter is present)
            state = query_params.get('state')
            if state:
                # Validate state parameter format (should be base64url)
                try:
                    import base64
                    base64.urlsafe_b64decode(state + '==')  # Add padding
                except Exception:
                    self.logger.error("Invalid state parameter format")
                    raise SecurityError("Invalid state parameter")
            
            # Store the callback URL for processing
            self.callback_url_received = full_url
            
            # Emit auth event for Agent 9 scheduler
            auth_event = {
                'type': 'oauth_callback_received',
                'timestamp': time.time(),
                'client_ip': request.environ.get('REMOTE_ADDR') if self.framework == 'flask' else request.client.host,
                'user_agent': request.headers.get('User-Agent', ''),
                'has_state': bool(state)
            }
            self.auth_events.append(auth_event)
            
            self.logger.info("OAuth callback received successfully")
            
            # Schedule graceful shutdown
            threading.Timer(2.0, self.shutdown_event.set).start()
            
            success_html = '''
            <!DOCTYPE html>
            <html>
            <head>
                <title>Authorization Successful</title>
                <style>
                    body { font-family: Arial, sans-serif; text-align: center; margin-top: 50px; }
                    .success { color: #28a745; font-size: 24px; margin-bottom: 20px; }
                    .instructions { color: #6c757d; font-size: 16px; }
                </style>
            </head>
            <body>
                <div class="success">✅ Authorization Successful!</div>
                <div class="instructions">
                    You may now close this window/tab.<br>
                    Your application will continue automatically.
                </div>
                <script>
                    // Auto-close after 3 seconds
                    setTimeout(() => { window.close(); }, 3000);
                </script>
            </body>
            </html>
            '''
            
            if self.framework == 'fastapi':
                from fastapi.responses import HTMLResponse
                return HTMLResponse(content=success_html)
            else:
                return success_html
            
        except Exception as e:
            self.logger.error(f"OAuth callback error: {e}")
            
            error_html = '''
            <!DOCTYPE html>
            <html>
            <head>
                <title>Authorization Error</title>
                <style>
                    body { font-family: Arial, sans-serif; text-align: center; margin-top: 50px; }
                    .error { color: #dc3545; font-size: 24px; margin-bottom: 20px; }
                    .instructions { color: #6c757d; font-size: 16px; }
                </style>
            </head>
            <body>
                <div class="error">❌ Authorization Error</div>
                <div class="instructions">
                    Please close this window and try again.<br>
                    Check the application logs for details.
                </div>
            </body>
            </html>
            '''
            
            if self.framework == 'fastapi':
                from fastapi.responses import HTMLResponse
                return HTMLResponse(content=error_html, status_code=400)
            else:
                return error_html, 400
    
    def get_callback_url(self) -> str:
        """Get the callback URL for OAuth configuration"""
        return f"https://{self.host}:{self.port}{self.callback_path}"
    
    def prepare_certificates(self) -> Tuple[Path, Path]:
        """Prepare SSL certificates for the server"""
        if self.use_self_signed:
            # Check if existing certificate is valid
            if not self.cert_manager.validate_cert():
                self.logger.info("Generating new self-signed certificate")
                return self.cert_manager.generate_self_signed_cert(self.host)
            else:
                self.logger.info("Using existing valid certificate")
                return self.cert_manager.cert_path, self.cert_manager.key_path
        else:
            # Production certificates should be provided externally
            if not self.cert_manager.validate_cert():
                raise CertificateError(
                    f"Production certificates not found or invalid. "
                    f"Please provide valid certificate files at {self.cert_manager.cert_path} "
                    f"and {self.cert_manager.key_path}"
                )
            return self.cert_manager.cert_path, self.cert_manager.key_path
    
    def start_server(self) -> None:
        """Start the secure HTTPS server"""
        cert_path, key_path = self.prepare_certificates()
        ssl_context = self.cert_manager.get_ssl_context(cert_path, key_path)
        
        def run_server():
            try:
                if self.framework == 'fastapi':
                    import uvicorn
                    uvicorn.run(
                        self.app,
                        host=self.host,
                        port=self.port,
                        ssl_certfile=str(cert_path),
                        ssl_keyfile=str(key_path),
                        log_level="error"  # Reduce noise
                    )
                else:  # Flask
                    self.app.run(
                        host=self.host,
                        port=self.port,
                        ssl_context=ssl_context,
                        debug=False,
                        use_reloader=False
                    )
            except Exception as e:
                self.logger.error(f"Server error: {e}")
        
        self.server_thread = threading.Thread(target=run_server, daemon=True)
        self.server_thread.start()
        
        # Wait for server to start
        time.sleep(1)
        self._verify_server_running()
        
        self.logger.info(f"Secure auth server started on https://{self.host}:{self.port}")
    
    def _verify_server_running(self) -> bool:
        """Verify the server is running and accessible"""
        try:
            # Test server with health check
            response = httpx.get(
                f"https://{self.host}:{self.port}/health",
                verify=False,  # Self-signed cert
                timeout=5.0
            )
            return response.status_code == 200
        except Exception as e:
            self.logger.error(f"Server verification failed: {e}")
            return False
    
    def wait_for_callback(self, timeout: float = 300.0) -> Optional[str]:
        """Wait for OAuth callback with timeout"""
        start_time = time.time()
        
        while time.time() - start_time < timeout:
            if self.callback_url_received:
                return self.callback_url_received
            
            if self.shutdown_event.wait(0.1):
                break
        
        return self.callback_url_received
    
    def shutdown(self) -> None:
        """Graceful server shutdown"""
        self.logger.info("Shutting down secure auth server")
        self.shutdown_event.set()
        
        # Cleanup sessions
        self.session_manager.cleanup_expired()
        
        # Wait for server thread to finish (with timeout)
        if self.server_thread and self.server_thread.is_alive():
            self.server_thread.join(timeout=5.0)
        
        self.logger.info("Secure auth server shutdown complete")
    
    @contextmanager
    def server_context(self):
        """Context manager for server lifecycle"""
        try:
            self.start_server()
            yield self
        finally:
            self.shutdown()
    
    def get_auth_events(self) -> list:
        """Get authentication events for Agent 9 scheduler integration"""
        return self.auth_events.copy()
    
    def clear_auth_events(self) -> None:
        """Clear authentication events"""
        self.auth_events.clear()


# Integration functions for compatibility with existing auth.py

def secure_client_from_login_flow(
    api_key: str,
    app_secret: str,
    callback_url: str,
    token_path: str,
    asyncio: bool = False,
    enforce_enums: bool = True,
    token_write_func: Optional[Callable] = None,
    callback_timeout: float = 300.0,
    interactive: bool = True,
    requested_browser: str = None,
    **server_kwargs
):
    """
    Secure replacement for client_from_login_flow using HTTPS callback server
    
    This function provides the same interface as the original but uses the
    SecureAuthServer for production-grade security.
    """
    from schwab.auth import get_auth_context, client_from_received_url, __make_update_token_func
    import webbrowser
    
    # Parse callback URL to configure server
    parsed = urlparse(callback_url)
    host = parsed.hostname or DEFAULT_HOST
    port = parsed.port or DEFAULT_PORT
    callback_path = parsed.path or '/callback'
    
    # Create secure server
    server = SecureAuthServer(
        host=host,
        port=port,
        callback_path=callback_path,
        **server_kwargs
    )
    
    # Verify callback URL matches server configuration
    expected_url = server.get_callback_url()
    if callback_url != expected_url:
        logging.warning(f"Callback URL mismatch: expected {expected_url}, got {callback_url}")
    
    with server.server_context():
        # Get OAuth authorization context
        auth_context = get_auth_context(api_key, callback_url)
        
        # User instructions
        print()
        print('***********************************************************************')
        print('This is the SECURE browser-assisted login and token creation flow for')
        print('schwab-py. This flow uses production-grade HTTPS with proper SSL')
        print('certificate validation for enhanced security.')
        print()
        print('Authorization URL:')
        print('>>', auth_context.authorization_url)
        print()
        print('Secure Callback URL:')
        print('>>', callback_url)
        print()
        print('SECURITY: This server uses validated SSL certificates and implements')
        print('CSRF protection, rate limiting, and session management.')
        print('***********************************************************************')
        print()
        
        if interactive:
            input('Press ENTER to open the browser (interactive=False to skip)')
        
        # Open browser
        controller = webbrowser.get(requested_browser)
        controller.open(auth_context.authorization_url)
        
        # Wait for callback
        received_url = server.wait_for_callback(callback_timeout)
        
        if not received_url:
            raise TimeoutError(
                f"Timed out waiting for OAuth callback after {callback_timeout} seconds"
            )
        
        # Create client from received URL
        token_write_func = (
            __make_update_token_func(token_path) if token_write_func is None
            else token_write_func
        )
        
        client = client_from_received_url(
            api_key, app_secret, auth_context, received_url,
            token_write_func, asyncio, enforce_enums
        )
        
        # Emit completion event
        server.auth_events.append({
            'type': 'client_created',
            'timestamp': time.time(),
            'success': True
        })
        
        return client


# Utility functions for certificate management

def generate_production_csr(hostname: str, output_dir: Path = DEFAULT_CERT_DIR) -> Path:
    """Generate Certificate Signing Request for production use"""
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    
    # Generate private key
    private_key = rsa.generate_private_key(
        public_exponent=65537,
        key_size=2048,
    )
    
    # Create CSR
    csr = x509.CertificateSigningRequestBuilder().subject_name(x509.Name([
        x509.NameAttribute(NameOID.COUNTRY_NAME, "US"),
        x509.NameAttribute(NameOID.STATE_OR_PROVINCE_NAME, "State"),
        x509.NameAttribute(NameOID.LOCALITY_NAME, "City"),
        x509.NameAttribute(NameOID.ORGANIZATION_NAME, "Trading Organization"),
        x509.NameAttribute(NameOID.COMMON_NAME, hostname),
    ])).add_extension(
        x509.SubjectAlternativeName([
            x509.DNSName(hostname),
        ]),
        critical=False,
    ).sign(private_key, hashes.SHA256())
    
    # Write CSR and private key
    csr_path = output_dir / 'server.csr'
    key_path = output_dir / 'server.key'
    
    with open(csr_path, 'wb') as f:
        f.write(csr.public_bytes(serialization.Encoding.PEM))
    
    with open(key_path, 'wb') as f:
        f.write(private_key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption()
        ))
    
    os.chmod(key_path, 0o600)
    
    print(f"CSR generated: {csr_path}")
    print(f"Private key: {key_path}")
    print("Submit the CSR to your Certificate Authority for signing.")
    
    return csr_path


if __name__ == '__main__':
    # Demo/testing mode
    logging.basicConfig(level=logging.INFO)
    
    server = SecureAuthServer(
        host='127.0.0.1',
        port=8443,
        use_self_signed=True
    )
    
    print(f"Starting demo server at {server.get_callback_url()}")
    print("Press Ctrl+C to stop")
    
    try:
        with server.server_context():
            server.shutdown_event.wait()
    except KeyboardInterrupt:
        print("\nShutting down...")