# dns_manager.py
import logging
import time
import re
import json
import threading
from typing import Dict, List, Set, Tuple, Optional, Any

# Get module logger
logger = logging.getLogger('dns_updater.dns')

class DNSManager:
    def __init__(self, api_client, base_domain="docker.local", host_name="unknown"):
        """Initialize the DNS Manager with API client and settings."""
        self.api = api_client
        self.base_domain = base_domain
        self.host_name = host_name
        
        # Track when Unbound was last reconfigured
        self.last_reconfigure_time = 0
        self.min_reconfigure_interval = 30  # Minimum seconds between reconfigures
        self.updates_since_restart = 0
        self.restart_threshold = 10  # Restart after this many reconfigures 
        self.restart_interval = 3600  # Force restart every hour
        
        # Import cache here to avoid circular imports
        from cache_manager import get_cache
        self.cache = get_cache()
        
        logger.info(f"Initialized DNS Manager for domain {base_domain}")
        
    def sanitize_network_name(self, network_name: str) -> str:
        """Sanitize network name to be DNS-compatible."""
        if network_name is None:
            return "network"
            
        # Remove common suffixes
        for suffix in ['_net', '-net', '_default', '-default']:
            if network_name.endswith(suffix):
                network_name = network_name[:-len(suffix)]
                break
        
        # Remove invalid characters
        network_name = re.sub(r'[^a-zA-Z0-9\-]', '', network_name)
        
        # Ensure result is not empty
        if not network_name:
            network_name = "network"
            
        return network_name
    
    def get_domain_for_network(self, network_name: str = None) -> str:
        """Generate appropriate domain for a network."""
        if network_name is None:
            return self.base_domain
        
        if network_name == "flannel":
            return f"flannel.{self.base_domain}"
            
        sanitized_name = self.sanitize_network_name(network_name)
        return f"{sanitized_name}.{self.base_domain}"
    
    def get_all_dns_entries(self) -> Dict[str, List[Dict[str, str]]]:
        """Get all DNS entries from OPNsense."""
        # Check if we have a valid cached version
        cached_entries = self.cache.get('all_dns_entries')
        if cached_entries:
            return cached_entries
            
        logger.info("Fetching all DNS entries")
        response = self.api.get("unbound/settings/searchHostOverride")
        
        if response.get("status") == "error":
            logger.error(f"Failed to get DNS entries: {response.get('message')}")
            return {}
            
        hosts = response.get('rows', [])
        dns_entries: Dict[str, List[Dict[str, str]]] = {}
        
        for host in hosts:
            hostname = host.get('hostname', '')
            ip = host.get('server', '')
            domain = host.get('domain', '')
            
            rec = {
                'uuid': host.get('uuid', ''),
                'ip': ip,
                'domain': domain,
                'description': host.get('description', '')
            }
            
            if hostname not in dns_entries:
                dns_entries[hostname] = []
                
            dns_entries[hostname].append(rec)
        
        # Cache the result
        self.cache.set('all_dns_entries', dns_entries)
        return dns_entries
    
    def update_dns(self, hostname: str, ip: str, network_name: str = None) -> bool:
        """Update DNS entry for a hostname with the given IP."""
        domain = self.get_domain_for_network(network_name)
        network_desc = network_name or "default"
        
        logger.info(f"Updating DNS: {hostname}.{domain} → {ip} ({network_desc})")
        
        # Check if this entry already exists and has the same IP
        if self._entry_exists(hostname, domain, ip):
            logger.info(f"Entry already exists with same IP: {hostname}.{domain} → {ip}")
            return True
        
        # Prepare payload
        payload = {
            "host": {
                "enabled": "1",
                "hostname": hostname,
                "domain": domain,
                "server": ip,
                "description": f"Docker container on {self.host_name} ({network_desc})"
            }
        }
        
        # Make API call
        response = self.api.post("unbound/settings/addHostOverride", payload)
        
        if response.get("status") == "error":
            logger.error(f"DNS update failed: {response.get('message')}")
            return False
            
        # Check if the response indicates failure
        if response.get("result") == "failed":
            validations = response.get("validations", {})
            logger.error(f"DNS update failed with validations: {validations}")
            return False
            
        # Invalidate cache
        self.cache.invalidate('all_dns_entries')
        
        logger.info(f"DNS update successful: {hostname}.{domain} → {ip}")
        return True
    
    def _entry_exists(self, hostname: str, domain: str, ip: str) -> bool:
        """Check if a DNS entry already exists with the same IP."""
        dns_entries = self.get_all_dns_entries()
        
        if hostname in dns_entries:
            for entry in dns_entries[hostname]:
                if entry['domain'] == domain and entry['ip'] == ip:
                    return True
                    
        return False
    
    def remove_dns(self, hostname: str) -> bool:
        """Remove all DNS entries for a hostname."""
        logger.info(f"Removing all DNS entries for {hostname}")
        entries = self.get_all_dns_entries()
        
        if hostname not in entries:
            logger.info(f"No DNS entries found for {hostname}")
            return False
            
        removed = False
        for entry in entries[hostname]:
            desc = entry.get('description', '')
            if f"Docker container on {self.host_name}" in desc:
                uuid = entry.get('uuid', '')
                domain = entry.get('domain', '')
                ip = entry.get('ip', '')
                
                if self.remove_specific_dns(uuid, hostname, domain, ip):
                    removed = True
        
        # Invalidate cache if any entries were removed
        if removed:
            self.cache.invalidate('all_dns_entries')
            
        return removed
    
    def remove_specific_dns(self, uuid: str, hostname: str, domain: str, ip: str) -> bool:
        """Remove a specific DNS entry identified by UUID."""
        logger.info(f"Removing DNS entry: {hostname}.{domain} → {ip} (UUID: {uuid})")
        
        response = self.api.post(f"unbound/settings/delHostOverride/{uuid}")
        
        if response.get("status") == "error":
            logger.error(f"Failed to remove DNS entry: {response.get('message')}")
            return False
            
        # Invalidate cache
        self.cache.invalidate('all_dns_entries')
            
        logger.info(f"Successfully removed DNS entry: {hostname}.{domain} → {ip}")
        return True
    
    def reconfigure_unbound(self) -> bool:
        """Reconfigure Unbound to apply DNS changes with rate limiting."""
        now = time.time()
        elapsed = now - self.last_reconfigure_time
        
        # Rate limit reconfiguration
        if elapsed < self.min_reconfigure_interval:
            logger.info(f"Skipping reconfigure - last one was {elapsed:.1f}s ago")
            return False
            
        logger.info(f"Reconfiguring Unbound ({elapsed:.1f}s since last reconfigure)")
        self.last_reconfigure_time = now
        self.updates_since_restart += 1
        
        # Decide if we should restart instead of reconfigure
        should_restart = False
        if self.updates_since_restart >= self.restart_threshold:
            logger.info(f"Reached {self.updates_since_restart} updates, forcing restart")
            should_restart = True
        elif elapsed > self.restart_interval:
            logger.info(f"It's been {elapsed/60:.1f} minutes since last restart")
            should_restart = True
        
        if should_restart:
            return self._restart_unbound()
        
        # Make the reconfigure API call
        response = self.api.post("unbound/service/reconfigure")
        
        if response.get("status") == "error":
            logger.error(f"Failed to reconfigure Unbound: {response.get('message')}")
            # Try restarting as a fallback
            return self._restart_unbound()
            
        logger.info("Unbound reconfiguration successful")
        return True
    
    def _restart_unbound(self) -> bool:
        """Restart the Unbound service."""
        logger.info("Restarting Unbound service")
        response = self.api.post("unbound/service/restart")
        
        if response.get("status") == "error":
            logger.error(f"Failed to restart Unbound: {response.get('message')}")
            return False
            
        logger.info("Unbound service restart successful")
        self.updates_since_restart = 0
        self.last_reconfigure_time = time.time()
        return True
    
    def batch_update_dns(self, updates: List[Tuple[str, str, str]]) -> bool:
        """Update multiple DNS entries in a batch and reconfigure once."""
        if not updates:
            return True
            
        logger.info(f"Processing batch of {len(updates)} DNS updates")
        success_count = 0
        
        for hostname, ip, network_name in updates:
            if self.update_dns(hostname, ip, network_name):
                success_count += 1
                
        success_rate = success_count / len(updates) if updates else 0
        logger.info(f"Batch update completed with {success_rate:.0%} success rate")
        
        # Only reconfigure if at least one update succeeded
        if success_count > 0:
            self.reconfigure_unbound()
            
        return success_count > 0
