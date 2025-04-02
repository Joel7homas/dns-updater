# cache_manager.py
import time
import logging
from typing import Dict, Any, Optional, List, Tuple

# Get module logger
logger = logging.getLogger('dns_updater.cache')

class DNSCache:
    def __init__(self, ttl_seconds: int = 60):
        """Initialize the DNS cache with specified TTL."""
        self.cache: Dict[str, Dict[str, Any]] = {}
        self.default_ttl = ttl_seconds
        logger.info(f"Initialized DNS cache with {ttl_seconds}s TTL")
    
    def get(self, key: str) -> Optional[Any]:
        """Retrieve item from cache if valid."""
        if key not in self.cache:
            return None
            
        cache_entry = self.cache[key]
        if time.time() > cache_entry['expires']:
            logger.debug(f"Cache entry expired: {key}")
            return None
            
        logger.debug(f"Cache hit: {key}")
        return cache_entry['value']
    
    def set(self, key: str, value: Any, ttl: Optional[int] = None) -> None:
        """Store item in cache with expiration time."""
        ttl = ttl or self.default_ttl
        expires = time.time() + ttl
        
        self.cache[key] = {
            'value': value, 
            'expires': expires
        }
        logger.debug(f"Cache set: {key} (expires in {ttl}s)")
    
    def invalidate(self, key: str) -> bool:
        """Remove item from cache."""
        if key in self.cache:
            del self.cache[key]
            logger.debug(f"Cache invalidated: {key}")
            return True
        return False
    
    def cleanup(self) -> int:
        """Remove all expired entries and return count of removed items."""
        now = time.time()
        expired_keys = [
            k for k, v in self.cache.items() 
            if v['expires'] < now
        ]
        
        for key in expired_keys:
            del self.cache[key]
            
        if expired_keys:
            logger.debug(f"Cleaned up {len(expired_keys)} expired cache entries")
            
        return len(expired_keys)
    
    def clear(self) -> None:
        """Clear all cache entries."""
        count = len(self.cache)
        self.cache.clear()
        logger.debug(f"Cache cleared ({count} entries)")

# Singleton cache instance
_dns_cache = None

def get_cache(ttl_seconds: Optional[int] = None) -> DNSCache:
    """Get or initialize the singleton cache instance."""
    global _dns_cache
    
    if _dns_cache is None:
        from os import environ
        ttl = ttl_seconds or int(environ.get('DNS_CACHE_TTL', '60'))
        _dns_cache = DNSCache(ttl)
        
    return _dns_cache
