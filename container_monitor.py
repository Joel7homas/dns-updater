# container_monitor.py
import os
import logging
import time
import docker
from typing import Dict, List, Set, Tuple, Optional, Any
import ipaddress

# Get module logger
logger = logging.getLogger('dns_updater.container')

class ContainerMonitor:

    def __init__(self, dns_manager):
        """Initialize container monitor with DNS manager."""
        self.dns_manager = dns_manager
        self.docker_client = None
        
        # Initialize container network state tracker
        from container_network_state import ContainerNetworkState
        self.network_state = ContainerNetworkState(
            cleanup_cycles=int(os.environ.get('STATE_CLEANUP_CYCLES', '3'))
        )
        
        # Track flannel network information
        self.flannel_network = None
        
        # Load configuration from environment variables
        self.sync_interval = int(os.environ.get('DNS_SYNC_INTERVAL', '60'))
        self.cleanup_interval = int(os.environ.get('DNS_CLEANUP_INTERVAL', '3600'))
        
        # Connect to Docker
        self._connect_to_docker()
        self._detect_flannel_network()
        
        logger.info("Container monitor initialized")
        
    def _connect_to_docker(self) -> None:
        """Connect to Docker daemon."""
        try:
            self.docker_client = docker.from_env()
            logger.info("Connected to Docker daemon")
        except docker.errors.DockerException as e:
            logger.error(f"Failed to connect to Docker: {e}")
            raise
            
    def _detect_flannel_network(self) -> None:
        """Detect flannel network from env file if it exists."""
        try:
            import os
            if os.path.exists('/var/run/flannel/subnet.env'):
                with open('/var/run/flannel/subnet.env', 'r') as f:
                    for line in f:
                        if line.startswith('FLANNEL_NETWORK='):
                            network_str = line.strip().split('=')[1]
                            self.flannel_network = ipaddress.IPv4Network(network_str)
                            logger.info(f"Detected flannel network: {self.flannel_network}")
                            return
        except Exception as e:
            logger.error(f"Failed to detect flannel network: {e}")
            
        logger.info("No flannel network detected")
    
    def is_flannel_ip(self, ip: str) -> bool:
        """Check if an IP address is in the flannel network."""
        if self.flannel_network is None:
            return False
            
        try:
            ip_obj = ipaddress.IPv4Address(ip)
            return ip_obj in self.flannel_network
        except ValueError:
            return False
    
    def get_container_networks(self) -> Dict[str, Dict[str, Set[str]]]:
        """Get updated container network information."""
        container_networks = {}
        
        try:
            for container in self.docker_client.containers.list():
                networks = container.attrs['NetworkSettings']['Networks']
                container_networks[container.name] = {}
                
                for network_name, network_config in networks.items():
                    ip = network_config.get('IPAddress', '')
                    if ip:
                        if network_name not in container_networks[container.name]:
                            container_networks[container.name][network_name] = set()
                        container_networks[container.name][network_name].add(ip)
        except Exception as e:
            logger.error(f"Error getting container networks: {e}")
            
        return container_networks
    
    def get_container_networks(self) -> Dict[str, Dict[str, str]]:
        """
        Get updated container network information as a nested dictionary.
        
        Returns:
            Dict mapping container names to dicts of {network_name: ip_address}
        """
        container_networks = {}
        
        try:
            for container in self.docker_client.containers.list():
                networks = container.attrs['NetworkSettings']['Networks']
                container_networks[container.name] = {}
                
                for network_name, network_config in networks.items():
                    ip = network_config.get('IPAddress', '')
                    if ip:
                        container_networks[container.name][network_name] = ip
        except Exception as e:
            logger.error(f"Error getting container networks: {e}")
            
        return container_networks
    
    def prepare_dns_updates(self) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
        """
        Prepare DNS updates from container network information.
        
        Returns:
            Tuple containing:
            - List of entries to add: [{hostname, ip, network_name}]
            - List of entries to remove: [{hostname, uuid, domain, ip}] or [{hostname}] for full removal
        """
        # Get current network state
        new_networks = self.get_container_networks()
        
        # Initialize return values
        entries_to_add = []
        entries_to_remove = []
        
        # Update the network state
        has_changes = self.network_state.update_state(new_networks)
        
        # If no changes, return empty lists
        if not has_changes:
            logger.info("No container network changes detected")
            return entries_to_add, entries_to_remove
        
        # Get specific changes
        changes = self.network_state.get_changes()
        
        # Log changes
        logger.info(f"Container changes: {len(changes['added_containers'])} new, " 
                   f"{len(changes['removed_containers'])} removed, "
                   f"{len(changes['network_changes'])} modified")
        
        # Process added containers
        for container in changes['added_containers']:
            # Safety check
            if container not in new_networks:
                continue
                
            for network_name, ip in new_networks[container].items():
                entries_to_add.append({
                    'hostname': container,
                    'ip': ip,
                    'network_name': network_name
                })
                
                # Also add to flannel domain if appropriate
                if self.is_flannel_ip(ip):
                    entries_to_add.append({
                        'hostname': container,
                        'ip': ip,
                        'network_name': 'flannel'
                    })
        
        # Process removed containers - these will be handled by the DNS manager
        entries_to_remove.extend([{'hostname': container} for container in changes['removed_containers']])
        
        # Process network changes
        for container, network_changes in changes['network_changes'].items():
            # Add new networks
            for network_name, ip in network_changes['added'].items():
                entries_to_add.append({
                    'hostname': container,
                    'ip': ip,
                    'network_name': network_name
                })
                
                # Also add to flannel domain if appropriate
                if self.is_flannel_ip(ip):
                    entries_to_add.append({
                        'hostname': container,
                        'ip': ip,
                        'network_name': 'flannel'
                    })
            
            # Remove obsolete networks
            for network_name, ip in network_changes['removed'].items():
                # The DNS manager will need to find the UUID for this entry
                entries_to_remove.append({
                    'hostname': container,
                    'ip': ip,
                    'network_name': network_name
                })
                
                # Also remove from flannel domain if appropriate
                if self.is_flannel_ip(ip):
                    entries_to_remove.append({
                        'hostname': container,
                        'ip': ip,
                        'network_name': 'flannel'
                    })
        
        return entries_to_add, entries_to_remove
    
    def sync_dns_entries(self) -> bool:
        """
        Synchronize DNS entries with current container state.
        
        Returns:
            bool: True if changes were made, False otherwise
        """
        logger.info("Starting DNS synchronization")
        
        # Prepare additions and removals
        entries_to_add, entries_to_remove = self.prepare_dns_updates()
        
        # If no changes, return early
        if not entries_to_add and not entries_to_remove:
            logger.info("No DNS changes needed")
            return False
            
        # Process changes
        changes_made = self.dns_manager.process_dns_changes(entries_to_add, entries_to_remove)
        
        # Get statistics for logging
        stats = self.network_state.get_statistics()
        logger.info(f"DNS synchronization complete: changed={changes_made}, "
                   f"containers={stats['container_count']}, "
                   f"multi-network={stats['multi_network_containers']}")
                   
        return changes_made
    
    def listen_for_events(self):
        """Listen for Docker events and update DNS accordingly."""
        logger.info("Starting Docker event listener")
        logger.info(f"Using sync interval: {self.sync_interval}s, cleanup interval: {self.cleanup_interval}s")
        
        last_sync_time = 0
        last_cleanup_time = 0
        changes_detected = False
        
        # Initial synchronization
        self.sync_dns_entries()
        last_sync_time = time.time()
        
        # Run cleanup on startup if configured
        if os.environ.get('CLEANUP_ON_STARTUP', 'true').lower() == 'true':
            logger.info("Performing initial cleanup")
            self.dns_manager.cleanup_dns_records()
            last_cleanup_time = time.time()
        
        try:
            for event in self.docker_client.events(decode=True):
                current_time = time.time()
                
                # Process container events that affect networking
                if event.get('Type') == 'container' and event.get('Action') in ['start', 'die', 'destroy', 'create']:
                    container_name = event['Actor']['Attributes'].get('name', 'unknown')
                    logger.info(f"Container event: {event.get('Action')} - {container_name}")
                    changes_detected = True
                
                # Check if it's time for periodic sync
                if current_time - last_sync_time > self.sync_interval:
                    logger.info(f"Periodic sync after {self.sync_interval}s")
                    
                    # Perform the sync - reconfiguration happens inside if changes were made
                    self.sync_dns_entries()
                    
                    # Reset state for next cycle
                    last_sync_time = current_time
                    changes_detected = False
                        
                # Periodic cleanup of duplicate DNS records
                if current_time - last_cleanup_time > self.cleanup_interval:
                    logger.info(f"Periodic DNS cleanup after {(current_time - last_cleanup_time)/3600:.1f}h")
                    self.dns_manager.cleanup_dns_records()
                    last_cleanup_time = current_time
                        
            # The for loop will exit if the Docker event stream ends
            logger.warning("Docker event stream ended unexpectedly, reconnecting")
            time.sleep(5)
            self._connect_to_docker()
            return self.listen_for_events()
                        
        except Exception as e:
            logger.error(f"Event listener error: {e}")
            # Try to reconnect
            time.sleep(5)
            self._connect_to_docker()
            return self.listen_for_events()
