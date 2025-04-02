import docker
import logging
import os
import time
import ipaddress
import json
import re
from typing import Dict, List, Set, Tuple, Optional
import requests
import certifi
import threading
import sys
from requests.adapters import HTTPAdapter
from requests.packages.urllib3.util.retry import Retry

# Set up logging. Set the level to DEBUG to see full responses.
logging.basicConfig(level=logging.DEBUG, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

class OPNsenseAPI:
    def __init__(self):
        required_env_vars = ['OPNSENSE_KEY', 'OPNSENSE_SECRET', 'OPNSENSE_URL']
        missing_vars = [var for var in required_env_vars if var not in os.environ or not os.environ[var]]
        if missing_vars:
            logger.error(f"Missing required environment variables: {', '.join(missing_vars)}")
            logger.error("Please set these environment variables and restart the script.")
            sys.exit(1)

        self.key = os.environ['OPNSENSE_KEY']
        self.secret = os.environ['OPNSENSE_SECRET']
        self.base_url = os.environ['OPNSENSE_URL']
        self.base_domain = "docker.local"

        # Restart timing configuration
        self.last_restart_time = 0
        self.updates_since_restart = 0
        self.restart_threshold = 5  # Restart after this many updates
        self.restart_interval = 3600  # Seconds between forced restarts (1 hour)

        # Read the host name from the mounted file
        try:
            with open('/etc/docker_host_name', 'r') as f:
                self.host_name = f.read().strip()
            logger.debug(f"Host name read from /etc/docker_host_name: {self.host_name}")
        except Exception as e:
            logger.error(f"Failed to read host name from /etc/docker_host_name: {e}")
            self.host_name = "unknown"

        # Log a brief summary of credentials (do not log secrets in production!)
        logger.debug(f"Using OPNSENSE_URL: {self.base_url}")
        logger.debug(f"Using OPNSENSE_KEY of length: {len(self.key)}")
        logger.debug(f"Using OPNSENSE_SECRET of length: {len(self.secret)}")

        self.session = requests.Session()
        retry_strategy = Retry(
            total=5,
            backoff_factor=0.1,
            status_forcelist=[429, 500, 502, 503, 504],
            allowed_methods=["HEAD", "GET", "OPTIONS", "POST"]
        )
        adapter = HTTPAdapter(max_retries=retry_strategy)
        self.session.mount("https://", adapter)
        self.session.mount("http://", adapter)

        self.session.auth = (self.key, self.secret)
        self.session.verify = certifi.where()
        self.hostname = os.uname().nodename

        # Initialize flannel network information
        self.flannel_network = self._get_flannel_network()
        if self.flannel_network:
            logger.info(f"Detected flannel network: {self.flannel_network}")
        else:
            logger.info("No flannel network detected")

        # Get all currently configured DNS host overrides for diagnostic purposes
        self.dump_all_dns_records()

    def _get_flannel_network(self) -> Optional[ipaddress.IPv4Network]:
        """Read flannel network information from subnet.env if it exists."""
        try:
            if os.path.exists('/var/run/flannel/subnet.env'):
                with open('/var/run/flannel/subnet.env', 'r') as f:
                    for line in f:
                        if line.startswith('FLANNEL_NETWORK='):
                            network_str = line.strip().split('=')[1]
                            return ipaddress.IPv4Network(network_str)
            return None
        except Exception as e:
            logger.error(f"Failed to read or parse flannel network information: {e}")
            return None

    def sanitize_network_name(self, network_name: str) -> str:
        """
        Sanitize network name to be DNS-compatible by:
        1. Removing common suffixes like _net, -net, _default
        2. Removing invalid characters (keeping only letters, numbers, and hyphens)
        3. Ensuring the result is not empty
        """
        # Remove common suffixes
        for suffix in ['_net', '-net', '_default', '-default']:
            if network_name.endswith(suffix):
                network_name = network_name[:-len(suffix)]
                break
        
        # Remove invalid characters (keep only letters, numbers, and hyphens)
        # Note: We're allowing hyphens but OPNsense validation might still reject them
        network_name = re.sub(r'[^a-zA-Z0-9\-]', '', network_name)
        
        # Ensure result is not empty
        if not network_name:
            network_name = "network"
            
        return network_name

    def test_api_connection(self):
        try:
            logger.info(f"Testing API connection to {self.base_url}")
            response = self.session.get(f"{self.base_url}/core/firmware/status", timeout=5)
            response.raise_for_status()
            logger.info(f"API connection successful. Status: {response.status_code}")
        except requests.exceptions.RequestException as e:
            logger.error(f"API connection failed: {e}")
            if hasattr(e, 'response'):
                logger.error(f"Response content: {e.response.content}")
            else:
                logger.error("No response received")
            raise

    def dump_all_dns_records(self):
        """
        Dump all DNS host override records for diagnostic purposes.
        """
        try:
            logger.info("Fetching all DNS host override records for diagnostics")
            response = self.session.get(f"{self.base_url}/unbound/settings/searchHostOverride", timeout=5)
            response.raise_for_status()
            hosts = response.json().get('rows', [])
            
            logger.info(f"Total DNS host override records: {len(hosts)}")
            
            network_specific_records = []
            for host in hosts:
                hostname = host.get('hostname', '')
                domain = host.get('domain', '')
                if domain != self.base_domain and domain.endswith(self.base_domain):
                    network_specific_records.append({
                        'hostname': hostname,
                        'domain': domain,
                        'ip': host.get('server', ''),
                        'uuid': host.get('uuid', ''),
                        'description': host.get('description', '')
                    })
            
            if network_specific_records:
                logger.info(f"Found {len(network_specific_records)} network-specific domain records:")
                for record in network_specific_records:
                    logger.info(f"  {record['hostname']}.{record['domain']} -> {record['ip']} (UUID: {record['uuid']})")
            else:
                logger.info("No network-specific domain records found in DNS")
                
            # Also dump total domains
            domains = set()
            for host in hosts:
                domains.add(host.get('domain', ''))
            
            logger.info(f"Domains in use: {', '.join(sorted(domains))}")
            
        except requests.exceptions.RequestException as e:
            logger.error(f"Failed to get DNS records for diagnostics: {e}")

    def update_dns(self, hostname: str, ip: str, network_name: str = None) -> bool:
        """
        Update DNS with network-specific domain if network_name is provided.
        For flannel network IPs, use flannel.docker.local domain.
        For other networks, use {sanitized_network_name}.docker.local if network_name is provided.
        Otherwise, use the default docker.local domain.
        """
        try:
            # Determine the appropriate domain based on network
            domain = self.base_domain
            
            # Check if this IP is in the flannel network
            ip_obj = None
            try:
                ip_obj = ipaddress.IPv4Address(ip)
                is_flannel = self.flannel_network and ip_obj in self.flannel_network
            except ValueError:
                is_flannel = False
            
            # Create domain for the specific network or flannel
            if is_flannel and network_name != "flannel":  # Use explicit flannel domain
                domain = f"flannel.{self.base_domain}"
                network_desc = "flannel network"
            elif network_name:
                if network_name == "flannel":
                    domain = f"flannel.{self.base_domain}"
                else:
                    sanitized_name = self.sanitize_network_name(network_name)
                    domain = f"{sanitized_name}.{self.base_domain}"
                network_desc = f"{network_name} network"
            else:
                network_desc = "default network"
            
            logger.info(f"Updating DNS for {hostname}.{domain} with IP {ip} on {network_desc}")
            
            # Log the full JSON payload for debugging
            payload = {
                "host": {
                    "enabled": "1",
                    "hostname": hostname,
                    "domain": domain,
                    "server": ip,
                    "description": f"Docker container on {self.host_name} ({network_desc})"
                }
            }
            logger.debug(f"DNS update payload: {json.dumps(payload)}")
            
            response = self.session.post(
                f"{self.base_url}/unbound/settings/addHostOverride",
                json=payload,
                timeout=5
            )
            
            # Log the complete response for debugging
            logger.debug(f"DNS update response status: {response.status_code}")
            logger.debug(f"DNS update response content: {response.text}")
            
            response.raise_for_status()
            
            # Check if the response indicates failure
            response_data = response.json()
            if response_data.get("result") == "failed":
                validations = response_data.get("validations", {})
                logger.error(f"DNS update failed with validations: {validations}")
                return False
            
            # Now try to explicitly get this entry to make sure it exists
            self.verify_dns_entry(hostname, domain, ip)
            
            logger.info(f"DNS update for {hostname}.{domain} successful")
            return True
        except requests.exceptions.RequestException as e:
            logger.error(f"Failed to update DNS for {hostname}: {e}")
            if hasattr(e, 'response'):
                logger.error(f"Response content: {e.response.content}")
            return False
        except Exception as e:
            logger.error(f"Unexpected error updating DNS for {hostname}: {e}")
            return False

    def verify_dns_entry(self, hostname: str, domain: str, ip: str):
        """
        Verify that a DNS entry exists after creating it
        """
        try:
            logger.info(f"Verifying DNS entry for {hostname}.{domain} with IP {ip}")
            all_dns = self.get_all_dns_entries()
            
            if hostname in all_dns:
                records = all_dns[hostname]
                found = False
                for record in records:
                    if record['domain'] == domain and record['ip'] == ip:
                        logger.info(f"✅ Verified: {hostname}.{domain} record with IP {ip} exists (UUID: {record['uuid']})")
                        found = True
                        break
                
                if not found:
                    logger.warning(f"⚠️ Verification failed: {hostname}.{domain} record with IP {ip} not found in DNS!")
                    matching_domain = [r for r in records if r['domain'] == domain]
                    if matching_domain:
                        logger.warning(f"Found records for {hostname}.{domain} but with different IPs: {[r['ip'] for r in matching_domain]}")
                    
                    matching_ip = [r for r in records if r['ip'] == ip]
                    if matching_ip:
                        logger.warning(f"Found records for {hostname} with IP {ip} but in different domains: {[r['domain'] for r in matching_ip]}")
            else:
                logger.warning(f"⚠️ Verification failed: No records found for hostname {hostname}")
        except Exception as e:
            logger.error(f"Error verifying DNS entry: {e}")

    def remove_dns(self, hostname: str) -> bool:
        """
        Remove all Docker-generated DNS override records for a given hostname across all domains.
        Only records with a description containing "Docker container on" are removed.
        """
        try:
            logger.info(f"Attempting to remove all Docker-generated DNS entries for {hostname}")
            response = self.session.get(f"{self.base_url}/unbound/settings/searchHostOverride", timeout=5)
            response.raise_for_status()
            hosts = response.json().get('rows', [])
            logger.debug(f"remove_dns(): Found records: {hosts}")

            removed = False
            for host in hosts:
                if host.get('hostname') == hostname and f"Docker container on {self.host_name}" in host.get('description', ''):
                    domain = host.get('domain', '')
                    logger.info(f"Found DNS entry for {hostname}.{domain} (IP: {host.get('server')}, UUID: {host.get('uuid')}), attempting to delete")
                    delete_response = self.session.post(
                        f"{self.base_url}/unbound/settings/delHostOverride/{host.get('uuid')}",
                        timeout=5
                    )
                    logger.debug(f"Deletion response: {delete_response.text}")
                    delete_response.raise_for_status()
                    logger.info(f"Successfully deleted DNS entry for {hostname}.{domain} (IP: {host.get('server')})")
                    removed = True

            return removed
        except requests.exceptions.RequestException as e:
            logger.error(f"Failed to remove DNS entries for {hostname}: {e}")
            return False

    def remove_specific_dns(self, uuid: str, hostname: str, domain: str, ip: str) -> bool:
        """
        Remove a specific DNS override record identified by its UUID.
        Only removes the record if its description indicates it was created by Docker.
        """
        try:
            logger.info(f"Attempting to remove DNS entry for {hostname}.{domain} with IP {ip} (UUID: {uuid})")
            delete_response = self.session.post(
                f"{self.base_url}/unbound/settings/delHostOverride/{uuid}",
                timeout=5
            )
            logger.debug(f"Deletion response for {hostname}.{domain} with IP {ip}: {delete_response.text}")
            delete_response.raise_for_status()
            logger.info(f"Successfully deleted DNS entry for {hostname}.{domain} with IP {ip} (UUID: {uuid})")
            return True
        except requests.exceptions.RequestException as e:
            logger.error(f"Failed to remove DNS entry for {hostname}.{domain} with IP {ip} (UUID: {uuid}): {e}")
            return False

    def reconfigure_unbound(self):
        def reconfigure_thread():
            try:
                logger.info("Attempting to reconfigure Unbound")
                reconfigure_response = self.session.post(f"{self.base_url}/unbound/service/reconfigure", timeout=5)
                reconfigure_response.raise_for_status()
                logger.info("Unbound reconfiguration successful")
                
                # Increment update counter
                self.updates_since_restart += 1
                current_time = time.time()
                
                # Decide whether to force a restart
                should_restart = False
                if self.updates_since_restart >= self.restart_threshold:
                    logger.info(f"Forcing restart after {self.updates_since_restart} updates")
                    should_restart = True
                elif current_time - self.last_restart_time > self.restart_interval:
                    logger.info(f"Forcing restart after {(current_time - self.last_restart_time) / 60:.1f} minutes since last restart")
                    should_restart = True
                    
                if should_restart:
                    self.restart_unbound_service()
                    self.updates_since_restart = 0
                    self.last_restart_time = current_time
                
            except requests.exceptions.RequestException as e:
                logger.error(f"Failed to reconfigure Unbound: {e}")
                self.restart_unbound_service()
                self.updates_since_restart = 0
                self.last_restart_time = time.time()

        thread = threading.Thread(target=reconfigure_thread)
        thread.start()
        thread.join(timeout=60)
        if thread.is_alive():
            logger.error("Unbound reconfiguration timed out after 60 seconds")
            self.restart_unbound_service()

    def restart_unbound_service(self):
        def restart_thread():
            try:
                logger.info("Attempting to restart Unbound service")
                restart_response = self.session.post(f"{self.base_url}/unbound/service/restart", timeout=5)
                restart_response.raise_for_status()
                logger.info("Unbound service restart successful")
                
                # Sleep to let Unbound fully restart
                time.sleep(5)
                
                # Add a final diagnostic
                self.dump_all_dns_records()
            except requests.exceptions.RequestException as e:
                logger.error(f"Failed to restart Unbound service: {e}")

        thread = threading.Thread(target=restart_thread)
        thread.start()
        thread.join(timeout=60)
        if thread.is_alive():
            logger.error("Unbound service restart timed out after 60 seconds")

    def get_all_dns_entries(self) -> Dict[str, List[Dict[str, str]]]:
        """
        Returns a dictionary mapping hostname to a list of records.
        Each record is a dict containing 'uuid', 'ip' (from the 'server' field), 'domain', and 'description'.
        Uses the searchHostOverride endpoint.
        """
        try:
            logger.info("Fetching all DNS entries using searchHostOverride")
            response = self.session.get(f"{self.base_url}/unbound/settings/searchHostOverride", timeout=5)
            response.raise_for_status()
            data = response.json()
            logger.debug(f"get_all_dns_entries(): Full response: {json.dumps(data)}")
            hosts = data.get('rows', [])

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
                dns_entries.setdefault(hostname, []).append(rec)

            logger.debug(f"get_all_dns_entries(): Parsed entries: {dns_entries}")
            return dns_entries
        except requests.exceptions.RequestException as e:
            logger.error(f"Failed to fetch DNS entries: {e}")
            return {}

    def get_dns_general_settings(self):
        """
        Get Unbound general settings for diagnostic purposes
        """
        try:
            logger.info("Getting Unbound general settings")
            response = self.session.get(f"{self.base_url}/unbound/settings/get", timeout=5)
            response.raise_for_status()
            
            # Only log selected important settings, not the full response which could be large
            data = response.json()
            important_settings = {
                "enable": data.get("unbound", {}).get("enable", ""),
                "active_interface": data.get("unbound", {}).get("active_interface", []),
                "port": data.get("unbound", {}).get("port", ""),
                "dnssec": data.get("unbound", {}).get("dnssec", ""),
                "forwarding": data.get("unbound", {}).get("forwarding", ""),
                "local_zone_type": data.get("unbound", {}).get("local_zone_type", ""),
            }
            
            logger.info(f"Unbound general settings: {json.dumps(important_settings)}")
            return data
        except requests.exceptions.RequestException as e:
            logger.error(f"Failed to get Unbound settings: {e}")
            return {}

    def cleanup_invalid_records(self, valid_entries: Dict[str, Dict[str, Set[str]]]):
        """
        Remove any Docker-generated DNS override records that do not match the current valid entries.
        For a hostname that is no longer valid, remove all its Docker-generated records.
        For a valid hostname, remove Docker-generated records for domain/IPs not in the valid set.
        Additionally, if multiple Docker-generated records exist for a valid IP, remove duplicates.
        Records without the phrase "Docker container on" in their description are assumed to be manually created and will be preserved.
        
        valid_entries format: {hostname: {domain: {ip1, ip2, ...}, ...}, ...}
        """
        try:
            logger.info("Starting cleanup of invalid DNS records")
            current_entries = self.get_all_dns_entries()

            for hostname, records in current_entries.items():
                # Filter to only include Docker-generated records
                docker_records = [r for r in records if f"Docker container on {self.host_name}" in r.get('description', '')]
                if not docker_records:
                    logger.info(f"No Docker-generated records for hostname {hostname}. Skipping cleanup for this hostname.")
                    continue

                if hostname not in valid_entries:
                    logger.info(f"Container {hostname} is no longer running. Removing all its Docker-generated DNS entries.")
                    for rec in docker_records:
                        self.remove_specific_dns(rec['uuid'], hostname, rec['domain'], rec['ip'])
                else:
                    valid_domains = valid_entries[hostname]
                    
                    # Group records by domain and IP
                    domain_ip_map: Dict[str, Dict[str, List[str]]] = {}
                    for rec in docker_records:
                        domain = rec.get('domain', '')
                        ip = rec.get('ip', '')
                        uuid = rec.get('uuid', '')
                        
                        if domain not in domain_ip_map:
                            domain_ip_map[domain] = {}
                        
                        if ip not in domain_ip_map[domain]:
                            domain_ip_map[domain][ip] = []
                            
                        domain_ip_map[domain][ip].append(uuid)
                    
                    # Clean up invalid records
                    for domain, ip_map in domain_ip_map.items():
                        valid_ips = valid_domains.get(domain, set())
                        
                        for ip, uuids in ip_map.items():
                            if ip not in valid_ips:
                                logger.info(f"DNS record for {hostname}.{domain} with IP {ip} is no longer valid. Removing all {len(uuids)} record(s).")
                                for uuid in uuids:
                                    self.remove_specific_dns(uuid, hostname, domain, ip)
                            elif len(uuids) > 1:
                                logger.info(f"Multiple ({len(uuids)}) Docker DNS records exist for {hostname}.{domain} with IP {ip}. Removing duplicates.")
                                for uuid in uuids[1:]:
                                    self.remove_specific_dns(uuid, hostname, domain, ip)

            logger.info("Finished cleanup of invalid DNS records")
        except Exception as e:
            logger.error(f"Failed to cleanup invalid records: {e}")

class DockerDNSManager:
    def __init__(self):
        try:
            self.client = docker.from_env()
        except docker.errors.DockerException as e:
            logger.error(f"Failed to initialize Docker client: {e}")
            logger.error("Please ensure that Docker is running and accessible.")
            sys.exit(1)

        self.api = OPNsenseAPI()
        # Store container IPs as: { container_name: { network_name: {ip1, ip2, ...}, ... } }
        self.container_networks: Dict[str, Dict[str, Set[str]]] = {}

    def update_container_networks(self) -> Dict[str, Dict[str, Set[str]]]:
        """
        Get updated container network information
        Returns a mapping of container names to networks and their IPs
        Format: {container_name: {network_name: {ip1, ip2, ...}, ...}, ...}
        """
        new_container_networks: Dict[str, Dict[str, Set[str]]] = {}
        
        try:
            for container in self.client.containers.list():
                networks = container.attrs['NetworkSettings']['Networks']
                container_networks = {}
                
                for network_name, network_config in networks.items():
                    ip = network_config.get('IPAddress', '')
                    if ip:
                        # Store the original network name
                        if network_name not in container_networks:
                            container_networks[network_name] = set()
                        container_networks[network_name].add(ip)
                
                if container_networks:
                    new_container_networks[container.name] = container_networks
        except Exception as e:
            logger.error(f"Error getting container networks: {e}")
        
        return new_container_networks

    def sync_dns_entries(self):
        logger.info("Starting DNS entry synchronization")
        new_container_networks = self.update_container_networks()
        valid_entries: Dict[str, Dict[str, Set[str]]] = {}
        updates_made = False

        # Add all containers to both their specific network domains and the default domain
        for container_name, networks in new_container_networks.items():
            logger.info(f"Processing container: {container_name} with networks: {networks}")
            valid_entries[container_name] = {}
            
            # Initialize the default domain
            default_domain = "docker.local"
            valid_entries[container_name][default_domain] = set()
            
            # Initialize flannel domain if needed
            if self.api.flannel_network:
                flannel_domain = "flannel.docker.local"
                valid_entries[container_name][flannel_domain] = set()
            
            # Process each network
            for network_name, ips in networks.items():
                # Create sanitized network name for domain
                sanitized_name = self.api.sanitize_network_name(network_name)
                network_domain = f"{sanitized_name}.{self.api.base_domain}"
                
                if network_domain not in valid_entries[container_name]:
                    valid_entries[container_name][network_domain] = set()
                
                # Process each IP in this network
                for ip in ips:
                    # Check if this is a flannel IP
                    is_flannel = False
                    try:
                        ip_obj = ipaddress.IPv4Address(ip)
                        is_flannel = self.api.flannel_network and ip_obj in self.api.flannel_network
                    except ValueError:
                        pass
                    
                    # 1. Add to network-specific domain using original network name
                    logger.info(f"Adding {container_name}.{network_domain} with IP {ip}")
                    if self.api.update_dns(container_name, ip, network_name):
                        updates_made = True
                    
                    valid_entries[container_name][network_domain].add(ip)
                    
                    # 2. Add to default domain
                    logger.info(f"Adding {container_name}.{default_domain} with IP {ip}")
                    if self.api.update_dns(container_name, ip):
                        updates_made = True
                    
                    valid_entries[container_name][default_domain].add(ip)
                    
                    # 3. Add to flannel domain if it's a flannel IP
                    if is_flannel and self.api.flannel_network:
                        flannel_domain = "flannel.docker.local"
                        if flannel_domain not in valid_entries[container_name]:
                            valid_entries[container_name][flannel_domain] = set()
                        
                        logger.info(f"Adding {container_name}.{flannel_domain} with IP {ip} (flannel network detected)")
                        if self.api.update_dns(container_name, ip, "flannel"):
                            updates_made = True
                        
                        valid_entries[container_name][flannel_domain].add(ip)

        # Check for containers that are no longer running
        for container_name in self.container_networks:
            if container_name not in new_container_networks:
                logger.info(f"Removing DNS entries for stopped container: {container_name}")
                if self.api.remove_dns(container_name):
                    updates_made = True

        logger.info("Cleaning up invalid DNS records")
        self.api.cleanup_invalid_records(valid_entries)
        self.container_networks = new_container_networks

        if updates_made:
            logger.info("Reconfiguring Unbound after DNS updates")
            self.api.reconfigure_unbound()

        logger.info("DNS entry synchronization completed")

    def run(self):
        self.api.test_api_connection()
        
        # Get Unbound general settings for diagnostics
        self.api.get_dns_general_settings()
        
        self.sync_dns_entries()

        last_log_time = time.time()
        for event in self.client.events(decode=True):
            current_time = time.time()
            if current_time - last_log_time > 300:
                logger.info("Waiting for Docker events...")
                last_log_time = current_time

            if event.get('Type') == 'container' and event.get('Action') in ['start', 'die', 'destroy']:
                container_name = event['Actor']['Attributes'].get('name', 'unknown')
                logger.info(f"Container event: {event.get('Action')} - {container_name}")
                self.sync_dns_entries()

def main():
    try:
        manager = DockerDNSManager()
        logger.info(f"DNS Updater version: {os.environ.get('VERSION', 'unknown')}")
        while True:
            try:
                manager.run()
            except requests.exceptions.RequestException as e:
                logger.error(f"Network error: {e}")
                time.sleep(60)
            except Exception as e:
                logger.error(f"Main loop error: {e}")
                time.sleep(10)
    except KeyboardInterrupt:
        logger.info("Script terminated by user.")
    except Exception as e:
        logger.error(f"Unhandled exception: {e}")
        sys.exit(1)

if __name__ == "__main__":
    logger.info("Script started")
    main()

