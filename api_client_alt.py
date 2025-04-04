# api_client_alt.py
"""
Alternative implementation methods for the OPNsense API client.
"""
import os
import time
import logging
import json
import subprocess
from typing import Dict, Any, Optional

from api_client_core import OPNsenseAPICore

# Get module logger
logger = logging.getLogger('dns_updater.api')

class OPNsenseAPICurl(OPNsenseAPICore):
    """
    OPNsense API client implementation using curl subprocess.
    
    This implementation is a fallback for systems where the requests
    library has connectivity issues.
    """
    def __init__(self, base_url: str, key: str, secret: str):
        """Initialize the OPNsense API client with credentials."""
        super().__init__(base_url, key, secret)
        
        # Check if curl is available
        self._check_curl()
        logger.info(f"Curl-based API client initialized")
    
    def _check_curl(self) -> bool:
        """Check if curl is available on the system."""
        try:
            result = subprocess.run(
                ["curl", "--version"], 
                capture_output=True, 
                text=True, 
                timeout=5
            )
            if result.returncode == 0:
                logger.info(f"Found curl: {result.stdout.splitlines()[0]}")
                return True
            else:
                logger.warning("Curl command returned non-zero exit code")
                return False
        except (subprocess.SubprocessError, FileNotFoundError) as e:
            logger.error(f"Curl not available: {e}")
            return False
    
    def get(self, endpoint: str, params: Optional[Dict] = None) -> Dict:
        """Make a GET request to the OPNsense API using curl."""
        self._rate_limit()
        
        # Build URL with params if provided
        url = f"{self.base_url}/{endpoint}"
        if params:
            # Simple URL param encoding
            param_str = "&".join(f"{k}={v}" for k, v in params.items())
            url = f"{url}?{param_str}"
        
        return self._curl_request("GET", url)
    
    def post(self, endpoint: str, data: Any = None) -> Dict:
        """Make a POST request to the OPNsense API using curl."""
        self._rate_limit()
        url = f"{self.base_url}/{endpoint}"
        return self._curl_request("POST", url, data)
    
    def _curl_request(self, method: str, url: str, data: Any = None) -> Dict:
        """Make a request using curl subprocess."""
        # Build curl command
        cmd = ["curl", "-s"]
        
        # Add method
        cmd.extend(["-X", method])
        
        # Add timeout options 
        cmd.extend(["--connect-timeout", str(self.config.connect_timeout)])
        
        # Calculate timeout - add adaptive timeout for Unbound operations
        operation_timeout = self.config.read_timeout
        if "unbound/service/" in url:
            # Unbound service operations need more time
            operation_timeout = max(45, operation_timeout)  # At least 45 seconds
        
        # Set the max-time option
        cmd.extend(["-m", str(self.config.connect_timeout + operation_timeout)])
        
        # Add extensive retry options for better reliability
        cmd.extend(["--retry", "3"])  # 3 retries
        cmd.extend(["--retry-delay", "2"])  # 2 second between retries
        cmd.extend(["--retry-max-time", "90"])  # Give up after 90 seconds of retries
        # Add crucial option for retry on all errors - not just transient ones
        cmd.extend(["--retry-all-errors"])
        
        # Add authentication
        cmd.extend(["-u", f"{self.auth[0]}:{self.auth[1]}"])
        
        # Add SSL options
        if not self.config.verify_ssl:
            cmd.append("-k")
            
        # Force HTTP/1.1 if configured
        if self.config.force_http1:
            cmd.append("--http1.1")
            
        # For POST requests, handle data or empty request
        if method.upper() == "POST":
            cmd.extend(["-H", "Content-Type: application/json"])
            if data is None:
                # For empty POST, add empty data
                cmd.extend(["-d", ""])
            else:
                cmd.extend(["-d", json.dumps(data)])
            
        # Add URL
        cmd.append(url)
        
        # Log command (with auth redacted)
        safe_cmd = cmd.copy()
        auth_index = safe_cmd.index("-u") if "-u" in safe_cmd else -1
        if auth_index >= 0:
            safe_cmd[auth_index+1] = "REDACTED"
        logger.debug(f"curl command: {' '.join(safe_cmd)}")
        
        # Execute command
        try:
            start_time = time.time()
            result = subprocess.run(
                cmd, 
                capture_output=True, 
                text=True, 
                timeout=self.config.connect_timeout + operation_timeout + 10  # Extra buffer
            )
            elapsed = time.time() - start_time
            
            if result.returncode != 0:
                logger.error(f"curl failed with code {result.returncode}: {result.stderr}")
                return {"status": "error", "message": result.stderr or "Unknown curl error"}
                
            logger.debug(f"curl request completed in {elapsed:.2f}s")
            
            # Try to parse JSON response
            try:
                response_data = json.loads(result.stdout)
                self.connection_errors = 0
                self.is_connected = True
                return response_data
            except json.JSONDecodeError:
                logger.warning(f"Invalid JSON response: {result.stdout[:100]}")
                return {"status": "error", "message": "Invalid JSON response"}
                
        except (subprocess.SubprocessError, FileNotFoundError) as e:
            return self._handle_error(e, method, url)

# Factory function to create the appropriate client
def create_api_client(base_url: str, key: str, secret: str) -> OPNsenseAPICore:
    """
    Factory function to create the appropriate API client implementation.
    
    Tries to use the requests implementation first, and falls back to curl
    if specified in the environment or if requests is not available.
    """
    # Check if we should use the curl implementation directly
    use_curl = os.environ.get('USE_CURL', 'false').lower() == 'true'
    
    if use_curl:
        logger.info("Using curl implementation as configured")
        return OPNsenseAPICurl(base_url, key, secret)
    
    # Try to import and use the requests implementation
    try:
        from api_client_requests import OPNsenseAPI
        return OPNsenseAPI(base_url, key, secret)
    except ImportError:
        logger.warning("Requests not available, falling back to curl implementation")
        return OPNsenseAPICurl(base_url, key, secret)
