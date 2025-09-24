# dns_manager.py
import logging
import time
import re
import json
import threading
import subprocess
import os
from typing import Dict, List, Set, Tuple, Optional, Any

# Get module logger
logger = logging.getLogger('dns_updater.dns')

class HybridDNSManager:
    """
    DNS Manager that uses local Unbound when available, falls back to OPNsense API
    """
    
    def __init__(self, api_client=None, base_domain="docker.local", host_name="unknown"):
        self.api_client = api_client
        self.base_domain = base_domain
        self.host_name = host_name
        
        # Initialize distributed DNS manager
        self.distributed_dns = None
        try:
            from distributed_dns_manager import create_distributed_dns_manager
            self.distributed_dns = create_distributed_dns_manager()
            logger.info(f"Initialized distributed DNS manager: {self.distributed_dns.role}")
        except Exception as e:
            logger.warning(f"Failed to initialize distributed DNS manager: {e}")
            logger.info("Falling back to OPNsense API only")
        
        # Keep the original API-based manager for fallback
        self.api_dns_manager = None
        if api_client:
            # Import and initialize the original DNS manager
            from dns_manager import DNSManager as OriginalDNSManager
            self.api_dns_manager = OriginalDNSManager(api_client, base_domain, host_name)
    
    def process_dns_changes(self, 
                           entries_to_add: List[Dict[str, Any]], 
                           entries_to_remove: List[Dict[str, Any]]) -> bool:
        """
        Process DNS changes using distributed DNS manager when available
        """
        if not entries_to_add and not entries_to_remove:
            logger.info("No DNS changes to process")
            return False
        
        changes_made = False
        
        # Use distributed DNS manager if available
        if self.distributed_dns:
            changes_made = self._process_changes_distributed(entries_to_add, entries_to_remove)
        
        # Fallback to API manager if distributed DNS failed or not available
        if not changes_made and self.api_dns_manager:
            logger.info("Using API fallback for DNS changes")
            changes_made = self.api_dns_manager.process_dns_changes(entries_to_add, entries_to_remove)
        
        return changes_made
    
    def _process_changes_distributed(self, 
                                   entries_to_add: List[Dict[str, Any]], 
                                   entries_to_remove: List[Dict[str, Any]]) -> bool:
        """Process changes using distributed DNS manager"""
        changes_made = False
        
        try:
            # Process removals first
            for entry in entries_to_remove:
                hostname = entry.get('hostname')
                if not hostname:
                    continue
                
                # Handle container removals (all entries)
                if 'ip' not in entry and 'network_name' not in entry:
                    if self.distributed_dns.remove_container_record(hostname):
                        changes_made = True
                    continue
                
                # Handle specific entry removals
                network_name = entry.get('network_name')
                if self.distributed_dns.remove_container_record(hostname, network_name):
                    changes_made = True
            
            # Process additions
            for entry in entries_to_add:
                hostname = entry.get('hostname')
                ip = entry.get('ip')
                network_name = entry.get('network_name')
                
                if not hostname or not ip:
                    continue
                
                if self.distributed_dns.add_container_record(hostname, ip, network_name):
                    changes_made = True
            
            logger.info(f"Processed {len(entries_to_add)} additions and {len(entries_to_remove)} removals via distributed DNS")
            
        except Exception as e:
            logger.error(f"Distributed DNS processing failed: {e}")
            changes_made = False
        
        return changes_made
    
    def cleanup_dns_records(self, batch_size=None, max_hostnames=None) -> int:
        """Clean up DNS records - delegate to appropriate manager"""
        if self.api_dns_manager:
            return self.api_dns_manager.cleanup_dns_records(batch_size, max_hostnames)
        else:
            logger.info("No cleanup available without API manager")
            return 0
    
    def update_dns(self, hostname: str, ip: str, network_name: str = None, pre_fetched_entries=None) -> bool:
        """Update DNS entry - use distributed DNS when available"""
        if self.distributed_dns:
            return self.distributed_dns.add_container_record(hostname, ip, network_name)
        elif self.api_dns_manager:
            return self.api_dns_manager.update_dns(hostname, ip, network_name, pre_fetched_entries)
        else:
            logger.error("No DNS manager available")
            return False
    
    def remove_dns(self, hostname: str, pre_fetched_entries=None) -> bool:
        """Remove DNS entries - use distributed DNS when available"""
        if self.distributed_dns:
            return self.distributed_dns.remove_container_record(hostname)
        elif self.api_dns_manager:
            return self.api_dns_manager.remove_dns(hostname, pre_fetched_entries)
        else:
            logger.error("No DNS manager available")
            return False

