#!/usr/bin/env python3
# dns-mass-cleanup-fixed.py - Aggressive DNS records cleanup script for OPNsense
# 
# This standalone script connects to OPNsense and removes duplicate DNS entries
# in batches, focusing on the hostnames with the most duplicates first.

import os
import time
import json
import logging
import argparse
import subprocess
import sys  # Added missing import
from typing import Dict, List, Tuple, Any, Optional, Set

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger('dns-cleanup')

class DNSCleanupTool:
    def __init__(self, api_url, api_key, api_secret, host_name="unknown", 
                 host_filter_disabled=False,
                 batch_size=50, max_hostnames=25, dry_run=False, 
                 skip_reconfigure=False, target_hostname=None,
                 verbose=False):
        """Initialize DNS cleanup tool with OPNsense API credentials."""
        self.api_url = api_url
        self.api_key = api_key
        self.api_secret = api_secret
        self.host_name = host_name
        self.host_filter_disabled = host_filter_disabled
        self.batch_size = batch_size
        self.max_hostnames = max_hostnames
        self.dry_run = dry_run
        self.skip_reconfigure = skip_reconfigure
        self.target_hostname = target_hostname
        self.verbose = verbose
        
        # Track performance metrics
        self.start_time = time.time()
        self.dns_entries = None
        
        logger.info(f"DNS Cleanup Tool initialized for {api_url}")
        logger.info(f"Batch size: {batch_size}, Max hostnames: {max_hostnames}")
        logger.info(f"Dry run: {dry_run}, Skip reconfigure: {skip_reconfigure}")
        if target_hostname:
            logger.info(f"Target hostname filter: {target_hostname}")
    
    def get_all_dns_entries(self) -> Dict[str, List[Dict[str, str]]]:
        """Get all DNS entries from OPNsense."""
        logger.info("Fetching all DNS entries...")
        fetch_start = time.time()
        
        cmd = [
            "curl", "-s", 
            "--connect-timeout", "10", 
            "-m", "60",
            "-k", 
            "-u", f"{self.api_key}:{self.api_secret}",
            f"{self.api_url}/unbound/settings/searchHostOverride"
        ]
        
        try:
            result = subprocess.run(cmd, capture_output=True, text=True)
            elapsed = time.time() - fetch_start
            
            if result.returncode != 0:
                logger.error(f"Failed to get DNS entries: {result.stderr}")
                return {}
                
            try:
                response = json.loads(result.stdout)
                if self.verbose:
                    logger.debug(f"API response: {json.dumps(response)[:200]}...")
                
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
                
                logger.info(f"Fetched {len(hosts)} DNS entries for {len(dns_entries)} hostnames in {elapsed:.2f}s")
                return dns_entries
                
            except (json.JSONDecodeError, ValueError) as e:
                logger.error(f"Failed to parse DNS entries response: {e}")
                if self.verbose:
                    logger.debug(f"Response: {result.stdout[:500]}...")
                return {}
                
        except Exception as e:
            logger.error(f"Error fetching DNS entries: {e}")
            return {}
    
    def remove_specific_dns(self, uuid: str, hostname: str, domain: str, ip: str) -> bool:
        """Remove a specific DNS entry by UUID."""
        if self.dry_run:
            logger.info(f"[DRY RUN] Would remove DNS entry: {hostname}.{domain} → {ip} (UUID: {uuid})")
            return True
            
        logger.info(f"Removing DNS entry: {hostname}.{domain} → {ip} (UUID: {uuid})")
        remove_start = time.time()
        
        cmd = [
            "curl", "-s", 
            "--connect-timeout", "5",
            "-H", "Content-Type: application/json", 
            "-m", "15",
            "-X", "POST",
            "-d", "{}",
            "-k", 
            "-u", f"{self.api_key}:{self.api_secret}",
            f"{self.api_url}/unbound/settings/delHostOverride/{uuid}"
        ]
        
        if self.verbose:
            logger.debug(f"Running command: {' '.join([c if i != 5 else 'REDACTED' for i, c in enumerate(cmd)])}")
        
        try:
            result = subprocess.run(cmd, capture_output=True, text=True)
            elapsed = time.time() - remove_start
            
            if result.returncode != 0:
                logger.error(f"Failed to remove DNS entry: {result.stderr}")
                return False
                
            try:
                response = json.loads(result.stdout)
                if self.verbose:
                    logger.debug(f"API response: {response}")
                
                # Check for endpoint not found error
                if isinstance(response, dict) and response.get("errorMessage") == "Endpoint not found":
                    logger.warning(f"Endpoint not found when removing entry. The entry may have already been removed.")
                    return True
                    
                # Check for successful deletion
                if response.get("result") == "deleted":
                    logger.info(f"Successfully removed DNS entry: {hostname}.{domain} → {ip} in {elapsed:.2f}s")
                    return True
                else:
                    logger.warning(f"Failed to remove DNS entry: {response}")
                    # If we get "failed" result, dump more diagnostic info in verbose mode
                    if self.verbose:
                        logger.debug(f"Failed removal - Full response: {result.stdout}")
                        logger.debug(f"Failed removal - Error output: {result.stderr}")
                    return False
                    
            except (json.JSONDecodeError, ValueError) as e:
                logger.error(f"Failed to parse DNS entry removal response: {e}")
                if self.verbose:
                    logger.debug(f"Failed JSON parse: {result.stdout[:500]}...")
                return False
                
        except Exception as e:
            logger.error(f"Error removing DNS entry: {e}")
            return False
    
    def reconfigure_unbound(self) -> bool:
        """Reconfigure Unbound to apply DNS changes."""
        if self.dry_run:
            logger.info("[DRY RUN] Would reconfigure Unbound")
            return True
            
        if self.skip_reconfigure:
            logger.info("Skipping Unbound reconfiguration as requested")
            return True
            
        logger.info("Reconfiguring Unbound...")
        reconfigure_start = time.time()
        
        cmd = [
            "curl", "-s", 
            "--connect-timeout", "5",
            "-H", "Content-Type: application/json", 
            "-m", "30",
            "-k", 
            "-u", f"{self.api_key}:{self.api_secret}",
            "-X", "POST",
            "-d", "{}",
            "-H", "Content-Type: application/json",
            "-d", "{}",
            f"{self.api_url}/unbound/service/reconfigure"
        ]
        
        try:
            result = subprocess.run(cmd, capture_output=True, text=True)
            elapsed = time.time() - reconfigure_start
            
            if result.returncode != 0:
                logger.error(f"Failed to reconfigure Unbound: {result.stderr}")
                return False
                
            try:
                response = json.loads(result.stdout)
                if self.verbose:
                    logger.debug(f"Reconfigure response: {response}")
                logger.info(f"Unbound reconfiguration completed in {elapsed:.2f}s")
                return True
                
            except (json.JSONDecodeError, ValueError) as e:
                logger.error(f"Failed to parse Unbound reconfiguration response: {e}")
                if self.verbose:
                    logger.debug(f"Reconfigure response text: {result.stdout[:500]}")
                return False
                
        except Exception as e:
            logger.error(f"Error reconfiguring Unbound: {e}")
            return False
    
    def identify_duplicates(self) -> List[Tuple[str, str, Dict[str, List[Dict[str, str]]]]]:
        """Identify duplicate DNS entries and prioritize by count."""
        dns_entries = self.dns_entries or self.get_all_dns_entries()
        self.dns_entries = dns_entries  # Store for later use
        
        # Dictionary to track expected IPs and counts for each hostname+domain
        hostname_domains: Dict[str, Dict[str, Dict[str, Any]]] = {}
        
        # First pass: identify latest IPs for each hostname+domain
        for hostname, entries in dns_entries.items():
            # Filter by target hostname if specified
            if self.target_hostname and not hostname.startswith(self.target_hostname):
                continue
                
            if hostname not in hostname_domains:
                hostname_domains[hostname] = {}
                
            for entry in entries:
                domain = entry.get('domain', '')
                ip = entry.get('ip', '')
                
                # Track expected IPs and counts for each hostname+domain combination
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
        
        # Log the top 10 worst offenders
        if duplicates:
            logger.info("Top duplicate offenders:")
            for i, (hostname, domain, data) in enumerate(duplicates[:10]):
                logger.info(f"  {i+1}. {hostname}.{domain}: {data['count']} entries")
                
        return duplicates
    
    def analyze_hostnames(self):
        """Analyze hostnames to understand the duplicate distribution."""
        dns_entries = self.dns_entries or self.get_all_dns_entries()
        
        # Count hostnames by prefix (e.g., "container-" vs "ix-container-")
        prefix_counts = {}
        for hostname in dns_entries.keys():
            # Extract prefix (everything up to the first non-prefix character)
            parts = hostname.split('-')
            if len(parts) > 1:
                prefix = parts[0]
                if prefix not in prefix_counts:
                    prefix_counts[prefix] = 0
                prefix_counts[prefix] += 1
        
        # Log hostname prefix distribution
        logger.info("Hostname prefix distribution:")
        for prefix, count in sorted(prefix_counts.items(), key=lambda x: x[1], reverse=True):
            logger.info(f"  {prefix}: {count} hostnames")
        
        # Count entries per hostname
        entries_per_hostname = [(hostname, len(entries)) for hostname, entries in dns_entries.items()]
        entries_per_hostname.sort(key=lambda x: x[1], reverse=True)
        
        # Log hostnames with most entries
        logger.info("Hostnames with most entries:")
        for hostname, count in entries_per_hostname[:20]:
            logger.info(f"  {hostname}: {count} entries")
    
    def process_batch(self, current_batch, total_to_process, batch_number, total_batches):
        """Process a batch of DNS entry removals."""
        batch_start = time.time()
        records_removed = 0
        
        logger.info(f"Processing batch {batch_number}/{total_batches} - {len(current_batch)} entries")
        
        if self.dry_run:
            logger.info(f"[DRY RUN] Would remove {len(current_batch)} DNS entries")
            return len(current_batch)  # Simulate removing all entries in dry run
        
        for uuid, hostname, domain, ip in current_batch:
            if self.remove_specific_dns(uuid, hostname, domain, ip):
                records_removed += 1
                
                # Log progress every 10 entries
                if records_removed % 10 == 0:
                    batch_elapsed = time.time() - batch_start
                    total_elapsed = time.time() - self.start_time
                    logger.info(f"Progress: {records_removed}/{len(current_batch)} in batch, "
                               f"{records_removed}/{total_to_process} total, "
                               f"avg {batch_elapsed/max(1, records_removed):.2f}s per entry, "
                               f"elapsed {total_elapsed:.2f}s")
        
        batch_elapsed = time.time() - batch_start
        if records_removed > 0:
            logger.info(f"Batch {batch_number} complete: {records_removed}/{len(current_batch)} entries removed in {batch_elapsed:.2f}s "
                      f"({batch_elapsed/records_removed:.2f}s per entry)")
        else:
            logger.info(f"Batch {batch_number} complete: {records_removed}/{len(current_batch)} entries removed in {batch_elapsed:.2f}s")
        
        return records_removed
    
    def cleanup_dns_records(self) -> int:
        """Clean up duplicate DNS records in batches."""
        logger.info(f"Starting aggressive DNS cleanup")
        
        # Identify duplicates
        duplicates = self.identify_duplicates()
        
        if not duplicates:
            logger.info("No duplicates found!")
            return 0
            
        # Calculate processing plan
        total_duplicates = sum(data['count'] - 1 for _, _, data in duplicates)
        logger.info(f"Found {total_duplicates} duplicate entries to remove")
        
        # Decide how many hostnames to process
        hostnames_to_process = min(self.max_hostnames, len(duplicates))
        logger.info(f"Will process {hostnames_to_process} hostname/domain combinations in this run")
        
        # Prepare entries to remove
        entries_to_remove = []
        hostnames_processed = 0
        
        for hostname, domain, data in duplicates[:hostnames_to_process]:
            expected_ip = data['expected_ip']
            all_entries = data['entries']
            
            # Sort entries - keep the entry with expected_ip, remove others
            duplicates_for_hostname = []
            
            for entry in all_entries:
                ip = entry.get('ip', '')
                uuid = entry.get('uuid', '')
                desc = entry.get('description', '')
                
                # Keep only the first entry with expected IP
                if ip == expected_ip and "expected_ip_kept" not in data:
                    # Mark that we've kept an entry with the expected IP
                    data['expected_ip_kept'] = True
                    if self.verbose:
                        logger.debug(f"Keeping entry {hostname}.{domain} → {ip} as expected IP")
                    continue
                
                # Skip removal if the description doesn't match our host
                # Unless target_hostname is specified, then remove regardless of description
                if not self.target_hostname and not self.host_filter_disabled and self.host_name != "unknown" and f"Docker container on {self.host_name}" not in desc:
                    if self.verbose:
                        logger.debug(f"Skipping entry {hostname}.{domain} → {ip} (not our host)")
                    continue
                
                duplicates_for_hostname.append((uuid, hostname, domain, ip))
            
            if duplicates_for_hostname:
                entries_to_remove.extend(duplicates_for_hostname)
                hostnames_processed += 1
                logger.debug(f"Will remove {len(duplicates_for_hostname)} duplicates for {hostname}.{domain}")
        
        # Process entries in batches
        total_removed = 0
        batch_count = (len(entries_to_remove) + self.batch_size - 1) // self.batch_size if entries_to_remove else 0
        
        logger.info(f"Will process {len(entries_to_remove)} entries in {batch_count} batches of up to {self.batch_size}")
        
        for i in range(0, len(entries_to_remove), self.batch_size):
            batch_number = (i // self.batch_size) + 1
            current_batch = entries_to_remove[i:i+self.batch_size]
            
            batch_removed = self.process_batch(current_batch, len(entries_to_remove), 
                                           batch_number, batch_count)
            total_removed += batch_removed
            
            # Reconfigure after each batch
            if not self.skip_reconfigure and batch_removed > 0:
                logger.info(f"Reconfiguring Unbound after batch {batch_number}")
                self.reconfigure_unbound()
        
        # Final summary
        total_elapsed = time.time() - self.start_time
        if total_removed > 0:
            logger.info(f"DNS cleanup complete: removed {total_removed} duplicate records "
                       f"across {hostnames_processed} hostnames in {total_elapsed:.2f}s "
                       f"({total_elapsed/total_removed:.2f}s per entry)")
        else:
            logger.info(f"DNS cleanup complete: no records removed in {total_elapsed:.2f}s")
        
        return total_removed
    
    def run_full_cleanup(self, target_count=None, max_runs=None, wait_between_runs=5):
        """Run full cleanup process until target count is reached or max runs is hit."""
        total_removed = 0
        run_count = 0
        
        while True:
            run_count += 1
            if max_runs is not None and run_count > max_runs:
                logger.info(f"Reached maximum run count of {max_runs}")
                break
                
            logger.info(f"Starting cleanup run {run_count}{' (dry run)' if self.dry_run else ''}")
            
            # Reset DNS entries cache for each run
            self.dns_entries = None
            
            # Run cleanup
            removed = self.cleanup_dns_records()
            total_removed += removed
            
            if removed == 0:
                logger.info("No more records to remove")
                break
                
            if target_count is not None and total_removed >= target_count:
                logger.info(f"Reached target removal count of {target_count}")
                break
                
            # Wait between runs
            if wait_between_runs > 0 and not self.dry_run:
                logger.info(f"Waiting {wait_between_runs} seconds before next run...")
                time.sleep(wait_between_runs)
        
        logger.info(f"Full cleanup process complete: removed {total_removed} records in {run_count} runs")
        return total_removed
    
def main():
    # Parse arguments
    parser = argparse.ArgumentParser(description='Aggressive DNS records cleanup for OPNsense')
    parser.add_argument('--url', help='OPNsense API URL', default=os.environ.get('OPNSENSE_URL'))
    parser.add_argument('--key', help='OPNsense API key', default=os.environ.get('OPNSENSE_KEY'))
    parser.add_argument('--secret', help='OPNsense API secret', default=os.environ.get('OPNSENSE_SECRET'))
    parser.add_argument('--host', help='Host name for filtering Docker containers', 
                      default=os.environ.get('HOST_NAME', 'unknown'))
    parser.add_argument('--batch-size', help='Number of entries to process in a batch', 
                      type=int, default=int(os.environ.get('BATCH_SIZE', '50')))
    parser.add_argument('--max-hostnames', help='Maximum number of hostnames to process in one run', 
                      type=int, default=int(os.environ.get('MAX_HOSTNAMES', '25')))
    parser.add_argument('--dry-run', help='Do not actually remove entries', 
                      action='store_true', default=os.environ.get('DRY_RUN', 'false').lower() == 'true')
    parser.add_argument('--skip-reconfigure', help='Skip Unbound reconfiguration', 
                      action='store_true', default=os.environ.get('SKIP_RECONFIGURE', 'false').lower() == 'true')
    parser.add_argument('--target-count', help='Target number of records to remove', 
                      type=int, default=int(os.environ.get('TARGET_COUNT', '0')) or None)
    parser.add_argument('--max-runs', help='Maximum number of cleanup runs to perform', 
                      type=int, default=int(os.environ.get('MAX_RUNS', '0')) or None)
    parser.add_argument('--wait-between-runs', help='Seconds to wait between runs', 
                      type=int, default=int(os.environ.get('WAIT_BETWEEN_RUNS', '5')))
    parser.add_argument('--analyze', help='Analyze hostname patterns only, no cleanup', 
                      action='store_true', default=False)
    parser.add_argument('--target-hostname', help='Target specific hostname prefix',
                      default=os.environ.get('TARGET_HOSTNAME', ''))
    parser.add_argument('--host-filter-disabled', help='Disable host filtering based on description',
                      action='store_true', default=False)
    parser.add_argument('--verbose', help='Enable verbose logging',
                      action='store_true', default=False)
    
    args = parser.parse_args()
    
    # Validate required arguments
    if not args.url or not args.key or not args.secret:
        logger.error("Missing required arguments: url, key, and secret")
        logger.info("Use environment variables OPNSENSE_URL, OPNSENSE_KEY, OPNSENSE_SECRET or command line arguments")
        return 1
    
    # Set log level
    if args.verbose:
        logger.setLevel(logging.DEBUG)
    
    # Initialize cleanup tool
    cleanup_tool = DNSCleanupTool(
        api_url=args.url,
        api_key=args.key,
        api_secret=args.secret,
        host_name=args.host,
        host_filter_disabled=args.host_filter_disabled,
        batch_size=args.batch_size,
        max_hostnames=args.max_hostnames,
        dry_run=args.dry_run,
        skip_reconfigure=args.skip_reconfigure,
        target_hostname=args.target_hostname,
        verbose=args.verbose
    )
    
    # Run analysis if requested
    if args.analyze:
        logger.info("Running hostname analysis only")
        cleanup_tool.analyze_hostnames()
        return 0
    
    # Run cleanup
    return cleanup_tool.run_full_cleanup(
        target_count=args.target_count,
        max_runs=args.max_runs,
        wait_between_runs=args.wait_between_runs
    )

if __name__ == "__main__":
    try:
        exit_code = main()
        sys.exit(exit_code)
    except KeyboardInterrupt:
        logger.info("Interrupted by user")
        sys.exit(130)
    except Exception as e:
        logger.exception(f"Unhandled exception: {e}")
        sys.exit(1)

def test_api_operations(api_url, api_key, api_secret):
    """Test basic API operations to diagnose issues."""
    logging.info("Running API diagnostic tests...")
    
    # Test GET for a listing of all host overrides
    cmd = [
        "curl", "-v", 
        "--connect-timeout", "5", 
        "-m", "15",
        "-k", 
        "-u", f"{api_key}:{api_secret}",
        f"{api_url}/unbound/settings/searchHostOverride?current=1&rowCount=10"
    ]
    
    logging.info("Test 1: Fetching host overrides (first 10)...")
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode == 0 and '"total":' in result.stdout:
        logging.info("✅ Test 1 passed: Can fetch host overrides")
    else:
        logging.error("❌ Test 1 failed: Cannot fetch host overrides")
        logging.error(f"Stdout: {result.stdout[:200]}")
        logging.error(f"Stderr: {result.stderr[:200]}")
    
    # Test handling of a non-existent UUID (to understand error format)
    cmd = [
        "curl", "-v", 
        "--connect-timeout", "5", 
        "-m", "15",
        "-k", 
        "-u", f"{api_key}:{api_secret}",
        "-X", "POST",
            "-d", "{}",
        "-H", "Content-Type: application/json",
        f"{api_url}/unbound/settings/delHostOverride/00000000-0000-0000-0000-000000000000"
    ]
    
    logging.info("Test 2: Deleting non-existent record (to see error format)...")
    result = subprocess.run(cmd, capture_output=True, text=True)
    logging.info(f"Test 2 response code: {result.returncode}")
    logging.info(f"Test 2 output: {result.stdout}")
    logging.info(f"Test 2 error: {result.stderr}")
    
    # Test if API documentation is available to check endpoint names
    cmd = [
        "curl", "-v", 
        "--connect-timeout", "5", 
        "-m", "15",
        "-k", 
        "-u", f"{api_key}:{api_secret}",
        f"{api_url}/unbound/settings"
    ]
    
    logging.info("Test 3: Checking API schema/capabilities...")
    result = subprocess.run(cmd, capture_output=True, text=True)
    logging.info(f"Test 3 response code: {result.returncode}")
    logging.info(f"Test 3 output: {result.stdout[:200]}")

# Add this to the bottom of main() before the return
if args.verbose:
    test_api_operations(args.url, args.key, args.secret)
