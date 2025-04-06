# api_client.py
"""
OPNsense API client wrapper module.

This module selects and provides the appropriate API client implementation
based on environment variables and available dependencies.
"""
import os
import logging
import platform
import importlib.util
from typing import Dict, List, Any, Optional, Union

# Get module logger
logger = logging.getLogger('dns_updater.api')

# First check if required modules exist before attempting imports
def check_module_exists(module_name):
    """Check if a module exists in the current environment."""
    return importlib.util.find_spec(module_name) is not None

# Check for direct IP configuration - set this up early
direct_ip = os.environ.get('OPNSENSE_DIRECT_IP', '')
if direct_ip:
    # Log that we're using direct IP
    logger.info(f"Using direct IP address: {direct_ip}")
    
    # Find the OPNsense URL from environment
    opnsense_url = os.environ.get("OPNSENSE_URL", "https://lavash.7homas.com/api")
    
    # Simple string replacement to avoid modifying existing code paths
    from urllib.parse import urlparse
    parsed_url = urlparse(opnsense_url)
    hostname = parsed_url.netloc.split(':')[0]  # Handle port if present
    
    # Tell existing code to use direct IP by setting environment variable
    os.environ['OPNSENSE_URL'] = opnsense_url.replace(hostname, direct_ip)
    
    # Disable SSL verification since cert won't match IP
    logger.info("Disabling SSL verification due to direct IP usage")
    os.environ['VERIFY_SSL'] = 'false'

# Detect TrueNAS Scale specifically
is_truenas = False
try:
    with open('/etc/os-release', 'r') as f:
        os_release_content = f.read()
        if 'truenas' in os_release_content.lower():
            is_truenas = True
            logger.info("TrueNAS Scale detected, optimizing API client")
except Exception:
    pass

def create_api_client(base_url, key, secret):
    """Create the appropriate API client implementation."""
    # Start with checking environment variable preferences
    use_curl = os.environ.get('USE_CURL', 'false').lower() == 'true'

    # Check if requests is available
    has_requests = check_module_exists('requests')
    if not has_requests:
        logger.error("Required 'requests' module not available")
        raise ImportError("Cannot create API client: 'requests' module not available")
    
    if use_curl:
        # Try to directly import the curl implementation
        try:
            # Import the underlying OPNsenseAPICore first
            from api_client_core import OPNsenseAPICore, ConnectionConfig
            # Then try to import the curl implementation
            from api_client_alt import OPNsenseAPICurl
            logger.info("Using curl implementation as configured")
            return OPNsenseAPICurl(base_url, key, secret)
        except ImportError as e:
            logger.warning(f"Curl implementation not available: {e}, falling back")
    
    # Try to use the requests implementation
    try:
        # Explicitly import from a module file in the current directory
        from api_client_requests import OPNsenseAPI
        logger.info("Using requests implementation")
        return OPNsenseAPI(base_url, key, secret)
    except ImportError as e:
        logger.warning(f"Requests implementation not available: {e}")
    
    # If all else fails, use the base implementation with minimal functionality
    try:
        # Make sure required modules are imported
        import requests
        # Correctly import ConnectionConfig (not APIConfig)
        from api_client_core import OPNsenseAPICore, ConnectionConfig
        logger.warning("Using core API client with minimal functionality")
        return OPNsenseAPICore(base_url, key, secret)
    except ImportError as e:
        logger.error(f"Core API client import failed: {e}")
        raise ImportError(f"Cannot create API client: {e}")

# The main OPNsenseAPI class that will be used by applications
class OPNsenseAPI:
    """
    Main OPNsense API client class.
    
    This is a wrapper around the actual implementation which is selected
    based on environment variables and available dependencies.
    """
    def __init__(self, base_url: str, key: str, secret: str):
        """Initialize the OPNsense API client with credentials."""
        # Start with curl on TrueNAS Scale to avoid initial connection issues
        use_curl_first = os.environ.get('USE_CURL_FIRST', 'auto').lower()
        
        if use_curl_first == 'auto':
            use_curl_first = is_truenas
        else:
            use_curl_first = use_curl_first in ('true', 'yes', '1')
        
        # Create the client implementation
        self._implementation = None
        
        # Try to directly import OPNsenseAPICurl for initial connection if configured
        curl_implementation = None
        if use_curl_first:
            try:
                from api_client_alt import OPNsenseAPICurl
                logger.info("Starting with curl implementation for first connection")
                curl_implementation = OPNsenseAPICurl(base_url, key, secret)
                
                # Test connection with curl first
                try:
                    logger.info("Testing initial connection with curl")
                    result = curl_implementation.get("core/firmware/status")
                    if "product_version" in result:
                        logger.info(f"Curl connection successful: OPNsense {result.get('product_version', 'unknown')}")
                        self._implementation = curl_implementation
                    else:
                        logger.warning("Curl connection returned unexpected response")
                except Exception as e:
                    logger.error(f"Initial curl connection failed: {e}, falling back to standard client")
            except ImportError as e:
                logger.warning(f"Curl implementation not available for initial connection: {e}")
        
        # If curl was successful and we should stay with it
        if self._implementation is not None and os.environ.get('STAY_WITH_CURL', 'false').lower() == 'true':
            logger.info("Staying with curl implementation as configured")
        else:
            # Create standard implementation
            self._implementation = create_api_client(base_url, key, secret)
            
        logger.info(f"OPNsense API client wrapper initialized")
    
    def get(self, endpoint: str, params: Optional[Dict] = None) -> Dict:
        """Make a GET request to the OPNsense API."""
        return self._implementation.get(endpoint, params)
    
    def post(self, endpoint: str, data: Any = None) -> Dict:
        """Make a POST request to the OPNsense API."""
        return self._implementation.post(endpoint, data)
