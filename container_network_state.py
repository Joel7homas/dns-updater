# container_network_state.py
"""
Module for tracking container network states and detecting changes.
This implements a set-based approach to manage container IP addresses
and avoid unnecessary DNS updates.
"""
import time
import logging
import copy
from typing import Dict, Set, List, Any, Optional, Tuple

# Get module logger
logger = logging.getLogger('dns_updater.state')

class ContainerNetworkState:
    """Tracks the network state of containers between cycles."""
    
    def __init__(self, cleanup_cycles: int = 3):
        """
        Initialize container network state tracker.
        
        Args:
            cleanup_cycles: Number of cycles before removing containers that no longer exist
        """
        # Main state storage: {container_name: {network_name: ip_address}}
        self.container_networks: Dict[str, Dict[str, str]] = {}
        
        # Previous state for comparison: {container_name: {network_name: ip_address}}
        self.previous_networks: Dict[str, Dict[str, str]] = {}
        
        # Track containers that no longer exist: {container_name: cycles_gone}
        self.gone_containers: Dict[str, int] = {}
        
        # Configuration
        self.cleanup_cycles = cleanup_cycles
        
        # Track when changes occurred
        self.last_change_time = 0
        
        logger.info(f"Container network state tracker initialized (cleanup after {cleanup_cycles} cycles)")
    
    def update_state(self, new_networks: Dict[str, Dict[str, str]]) -> bool:
        """
        Update the network state with new information.
        
        Args:
            new_networks: New container network state {container: {network: ip}}
            
        Returns:
            bool: True if there were real changes, False otherwise
        """
        if new_networks is None:
            logger.warning("Invalid network state update: None provided")
            return False
            
        # Store previous state for comparison
        self.previous_networks = copy.deepcopy(self.container_networks)
        
        # Update with new state
        self.container_networks = copy.deepcopy(new_networks)
        
        # Identify containers that have disappeared
        self._track_gone_containers(new_networks)
        
        # Check if there were real changes
        changes = self._has_real_changes()
        if changes:
            self.last_change_time = time.time()
            return True
        
        return False
    
    def _track_gone_containers(self, new_networks: Dict[str, Dict[str, str]]) -> None:
        """
        Track containers that have disappeared to clean them up later.
        
        Args:
            new_networks: New container network state
        """
        # Identify containers that are gone in this cycle
        current_containers = set(new_networks.keys())
        previous_containers = set(self.previous_networks.keys())
        
        # New containers that disappeared this cycle
        newly_gone = previous_containers - current_containers
        
        # Update gone counter for containers that are still gone
        for container in list(self.gone_containers.keys()):
            if container in current_containers:
                # Container is back, remove from gone list
                del self.gone_containers[container]
            else:
                # Container is still gone, increment counter
                self.gone_containers[container] += 1
                
                # Clean up if container has been gone too long
                if self.gone_containers[container] >= self.cleanup_cycles:
                    logger.info(f"Cleaning up state for container {container} after {self.cleanup_cycles} cycles")
                    del self.gone_containers[container]
        
        # Add newly gone containers to tracking
        for container in newly_gone:
            self.gone_containers[container] = 1
            logger.debug(f"Container {container} not present in current cycle")
    
    def _has_real_changes(self) -> bool:
        """
        Determine if there were real changes to the network state.
        
        Returns:
            bool: True if there were real changes, False otherwise
        """
        # Check for new or removed containers
        current_containers = set(self.container_networks.keys())
        previous_containers = set(self.previous_networks.keys())
        
        if current_containers != previous_containers:
            logger.info(f"Container set changed: {len(current_containers)} current, {len(previous_containers)} previous")
            return True
            
        # Check for changes in network configuration
        for container, networks in self.container_networks.items():
            # This shouldn't happen, but check anyway
            if container not in self.previous_networks:
                logger.info(f"New container detected: {container}")
                return True
                
            previous_container_networks = self.previous_networks[container]
            
            # Check for new or removed networks
            if set(networks.keys()) != set(previous_container_networks.keys()):
                logger.info(f"Network configuration changed for {container}")
                return True
                
            # Check for IP changes in existing networks
            for network, ip in networks.items():
                if (network in previous_container_networks and 
                    ip != previous_container_networks[network]):
                    logger.info(f"IP changed for {container} on network {network}: "
                              f"{previous_container_networks[network]} -> {ip}")
                    return True
        
        logger.debug("No real network changes detected")
        return False
    
    def get_changes(self) -> Dict[str, Any]:
        """
        Get the specific changes between current and previous state.
        
        Returns:
            Dict with:
            - 'added_containers': List of new containers
            - 'removed_containers': List of removed containers
            - 'network_changes': Dict of network changes per container
        """
        changes = {
            'added_containers': [],
            'removed_containers': [],
            'network_changes': {}  # {container: {'added': {network: ip}, 'removed': {network: ip}}}
        }
        
        # Find added and removed containers
        current_containers = set(self.container_networks.keys())
        previous_containers = set(self.previous_networks.keys())
        
        changes['added_containers'] = list(current_containers - previous_containers)
        changes['removed_containers'] = list(previous_containers - current_containers)
        
        # Find network changes for existing containers
        for container in current_containers & previous_containers:
            current_networks = self.container_networks[container]
            previous_networks = self.previous_networks[container]
            
            # Skip if no changes
            if current_networks == previous_networks:
                continue
                
            changes['network_changes'][container] = {
                'added': {},
                'removed': {}
            }
            
            # Find added networks/IPs
            for network, ip in current_networks.items():
                if network not in previous_networks or previous_networks[network] != ip:
                    changes['network_changes'][container]['added'][network] = ip
            
            # Find removed networks/IPs
            for network, ip in previous_networks.items():
                if network not in current_networks:
                    changes['network_changes'][container]['removed'][network] = ip
        
        return changes
    
    def get_all_container_ips(self) -> Dict[str, Set[str]]:
        """
        Get a set of all IPs for each container across all networks.
        
        Returns:
            Dict mapping container names to sets of IP addresses
        """
        result: Dict[str, Set[str]] = {}
        
        for container, networks in self.container_networks.items():
            if container not in result:
                result[container] = set()
                
            for network, ip in networks.items():
                if ip:  # Only add non-empty IPs
                    result[container].add(ip)
        
        return result
    
    def get_statistics(self) -> Dict[str, Any]:
        """
        Get statistics about the current state.
        
        Returns:
            Dict with statistics about containers, networks, and IPs
        """
        container_count = len(self.container_networks)
        network_counts = {}
        ip_count = 0
        
        for container, networks in self.container_networks.items():
            network_count = len(networks)
            network_counts[container] = network_count
            ip_count += network_count
        
        return {
            'container_count': container_count,
            'total_networks': sum(network_counts.values()),
            'total_ips': ip_count,
            'multi_network_containers': sum(1 for count in network_counts.values() if count > 1),
            'gone_containers': len(self.gone_containers),
            'last_change': self.last_change_time
        }
