#!/usr/bin/env python3
# api_import_check.py - Check for import issues with API clients

import sys
import traceback
import logging

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger()

def check_import(module_name, class_name=None):
    """Attempt to import a module and optionally a class from it."""
    try:
        logger.info(f"Attempting to import {module_name}")
        module = __import__(module_name)
        
        if class_name:
            if hasattr(module, class_name):
                logger.info(f"Successfully imported {class_name} from {module_name}")
                return True
            else:
                logger.error(f"Module {module_name} does not have class {class_name}")
                return False
        
        logger.info(f"Successfully imported {module_name}")
        return True
        
    except ImportError as e:
        logger.error(f"Failed to import {module_name}: {e}")
        return False
    except Exception as e:
        logger.error(f"Unexpected error importing {module_name}: {e}")
        traceback.print_exc()
        return False

def check_api_client_requests():
    """Check api_client_requests and its dependencies."""
    logger.info("Checking api_client_requests.py dependencies:")
    
    # First check basic dependencies
    dependencies = ['os', 'time', 'socket', 'logging', 'json', 'requests', 'typing']
    missing = []
    
    for dep in dependencies:
        if not check_import(dep):
            missing.append(dep)
    
    if missing:
        logger.error(f"Missing dependencies for api_client_requests: {', '.join(missing)}")
        return False
    
    # Now try to import the actual module
    try:
        logger.info("Attempting to import api_client_requests")
        import api_client_requests
        
        # Check for specific required classes
        if hasattr(api_client_requests, 'OPNsenseAPI'):
            logger.info("Successfully imported OPNsenseAPI from api_client_requests")
        else:
            logger.error("api_client_requests does not have OPNsenseAPI class")
            return False
        
        logger.info("api_client_requests module looks good")
        return True
        
    except ImportError as e:
        logger.error(f"Failed to import api_client_requests: {e}")
        return False
    except Exception as e:
        logger.error(f"Unexpected error with api_client_requests: {e}")
        traceback.print_exc()
        return False

def check_api_client_alt():
    """Check api_client_alt.py and its dependencies."""
    logger.info("Checking api_client_alt.py dependencies:")
    
    # First check basic dependencies
    dependencies = ['os', 'time', 'json', 'logging', 'subprocess', 'typing', 're']
    missing = []
    
    for dep in dependencies:
        if not check_import(dep):
            missing.append(dep)
    
    if missing:
        logger.error(f"Missing dependencies for api_client_alt: {', '.join(missing)}")
        return False
    
    # Now try to import the actual module
    try:
        logger.info("Attempting to import api_client_alt")
        import api_client_alt
        
        # Check for specific required classes
        if hasattr(api_client_alt, 'OPNsenseAPICurl'):
            logger.info("Successfully imported OPNsenseAPICurl from api_client_alt")
        else:
            logger.error("api_client_alt does not have OPNsenseAPICurl class")
            return False
        
        logger.info("api_client_alt module looks good")
        return True
        
    except ImportError as e:
        logger.error(f"Failed to import api_client_alt: {e}")
        return False
    except Exception as e:
        logger.error(f"Unexpected error with api_client_alt: {e}")
        traceback.print_exc()
        return False

def check_create_api_client():
    """Check the create_api_client function and see what it returns."""
    logger.info("Checking create_api_client function:")
    
    try:
        from api_client import create_api_client
        from api_client_core import APIConfig
        
        # Create a dummy config
        logger.info("Testing create_api_client with dummy values")
        api = create_api_client("https://example.com", "dummy_key", "dummy_secret")
        
        logger.info(f"create_api_client returned object of type: {type(api).__name__}")
        
        # Check which implementation was used
        if hasattr(api, 'session'):
            logger.info("Using requests-based client implementation")
        elif hasattr(api, 'curl_command'):
            logger.info("Using curl-based client implementation")
        else:
            logger.info("Using fallback core client implementation")
        
        return True
        
    except Exception as e:
        logger.error(f"Error testing create_api_client: {e}")
        traceback.print_exc()
        return False

def main():
    """Main function to check all API client implementations."""
    logger.info("Starting API client import check")
    
    check_api_client_requests()
    print()
    check_api_client_alt()
    print()
    check_create_api_client()
    
    logger.info("API client import check complete")

if __name__ == "__main__":
    main()
