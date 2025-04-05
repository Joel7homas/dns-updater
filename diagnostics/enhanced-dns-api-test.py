#!/usr/bin/env python3
# enhanced-dns-api-test.py - Test DNS and API connectivity together
import socket
import time
import datetime
import subprocess
import requests
import csv
import random

# Configuration
TEST_INTERVALS = [1, 3, 5, 10, 20]  # seconds between tests
DURATION = 300  # total test duration in seconds
DNS_TARGETS = ["lavash.7homas.com", "example.com"]
API_URL = "https://192.168.4.1/api/core/firmware/status"  # Direct IP test
OUTPUT_FILE = "dns_api_correlation.csv"

# Initialize CSV file
with open(OUTPUT_FILE, 'w', newline='') as f:
    writer = csv.writer(f)
    writer.writerow(["timestamp", "test_type", "target", "result", "response_time", "details"])

def test_dns(hostname):
    """Test DNS resolution."""
    try:
        start_time = time.time()
        ip = socket.gethostbyname(hostname)
        elapsed = time.time() - start_time
        return True, elapsed, ip
    except Exception as e:
        elapsed = time.time() - start_time
        return False, elapsed, str(e)

def test_api(url):
    """Test API connectivity."""
    try:
        start_time = time.time()
        response = requests.get(url, verify=False, timeout=5)
        elapsed = time.time() - start_time
        return True, elapsed, f"Status: {response.status_code}"
    except Exception as e:
        elapsed = time.time() - start_time
        return False, elapsed, str(e)

def record_result(test_type, target, success, elapsed, details):
    """Record test result to CSV file."""
    timestamp = datetime.datetime.now().isoformat()
    with open(OUTPUT_FILE, 'a', newline='') as f:
        writer = csv.writer(f)
        writer.writerow([timestamp, test_type, target, "success" if success else "failure", f"{elapsed:.6f}", details])

print(f"Starting enhanced DNS/API correlation test for {DURATION} seconds...")
print(f"Results will be logged to {OUTPUT_FILE}")

start_time = time.time()
next_test_time = start_time

while time.time() - start_time < DURATION:
    # Wait until next test time
    current_time = time.time()
    if current_time < next_test_time:
        time.sleep(0.1)  # Small sleep to avoid busy waiting
        continue

    # Pick random interval for next test
    interval = random.choice(TEST_INTERVALS)
    next_test_time = current_time + interval
    
    # DNS tests
    for hostname in DNS_TARGETS:
        success, elapsed, details = test_dns(hostname)
        record_result("dns", hostname, success, elapsed, details)
        
    # API test
    success, elapsed, details = test_api(API_URL)
    record_result("api", API_URL, success, elapsed, details)
    
    # Brief status update
    print(f"Test at {datetime.datetime.now().strftime('%H:%M:%S')} - Next in {interval}s")

print(f"Testing completed. Results saved to {OUTPUT_FILE}")
