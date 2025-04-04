# dns_manager.py
import logging
import time
import re
import json
import threading
import subprocess
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
        self.max_reconfigure_time = 60      # Maximum time for reconfiguration
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
    
    def get_all_dns_entries(self, force_refresh=False) -> Dict[str, List[Dict[str, str]]]:
        """Get all DNS entries from OPNsense."""
        # Check if we have a valid cached version
        cached_entries = None if force_refresh else self.cache.get('all_dns_entries')
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
        
        # Check if this entry already exists with the same IP
        if self._entry_exists(hostname, domain, ip):
            logger.info(f"Entry already exists with same IP: {hostname}.{domain} → {ip}")
            return True
        
        # Check if entries exist with different IPs and remove them
        self._clean_old_entries(hostname, domain, ip)
        
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
    
    def _clean_old_entries(self, hostname: str, domain: str, new_ip: str) -> None:
        """Remove existing entries for hostname/domain with different IPs."""
        dns_entries = self.get_all_dns_entries()
        
        if hostname not in dns_entries:
            return
            
        entries_to_remove = []
        for entry in dns_entries[hostname]:
            if entry['domain'] == domain and entry['ip'] != new_ip:
                entries_to_remove.append(entry)
        
        if entries_to_remove:
            logger.info(f"Found {len(entries_to_remove)} obsolete records for {hostname}.{domain}")
            
            for entry in entries_to_remove:
                uuid = entry.get('uuid', '')
                old_ip = entry.get('ip', '')
                logger.info(f"Removing obsolete DNS entry: {hostname}.{domain} → {old_ip}")
                self.remove_specific_dns(uuid, hostname, domain, old_ip)
    
    def cleanup_dns_records(self) -> int:
        """Clean up duplicate and stale DNS records."""
        logger.info("Starting DNS record cleanup")
        dns_entries = self.get_all_dns_entries()
        records_removed = 0
        deletion_occurred = False
        
        # Dictionary to track latest IP for each hostname/domain
        latest_ips = {}
        
        # First pass: identify the latest IP for each hostname/domain
        # [existing code]
        
        # Second pass: remove duplicates and keep only the latest
        for hostname, entries in dns_entries.items():
            for entry in entries:
                domain = entry.get('domain', '')
                ip = entry.get('ip', '')
                uuid = entry.get('uuid', '')
                desc = entry.get('description', '')
                
                # Skip entries that don't belong to Docker containers on this host
                if f"Docker container on {self.host_name}" not in desc:
                    continue
                    
                key = f"{hostname}.{domain}"
                if key in latest_ips and latest_ips[key]['count'] > 1 and ip != latest_ips[key]['ip']:
                    # Remove duplicate with outdated IP
                    logger.info(f"Removing duplicate DNS entry: {hostname}.{domain} → {ip}")
                    success = self.remove_specific_dns(uuid, hostname, domain, ip)
                    if success:
                        records_removed += 1
                        latest_ips[key]['count'] -= 1
                        deletion_occurred = True
        
        # If any records were removed, force a reconfiguration to apply changes
        if deletion_occurred:
            logger.info(f"Forcing Unbound reconfiguration after removing {records_removed} records")
            self.reconfigure_unbound()
        
        logger.info(f"DNS cleanup complete: removed {records_removed} duplicate records")
        return records_removed

    def aggressive_cleanup(self) -> int:
        """Perform a more aggressive cleanup by operating on smaller batches with reconfiguration."""
        logger.info("Starting aggressive DNS record cleanup")
        
        # Get all entries
        dns_entries = self.get_all_dns_entries(force_refresh=True)
        
        # Track container hostnames to keep one record per container
        container_records = {}
        
        # Count total duplicate records
        total_removed = 0
        
        # First, identify valid records to keep
        for hostname, entries in dns_entries.items():
            if len(entries) <= 1:
                continue
                
            # Only process entries for this host
            host_entries = [
                entry for entry in entries 
                if f"Docker container on {self.host_name}" in entry.get('description', '')
            ]
            
            if not host_entries:
                continue
                
            # Group by domain
            domain_groups = {}
            for entry in host_entries:
                domain = entry.get('domain', '')
                if domain not in domain_groups:
                    domain_groups[domain] = []
                domain_groups[domain].append(entry)
                
            # Process each domain group
            for domain, domain_entries in domain_groups.items():
                if len(domain_entries) <= 1:
                    continue
                    
                # Keep only the most recent entry (assuming latest is the correct one)
                # Sort by UUID as a proxy for creation time
                domain_entries.sort(key=lambda e: e.get('uuid', ''))
                entries_to_remove = domain_entries[:-1]  # Remove all but the last entry
                
                # Remove in smaller batches with verification
                for i, entry in enumerate(entries_to_remove):
                    uuid = entry.get('uuid', '')
                    ip = entry.get('ip', '')
                    
                    if self.remove_specific_dns(uuid, hostname, domain, ip):
                        total_removed += 1
                    
                    # Reconfigure every few deletions to avoid overwhelming the server
                    if i > 0 and i % 5 == 0:
                        logger.info(f"Intermediate reconfiguration after {i} deletions")
                        self.reconfigure_unbound()
                        time.sleep(5)  # Give the server a short break
        
        # Final reconfiguration if any records were removed
        if total_removed > 0:
            logger.info(f"Final reconfiguration after removing {total_removed} records")
            self.reconfigure_unbound()
        
        logger.info(f"Aggressive DNS cleanup complete: removed {total_removed} duplicate records")
        return total_removed

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
        
        # Verify the record was actually removed
        # Wait a short time to allow the backend to process
        time.sleep(1)
        
        # Reload DNS entries
        entries = self.get_all_dns_entries(force_refresh=True)
        
        # Check if the entry is still present
        removed = True
        if hostname in entries:
            for entry in entries[hostname]:
                if entry.get('uuid') == uuid:
                    logger.warning(f"Record removal reported success but record still exists: {hostname}.{domain}")
                    removed = False
        
        if removed:
            logger.info(f"Successfully removed DNS entry: {hostname}.{domain} → {ip}")
        
        return removed
    
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
        
        # Make the reconfigure API call with timeout
        return self._reconfigure_with_timeout()
        
    def _reconfigure_with_timeout(self) -> bool:
        """Reconfigure Unbound with timeout to prevent hanging."""
        result = [False]  # Use a list to allow modification in the thread
        exception = [None]
        
        def do_reconfigure():
            try:
                # For the reconfigure endpoint specifically, we need to ensure we send
                # a proper POST request with empty data to avoid 411 errors
                response = self.api.post("unbound/service/reconfigure")
                
                if response.get("status") == "error":
                    logger.error(f"Failed to reconfigure Unbound: {response.get('message')}")
                    result[0] = False
                else:
                    logger.info("Unbound reconfiguration successful")
                    result[0] = True
            except Exception as e:
                exception[0] = e
                result[0] = False
                
        # Create and start a thread for the reconfigure operation
        thread = threading.Thread(target=do_reconfigure)
        thread.daemon = True
        thread.start()
        
        # Wait for the thread to complete or timeout
        # Use a longer timeout for reconfiguration
        extended_timeout = max(120, self.max_reconfigure_time)
        thread.join(extended_timeout)
        
        # Check if the thread is still alive (timeout occurred)
        if thread.is_alive():
            logger.error(f"Unbound reconfiguration timed out after {extended_timeout}s")
            # Try restarting as a fallback
            return self._restart_unbound()
        
        # Check if an exception occurred
        if exception[0] is not None:
            logger.error(f"Unbound reconfiguration failed with error: {exception[0]}")
            # Try restarting as a fallback
            return self._restart_unbound()
            
        return result[0]
    
    def _restart_unbound(self) -> bool:
        """Restart the Unbound service."""
        logger.info("Restarting Unbound service")
        
        # First try the API restart
        try:
            response = self.api.post("unbound/service/restart")
            
            if response.get("status") == "error":
                logger.error(f"Failed to restart Unbound via API: {response.get('message')}")
                return False
                
            logger.info("Unbound service restart successful")
            self.updates_since_restart = 0
            self.last_reconfigure_time = time.time()
            return True
        except Exception as e:
            logger.error(f"API restart failed: {e}")
            return False
    
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
