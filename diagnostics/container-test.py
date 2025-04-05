#!/usr/bin/env python3
import subprocess
import time
import sys
import os

# Test network connectivity
def test_connectivity():
    print("=== Network Connectivity Test ===")
    targets = [
        ("DNS", "lavash.7homas.com"),
        ("API", "https://lavash.7homas.com/api/core/firmware/status")
    ]
    
    for name, target in targets:
        start = time.time()
        print(f"Testing {name} connectivity to {target}...")
        
        if name == "DNS":
            # Test DNS resolution
            try:
                result = subprocess.run(["nslookup", target], 
                                      capture_output=True, text=True, timeout=5)
                elapsed = time.time() - start
                if result.returncode == 0 and "Address:" in result.stdout:
                    print(f"  Success: DNS resolved in {elapsed:.2f}s")
                    print(f"  {result.stdout.strip().split('Address:')[-1].strip()}")
                else:
                    print(f"  Failed: DNS resolution failed in {elapsed:.2f}s")
                    print(f"  {result.stderr}")
            except Exception as e:
                elapsed = time.time() - start
                print(f"  Error: {str(e)} after {elapsed:.2f}s")
        else:
            # Test HTTP connectivity
            try:
                result = subprocess.run(["curl", "-s", "-k", "--connect-timeout", "5", 
                                       "-m", "10", "-w", "%{http_code}", "-o", "/dev/null", 
                                       target], 
                                      capture_output=True, text=True, timeout=15)
                elapsed = time.time() - start
                
                if result.returncode == 0 and result.stdout.strip() == "200":
                    print(f"  Success: API connection in {elapsed:.2f}s")
                else:
                    print(f"  Failed: API connection failed in {elapsed:.2f}s")
                    print(f"  Status: {result.stdout.strip()}")
                    print(f"  Error: {result.stderr}")
            except Exception as e:
                elapsed = time.time() - start
                print(f"  Error: {str(e)} after {elapsed:.2f}s")

# Test HTTP parameters
def test_http_parameters():
    print("\n=== HTTP Parameters Test ===")
    
    # Test different curl commands
    tests = [
        ("Default", ["curl", "-s", "-k", "-m", "10", 
                    "https://lavash.7homas.com/api/core/firmware/status"]),
        ("IPv4 Only", ["curl", "-s", "-k", "-m", "10", "--ipv4",
                      "https://lavash.7homas.com/api/core/firmware/status"]),
        ("No Keep-Alive", ["curl", "-s", "-k", "-m", "10", "--no-keepalive",
                          "https://lavash.7homas.com/api/core/firmware/status"]),
        ("Resolve Manually", ["curl", "-s", "-k", "-m", "10", 
                             "--resolve", "lavash.7homas.com:443:192.168.4.1",
                             "https://lavash.7homas.com/api/core/firmware/status"])
    ]
    
    for name, cmd in tests:
        start = time.time()
        print(f"Testing {name} method...")
        
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
            elapsed = time.time() - start
            
            if result.returncode == 0 and len(result.stdout) > 10:
                print(f"  Success: Completed in {elapsed:.2f}s")
                print(f"  Response size: {len(result.stdout)} bytes")
            else:
                print(f"  Failed: Completed in {elapsed:.2f}s with code {result.returncode}")
                print(f"  Error: {result.stderr}")
        except Exception as e:
            elapsed = time.time() - start
            print(f"  Error: {str(e)} after {elapsed:.2f}s")

# Print environment information
def print_environment():
    print("\n=== Environment Information ===")
    print(f"Python version: {sys.version}")
    
    # Print relevant environment variables
    env_vars = ["PATH", "LD_LIBRARY_PATH", "http_proxy", "https_proxy", 
               "NO_PROXY", "CURL_CA_BUNDLE", "SSL_CERT_FILE"]
    
    for var in env_vars:
        print(f"{var}: {os.environ.get(var, 'Not set')}")
    
    # Check for DNS configuration
    print("\nDNS Configuration:")
    try:
        with open("/etc/resolv.conf", "r") as f:
            print(f.read())
    except Exception as e:
        print(f"Error reading resolv.conf: {e}")

if __name__ == "__main__":
    print("=== Container Environment Diagnostics ===")
    print(f"Date/Time: {time.strftime('%Y-%m-%d %H:%M:%S')}")
    
    print_environment()
    test_connectivity()
    test_http_parameters()
