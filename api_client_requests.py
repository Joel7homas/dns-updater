# api_client_requests.py
"""
Requests-based implementation of the OPNsense API client.
"""
import os
import time
import logging
import socket
import requests
import urllib3
import re
from requests.adapters import HTTPAdapter
from requests.packages.urllib3.util.retry import Retry
from typing import Dict, Any, Optional, Union

from api_client_core import OPNsenseAPICore

# Get module logger
logger = logging.getLogger('dns_updater.api')

class OPNsenseAPI(OPNsenseAPICore):
    """
    Complete OPNsense API client implementation using requests library.
    """
    def __init__(self, base_url: str, key: str, secret: str):
        """Initialize the OPNsense API client with credentials."""
        super().__init__(base_url, key, secret)
        
        # Create the session with appropriate settings
        self.session = self._create_session()
        logger.info(f"Requests-based API client initialized")
        
        # Test connection initially to detect any issues
        self._test_connection()
        
    def _create_session(self) -> requests.Session:
        """Create and configure a requests session with retry logic."""
        # Set lower-level socket timeout to prevent connection hanging
        socket.setdefaulttimeout(self.config.socket_timeout)
        
        # Configure retry strategy
        retry_strategy = Retry(
            total=self.config.retry_count,
            backoff_factor=self.config.backoff_factor,
            status_forcelist=[429, 500, 502, 503, 504],
            allowed_methods=["HEAD", "GET", "POST"],
            raise_on_redirect=False,
            raise_on_status=False
        )
        
        # Create session
        adapter = HTTPAdapter(max_retries=retry_strategy)
        session = requests.Session()
        session.mount("https://", adapter)
        session.mount("http://", adapter)
        session.auth = self.auth
        
        # Use tuple for connect and read timeouts (important distinction!)
        session.timeout = (self.config.connect_timeout, self.config.read_timeout)
        
        # Set SSL verification according to configuration
        session.verify = self.config.verify_ssl
        if not self.config.verify_ssl:
            urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
            logger.warning("SSL verification disabled - SECURITY RISK")
        
        # Force HTTP/1.1 if configured (can help with compatibility issues)
        if self.config.force_http1:
            if hasattr(requests.packages.urllib3.util, 'ALPN_PROTOCOLS'):
                requests.packages.urllib3.util.ALPN_PROTOCOLS = ['http/1.1']
                logger.info("Forcing HTTP/1.1 via ALPN")
            else:
                # Alternative approach to force HTTP/1.1
                session.config = {'http_version': '1.1'}
                logger.info("Forcing HTTP/1.1 via session config")
        
        return session
    
    def _test_connection(self) -> bool:
        """Test API connection and adjust settings if needed."""
        logger.info("Testing API connection...")
        try:
            # Set shorter timeout for the test
            original_timeout = self.session.timeout
            self.session.timeout = (5, 10)
            
            start_time = time.time()
            url = f"{self.base_url}/core/firmware/status"
            
            logger.debug(f"Testing connection to {url}")
            response = self.session.get(url)
            
            elapsed = time.time() - start_time
            logger.info(f"API connection test successful ({elapsed:.2f}s)")
            
            # Restore original timeout
            self.session.timeout = original_timeout
            self.is_connected = True
            return True
            
        except requests.exceptions.RequestException as e:
            elapsed = time.time() - start_time
            logger.warning(f"API connection test failed after {elapsed:.2f}s: {e}")
            
            # Try to identify slow connections and adjust timeouts
            if isinstance(e, requests.exceptions.ConnectTimeout):
                new_timeout = self.config.connect_timeout * 2
                logger.info(f"Increasing connect timeout to {new_timeout}s")
                self.session.timeout = (new_timeout, self.config.read_timeout)
                
            # Restore original timeout
            self.session.timeout = original_timeout
            return False
            
        finally:
            # Restore original socket timeout
            socket.setdefaulttimeout(self.original_socket_timeout)
            
    def get(self, endpoint: str, params: Optional[Dict] = None) -> Dict:
        """Make a GET request to the OPNsense API."""
        self._rate_limit()
        url = f"{self.base_url}/{endpoint}"
        
        # Temporarily set socket timeout
        socket.setdefaulttimeout(self.config.socket_timeout)
        
        try:
            logger.debug(f"GET {url}")
            start_time = time.time()
            
            response = self.session.get(url, params=params)
            
            elapsed = time.time() - start_time
            logger.debug(f"GET request completed in {elapsed:.2f}s")
            
            return self._handle_response(response)
            
        except requests.exceptions.RequestException as e:
            # Redact any sensitive information in the error message
            error_msg = str(e)
            safe_error = self._redact_sensitive_data(error_msg)
            return self._handle_error(Exception(safe_error), "GET", url)
            
        finally:
            # Restore original socket timeout
            socket.setdefaulttimeout(self.original_socket_timeout)
    
    def post(self, endpoint: str, data: Any = None) -> Dict:
        """Make a POST request to the OPNsense API."""
        self._rate_limit()
        url = f"{self.base_url}/{endpoint}"
    
        # Temporarily set socket timeout
        socket.setdefaulttimeout(self.config.socket_timeout)
    
        try:
            logger.debug(f"POST {url}")
            start_time = time.time()
        
            # Fix: Always use JSON format - empty JSON object for empty data
            if data is None:
                response = self.session.post(url, json={})  # Changed from data="" to json={}
            else:
                response = self.session.post(url, json=data)
        
            elapsed = time.time() - start_time
            logger.debug(f"POST request completed in {elapsed:.2f}s")
        
            return self._handle_response(response)
        
        except requests.exceptions.RequestException as e:
            # Redact any sensitive information in the error message
            error_msg = str(e)
            safe_error = self._redact_sensitive_data(error_msg)
            return self._handle_error(Exception(safe_error), "POST", url)
        
        finally:
            # Restore original socket timeout
            socket.setdefaulttimeout(self.original_socket_timeout)
    
    def _handle_response(self, response: requests.Response) -> Dict:
        """Process and validate API response."""
        try:
            response.raise_for_status()
            self.is_connected = True
            self.connection_errors = 0
            
            # Reset alternate method flag if we're using it and this succeeded
            if self.using_alternate_method:
                logger.info("Switching back to primary connection method for future requests")
                self.using_alternate_method = False
            
            # Only try to parse JSON for successful responses
            try:
                return response.json()
            except ValueError:
                # Redact any sensitive data that might be in the response
                safe_response = self._redact_sensitive_data(response.text[:100])
                logger.warning(f"Invalid JSON response: {safe_response}")
                return {"status": "error", "message": "Invalid JSON response"}
            
        except requests.exceptions.HTTPError as e:
            # Redact any sensitive information in the error response
            error_msg = str(e)
            safe_error = self._redact_sensitive_data(error_msg)
            logger.error(f"HTTP error: {safe_error}")
            
            # Also redact response content for logging
            safe_content = self._redact_sensitive_data(response.text[:200])
            logger.debug(f"Response content: {safe_content}")
            return {"status": "error", "message": safe_error}

    def _redact_sensitive_data(self, text: str) -> str:
        """Redact potentially sensitive information from text."""
        if not text:
            return text
            
        # List of patterns to redact
        patterns = [
            # API keys and tokens (hex format)
            r'([a-zA-Z0-9]{8,}[-_]?[a-zA-Z0-9]{4,}[-_]?[a-zA-Z0-9]{4,}[-_]?[a-zA-Z0-9]{4,}[-_]?[a-zA-Z0-9]{12,})',
            # Basic auth credentials
            r'([a-zA-Z0-9+/=]{20,}:)?[a-zA-Z0-9+/=]{20,}',
            # URL with credentials
            r'(https?://)([^:]+):([^@]+)@',
            # OPNsense specific API key format
            r'([A-Za-z0-9]{16,})'
        ]
        
        # Apply redaction
        redacted_text = text
        for pattern in patterns:
            redacted_text = re.sub(pattern, 'REDACTED', redacted_text)
        
        return redacted_text
    
