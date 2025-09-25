# distributed_dns_manager.py
"""
Distributed DNS Management for dns-updater
Handles local Unbound instances and replication between hosts
"""

import os
import json
import time
import logging
import subprocess
import socket
import threading
from typing import Dict, List, Set, Tuple, Optional, Any
from pathlib import Path
import requests

logger = logging.getLogger('dns_updater.distributed')

class LocalUnboundManager:
    """Manages local Unbound instance (direct file manipulation)"""
    
    def __init__(self, records_file: str, reload_command: str, host_type: str = "host"):
        self.records_file = Path(records_file)
        self.reload_command = reload_command
        self.host_type = host_type  # "host" or "docker"
        self.lock_file = Path(f"/tmp/unbound-{os.getpid()}.lock")
        
        # Ensure records file exists
        self._ensure_records_file()
        
        logger.info(f"Initialized LocalUnboundManager: {records_file} ({host_type})")
    
    def _ensure_records_file(self):
        """Ensure the DNS records file exists with proper header"""
        if not self.records_file.exists():
            self.records_file.parent.mkdir(parents=True, exist_ok=True)
            self._write_header()
        elif not self._has_header():
            self._write_header()
    
    def _has_header(self) -> bool:
        """Check if file has the proper header"""
        if not self.records_file.exists():
            return False
        try:
            with open(self.records_file, 'r') as f:
                content = f.read(200)  # Read first 200 chars
                return "Dynamic Docker container records" in content
        except Exception:
            return False
    
    def _write_header(self):
        """Write header to records file"""
        header = """# Dynamic Docker container records
# This file is automatically managed by dns-updater
# Manual changes will be overwritten

"""
        try:
            with open(self.records_file, 'w') as f:
                f.write(header)
            logger.info(f"Created/updated records file: {self.records_file}")
        except Exception as e:
            logger.error(f"Failed to write header to {self.records_file}: {e}")
    
    def add_record(self, hostname: str, ip: str, domain: str = "docker.local") -> bool:
        """Add DNS record to local Unbound"""
        record_line = f'local-data: "{hostname}.{domain}. IN A {ip}"'
        
        try:
            # Read current records
            current_records = []
            if self.records_file.exists():
                with open(self.records_file, 'r') as f:
                    current_records = f.readlines()
            
            # Remove existing record for this hostname.domain
            filtered_records = [
                line for line in current_records 
                if not line.strip().startswith(f'local-data: "{hostname}.{domain}.')
            ]
            
            # Add new record
            if not any(line.startswith('#') for line in filtered_records[-3:]):
                filtered_records.append(record_line + '\n')
            else:
                # Insert before any trailing comments
                insert_pos = len(filtered_records)
                filtered_records.insert(insert_pos, record_line + '\n')
            
            # Write back to file
            with open(self.records_file, 'w') as f:
                f.writelines(filtered_records)
            
            logger.info(f"Added record: {hostname}.{domain} -> {ip}")
            return True
            
        except Exception as e:
            logger.error(f"Failed to add record {hostname}.{domain}: {e}")
            return False
    
    def remove_record(self, hostname: str, domain: str = "docker.local") -> bool:
        """Remove DNS record from local Unbound"""
        try:
            if not self.records_file.exists():
                return True  # Nothing to remove
            
            # Read current records
            with open(self.records_file, 'r') as f:
                current_records = f.readlines()
            
            # Filter out the record
            original_count = len(current_records)
            filtered_records = [
                line for line in current_records 
                if not line.strip().startswith(f'local-data: "{hostname}.{domain}.')
            ]
            
            # Write back if changed
            if len(filtered_records) != original_count:
                with open(self.records_file, 'w') as f:
                    f.writelines(filtered_records)
                logger.info(f"Removed record: {hostname}.{domain}")
                return True
            else:
                logger.debug(f"Record not found: {hostname}.{domain}")
                return True
                
        except Exception as e:
            logger.error(f"Failed to remove record {hostname}.{domain}: {e}")
            return False
    
    def remove_all_records(self, hostname: str) -> bool:
        """Remove all DNS records for a hostname"""
        try:
            if not self.records_file.exists():
                return True
            
            # Read current records
            with open(self.records_file, 'r') as f:
                current_records = f.readlines()
            
            # Filter out all records for this hostname
            original_count = len(current_records)
            filtered_records = [
                line for line in current_records 
                if not (line.strip().startswith('local-data: "') and f'"{hostname}.' in line)
            ]
            
            # Write back if changed
            if len(filtered_records) != original_count:
                with open(self.records_file, 'w') as f:
                    f.writelines(filtered_records)
                removed_count = original_count - len(filtered_records)
                logger.info(f"Removed {removed_count} records for hostname: {hostname}")
                return True
            else:
                logger.debug(f"No records found for hostname: {hostname}")
                return True
                
        except Exception as e:
            logger.error(f"Failed to remove records for {hostname}: {e}")
            return False
    
    def reload_unbound(self) -> bool:
        """Reload Unbound configuration"""
        try:
            if self.host_type == "docker":
                # For Docker-based Unbound
                result = subprocess.run(
                    self.reload_command.split(),
                    capture_output=True,
                    text=True,
                    timeout=30
                )
            else:
                # For host-based Unbound - create signal file that host can monitor
                signal_file = Path("/etc/unbound/reload-signal")
                try:
                    signal_file.touch()
                    logger.info("Created reload signal file")
                    # Give it a moment to be processed
                    time.sleep(1)
                    return True
                except Exception as e:
                    logger.error(f"Failed to create reload signal: {e}")
                    return False
            
            if result.returncode == 0:
                logger.info("Unbound reloaded successfully")
                return True
            else:
                logger.error(f"Unbound reload failed: {result.stderr}")
                return False
                
        except subprocess.TimeoutExpired:
            logger.error("Unbound reload timed out")
            return False
        except Exception as e:
            logger.error(f"Unbound reload error: {e}")
            return False

