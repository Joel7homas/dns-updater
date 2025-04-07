#!/usr/bin/env python3
# api_diagnostics.py - Diagnose API client implementation availability

import os
import sys
import importlib.util
import logging
import time

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(name)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger('api_diagnostics')

def check_module_exists(module_name):
    """Check if a module exists and is importable."""
    try:
        spec = importlib.util.find_spec(module_name)
        return spec is not None
    except (ImportError, AttributeError):
        return False

def check_module_content(module_name):
    """Check module content to verify key functions/classes exist."""
    try:
        module = importlib.import_module(module_name)
        
        if module_name == 'api_client_core':
            has_core_class = hasattr(module, 'OPNsenseAPICore')
            has_config_class = hasattr(module, 'ConnectionConfig')
            logger.info(f"  - OPNsenseAPICore class: {'✓' if has_core_class else '✗'}")
            logger.info(f"  - ConnectionConfig class: {'✓' if has_config_class else '✗'}")
            
            if hasattr(module, 'APIConfig') and not hasattr(module, 'ConnectionConfig'):
                logger.error("  - Found APIConfig instead of ConnectionConfig - this needs to be fixed!")
            
            return has_core_class and has_config_class
            
        elif module_name == 'api_client_requests':
            has_api_class = hasattr(module, 'OPNsenseAPI')
            logger.info(f"  - OPNsenseAPI class: {'✓' if has_api_class else '✗'}")
            return has_api_class
            
        elif module_name == 'api_client_alt':
            has_curl_class = hasattr(module, 'OPNsenseAPICurl')
            logger.info(f"  - OPNsenseAPICurl class: {'✓' if has_curl_class else '✗'}")
            return has_curl_class
            
        elif module_name == 'api_client':
            has_create_func = hasattr(module, 'create_api_client')
            has_api_class = hasattr(module, 'OPNsenseAPI')
            logger.info(f"  - create_api_client function: {'✓' if has_create_func else '✗'}")
            logger.info(f"  - OPNsenseAPI class: {'✓' if has_api_class else '✗'}")
            return has_create_func and has_api_class
            
        return True
        
    except Exception as e:
        logger.error(f"  - Error checking module content: {e}")
        return False

def check_api_modules():
    """Check if all API client modules are available."""
    modules = [
        'api_client',
        'api_client_core',
        'api_client_requests',
        'api_client_alt'
    ]
    
    logger.info("Checking API client modules:")
    
    all_available = True
    module_statuses = {}
    
    for module_name in modules:
        exists = check_module_exists(module_name)
        logger.info(f"Module {module_name}: {'Available' if exists else 'Not Available'}")
        
        if exists:
            module_content_valid = check_module_content(module_name)
            module_statuses[module_name] = module_content_valid
        else:
            module_statuses[module_name] = False
            all_available = False
    
    return all_available, module_statuses

def check_dependencies():
    """Check if required external dependencies are available."""
    dependencies = ['requests', 'docker']
    
    logger.info("\nChecking external dependencies:")
    
    all_available = True
    for dep in dependencies:
        exists = check_module_exists(dep)
        logger.info(f"Dependency {dep}: {'Available' if exists else 'Not Available'}")
        
        if not exists:
            all_available = False
    
    return all_available

def test_api_client():
    """Test creating an API client."""
    logger.info("\nTesting API client creation:")
    
    try:
        # Set test credentials
        os.environ['OPNSENSE_URL'] = 'https://example.com/api'
        os.environ['OPNSENSE_KEY'] = 'test_key'
        os.environ['OPNSENSE_SECRET'] = 'test_secret'
        
        # Try to import and create the client
        from api_client import OPNsenseAPI
        
        logger.info("Creating test API client instance...")
        start_time = time.time()
        client = OPNsenseAPI('https://example.com/api', 'test_key', 'test_secret')
        elapsed = time.time() - start_time
        
        logger.info(f"API client created in {elapsed:.2f}s")
        
        # Check which implementation was used
        impl_type = type(client._implementation).__name__
        logger.info(f"Using implementation: {impl_type}")
        
        # Basic test of get/post methods
        has_get = hasattr(client, 'get') and callable(client.get)
        has_post = hasattr(client, 'post') and callable(client.post)
        
        logger.info(f"get method: {'✓' if has_get else '✗'}")
        logger.info(f"post method: {'✓' if has_post else '✗'}")
        
        return True, impl_type
        
    except ImportError as e:
        logger.error(f"Import error: {e}")
        return False, str(e)
    except Exception as e:
        logger.error(f"Error creating API client: {e}")
        return False, str(e)

def suggest_fixes(module_statuses):
    """Suggest fixes based on what was found."""
    logger.info("\nDiagnostic Results:")
    
    if not module_statuses.get('api_client_core', False):
        logger.info("- api_client_core module is missing or invalid")
        logger.info("  Fix: Ensure api_client_core.py is in the same directory")
        logger.info("  Fix: Check for ConnectionConfig class (not APIConfig)")
        
    if not module_statuses.get('api_client_requests', False):
        logger.info("- api_client_requests module is missing or invalid")
        logger.info("  Fix: Ensure api_client_requests.py is in the same directory")
        logger.info("  Fix: Verify OPNsenseAPI class is defined properly")
        
    if not module_statuses.get('api_client', False):
        logger.info("- api_client module is missing or invalid")
        logger.info("  Fix: Ensure api_client.py is properly importing from other modules")
        
    if not check_module_exists('requests'):
        logger.info("- requests module is missing")
        logger.info("  Fix: Run 'pip install requests'")
        
    if all(not status for status in module_statuses.values()):
        logger.info("\nAll API client modules missing or invalid!")
        logger.info("This could indicate a path issue or installation problem.")
        logger.info(f"Current directory: {os.getcwd()}")
        logger.info(f"Files in directory: {os.listdir('.')}")
        logger.info(f"Python path: {sys.path}")

def print_docker_command():
    """Print a Docker command to rebuild and restart the container."""
    logger.info("\nTo rebuild and restart the container, run:")
    logger.info("docker build -t dns-updater:latest .")
    logger.info("docker stop dns-updater")
    logger.info("docker rm dns-updater")
    logger.info("docker run -d --name dns-updater \\")
    logger.info("  -v /var/run/docker.sock:/var/run/docker.sock:rw \\")
    logger.info("  -v /etc/hostname:/etc/docker_host_name:ro \\")
    logger.info("  -e OPNSENSE_URL=https://your-opnsense-ip/api \\")
    logger.info("  -e OPNSENSE_KEY=your_key \\")
    logger.info("  -e OPNSENSE_SECRET=your_secret \\")
    logger.info("  -e LOG_LEVEL=INFO \\")
    logger.info("  -e USE_CURL=false \\")
    logger.info("  -e VERIFICATION_DELAY=0 \\")
    logger.info("  dns-updater:latest")

def main():
    """Run all diagnostics."""
    logger.info("Starting API client diagnostics")
    
    # Check Python version
    logger.info(f"Python version: {sys.version}")
    
    # Check for API modules
    all_modules, module_statuses = check_api_modules()
    
    # Check dependencies
    all_deps = check_dependencies()
    
    # Test API client
    client_ok, impl_type = test_api_client()
    
    # Overall status
    if all_modules and all_deps and client_ok:
        logger.info("\n✅ All checks passed! API client should be working correctly.")
        logger.info(f"Using implementation: {impl_type}")
    else:
        logger.info("\n❌ Some checks failed. API client may not work correctly.")
        suggest_fixes(module_statuses)
        print_docker_command()

if __name__ == "__main__":
    main()
