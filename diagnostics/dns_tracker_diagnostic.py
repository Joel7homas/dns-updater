#!/usr/bin/env python3
# dns_tracker_diagnostic.py - Diagnostic tool for testing the set-based container state tracker
import os
import sys
import time
import json
import logging
import argparse
import docker
from typing import Dict, List, Set, Any, Optional

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(name)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger('dns-diagnostic')

# Import our container state tracker
try:
    from container_network_state import ContainerNetworkState
    logger.info("Successfully imported ContainerNetworkState")
except ImportError:
    logger.error("Failed to import ContainerNetworkState. Make sure container_network_state.py is in the same directory")
    sys.exit(1)

class DiagnosticTool:
    """Tool for testing and diagnosing the set-based DNS tracker."""
    
    def __init__(self, dry_run=False, verbose=False):
        """Initialize the diagnostic tool."""
        self.state_tracker = ContainerNetworkState()
        self.docker_client = None
        self.dns_entries = {}
        self.dry_run = dry_run
        self.verbose = verbose
        
        # Set log level based on verbosity
        if verbose:
            logger.setLevel(logging.DEBUG)
        
        # Try to connect to Docker
        try:
            self.docker_client = docker.from_env()
            logger.info("Connected to Docker daemon")
        except Exception as e:
            logger.error(f"Failed to connect to Docker: {e}")
            sys.exit(1)
    
    def get_container_networks(self):
        """Get container network information."""
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
    
    def run_test_cycle(self):
        """Run a test cycle and return change information."""
        # Get current container networks
        networks = self.get_container_networks()
        
        # Print current state if verbose
        if self.verbose:
            logger.debug("Current container networks:")
            for container, container_networks in networks.items():
                logger.debug(f"  {container}: {json.dumps(container_networks)}")
        
        # Update state and check for changes
        has_changes = self.state_tracker.update_state(networks)
        
        if has_changes:
            changes = self.state_tracker.get_changes()
            logger.info(f"Changes detected: {len(changes['added_containers'])} new, "
                      f"{len(changes['removed_containers'])} removed, "
                      f"{len(changes['network_changes'])} modified")
            
            # Print detailed changes if verbose
            if self.verbose:
                self._log_detailed_changes(changes)
            
            return changes
        else:
            logger.info("No changes detected")
            return {'added_containers': [], 'removed_containers': [], 'network_changes': {}}
    
    def _log_detailed_changes(self, changes):
        """Log detailed information about changes."""
        if changes['added_containers']:
            logger.debug(f"New containers: {changes['added_containers']}")
        if changes['removed_containers']:
            logger.debug(f"Removed containers: {changes['removed_containers']}")
        for container, container_changes in changes['network_changes'].items():
            if container_changes['added']:
                logger.debug(f"  {container} added networks: {json.dumps(container_changes['added'])}")
            if container_changes['removed']:
                logger.debug(f"  {container} removed networks: {json.dumps(container_changes['removed'])}")
    
    def fetch_dns_entries(self):
        """Mock DNS entry fetching from container state."""
        logger.info("Fetching DNS entries (mock)")
        
        # Convert container networks to DNS entries
        networks = self.state_tracker.container_networks
        dns_entries = {}
        
        for container, container_networks in networks.items():
            dns_entries[container] = []
            
            for network, ip in container_networks.items():
                # Network-specific domain
                dns_entries[container].append({
                    'uuid': f"mock-uuid-{container}-{network}",
                    'domain': f"{network}.docker.local",
                    'ip': ip,
                    'description': f"Docker container on test-host ({network})"
                })
                
                # Default domain
                dns_entries[container].append({
                    'uuid': f"mock-uuid-{container}-default",
                    'domain': "docker.local",
                    'ip': ip,
                    'description': f"Docker container on test-host (default)"
                })
        
        self.dns_entries = dns_entries
        logger.info(f"Fetched {sum(len(entries) for entries in dns_entries.values())} DNS entries "
                  f"for {len(dns_entries)} containers")
    
    def simulate_dns_updates(self, changes):
        """Simulate DNS updates based on changes."""
        stats = {'add': 0, 'remove': 0, 'reconfigured': False}
        
        if self.dry_run:
            logger.info("[DRY RUN] Would process DNS updates")
            return stats
        
        # Process additions
        self._simulate_additions(changes, stats)
        
        # Process removals
        self._simulate_removals(changes, stats)
        
        # Reconfigure if changes
        if stats['add'] > 0 or stats['remove'] > 0:
            logger.info(f"Would reconfigure Unbound after {stats['add']} additions and {stats['remove']} removals")
            stats['reconfigured'] = True
        
        return stats
    
    def _simulate_additions(self, changes, stats):
        """Simulate adding DNS entries."""
        # Process added containers
        for container in changes['added_containers']:
            if container in self.state_tracker.container_networks:
                for network, ip in self.state_tracker.container_networks[container].items():
                    logger.info(f"Would add: {container}.{network}.docker.local → {ip}")
                    stats['add'] += 1
                    logger.info(f"Would add: {container}.docker.local → {ip}")
                    stats['add'] += 1
        
        # Process network changes
        for container, network_changes in changes['network_changes'].items():
            # Added networks
            for network, ip in network_changes['added'].items():
                logger.info(f"Would add: {container}.{network}.docker.local → {ip}")
                stats['add'] += 1
                
                # Check if default domain entry exists
                has_entry = False
                if container in self.dns_entries:
                    for entry in self.dns_entries[container]:
                        if entry['domain'] == 'docker.local' and entry['ip'] == ip:
                            has_entry = True
                            break
                
                if not has_entry:
                    logger.info(f"Would add: {container}.docker.local → {ip}")
                    stats['add'] += 1
    
    def _simulate_removals(self, changes, stats):
        """Simulate removing DNS entries."""
        # Process removed containers
        for container in changes['removed_containers']:
            logger.info(f"Would remove all DNS entries for {container}")
            if container in self.dns_entries:
                stats['remove'] += len(self.dns_entries[container])
        
        # Process network changes
        for container, network_changes in changes['network_changes'].items():
            # Removed networks
            for network, ip in network_changes['removed'].items():
                logger.info(f"Would remove: {container}.{network}.docker.local → {ip}")
                stats['remove'] += 1
    
    def run_continuous_test(self, cycles=5, interval=10):
        """Run multiple test cycles with delay between them."""
        logger.info(f"Starting continuous test with {cycles} cycles at {interval}s intervals")
        
        for cycle in range(1, cycles + 1):
            logger.info(f"------ Cycle {cycle}/{cycles} ------")
            
            # Run cycle
            changes = self.run_test_cycle()
            
            # Get state statistics
            stats = self.state_tracker.get_statistics()
            logger.info(f"State statistics: {stats['container_count']} containers, "
                      f"{stats['multi_network_containers']} with multiple networks")
            
            # Mock fetching DNS entries
            self.fetch_dns_entries()
            
            # Simulate DNS updates
            update_stats = self.simulate_dns_updates(changes)
            logger.info(f"Update summary: {update_stats['add']} additions, {update_stats['remove']} removals, "
                      f"reconfigured={update_stats['reconfigured']}")
            
            # Wait between cycles (except for last cycle)
            if cycle < cycles:
                logger.info(f"Waiting {interval} seconds until next cycle...")
                time.sleep(interval)
        
        logger.info("Continuous test completed")
    
    def save_state_snapshot(self, filename="state_snapshot.json"):
        """Save current state to a file for debugging."""
        state = {
            'container_networks': self.state_tracker.container_networks,
            'previous_networks': self.state_tracker.previous_networks,
            'gone_containers': self.state_tracker.gone_containers,
            'statistics': self.state_tracker.get_statistics()
        }
        
        try:
            with open(filename, 'w') as f:
                json.dump(state, f, indent=2)
            logger.info(f"State snapshot saved to {filename}")
        except Exception as e:
            logger.error(f"Failed to save state snapshot: {e}")

def main():
    """Main function to run the diagnostic tool."""
    parser = argparse.ArgumentParser(description="DNS tracker diagnostic tool")
    parser.add_argument("--cycles", type=int, default=5, help="Number of test cycles to run")
    parser.add_argument("--interval", type=int, default=10, help="Seconds between test cycles")
    parser.add_argument("--dry-run", action="store_true", help="Don't simulate DNS updates")
    parser.add_argument("--verbose", action="store_true", help="Enable verbose logging")
    parser.add_argument("--snapshot", help="Save state snapshot to file")
    
    args = parser.parse_args()
    
    # Initialize diagnostic tool
    tool = DiagnosticTool(dry_run=args.dry_run, verbose=args.verbose)
    
    # Run continuous test
    tool.run_continuous_test(cycles=args.cycles, interval=args.interval)
    
    # Save snapshot if requested
    if args.snapshot:
        tool.save_state_snapshot(args.snapshot)

if __name__ == "__main__":
    main()