class DNSReplicationClient:
    """Client for replicating DNS records to remote hosts"""
    
    def __init__(self, remote_hosts: Dict[str, str]):
        self.remote_hosts = remote_hosts  # {host_name: host_ip}
        self.session = requests.Session()
        self.session.timeout = (5, 15)  # connect, read timeout
        
        logger.info(f"Initialized DNS replication to hosts: {list(remote_hosts.keys())}")
    
    def replicate_record(self, action: str, hostname: str, ip: str = None, domain: str = "docker.local") -> Dict[str, bool]:
        """Replicate DNS record action to remote hosts"""
        results = {}
        
        for host_name, host_ip in self.remote_hosts.items():
            try:
                url = f"http://{host_ip}:8080/dns/{action}"
                data = {
                    "hostname": hostname,
                    "domain": domain
                }
                if ip:
                    data["ip"] = ip
                
                response = self.session.post(url, json=data, timeout=10)
                results[host_name] = response.status_code == 200
                
                if response.status_code == 200:
                    logger.debug(f"Replicated {action} for {hostname}.{domain} to {host_name}")
                else:
                    logger.warning(f"Failed to replicate to {host_name}: {response.status_code}")
                    
            except Exception as e:
                logger.error(f"Replication failed to {host_name}: {e}")
                results[host_name] = False
        
        return results


