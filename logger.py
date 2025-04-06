# logger.py
import logging
import os
import sys
from typing import Optional, List

def configure_logging() -> logging.Logger:
    """Configure and return a logger based on environment variables."""
    log_level_name = os.environ.get('LOG_LEVEL', 'INFO').upper()
    log_levels = {
        'DEBUG': logging.DEBUG,
        'INFO': logging.INFO,
        'WARNING': logging.WARNING,
        'ERROR': logging.ERROR,
        'CRITICAL': logging.CRITICAL
    }
    log_level = log_levels.get(log_level_name, logging.INFO)
    
    # Configure root logger
    logging.basicConfig(
        level=log_level,
        format='%(asctime)s - %(levelname)s - %(name)s - %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )
    
    return logging.getLogger('dns_updater')

def get_logger(name: str) -> logging.Logger:
    """Get a configured logger for a specific module."""
    return logging.getLogger(f'dns_updater.{name}')

def log_startup_info(logger: logging.Logger) -> None:
    """Log startup configuration information with all env variables."""
    logger.info(f"Starting DNS Updater v{os.environ.get('VERSION', 'unknown')}")
    logger.info(f"Log level: {os.environ.get('LOG_LEVEL', 'INFO')}")
    
    # Define all known configuration environment variables
    env_vars = [
        # Logging
        'LOG_LEVEL',
        
        # API Connection
        'OPNSENSE_URL', 
        'OPNSENSE_DIRECT_IP',
        'API_TIMEOUT',
        'API_RETRY_COUNT',
        'API_BACKOFF_FACTOR',
        'SOCKET_TIMEOUT',
        'CONNECT_TIMEOUT',
        'READ_TIMEOUT',
        'VERIFY_SSL',
        
        # Rate Limiting
        'MIN_RECONFIGURE_INTERVAL',
        'SKIP_RECONFIG_AFTER_DELETE',
        'EMERGENCY_BYPASS_RECONFIG',
        
        # Caching
        'DNS_CACHE_TTL',
        
        # Sync and Cleanup Intervals
        'DNS_SYNC_INTERVAL',
        'DNS_CLEANUP_INTERVAL',
        'CLEANUP_ON_STARTUP',
        
        # Unbound Management
        'RESTART_THRESHOLD',
        'RESTART_INTERVAL',
        'VERIFICATION_DELAY',
        
        # API Implementation
        'USE_CURL',
        'USE_CURL_FIRST',
        'STAY_WITH_CURL',
        'FORCE_HTTP1',
        
        # Health Checks
        'HEALTH_CHECK_INTERVAL'
    ]
    
    # Log only variables that are set
    for var in env_vars:
        if var in os.environ:
            # Skip logging sensitive variables
            if var in ['OPNSENSE_KEY', 'OPNSENSE_SECRET']:
                continue
                
            logger.info(f"{var}: {os.environ[var]}")
    
    # Log hostname
    try:
        with open('/etc/docker_host_name', 'r') as f:
            hostname = f.read().strip()
            logger.info(f"Host name: {hostname}")
    except Exception as e:
        logger.warning(f"Could not read host name: {e}")
