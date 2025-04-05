# api_client_core.py
"""
Core OPNsense API client implementation with improved connection handling.
"""
import os
import time
import logging
import socket
from typing import Dict, Any, Optional, Union, List, Tuple

# Get module logger
logger = logging.getLogger('dns_updater.api')

class ConnectionConfig:
    """Configuration for connection parameters."""
    def __init__(self):
        """Load connection configuration from environment variables."""
        # Connection timeouts
        self.connect_timeout = int(os.environ.get('CONNECT_TIMEOUT', '5'))
        self.read_timeout = int(os.environ.get('READ_TIMEOUT', '30'))
        
        # Socket-level settings
        self.socket_timeout = float(os.environ.get('SOCKET_TIMEOUT', '5.0'))
        
        # Retry configuration
        self.retry_count = int(os.environ.get('API_RETRY_COUNT', '3'))
        self.backoff_factor = float(os.environ.get('API_BACKOFF_FACTOR', '0.3'))
        self.retry_max_time = int(os.environ.get('RETRY_MAX_TIME', '60'))
        
        # SSL verification
        self.verify_ssl = os.environ.get('VERIFY_SSL', 'true').lower() != 'false'
        
        # API rate limiting
        self.min_call_interval = float(os.environ.get('MIN_CALL_INTERVAL', '1.0'))
        
        # Protocol options
        self.use_ip_direct = os.environ.get('USE_IP_DIRECT', 'false').lower() == 'true'
        self.opnsense_ip = os.environ.get('OPNSENSE_IP', '')
        self.force_http1 = os.environ.get('FORCE_HTTP1', 'false').lower() == 'true'
        
        # Alternative methods
        self.use_curl_fallback = os.environ.get('USE_CURL_FALLBACK', 'false').lower() == 'true'
        
        # Connection handling
        self.max_connection_errors = int(os.environ.get('MAX_CONNECTION_ERRORS', '5'))
        self.reconnect_delay = float(os.environ.get('RECONNECT_DELAY', '5.0'))
        
        # DNS
        self.dns_cache_ttl = int(os.environ.get('DNS_CACHE_TTL', '60'))
        
        self._log_config()
        
    def _log_config(self):
        """Log the configuration settings."""
        logger.info(f"API Connection Configuration:")
        logger.info(f"- Connect timeout: {self.connect_timeout}s")
        logger.info(f"- Read timeout: {self.read_timeout}s")
        logger.info(f"- Socket timeout: {self.socket_timeout}s")
        logger.info(f"- Retry count: {self.retry_count}")
        logger.info(f"- Backoff factor: {self.backoff_factor}")
        logger.info(f"- Verify SSL: {self.verify_ssl}")
        logger.info(f"- Force HTTP/1: {self.force_http1}")
        
        if self.use_ip_direct and self.opnsense_ip:
            logger.info(f"- Using direct IP: {self.opnsense_ip}")
        if self.use_curl_fallback:
            logger.info(f"- Using curl fallback if needed")


class OPNsenseAPICore:
    """
    Core functionality for the OPNsense API client.
    """
    def __init__(self, base_url: str, key: str, secret: str):
        """Initialize the OPNsense API client with credentials."""
        self.base_url = base_url
        self.auth = (key, secret)
        self.config = ConnectionConfig()
        
        # Store original socket timeout
        self.original_socket_timeout = socket.getdefaulttimeout()
        
        # API state tracking
        self.is_connected = False
        self.connection_errors = 0
        self.last_api_call = 0
        self.using_alternate_method = False
        
        # Enable detailed logging for debugging
        if os.environ.get('LOG_LEVEL', '').upper() == 'DEBUG':
            self._enable_http_debugging()
            
        # Modify the base URL if using direct IP
        if self.config.use_ip_direct and self.config.opnsense_ip:
            self._use_direct_ip()
            
        logger.info(f"Initialized OPNsense API client core for {base_url}")
        
    def _enable_http_debugging(self):
        """Enable detailed HTTP debugging."""
        try:
            import http.client as http_client
            http_client.HTTPConnection.debuglevel = 1
            requests_log = logging.getLogger("requests.packages.urllib3")
            requests_log.setLevel(logging.DEBUG)
            requests_log.propagate = True
            logger.debug("HTTP debugging enabled")
        except Exception as e:
            logger.warning(f"Failed to enable HTTP debugging: {e}")
    
    def _use_direct_ip(self):
        """Convert base URL to use IP address directly."""
        try:
            from urllib.parse import urlparse, urlunparse
            parsed = urlparse(self.base_url)
            
            # Replace hostname with IP
            ip = self.config.opnsense_ip
            new_netloc = ip if ':' not in ip else f'[{ip}]'
            if parsed.port:
                new_netloc = f"{new_netloc}:{parsed.port}"
                
            self.base_url = urlunparse((
                parsed.scheme,
                new_netloc,
                parsed.path,
                parsed.params,
                parsed.query,
                parsed.fragment
            ))
            logger.info(f"Using direct IP connection: {self.base_url}")
        except Exception as e:
            logger.warning(f"Failed to use direct IP: {e}")
            
    def _rate_limit(self) -> None:
        """Enforce rate limiting between API calls."""
        now = time.time()
        elapsed = now - self.last_api_call
        
        if elapsed < self.config.min_call_interval:
            sleep_time = self.config.min_call_interval - elapsed
            logger.debug(f"Rate limiting: sleeping {sleep_time:.2f}s")
            time.sleep(sleep_time)
            
        self.last_api_call = time.time()
        
    def _handle_error(self, error: Exception, method: str, url: str) -> Dict:
        """Handle API request errors with appropriate logging."""
        self.connection_errors += 1
        
        # Try alternative method if max retries exhausted
        if self.connection_errors >= self.config.max_connection_errors:
            self.is_connected = False
            logger.error(f"Maximum connection errors reached ({self.connection_errors})")
            
            # Back off to avoid overwhelming the server
            logger.info(f"Waiting {self.config.reconnect_delay}s before next attempt")
            time.sleep(self.config.reconnect_delay)
        
        logger.error(f"{method} {url} failed: {error}")
        return {"status": "error", "message": str(error)}


    def get(self, endpoint: str, params: Optional[Dict] = None) -> Dict:
        """Make a GET request to the OPNsense API."""
        self._rate_limit()
        url = f"{self.base_url}/{endpoint}"
        logger.warning(f"Using minimally implemented GET method in core API client. Limited functionality.")
        
        try:
            import requests
            response = requests.get(
                url, 
                auth=self.auth, 
                params=params,
                verify=self.config.verify_ssl,
                timeout=(self.config.connect_timeout, self.config.read_timeout)
            )
            response.raise_for_status()
            return response.json()
        except Exception as e:
            logger.error(f"GET request failed: {e}")
            return {"status": "error", "message": str(e)}
    
    def post(self, endpoint: str, data: Any = None) -> Dict:
        """Make a POST request to the OPNsense API."""
        self._rate_limit()
        url = f"{self.base_url}/{endpoint}"
        logger.warning(f"Using minimally implemented POST method in core API client. Limited functionality.")
        
        try:
            import requests
            
            # Fix: Always use JSON format - empty JSON object for empty data
            if data is None:
                data = {}
                
            response = requests.post(
                url, 
                auth=self.auth, 
                json=data,
                verify=self.config.verify_ssl,
                timeout=(self.config.connect_timeout, self.config.read_timeout)
            )
            response.raise_for_status()
            return response.json()
        except Exception as e:
            logger.error(f"POST request failed: {e}")
            return {"status": "error", "message": str(e)}
