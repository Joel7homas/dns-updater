# container_monitor.py
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
        self.container_networks = {}  # Last known state
        self.flannel_network = None
        
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
    
    def prepare_dns_updates(self) -> List[Tuple[str, str, str]]:
        """Prepare DNS updates from container network information."""
        new_networks = self.get_container_networks()
        updates = []
        
        # Add or update container DNS records
        for container_name, networks in new_networks.items():
            for network_name, ips in networks.items():
                for ip in ips:
                    # Check if this is a flannel IP
                    is_flannel = self.is_flannel_ip(ip)
                    
                    # 1. Add to network-specific domain
                    updates.append((container_name, ip, network_name))
                    
                    # 2. Add to default domain
                    updates.append((container_name, ip, None))
                    
                    # 3. Add to flannel domain if it's a flannel IP
                    if is_flannel:
                        updates.append((container_name, ip, "flannel"))
        
        # Collect containers to delete
        to_delete = set(self.container_networks.keys()) - set(new_networks.keys())
        
        # Update saved state
        self.container_networks = new_networks
        
        # Return update info and containers to delete
        return updates, to_delete
    
    def sync_dns_entries(self) -> bool:
        """Synchronize DNS entries with current container state."""
        logger.info("Starting DNS synchronization")
        updates, to_delete = self.prepare_dns_updates()
        
        # Process deletes first
        for container_name in to_delete:
            logger.info(f"Removing DNS for stopped container: {container_name}")
            self.dns_manager.remove_dns(container_name)
        
        # Process updates in one batch
        if updates:
            logger.info(f"Applying {len(updates)} DNS updates")
            result = self.dns_manager.batch_update_dns(updates)
            
            if not result:
                logger.warning("Failed to apply DNS updates")
        else:
            logger.info("No DNS updates needed")
            
        logger.info("DNS synchronization complete")
        return True
    
    def listen_for_events(self):
        """Listen for Docker events and update DNS accordingly."""
        logger.info("Starting Docker event listener")
        last_sync_time = 0
        sync_interval = 60  # Force sync every minute
        cleanup_interval = 3600  # Force cleanup every hour
        last_cleanup_time = 0
    
        # Initial synchronization
        self.sync_dns_entries()
    
        # Run aggressive cleanup on startup
        logger.info("Performing initial aggressive cleanup")
        self.dns_manager.aggressive_cleanup()
        last_cleanup_time = time.time()
    
        try:
            for event in self.docker_client.events(decode=True):
                current_time = time.time()
                
                # Process container events that affect networking
                if event.get('Type') == 'container' and event.get('Action') in ['start', 'die', 'destroy']:
                    container_name = event['Actor']['Attributes'].get('name', 'unknown')
                    logger.info(f"Container event: {event.get('Action')} - {container_name}")
                    self.sync_dns_entries()
                    last_sync_time = current_time
                
                # Force periodic sync to catch any missed changes
                elif current_time - last_sync_time > sync_interval:
                    logger.info(f"Periodic sync after {sync_interval}s")
                    self.sync_dns_entries()
                    last_sync_time = current_time
                    
                # Periodic cleanup of duplicate DNS records
                if current_time - last_cleanup_time > cleanup_interval:
                    logger.info(f"Periodic DNS cleanup after {cleanup_interval/3600:.1f}h")
                    self.dns_manager.cleanup_dns_records()
                    last_cleanup_time = current_time
                    
        except Exception as e:
            logger.error(f"Event listener error: {e}")
            # Try to reconnect
            time.sleep(5)
            self._connect_to_docker()
            return self.listen_for_events()
