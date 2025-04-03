# api_client.py
"""
OPNsense API client wrapper module.

This module selects and provides the appropriate API client implementation
based on environment variables and available dependencies.
"""
import os
import logging
import platform
from typing import Dict, Any, Optional

# Get module logger
logger = logging.getLogger('dns_updater.api')

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

# Import the factory function to create the appropriate client
try:
    from api_client_alt import create_api_client, OPNsenseAPICurl
except ImportError:
    logger.warning("Alternative API client implementations not available")
    # Fallback implementation if modules are missing
    from api_client_core import OPNsenseAPICore

    def create_api_client(base_url, key, secret):
        """Fallback implementation that just uses the core class."""
        logger.warning("Using fallback API client (limited functionality)")
        return OPNsenseAPICore(base_url, key, secret)
    
    OPNsenseAPICurl = None

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

        if use_curl_first and OPNsenseAPICurl is not None:
            logger.info("Starting with curl implementation for first connection")
            self._implementation = OPNsenseAPICurl(base_url, key, secret)
            
            # Test connection with curl first
            try:
                logger.info("Testing initial connection with curl")
                result = self._implementation.get("core/firmware/status")
                if "product_version" in result:
                    logger.info(f"Curl connection successful: OPNsense {result.get('product_version', 'unknown')}")
                else:
                    logger.warning("Curl connection returned unexpected response")
                
                # Keep using curl if successful
                if os.environ.get('STAY_WITH_CURL', 'false').lower() != 'true':
                    logger.info("Switching to standard implementation after successful initial connection")
                    self._implementation = create_api_client(base_url, key, secret)
            except Exception as e:
                logger.error(f"Initial curl connection failed: {e}, falling back to standard client")
                self._implementation = create_api_client(base_url, key, secret)
        else:
            self._implementation = create_api_client(base_url, key, secret)
            
        logger.info(f"OPNsense API client wrapper initialized")
    
    def get(self, endpoint: str, params: Optional[Dict] = None) -> Dict:
        """Make a GET request to the OPNsense API."""
        return self._implementation.get(endpoint, params)
    
    def post(self, endpoint: str, data: Any = None) -> Dict:
        """Make a POST request to the OPNsense API."""
        return self._implementation.post(endpoint, data)
