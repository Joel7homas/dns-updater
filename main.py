# main.py
import os
import time
import signal
import sys
from typing import Dict, Any, Optional

# Initialize logging first
from logger import configure_logging, log_startup_info
logger = configure_logging()

def load_required_env(var_name: str, default: Optional[str] = None) -> str:
    """Load required environment variable with validation."""
    value = os.environ.get(var_name)
    
    if not value and default is None:
        logger.error(f"Missing required environment variable: {var_name}")
        sys.exit(1)
        
    return value or default

def initialize_components():
    """Initialize all system components."""
    # Load required environment variables
    base_url = load_required_env('OPNSENSE_URL')
    api_key = load_required_env('OPNSENSE_KEY')
    api_secret = load_required_env('OPNSENSE_SECRET')
    
    # Get hostname
    try:
        with open('/etc/docker_host_name', 'r') as f:
            hostname = f.read().strip()
    except Exception as e:
        logger.warning(f"Could not read hostname: {e}")
        hostname = "unknown"
    
    # Initialize API client
    from api_client import OPNsenseAPI
    api_client = OPNsenseAPI(base_url, api_key, api_secret)
    
    # Initialize DNS manager
    from dns_manager import DNSManager
    dns_manager = DNSManager(api_client, "docker.local", hostname)
    
    # Initialize container monitor
    from container_monitor import ContainerMonitor
    container_monitor = ContainerMonitor(dns_manager)
    
    return api_client, dns_manager, container_monitor

def handle_signal(sig, frame):
    """Handle termination signals."""
    logger.info(f"Received signal {sig}, shutting down")
    sys.exit(0)

def main():
    """Main entry point."""
    # Register signal handlers
    signal.signal(signal.SIGINT, handle_signal)
    signal.signal(signal.SIGTERM, handle_signal)
    
    # Log startup information
    log_startup_info(logger)
    
    try:
        # Initialize components
        api_client, dns_manager, container_monitor = initialize_components()
        
        # Test API connection
        try:
            logger.info("Testing API connection")
            response = api_client.get("core/firmware/status")
            if response.get("status") == "error":
                logger.error(f"API test failed: {response.get('message')}")
            else:
                logger.info("API connection successful")
        except Exception as e:
            logger.error(f"API connection test failed: {e}")
        
        # Start monitoring containers
        logger.info("Starting container monitoring")
        container_monitor.listen_for_events()
        
    except KeyboardInterrupt:
        logger.info("Script terminated by user")
    except Exception as e:
        logger.error(f"Unhandled exception: {e}")
        return 1
        
    return 0

if __name__ == "__main__":
    sys.exit(main())