class DistributedDNSManager:
    """Main distributed DNS management class"""
    
    def __init__(self, config: Dict[str, Any]):
        self.config = config
        self.role = config.get("role", "client")  # "master" or "client"
        self.host_name = config.get("host_name", "unknown")
        
        # Initialize local Unbound manager if configured
        self.local_unbound = None
        if config.get("local_unbound"):
            unbound_config = config["local_unbound"]
            self.local_unbound = LocalUnboundManager(
                records_file=unbound_config["records_file"],
                reload_command=unbound_config["reload_command"],
                host_type=unbound_config.get("type", "host")
            )
        
        # Initialize replication client if we're the master
        self.replication_client = None
        if self.role == "master" and config.get("replicate_to"):
            self.replication_client = DNSReplicationClient(config["replicate_to"])
        
        # Initialize API client for fallback
        self.api_client = None
        if config.get("opnsense_fallback"):
            # Import the existing API client
            from api_client import OPNsenseAPI
            api_config = config["opnsense_fallback"]
            self.api_client = OPNsenseAPI(
                api_config["url"],
                api_config["key"],
                api_config["secret"]
            )
        
        logger.info(f"Initialized DistributedDNSManager: role={self.role}, host={self.host_name}")
    
    def process_batch_changes(self, entries_to_add: List[Dict[str, Any]], entries_to_remove: List[Dict[str, Any]]) -> bool:
        """Process multiple DNS changes in a batch with single reload"""
        if not entries_to_add and not entries_to_remove:
            return False
        
        changes_made = False
        
        # Process all removals first (without reloading)
        for entry in entries_to_remove:
            hostname = entry.get('hostname')
            if not hostname:
                continue
                
            network_name = entry.get('network_name')
            if self._remove_record_no_reload(hostname, network_name):
                changes_made = True
                logger.info(f"Queued removal: {hostname} from {network_name or 'all domains'}")
        
        # Process all additions (without reloading)
        for entry in entries_to_add:
            hostname = entry.get('hostname')
            ip = entry.get('ip')
            network_name = entry.get('network_name')
            
            if not hostname or not ip:
                continue
                
            if self._add_record_no_reload(hostname, ip, network_name):
                changes_made = True
                logger.info(f"Queued addition: {hostname}.{network_name or 'docker.local'} -> {ip}")
        
        # Single reload at the end if any changes were made
        if changes_made and self.local_unbound:
            reload_success = self.local_unbound.reload_unbound()
            logger.info(f"Batch processed {len(entries_to_add)} additions and {len(entries_to_remove)} removals, reload: {'successful' if reload_success else 'failed'}")
            changes_made = reload_success
        
        # Handle replication for master role
        if changes_made and self.role == "master" and self.replication_client:
            self._replicate_batch_changes(entries_to_add, entries_to_remove)
        
        # Handle OPNsense fallback for critical records
        if changes_made and self.api_client:
            self._handle_opnsense_fallback(entries_to_add, entries_to_remove)
        
        return changes_made
    
    def _add_record_no_reload(self, container_name: str, ip: str, network_name: str) -> bool:
        """Add DNS record without triggering reload"""
        success = True
        domains = ["docker.local"]
        
        if network_name and network_name != "bridge":
            sanitized_network = self._sanitize_network_name(network_name)
            domains.append(f"{sanitized_network}.docker.local")
        
        if self.local_unbound:
            for domain in domains:
                local_success = self.local_unbound.add_record(container_name, ip, domain)
                success = success and local_success
        
        return success
    
    def _remove_record_no_reload(self, container_name: str, network_name: str = None) -> bool:
        """Remove DNS record without triggering reload"""
        success = True
        
        if self.local_unbound:
            if network_name:
                # Remove from specific domain
                domains = ["docker.local"]
                sanitized_network = self._sanitize_network_name(network_name)
                domains.append(f"{sanitized_network}.docker.local")
                
                for domain in domains:
                    local_success = self.local_unbound.remove_record(container_name, domain)
                    success = success and local_success
            else:
                # Remove all records for this hostname
                success = self.local_unbound.remove_all_records(container_name)
        
        return success
    
    def _replicate_batch_changes(self, entries_to_add: List[Dict[str, Any]], entries_to_remove: List[Dict[str, Any]]):
        """Handle replication to other hosts"""
        try:
            # Replicate removals
            for entry in entries_to_remove:
                hostname = entry.get('hostname')
                if hostname:
                    self.replication_client.replicate_record("remove", hostname)
            
            # Replicate additions
            for entry in entries_to_add:
                hostname = entry.get('hostname')
                ip = entry.get('ip')
                if hostname and ip:
                    self.replication_client.replicate_record("add", hostname, ip)
            
            logger.info(f"Replicated {len(entries_to_add)} additions and {len(entries_to_remove)} removals")
        except Exception as e:
            logger.error(f"Batch replication failed: {e}")
    
    def _handle_opnsense_fallback(self, entries_to_add: List[Dict[str, Any]], entries_to_remove: List[Dict[str, Any]]):
        """Handle OPNsense API fallback for critical records"""
        try:
            from dns_manager import DNSManager
            dns_manager = DNSManager(self.api_client, "docker.local", self.host_name)
            
            critical_changes = False
            
            # Check for critical record changes
            for entry in entries_to_add + entries_to_remove:
                hostname = entry.get('hostname')
                if hostname and self._is_critical_record(hostname):
                    critical_changes = True
                    break
            
            if critical_changes:
                # Use the existing batch processing for critical records
                critical_adds = [e for e in entries_to_add if self._is_critical_record(e.get('hostname', ''))]
                critical_removes = [e for e in entries_to_remove if self._is_critical_record(e.get('hostname', ''))]
                
                if critical_adds or critical_removes:
                    dns_manager.process_dns_changes(critical_adds, critical_removes)
                    logger.info(f"Processed {len(critical_adds)} critical additions and {len(critical_removes)} critical removals via OPNsense")
            
        except Exception as e:
            logger.error(f"OPNsense fallback failed: {e}")
    
    def add_container_record(self, container_name: str, ip: str, network_name: str) -> bool:
        """Add DNS record for a container - LEGACY METHOD for single records"""
        # Convert single record to batch format
        entries_to_add = [{
            'hostname': container_name,
            'ip': ip,
            'network_name': network_name
        }]
        return self.process_batch_changes(entries_to_add, [])
    
    def remove_container_record(self, container_name: str, network_name: str = None) -> bool:
        """Remove DNS records for a container - LEGACY METHOD for single records"""
        # Convert single record to batch format
        entries_to_remove = [{
            'hostname': container_name,
            'network_name': network_name
        }]
        return self.process_batch_changes([], entries_to_remove)
    
    def _sanitize_network_name(self, network_name: str) -> str:
        """Sanitize network name for DNS compatibility"""
        if not network_name:
            return "network"
        
        # Remove common suffixes
        for suffix in ['_net', '-net', '_default', '-default']:
            if network_name.endswith(suffix):
                network_name = network_name[:-len(suffix)]
                break
        
        # Replace invalid characters with hyphens
        import re
        network_name = re.sub(r'[^a-zA-Z0-9\-]', '-', network_name)
        network_name = re.sub(r'-+', '-', network_name)  # Collapse multiple hyphens
        network_name = network_name.strip('-')  # Remove leading/trailing hyphens
        
        return network_name or "network"
    
    def _is_critical_record(self, container_name: str) -> bool:
        """Determine if this is a critical record that should be replicated to OPNsense"""
        critical_prefixes = [
            "caddy-public",  # Public-facing Caddy
            "smtp-proxy",    # SMTP services
            "traefik",       # Load balancers
            "nginx-proxy"    # Proxy services
        ]
        
        return any(container_name.startswith(prefix) for prefix in critical_prefixes)

    def create_distributed_dns_manager() -> DistributedDNSManager:
        """Create DistributedDNSManager based on environment variables"""
    
        # Determine role and host
        role = os.environ.get("DNS_ROLE", "client")  # "master" or "client"
        host_name = os.environ.get("HOST_NAME", "unknown")
    
        # Base configuration
        config = {
            "role": role,
            "host_name": host_name
        }
    
        # Local Unbound configuration
        if os.environ.get("LOCAL_UNBOUND_ENABLED", "false").lower() == "true":
            unbound_type = os.environ.get("LOCAL_UNBOUND_TYPE", "host")  # "host" or "docker"
        
            if unbound_type == "host":
                # Host-based Unbound (pita)
                config["local_unbound"] = {
                    "records_file": "/etc/unbound/docker-records.conf",
                    "reload_command": "/usr/local/bin/reload-unbound.sh",  # Use the script we created
                    "type": "host"
                }
            else:
                # Docker-based Unbound (babka)
                container_name = os.environ.get("LOCAL_UNBOUND_CONTAINER", "unbound-babka")
                config["local_unbound"] = {
                    "records_file": "/mnt/data-tank/docker/unbound-babka/unbound-config/docker-records.conf",
                    "reload_command": f"docker exec {container_name} unbound-control reload",
                    "type": "docker"
                }
    
        # Replication configuration (master only)
        if role == "master":
            replicate_to = {}
            if os.environ.get("REPLICATE_TO_BABKA", "false").lower() == "true":
                replicate_to["babka"] = os.environ.get("BABKA_IP", "192.168.4.88")
        
            if replicate_to:
                config["replicate_to"] = replicate_to
    
        # OPNsense fallback configuration
        if os.environ.get("OPNSENSE_FALLBACK_ENABLED", "false").lower() == "true":
            config["opnsense_fallback"] = {
                "url": os.environ.get("OPNSENSE_URL"),
                "key": os.environ.get("OPNSENSE_KEY"),  
                "secret": os.environ.get("OPNSENSE_SECRET")
            }
    
        return DistributedDNSManager(config)
