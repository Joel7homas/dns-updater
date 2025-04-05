#!/usr/bin/env python3
# diagnose-container.py - DNS Updater diagnostic tool

import os
import sys
import time
import json
import socket
import subprocess
import requests
from urllib.parse import urlparse
import warnings

# Suppress insecure request warnings for clean output
warnings.filterwarnings("ignore", category=requests.packages.urllib3.exceptions.InsecureRequestWarning)

def log(message):
    timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
    print(f"{timestamp} - {message}")

def run_command(cmd, timeout=10):
    """Run a shell command and return output."""
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return result.stdout.strip(), result.returncode
    except subprocess.TimeoutExpired:
        return f"Command timed out after {timeout}s", 1
    except Exception as e:
        return f"Error executing command: {e}", 1

def test_dns_resolution(hostname):
    """Test DNS resolution for a hostname."""
    log(f"Testing DNS resolution for {hostname}...")
    
    try:
        start_time = time.time()
        ip = socket.gethostbyname(hostname)
        elapsed = time.time() - start_time
        
        log(f"  Success: Resolved {hostname} to {ip} in {elapsed:.2f}s")
        return ip
    except socket.gaierror as e:
        elapsed = time.time() - start_time
        log(f"  Failed: Could not resolve {hostname} ({e}) in {elapsed:.2f}s")
        return None

def test_direct_connection(ip, port=443, timeout=5):
    """Test direct TCP connection to IP:port."""
    log(f"Testing direct TCP connection to {ip}:{port}...")
    
    try:
        start_time = time.time()
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(timeout)
        s.connect((ip, port))
        s.close()
        elapsed = time.time() - start_time
        
        log(f"  Success: Connected to {ip}:{port} in {elapsed:.2f}s")
        return True
    except Exception as e:
        elapsed = time.time() - start_time
        log(f"  Failed: Could not connect to {ip}:{port} ({e}) in {elapsed:.2f}s")
        return False

def test_api_connection(url, auth=None, verify=True, timeout=10):
    """Test API connection with requests."""
    log(f"Testing API connection to {url}...")
    
    try:
        start_time = time.time()
        response = requests.get(url, auth=auth, verify=verify, timeout=timeout)
        elapsed = time.time() - start_time
        
        log(f"  Success: API responded in {elapsed:.2f}s (status: {response.status_code})")
        if response.status_code == 200:
            try:
                log(f"  Response preview: {response.text[:100]}...")
            except:
                pass
        return response.status_code, response.text
    except requests.exceptions.RequestException as e:
        elapsed = time.time() - start_time
        log(f"  Failed: API connection failed in {elapsed:.2f}s ({e})")
        return None, str(e)

def test_curl_connection(url, auth=None, verify=True, timeout=10):
    """Test API connection with curl."""
    log(f"Testing API connection to {url} using curl...")
    
    cmd = ["curl", "-s", "-v", "--max-time", str(timeout)]
    
    if auth:
        username, password = auth
        cmd.extend(["-u", f"{username}:{password}"])
    
    if not verify:
        cmd.append("-k")
    
    cmd.append(url)
    
    start_time = time.time()
    output, rc = run_command(cmd, timeout + 5)
    elapsed = time.time() - start_time
    
    if rc == 0:
        log(f"  Success: curl response in {elapsed:.2f}s")
        return 200, output
    else:
        log(f"  Failed: curl failed in {elapsed:.2f}s (code: {rc})")
        # Extract part of the error message
        if len(output) > 100:
            log(f"  Error snippet: {output[:100]}...")
        else:
            log(f"  Error: {output}")
        return None, output

def test_dns_cmd():
    """Test DNS resolution using dig or nslookup."""
    hostname = "lavash.7homas.com"
    log(f"Testing DNS resolution for {hostname} using command-line tools...")
    
    # Try dig first
    output, rc = run_command(["dig", "+short", hostname])
    if rc == 0 and output:
        log(f"  dig result: {output}")
    else:
        # Fall back to nslookup
        output, rc = run_command(["nslookup", hostname])
        if rc == 0:
            log(f"  nslookup result: {output}")
        else:
            log(f"  Failed to get DNS resolution using command-line tools")

