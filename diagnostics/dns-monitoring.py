#!/usr/bin/env python3
# dns-monitoring.py - Monitor DNS resolution stability
import socket
import time
import csv
import datetime
import subprocess

# Configuration
TEST_HOSTNAMES = [
    "lavash.7homas.com",  # OPNsense hostname
    "babka.7homas.com",    # TrueNAS Scale hostname
    "pita.7homas.com",     # Ubuntu hostname
    "example.com"         # External reference
]
TEST_INTERVAL = 1  # seconds
OUTPUT_FILE = "dns_resolution_log.csv"
DIRECT_DNS_SERVER = "192.168.4.1"  # OPNsense IP

# Test using system resolver
def test_system_dns(hostname):
    try:
        start_time = time.time()
        ip = socket.gethostbyname(hostname)
        elapsed = time.time() - start_time
        return ip, elapsed, "success"
    except Exception as e:
        elapsed = time.time() - start_time
        return None, elapsed, str(e)

# Test using direct DNS server query
def test_direct_dns(hostname, dns_server):
    try:
        start_time = time.time()
        cmd = ["dig", "@" + dns_server, hostname, "+short", "+time=2"]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=3)
        elapsed = time.time() - start_time
        
        if result.returncode == 0 and result.stdout.strip():
            return result.stdout.strip().split("\n")[0], elapsed, "success"
        else:
            return None, elapsed, "no_result"
    except Exception as e:
        elapsed = time.time() - start_time
        return None, elapsed, str(e)

# Initialize CSV file
with open(OUTPUT_FILE, 'w', newline='') as f:
    writer = csv.writer(f)
    writer.writerow(["timestamp", "hostname", "method", "result", "ip", "response_time"])

# Main monitoring loop
try:
    print(f"Starting DNS monitoring (Ctrl+C to stop)...")
    print(f"Results will be saved to {OUTPUT_FILE}")
    
    while True:
        timestamp = datetime.datetime.now().isoformat()
        
        for hostname in TEST_HOSTNAMES:
            # Test with system resolver
            ip, elapsed, result = test_system_dns(hostname)
            with open(OUTPUT_FILE, 'a', newline='') as f:
                writer = csv.writer(f)
                writer.writerow([timestamp, hostname, "system", result, ip, f"{elapsed:.6f}"])
            
            # Test with direct DNS server
            ip, elapsed, result = test_direct_dns(hostname, DIRECT_DNS_SERVER)
            with open(OUTPUT_FILE, 'a', newline='') as f:
                writer = csv.writer(f)
                writer.writerow([timestamp, hostname, "direct", result, ip, f"{elapsed:.6f}"])
        
        # Short report to console
        print(f"{timestamp}: Completed tests for {len(TEST_HOSTNAMES)} hostnames")
        time.sleep(TEST_INTERVAL)
        
except KeyboardInterrupt:
    print("\nMonitoring stopped by user")
    print(f"Results saved to {OUTPUT_FILE}")

