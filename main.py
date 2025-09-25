#!/usr/bin/env python3
"""
DNS Updater - Main entry point
Monitors Docker containers and updates DNS records in OPNsense
"""

import logging
import os
import sys
import time
from logger import configure_logging, log_startup_info

# Configure logging first
logger = configure_logging()

def main():
    """Main entry point"""
    log_startup_info(logger)
    
    try:
        # Import core modules
        from api_client import OPNsenseAPI
        from dns_manager import HybridDNSManager  # Use HybridDNSManager
        from container_monitor import ContainerMonitor
        from dns_replication_api import start_replication_api_if_needed
        
        # Read hostname
        try:
            with open('/etc/docker_host_name', 'r') as f:
                hostname = f.read().strip()
                logger.info(f"Host name: {hostname}")
        except Exception as e:
            logger.error(f"Failed to read host name: {e}")
            hostname = "unknown"
        
        # Initialize API client
        logger.info("Initializing API client")
        api_client = OPNsenseAPI()
        
        # Initialize DNS manager (now hybrid)
        logger.info("Initializing DNS manager")
        dns_manager = HybridDNSManager(api_client, "docker.local", hostname)
        
        # Start replication API server if configured
        replication_server = None
        if hasattr(dns_manager, 'distributed_dns') and dns_manager.distributed_dns:
            logger.info("Starting replication API server")
            replication_server = start_replication_api_if_needed(dns_manager.distributed_dns)
            if replication_server:
                logger.info(f"Replication API server started successfully")
            else:
                logger.info("Replication API server not started (not needed for this configuration)")
        
        # Initialize container monitor
        logger.info("Initializing container monitor")
        container_monitor = ContainerMonitor(dns_manager)
        
        # Test API connection
        logger.info("Testing API connection")
        try:
            result = api_client.get("core/firmware/status")
            if result:
                logger.info("API connection successful")
            else:
                logger.warning("API connection test returned no data")
        except Exception as e:
            logger.error(f"API connection test failed: {e}")
        
        # Start monitoring
        logger.info("Starting container monitoring")
        container_monitor.start()
        
        # Keep running
        try:
            while True:
                time.sleep(60)
        except KeyboardInterrupt:
            logger.info("Received interrupt signal, shutting down...")
        finally:
            if replication_server:
                logger.info("Stopping replication server")
                replication_server.stop()
            logger.info("Cleanup complete")
            
    except Exception as e:
        logger.error(f"Fatal error in main: {e}", exc_info=True)
        sys.exit(1)

if __name__ == "__main__":
    main()
