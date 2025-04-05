# api_client_alt.py
"""
Alternative implementation methods for the OPNsense API client.
"""
import os
import time
import logging
import json
import subprocess
from typing import Dict, List, Any, Optional, Union


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
        """Make a request using curl subprocess with credential redaction."""
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
            operation_timeout = max(60, operation_timeout)  # At least 60 seconds
        
        # Set the max-time option
        cmd.extend(["-m", str(self.config.connect_timeout + operation_timeout)])
        
        # Add extensive retry options for better reliability
        cmd.extend(["--retry", "3"])  # 3 retries
        cmd.extend(["--retry-delay", "3"])  # 3 second between retries
        cmd.extend(["--retry-max-time", "120"])  # Give up after 120 seconds of retries
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
                # For empty POST, add empty JSON object
                # CRITICAL CHANGE: Use '{}' instead of empty string
                cmd.extend(["-d", "{}"])
            else:
                cmd.extend(["-d", json.dumps(data)])
                
        # Add URL
        cmd.append(url)
    
        # Create redacted version of command for logging
        safe_cmd = self._redact_command(cmd)
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
                # Redact any credentials that might appear in error output
                safe_stderr = self._redact_sensitive_data(result.stderr)
                logger.error(f"curl failed with code {result.returncode}: {safe_stderr}")
                return {"status": "error", "message": safe_stderr or "Unknown curl error"}
                
            logger.debug(f"curl request completed in {elapsed:.2f}s")
            
            # Try to parse JSON response
            try:
                response_data = json.loads(result.stdout)
                self.connection_errors = 0
                self.is_connected = True
                return response_data
            except json.JSONDecodeError:
                # Redact any potential credentials in response
                safe_stdout = self._redact_sensitive_data(result.stdout[:100])
                logger.warning(f"Invalid JSON response: {safe_stdout}")
                return {"status": "error", "message": "Invalid JSON response"}
                    
        except (subprocess.SubprocessError, FileNotFoundError) as e:
            error_msg = str(e)
            safe_error = self._redact_sensitive_data(error_msg)
            return self._handle_error(Exception(safe_error), method, url)
    
    
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


    def _redact_command(self, cmd: List[str]) -> List[str]:
        """Create a safe version of a command for logging by redacting credentials."""
        safe_cmd = cmd.copy()
        
        # Find and redact auth information
        try:
            for i, arg in enumerate(safe_cmd):
                # Redact basic auth credentials
                if arg == "-u" and i+1 < len(safe_cmd):
                    safe_cmd[i+1] = "REDACTED_CREDENTIALS"
                
                # Redact any JSON data that might contain credentials
                if arg == "-d" and i+1 < len(safe_cmd):
                    try:
                        # Check if it's JSON
                        json_data = json.loads(safe_cmd[i+1])
                        # Redact any fields that might contain sensitive info
                        for key in json_data.keys():
                            if any(sensitive in key.lower() for sensitive in ['pass', 'secret', 'key', 'token', 'auth']):
                                json_data[key] = "REDACTED"
                        safe_cmd[i+1] = json.dumps(json_data)
                    except (json.JSONDecodeError, TypeError):
                        # Not JSON or couldn't parse, leave as is
                        pass
        except Exception as e:
            # If anything goes wrong with redaction, use a completely safe fallback
            logger.debug(f"Error in command redaction: {e}")
            # Just show the command without any arguments
            return [cmd[0], "[arguments redacted for security]"]
        
        return safe_cmd
    
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
