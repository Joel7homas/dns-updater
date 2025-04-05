# logger.py
import logging
import os
import sys
from typing import Optional

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
    """Log startup configuration information."""
    logger.info(f"Starting DNS Updater v{os.environ.get('VERSION', 'unknown')}")
    logger.info(f"Log level: {os.environ.get('LOG_LEVEL', 'INFO')}")
    
    # Log environment configuration (without sensitive info)
    safe_vars = ['LOG_LEVEL', 'API_TIMEOUT', 'API_RETRY_COUNT',
                 'API_BACKOFF_FACTOR', 'DNS_CACHE_TTL',
                 'HEALTH_CHECK_INTERVAL']
    
    for var in safe_vars:
        if var in os.environ:
            logger.info(f"{var}: {os.environ[var]}")
    
    # Log hostname
    try:
        with open('/etc/docker_host_name', 'r') as f:
            hostname = f.read().strip()
            logger.info(f"Host name: {hostname}")
    except Exception as e:
        logger.warning(f"Could not read host name: {e}")
