# api_client.py
"""
OPNsense API client wrapper module.

This module selects and provides the appropriate API client implementation
based on environment variables and available dependencies.
"""
import os
import logging
from typing import Dict, Any, Optional

# Get module logger
logger = logging.getLogger('dns_updater.api')

# Import the factory function to create the appropriate client
try:
    from api_client_alt import create_api_client
except ImportError:
    logger.warning("Alternative API client implementations not available")
    # Fallback implementation if modules are missing
    from api_client_core import OPNsenseAPICore

    def create_api_client(base_url, key, secret):
        """Fallback implementation that just uses the core class."""
        logger.warning("Using fallback API client (limited functionality)")
        return OPNsenseAPICore(base_url, key, secret)

# The main OPNsenseAPI class that will be used by applications
class OPNsenseAPI:
    """
    Main OPNsense API client class.
    
    This is a wrapper around the actual implementation which is selected
    based on environment variables and available dependencies.
    """
    def __init__(self, base_url: str, key: str, secret: str):
        """Initialize the OPNsense API client with credentials."""
        self._implementation = create_api_client(base_url, key, secret)
        logger.info(f"OPNsense API client wrapper initialized")
    
    def get(self, endpoint: str, params: Optional[Dict] = None) -> Dict:
        """Make a GET request to the OPNsense API."""
        return self._implementation.get(endpoint, params)
    
    def post(self, endpoint: str, data: Any = None) -> Dict:
        """Make a POST request to the OPNsense API."""
        return self._implementation.post(endpoint, data)