def inspect_container_network():
    """Inspect Docker container network settings."""
    log("Inspecting container network configuration...")
    output, rc = run_command(["cat", "/proc/net/route"])
    if rc == 0:
        log(f"Routing table (raw):\n{output}")
    
    # Check if we can access Docker socket from inside container
    output, rc = run_command(["ls", "-la", "/var/run/docker.sock"])
    if rc == 0:
        log("Docker socket is accessible, inspecting container network...")
        output, rc = run_command(["docker", "network", "inspect", "bridge"])
        if rc == 0:
            log(f"Docker network info:\n{output[:200]}...")
        else:
            log("Cannot inspect Docker network")
    else:
        log("Docker socket not accessible from inside container")

def inspect_network_config():
    """Inspect network configuration."""
    log("Inspecting network configuration...")
    
    # Check DNS configuration
    output, _ = run_command(["cat", "/etc/resolv.conf"])
    log(f"resolv.conf contents:\n{output}")
    
    # Check routing table
    output, _ = run_command(["ip", "route"])
    log(f"Routing table:\n{output}")
    
    # Check network interfaces
    output, _ = run_command(["ip", "addr"])
    log(f"Network interfaces:\n{output}")
    
    # Check hosts file
    output, _ = run_command(["cat", "/etc/hosts"])
    log(f"Hosts file contents:\n{output}")

def test_all_configs():
    """Test all possible configurations to find one that works."""
    # Get OPNsense configuration from environment variables
    opnsense_url = os.environ.get("OPNSENSE_URL", "https://lavash.7homas.com/api")
    opnsense_key = os.environ.get("OPNSENSE_KEY", "")
    opnsense_secret = os.environ.get("OPNSENSE_SECRET", "")
    auth = (opnsense_key, opnsense_secret) if opnsense_key and opnsense_secret else None
    
    log(f"Using OPNsense URL: {opnsense_url}")
    
    # Parse URL to get hostname
    parsed_url = urlparse(opnsense_url)
    hostname = parsed_url.netloc.split(':')[0]  # Handle port if present
    
    # Test DNS resolution for the hostname
    ip = test_dns_resolution(hostname)
    
    # Test direct connection to the resolved IP
    if ip:
        test_direct_connection(ip, 443)
    
    # Test direct connection to known OPNsense IP (likely gateway IP)
    direct_ip = "192.168.4.1"  # Common gateway IP
    log(f"Testing direct TCP connection to {direct_ip}:443...")
    test_direct_connection(direct_ip, 443)
    
    # Test API connection with the hostname
    base_url = opnsense_url.rstrip('/')
    if not base_url.endswith('/api'):
        base_url += '/api'
    
    # Test API connection with direct IP
    direct_url = base_url.replace(hostname, direct_ip)
    status_code, response = test_api_connection(f"{direct_url}/core/firmware/status", auth, False, 5)
    
    # Test API connection with hostname
    status_code, response = test_api_connection(f"{base_url}/core/firmware/status", auth, False, 5)
    
    # Test again with longer timeout as fallback
    if not status_code or status_code >= 400:
        status_code, response = test_api_connection(f"{base_url}/core/firmware/status", auth, False, 10)
    
    # Test with curl for comparison
    status_code, response = test_curl_connection(f"{base_url}/core/firmware/status", auth, False, 5)
    
    # Test unbound DNS API endpoints specifically
    log("Testing Unbound DNS API endpoints...")
    test_api_connection(f"{direct_url}/unbound/settings/searchHostOverride", auth, False, 5)
    
    # Test deletion with a fake ID
    test_url = f"{direct_url}/unbound/settings/delHostOverride/00000000-0000-0000-0000-000000000000"
    status_code, response = test_api_connection(test_url, auth, False, 5)
    log(f"  Delete test response code: {status_code}")
    
    # Test DNS command-line tools
    test_dns_cmd()

# Main execution
if __name__ == "__main__":
    log("Starting DNS Updater diagnostics")
    inspect_network_config()
    inspect_container_network()
    test_all_configs()
    log("Diagnostics complete")
