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
    
    def cleanup_dns_records(self) -> int:
        """Clean up duplicate and stale DNS records."""
        logger.info("Starting DNS record cleanup")
        dns_entries = self.get_all_dns_entries(force_refresh=True)
        records_removed = 0
        changes_made = False
        
        # Dictionary to track latest IP for each hostname/domain
        latest_ips = {}
        
        # First pass: identify the latest IP for each hostname/domain
        for hostname, entries in dns_entries.items():
            for entry in entries:
                domain = entry.get('domain', '')
                ip = entry.get('ip', '')
                
                key = f"{hostname}.{domain}"
                if key not in latest_ips:
                    latest_ips[key] = {'ip': ip, 'count': 1}
                else:
                    latest_ips[key]['count'] += 1
        
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
                    # Skip reconfigure for individual deletions, we'll do it once at the end if needed
                    if self.remove_specific_dns(uuid, hostname, domain, ip, skip_reconfigure=True):
                        records_removed += 1
                        latest_ips[key]['count'] -= 1
                        changes_made = True
        
        # If any records were removed, reconfigure to apply changes
        if changes_made:
            logger.info(f"Reconfiguring Unbound after removing {records_removed} records")
            self.reconfigure_unbound()
        
        logger.info(f"DNS cleanup complete: removed {records_removed} duplicate records")
        return records_removed

    def _entry_exists(self, hostname: str, domain: str, ip: str, 
                     pre_fetched_entries=None) -> bool:
        """Check if a DNS entry already exists with the same IP."""
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
        """Remove a specific DNS entry identified by UUID."""
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
                response = self.api.post(f"unbound/settings/delHostOverride/{uuid}")
                
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
            
            # Check entries from our initial fetch
            if hostname in all_entries:
                for entry in all_entries[hostname]:
                    if entry['domain'] == domain and entry['ip'] == ip:
                        logger.debug(f"Skipping existing entry: {hostname}.{domain} → {ip}")
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
        
