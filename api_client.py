# api_client.py
import os
import time
import logging
import requests
import json
from typing import Dict, Any, Optional, Union, List
from requests.adapters import HTTPAdapter
from requests.packages.urllib3.util.retry import Retry

# Get module logger
logger = logging.getLogger('dns_updater.api')

class OPNsenseAPI:
    def __init__(self, base_url: str, key: str, secret: str):
        """Initialize the OPNsense API client with credentials."""
        self.base_url = base_url
        # Add debug prints for certificate inspection
        logger.debug(f"Initializing API client for {base_url}")
        logger.debug(f"CA Bundle path: {requests.certs.where()}")
        
        # Check if we should verify SSL certificates
        self.verify_ssl = os.environ.get('VERIFY_SSL', 'true').lower() == 'true'
        logger.info(f"SSL verification: {'enabled' if self.verify_ssl else 'disabled'}")
        
        # Create the session with appropriate settings
        self.session = self._create_session(key, secret)
        self.last_api_call = 0
        self.min_call_interval = 1.0  # Minimum seconds between API calls
        
        # Track connection status
        self.is_connected = False
        self.connection_errors = 0
        self.max_connection_errors = 5
        
        logger.info(f"Initialized OPNsense API client for {base_url}")
        
    def _create_session(self, key: str, secret: str) -> requests.Session:
        """Create and configure a requests session with retry logic."""
        timeout = int(os.environ.get('API_TIMEOUT', '10'))
        retry_count = int(os.environ.get('API_RETRY_COUNT', '3'))
        backoff_factor = float(os.environ.get('API_BACKOFF_FACTOR', '0.3'))
        
        retry_strategy = Retry(
            total=retry_count,
            backoff_factor=backoff_factor,
            status_forcelist=[429, 500, 502, 503, 504],
            allowed_methods=["HEAD", "GET", "POST"],
            raise_on_redirect=False,
            raise_on_status=False
        )
        
        adapter = HTTPAdapter(max_retries=retry_strategy)
        session = requests.Session()
        session.mount("https://", adapter)
        session.mount("http://", adapter)
        session.auth = (key, secret)
        session.timeout = timeout
        
        # Set SSL verification according to environment setting
        session.verify = self.verify_ssl
        
        # If SSL verification is disabled, suppress warnings
        if not self.verify_ssl:
            import urllib3
            urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
        
        return session
    
    def _rate_limit(self) -> None:
        """Enforce rate limiting between API calls."""
        now = time.time()
        elapsed = now - self.last_api_call
        
        if elapsed < self.min_call_interval:
            sleep_time = self.min_call_interval - elapsed
            logger.debug(f"Rate limiting: sleeping {sleep_time:.2f}s")
            time.sleep(sleep_time)
            
        self.last_api_call = time.time()
    
    def get(self, endpoint: str, params: Optional[Dict] = None) -> Dict:
        """Make a GET request to the OPNsense API."""
        self._rate_limit()
        url = f"{self.base_url}/{endpoint}"
        
        try:
            logger.debug(f"GET {url}")
            response = self.session.get(url, params=params)
            return self._handle_response(response)
            
        except requests.exceptions.SSLError as e:
            logger.error(f"SSL Error: {e}")
            logger.error("Consider setting VERIFY_SSL=false if using self-signed certificates")
            return {"status": "error", "message": f"SSL Error: {str(e)}"}
            
        except requests.exceptions.RequestException as e:
            return self._handle_error(e, "GET", url)
    
    def post(self, endpoint: str, data: Any = None) -> Dict:
        """Make a POST request to the OPNsense API."""
        self._rate_limit()
        url = f"{self.base_url}/{endpoint}"
        
        try:
            logger.debug(f"POST {url}")
            response = self.session.post(url, json=data)
            return self._handle_response(response)
            
        except requests.exceptions.SSLError as e:
            logger.error(f"SSL Error: {e}")
            logger.error("Consider setting VERIFY_SSL=false if using self-signed certificates")
            return {"status": "error", "message": f"SSL Error: {str(e)}"}
            
        except requests.exceptions.RequestException as e:
            return self._handle_error(e, "POST", url)
    
    def _handle_response(self, response: requests.Response) -> Dict:
        """Process and validate API response."""
        try:
            response.raise_for_status()
            self.is_connected = True
            self.connection_errors = 0
            
            # Only try to parse JSON for successful responses
            try:
                return response.json()
            except ValueError:
                logger.warning(f"Invalid JSON response: {response.text[:100]}")
                return {"status": "error", "message": "Invalid JSON response"}
            
        except requests.exceptions.HTTPError as e:
            logger.error(f"HTTP error: {e}")
            logger.debug(f"Response content: {response.text[:200]}")
            return {"status": "error", "message": str(e)}
    
    def _handle_error(self, error: Exception, method: str, url: str) -> Dict:
        """Handle API request errors with appropriate logging."""
        self.connection_errors += 1
        
        if self.connection_errors >= self.max_connection_errors:
            self.is_connected = False
            logger.error(f"Maximum connection errors reached")
        
        logger.error(f"{method} {url} failed: {error}")
        return {"status": "error", "message": str(error)}