class DNSManager:
    def __init__(self, api_client, base_domain="docker.local", host_name="unknown"):
        """Initialize the DNS Manager with API client and settings."""
        self.api = api_client
        self.base_domain = base_domain
        self.host_name = host_name
    
        # Track when Unbound was last reconfigured - initialize to current time
        self.last_reconfigure_time = time.time()
    
        # Tracking reconfiguration statistics
        self.updates_since_restart = 0
        self.restart_threshold = int(os.environ.get('RESTART_THRESHOLD', '100'))
        self.restart_interval = int(os.environ.get('RESTART_INTERVAL', '86400'))  # Default 1 day
    
        # Maximum time for reconfiguration
        self.max_reconfigure_time = int(os.environ.get('MAX_RECONFIGURE_TIME', '120'))
    
        # Verification check delay (set to 0 to disable the post-deletion delay)
        self.verification_delay = int(os.environ.get('VERIFICATION_DELAY', '0'))
    
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
        """Get all DNS entries from OPNsense with improved caching."""
        # Check if we have a valid cached version
        cached_entries = None if force_refresh else self.cache.get('all_dns_entries')
        if cached_entries:
            logger.debug("Using cached DNS entries")
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
    
    def update_dns(self, hostname: str, ip: str, network_name: str = None, 
                  pre_fetched_entries=None) -> bool:
        """Update DNS entry for a hostname with the given IP."""
        domain = self.get_domain_for_network(network_name)
        network_desc = network_name or "default"
        
        logger.info(f"Updating DNS: {hostname}.{domain} → {ip} ({network_desc})")
        
        # Use pre-fetched entries if provided, otherwise fetch
        dns_entries = pre_fetched_entries if pre_fetched_entries is not None else self.get_all_dns_entries()
        
        # Check if this entry already exists with the same IP
        if self._entry_exists(hostname, domain, ip, dns_entries):
            logger.info(f"Entry already exists with same IP: {hostname}.{domain} → {ip}")
            return False  # No changes were made
        
        # Check if entries exist with different IPs and remove them
        self._clean_old_entries(hostname, domain, ip, dns_entries)
        
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
        return True  # Changes were made
    
    def _clean_old_entries(self, hostname: str, domain: str, new_ip: str, 
                          pre_fetched_entries=None) -> bool:
        """Remove existing entries for hostname/domain with different IPs."""
        dns_entries = pre_fetched_entries if pre_fetched_entries is not None else self.get_all_dns_entries()
        changes_made = False
        
        if hostname not in dns_entries:
            return changes_made
            
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
                if self.remove_specific_dns(uuid, hostname, domain, old_ip, skip_reconfigure=True):
                    changes_made = True
                    
        return changes_made
    
    def cleanup_dns_records(self, batch_size=None, max_hostnames=None) -> int:
        """
        Clean up duplicate and stale DNS records with batch processing.
        
        Args:
            batch_size: Maximum number of records to remove in a single batch (defaults to DNS_CLEANUP_BATCH_SIZE env var or 50)
            max_hostnames: Maximum number of hostnames to process in one run (defaults to DNS_CLEANUP_MAX_HOSTNAMES env var or 25)
                
        Returns:
            int: Number of records removed
        """
        # Use environment variables if parameters not specified
        if batch_size is None:
            batch_size = int(os.environ.get('DNS_CLEANUP_BATCH_SIZE', '50'))
        
        if max_hostnames is None:
            max_hostnames = int(os.environ.get('DNS_CLEANUP_MAX_HOSTNAMES', '25'))
        
        logger.info(f"Starting DNS record cleanup (batch_size={batch_size}, max_hostnames={max_hostnames})")
        dns_entries = self.get_all_dns_entries(force_refresh=True)
        records_removed = 0
        changes_made = False
        
        # Dictionary to track latest IP for each hostname/domain
        hostname_domains = {}
        
        # First pass: identify the latest IP for each hostname/domain
        for hostname, entries in dns_entries.items():
            if hostname not in hostname_domains:
                hostname_domains[hostname] = {}
                
            for entry in entries:
                domain = entry.get('domain', '')
                ip = entry.get('ip', '')
                
                key = f"{hostname}.{domain}"
                
                if domain not in hostname_domains[hostname]:
                    hostname_domains[hostname][domain] = {
                        'expected_ip': ip,
                        'count': 1,
                        'entries': [entry]
                    }
                else:
                    # Add this entry to the list
                    hostname_domains[hostname][domain]['count'] += 1
                    hostname_domains[hostname][domain]['entries'].append(entry)
        
        # Second pass: find hostnames with duplicates
        duplicates = []
        for hostname, domains in hostname_domains.items():
            for domain, data in domains.items():
                if data['count'] > 1:
                    duplicates.append((hostname, domain, data))
        
        # Sort by duplicate count (most duplicates first)
        duplicates.sort(key=lambda x: x[2]['count'], reverse=True)
        
        logger.info(f"Found {len(duplicates)} hostname/domain combinations with duplicates")
        
        if not duplicates:
            logger.info("No duplicate DNS entries found")
            return 0
        
        # Log the top 5 worst offenders
        if duplicates:
            logger.info("Top duplicate offenders:")
            for i, (hostname, domain, data) in enumerate(duplicates[:5]):
                logger.info(f"  {hostname}.{domain}: {data['count']} entries")
        
        # Calculate total duplicates
        total_duplicates = sum(data['count'] - 1 for _, _, data in duplicates)
        logger.info(f"Found {total_duplicates} duplicate entries to remove")
        
        # Process up to max_hostnames hostname/domain combinations
        hostnames_to_process = min(max_hostnames, len(duplicates))
        logger.info(f"Will process {hostnames_to_process} hostname/domain combinations in this run")
        
        # Prepare entries to remove
        entries_to_remove = []
        hostnames_processed = 0
        
        for hostname, domain, data in duplicates[:hostnames_to_process]:
            expected_ip = data['expected_ip']
            all_entries = data['entries']
            
            # Sort entries - keep one entry with expected_ip, remove others
            duplicates_for_hostname = []
            keep_first = True
            
            for entry in all_entries:
                ip = entry.get('ip', '')
                uuid = entry.get('uuid', '')
                desc = entry.get('description', '')
                
                # Keep only the first entry with expected IP
                if ip == expected_ip and keep_first:
                    keep_first = False  # Mark that we've kept one entry
                    continue
                
                # Skip removal if the description doesn't match our host
                if self.host_name != "unknown" and f"Docker container on {self.host_name}" not in desc:
                    continue
                
                duplicates_for_hostname.append((uuid, hostname, domain, ip))
            
            if duplicates_for_hostname:
                entries_to_remove.extend(duplicates_for_hostname)
                hostnames_processed += 1
                if len(duplicates_for_hostname) > 1:
                    logger.info(f"Will remove {len(duplicates_for_hostname)} duplicates for {hostname}.{domain}")
        
        # Process entries in batches
        total_removed = 0
        batch_count = (len(entries_to_remove) + batch_size - 1) // batch_size if entries_to_remove else 0
        
        logger.info(f"Will process {len(entries_to_remove)} entries in {batch_count} batches of up to {batch_size}")
        
        for i in range(0, len(entries_to_remove), batch_size):
            batch_number = (i // batch_size) + 1
            current_batch = entries_to_remove[i:i+batch_size]
            batch_removed = 0
            
            logger.info(f"Processing batch {batch_number}/{batch_count} - {len(current_batch)} entries")
            
            for uuid, hostname, domain, ip in current_batch:
                logger.info(f"Removing duplicate DNS entry: {hostname}.{domain} → {ip}")
                if self.remove_specific_dns(uuid, hostname, domain, ip, skip_reconfigure=True):
                    batch_removed += 1
                    total_removed += 1
                    changes_made = True
            
            logger.info(f"Batch {batch_number} complete: {batch_removed}/{len(current_batch)} entries removed")
            
            # Reconfigure after each batch if any records were removed
            if changes_made:
                logger.info(f"Reconfiguring Unbound after removing {batch_removed} records in batch {batch_number}")
                self.reconfigure_unbound()
                changes_made = False
        
        logger.info(f"DNS cleanup complete: removed {total_removed} duplicate records")
        return total_removed

    def process_dns_changes(self, 
                           entries_to_add: List[Dict[str, Any]], 
                           entries_to_remove: List[Dict[str, Any]]) -> bool:
        """
        Process DNS changes in a batch.
        
        Args:
            entries_to_add: List of entries to add [{hostname, ip, network_name}]
            entries_to_remove: List of entries to remove [{hostname, uuid, domain, ip}] or [{hostname}] for full removal
            
        Returns:
            bool: True if changes were made, False otherwise
        """
        if not entries_to_add and not entries_to_remove:
            logger.info("No DNS changes to process")
            return False
            
        changes_made = False
        
        # Fetch all entries once at the beginning
        all_dns_entries = self.get_all_dns_entries(force_refresh=True)
        
        # Process removals first
        if entries_to_remove:
            logger.info(f"Processing {len(entries_to_remove)} DNS entries to remove")
            for entry in entries_to_remove:
                hostname = entry.get('hostname')
                
                # Handle container removals (all entries)
                if 'ip' not in entry and 'network_name' not in entry:
                    if self.remove_dns(hostname, pre_fetched_entries=all_dns_entries):
                        changes_made = True
                        # Update our local cache of DNS entries to reflect removal
                        if hostname in all_dns_entries:
                            del all_dns_entries[hostname]
                    continue
                
                # Handle specific entry removals
                ip = entry.get('ip')
                network_name = entry.get('network_name')
                domain = self.get_domain_for_network(network_name)
                
                # Find the UUID for this entry
                uuid = None
                if hostname in all_dns_entries:
                    for dns_entry in all_dns_entries[hostname]:
                        if dns_entry.get('domain') == domain and dns_entry.get('ip') == ip:
                            uuid = dns_entry.get('uuid')
                            break
                
                if uuid:
                    logger.info(f"Removing DNS entry: {hostname}.{domain} → {ip}")
                    if self.remove_specific_dns(uuid, hostname, domain, ip, skip_reconfigure=True):
                        changes_made = True
                        # Update our local cache of DNS entries
                        if hostname in all_dns_entries:
                            all_dns_entries[hostname] = [e for e in all_dns_entries[hostname] 
                                                      if e.get('uuid') != uuid]
        
        # Process additions
        if entries_to_add:
            logger.info(f"Processing {len(entries_to_add)} DNS entries to add")
            for entry in entries_to_add:
                hostname = entry.get('hostname')
                ip = entry.get('ip')
                network_name = entry.get('network_name')
                
                # Check if this entry already exists
                domain = self.get_domain_for_network(network_name)
                if self._entry_exists(hostname, domain, ip, all_dns_entries):
                    logger.debug(f"Skipping existing entry: {hostname}.{domain} → {ip}")
                    continue
                    
                # Add the new entry
                logger.info(f"Adding DNS entry: {hostname}.{domain} → {ip}")
                if self.update_dns(hostname, ip, network_name, pre_fetched_entries=all_dns_entries):
                    changes_made = True
                    # Update our local cache of DNS entries
                    if hostname not in all_dns_entries:
                        all_dns_entries[hostname] = []
                    all_dns_entries[hostname].append({
                        'uuid': 'new', # Placeholder, will be replaced on next fetch
                        'domain': domain,
                        'ip': ip,
                        'description': f"Docker container on {self.host_name} ({network_name or 'default'})"
                    })
        
        # Reconfigure only if changes were made
        if changes_made:
            logger.info("Changes were made, reconfiguring Unbound")
            self.reconfigure_unbound()
        else:
            logger.info("No actual changes made, skipping reconfiguration")
        
        return changes_made
    
    # Additional helper function to find entry matching a certain domain and IP
    def _entry_exists(self, hostname: str, domain: str, ip: str, 
                     pre_fetched_entries=None) -> bool:
        """
        Check if a DNS entry already exists with the same IP.
        
        Args:
            hostname: The hostname to check
            domain: The domain to check
            ip: The IP address to check
            pre_fetched_entries: Optional pre-fetched DNS entries
            
        Returns:
            bool: True if the entry exists, False otherwise
        """
        dns_entries = pre_fetched_entries if pre_fetched_entries is not None else self.get_all_dns_entries()
        
        if hostname in dns_entries:
            for entry in dns_entries[hostname]:
                if entry['domain'] == domain and entry['ip'] == ip:
                    return True
                    
        return False
    
    def remove_dns(self, hostname: str, pre_fetched_entries=None) -> bool:
        """Remove all DNS entries for a hostname."""
        logger.info(f"Removing all DNS entries for {hostname}")
        entries = pre_fetched_entries if pre_fetched_entries is not None else self.get_all_dns_entries()
        
        if hostname not in entries:
            logger.info(f"No DNS entries found for {hostname}")
            return False
            
        changes_made = False
        for entry in entries[hostname]:
            desc = entry.get('description', '')
            if f"Docker container on {self.host_name}" in desc:
                uuid = entry.get('uuid', '')
                domain = entry.get('domain', '')
                ip = entry.get('ip', '')
                
                # Skip reconfigure for individual deletions, we'll do it once at the end if needed
                if self.remove_specific_dns(uuid, hostname, domain, ip, skip_reconfigure=True):
                    changes_made = True
        
        # Invalidate cache if any entries were removed
        if changes_made:
            self.cache.invalidate('all_dns_entries')
            
        return changes_made
    
    def remove_specific_dns(self, uuid: str, hostname: str, domain: str, ip: str, skip_reconfigure=False) -> bool:
        """Remove a specific DNS entry identified by UUID.
        
        Args:
            uuid: The UUID of the DNS entry to remove
            hostname: The hostname part of the DNS entry
            domain: The domain part of the DNS entry
            ip: The IP address of the DNS entry
            skip_reconfigure: If True, don't reconfigure Unbound after removal
            
        Returns:
            bool: True if the entry was removed, False otherwise
        """
        logger.info(f"Removing DNS entry: {hostname}.{domain} → {ip} (UUID: {uuid})")
        
        # Add retry logic for API timeouts
        max_retries = 2
        retry_count = 0
        success = False
        
        while retry_count <= max_retries and not success:
            if retry_count > 0:
                # Add exponential backoff between retries
                wait_time = 5 * (2 ** (retry_count - 1))
                logger.info(f"Retry attempt {retry_count}/{max_retries} after waiting {wait_time}s")
                time.sleep(wait_time)
            
            try:
                # Use POST with proper Content-Type header and empty JSON payload
                response = self.api.post(f"unbound/settings/delHostOverride/{uuid}", data={})
                
                # Check for endpoint not found error
                if isinstance(response, dict) and response.get("errorMessage") == "Endpoint not found":
                    logger.warning(f"Endpoint not found when removing entry. The entry may have already been removed or the API endpoint changed.")
                    # Consider this a success if we cannot find the endpoint - the entry is either gone or never existed
                    success = True
                    break
                    
                # Check for timeout errors
                if isinstance(response, dict) and response.get("status") == "error" and "curl failed with code 28" in str(response.get("message", "")):
                    logger.warning(f"Request timed out (attempt {retry_count+1}/{max_retries+1})")
                    retry_count += 1
                    continue
                    
                # Check for successful deletion
                if response.get("result") == "deleted":
                    logger.info(f"Successfully removed DNS entry: {hostname}.{domain} → {ip}")
                    success = True
                    break
                else:
                    logger.error(f"Failed to remove DNS entry: {response}")
                    retry_count += 1
            except Exception as e:
                logger.error(f"Exception when removing DNS entry: {e}")
                retry_count += 1
        
        # If we successfully deleted the record
        if success:
            # Invalidate cache
            self.cache.invalidate('all_dns_entries')
            
            # Only reconfigure if not skipping and no other operations are pending
            if not skip_reconfigure:
                logger.info("Reconfiguring Unbound after DNS entry removal")
                self.reconfigure_unbound()
            
            # Optional verification step with configurable delay
            if self.verification_delay > 0:
                logger.debug(f"Waiting {self.verification_delay}s for verification")
                time.sleep(self.verification_delay)
                
                # Verify the record was actually removed
                try:
                    # Verify deletion with forced refresh
                    entries = self.get_all_dns_entries(force_refresh=True)
                    
                    # Check if the entry is still present
                    removed = True
                    if hostname in entries:
                        for entry in entries[hostname]:
                            if entry.get('uuid') == uuid:
                                logger.warning(f"Record removal reported success but record still exists: {hostname}.{domain}")
                                removed = False
                    
                    return removed
                except Exception as e:
                    logger.warning(f"Could not verify record removal due to error: {e}")
                    # Consider it a success since the API reported deletion was successful
                    return True
            
            return True  # Success with no verification
        
        return False
        
    def reconfigure_unbound(self) -> bool:
        """Reconfigure Unbound to apply DNS changes."""
        logger.info("Reconfiguring Unbound to apply DNS changes")
        
        # Record reconfiguration time for statistics
        now = time.time()
        elapsed = now - self.last_reconfigure_time
        self.last_reconfigure_time = now
        self.updates_since_restart += 1
        
        # Decide if we should restart instead of reconfigure
        should_restart = False
        
        # Check service uptime if possible
        unbound_uptime = self._get_unbound_uptime()
        
        if self.updates_since_restart >= self.restart_threshold:
            logger.info(f"Reached {self.updates_since_restart} updates, forcing restart")
            should_restart = True
        elif unbound_uptime is not None and unbound_uptime > self.restart_interval:
            # Only restart if Unbound has been running longer than restart_interval
            logger.info(f"Unbound has been running for {unbound_uptime/60:.1f} minutes, restarting")
            should_restart = True
        elif unbound_uptime is None and elapsed > self.restart_interval:
            # Fallback to our own tracking if we couldn't get actual Unbound uptime
            logger.info(f"It's been {elapsed/60:.1f} minutes since last restart")
            should_restart = True
        
        if should_restart:
            return self._restart_unbound()
        
        # Make the reconfigure API call with timeout
        return self._reconfigure_with_timeout()
    
    def _get_unbound_uptime(self) -> Optional[float]:
        """Get the uptime of the Unbound service if possible."""
        try:
            # Try to get Unbound status from API
            response = self.api.get("unbound/service/status")
            if response and isinstance(response, dict):
                # Check if running and get start time
                if response.get("running", False):
                    # If there's a start time field in the response, calculate uptime
                    start_time = response.get("start_time")
                    if start_time and isinstance(start_time, (int, float)):
                        uptime = time.time() - start_time
                        logger.debug(f"Unbound service uptime: {uptime/60:.1f} minutes")
                        return uptime
        except Exception as e:
            logger.debug(f"Failed to get Unbound uptime: {e}")
        
        return None
        
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

        
    def batch_update_dns(self, updates: List[Tuple[str, str, str]], pre_fetched_entries=None) -> bool:
        """Update multiple DNS entries in a batch and reconfigure once."""
        if not updates:
            return False  # No changes were attempted
                
        logger.info(f"Processing batch of {len(updates)} DNS updates")
        success_count = 0
        changes_made = False
            
        # Use pre-fetched entries if provided, otherwise fetch once here
        all_entries = pre_fetched_entries if pre_fetched_entries is not None else self.get_all_dns_entries(force_refresh=True)
        
        for hostname, ip, network_name in updates:
            # Check if we already have this exact record to avoid unnecessary updates
            domain = self.get_domain_for_network(network_name)
            entry_exists = False
            
            # Check entries from our initial fetch - IMPROVED COMPARISON
            if hostname in all_entries:
                for entry in all_entries[hostname]:
                    # Proper domain comparison - either exact match or expected domain
                    domain_match = (
                        entry['domain'] == domain or
                        (entry['domain'] == self.base_domain and domain == self.base_domain)
                    )
                    
                    # Exact IP match
                    if domain_match and entry['ip'] == ip:
                        logger.info(f"Skipping existing entry: {hostname}.{domain} → {ip}")  # Changed to INFO level
                        success_count += 1
                        entry_exists = True
                        break
            
            if entry_exists:
                continue
                
            # Apply the update using the pre-fetched entries
            if self.update_dns(hostname, ip, network_name, pre_fetched_entries=all_entries):
                success_count += 1
                changes_made = True
                # Update the all_entries with the new entry to avoid unnecessary fetches
                if hostname not in all_entries:
                    all_entries[hostname] = []
                all_entries[hostname].append({
                    'domain': domain,
                    'ip': ip,
                    'description': f"Docker container on {self.host_name} ({network_name or 'default'})"
                })
                        
        success_rate = success_count / len(updates) if updates else 0
        logger.info(f"Batch update completed with {success_rate:.0%} success rate")
        
        # Only reconfigure if actual changes were made
        if changes_made:
            logger.info("Changes were made during batch update, reconfiguring Unbound")
            self.reconfigure_unbound()
        else:
            logger.info("No actual changes made during batch update, skipping reconfiguration")
                
        return changes_made  # Return whether changes were made
