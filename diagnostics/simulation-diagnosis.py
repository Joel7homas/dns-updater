#!/usr/bin/env python3
import subprocess
import json
import time
import os
import urllib3
from datetime import datetime

# Disable warnings
urllib3.disable_warnings()

# Load credentials
def load_credentials():
    with open("stack.env", "r") as f:
        config = {}
        for line in f:
            if line.strip() and not line.startswith('#'):
                key, value = line.strip().split('=', 1)
                config[key] = value
    return config

config = load_credentials()
BASE_URL = config["OPNSENSE_URL"]
API_KEY = config["OPNSENSE_KEY"]
API_SECRET = config["OPNSENSE_SECRET"]

def curl_request(method, endpoint, data=None, timeout=30):
    """Make a request using curl subprocess - mimicking container implementation."""
    url = f"{BASE_URL}/{endpoint}"
    
    # Build curl command like the container does
    cmd = ["curl", "-s"]
    cmd.extend(["-X", method])
    cmd.extend(["--connect-timeout", "5"])
    cmd.extend(["-m", str(timeout)])
    cmd.extend(["--retry", "3"])
    cmd.extend(["--retry-delay", "2"])
    cmd.extend(["--retry-max-time", "90"])
    cmd.extend(["--retry-all-errors"])
    cmd.extend(["-u", f"{API_KEY}:{API_SECRET}"])
    cmd.append("-k")  # Skip SSL verification
    
    # For POST requests, handle data
    if method.upper() == "POST":
        cmd.extend(["-H", "Content-Type: application/json"])
        if data is None:
            cmd.extend(["-d", "{}"])  # Empty JSON object
        else:
            cmd.extend(["-d", json.dumps(data)])
    
    # Add URL
    cmd.append(url)
    
    # Print the command (with auth redacted)
    safe_cmd = cmd.copy()
    auth_index = safe_cmd.index("-u") if "-u" in safe_cmd else -1
    if auth_index >= 0:
        safe_cmd[auth_index+1] = "REDACTED"
    print(f"Running: {' '.join(safe_cmd)}")
    
    # Execute command
    start_time = time.time()
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout+10)
        elapsed = time.time() - start_time
        
        if result.returncode != 0:
            print(f"Curl failed with code {result.returncode} after {elapsed:.2f}s")
            print(f"Stderr: {result.stderr}")
            return {"status": "error", "message": f"Curl error: {result.stderr}"}, elapsed
        
        print(f"Curl completed in {elapsed:.2f}s")
        
        # Try to parse JSON response
        try:
            response_data = json.loads(result.stdout)
            return response_data, elapsed
        except json.JSONDecodeError:
            print(f"Invalid JSON response: {result.stdout[:100]}")
            return {"status": "error", "message": "Invalid JSON response"}, elapsed
    
    except subprocess.TimeoutExpired:
        elapsed = time.time() - start_time
        print(f"Curl subprocess timed out after {elapsed:.2f}s")
        return {"status": "error", "message": "Subprocess timeout"}, elapsed
    
    except Exception as e:
        elapsed = time.time() - start_time
        print(f"Curl subprocess error after {elapsed:.2f}s: {str(e)}")
        return {"status": "error", "message": f"Subprocess error: {str(e)}"}, elapsed

def requests_api_call(method, endpoint, data=None, timeout=(5, 30)):
    """Make a request using Python requests library."""
    import requests
    url = f"{BASE_URL}/{endpoint}"
    print(f"Using requests to call {method} {url}")
    
    start_time = time.time()
    try:
        if method.upper() == "GET":
            response = requests.get(url, auth=(API_KEY, API_SECRET), verify=False, timeout=timeout)
        else:  # POST
            response = requests.post(url, json=data if data is not None else {}, 
                                   auth=(API_KEY, API_SECRET), verify=False, timeout=timeout)
        
        elapsed = time.time() - start_time
        print(f"Requests call completed in {elapsed:.2f}s with status {response.status_code}")
        
        # Return parsed JSON or text response
        try:
            return response.json(), elapsed
        except:
            return {"text": response.text}, elapsed
    
    except Exception as e:
        elapsed = time.time() - start_time
        print(f"Requests call failed after {elapsed:.2f}s: {str(e)}")
        return {"status": "error", "message": str(e)}, elapsed

def test_side_by_side():
    """Test both curl and requests implementations side by side."""
    print(f"=== Side-by-Side API Test - {datetime.now()} ===")
    
    # Test series of operations
    endpoints = [
        ("GET", "core/firmware/status", None),
        ("GET", "unbound/settings/searchHostOverride?searchPhrase=&current=1&rowCount=10", None),
        ("GET", "unbound/settings/searchHostOverride", None)
    ]
    
    # Run each test with both methods
    for method, endpoint, data in endpoints:
        print(f"\n=== Testing {method} {endpoint} ===")
        
        # First with curl implementation
        print("\nCURL IMPLEMENTATION:")
        curl_result, curl_time = curl_request(method, endpoint, data)
        
        # Then with requests implementation
        print("\nREQUESTS IMPLEMENTATION:")
        requests_result, requests_time = requests_api_call(method, endpoint, data)
        
        # Compare results
        print(f"\nCURL time: {curl_time:.2f}s, Requests time: {requests_time:.2f}s")
        print(f"Difference: {abs(curl_time - requests_time):.2f}s")
    
    # Test specific operations
    print("\n=== Testing Record Creation/Deletion ===")
    
    # Create a test record
    test_data = {
        "host": {
            "enabled": "1",
            "hostname": f"test-{int(time.time())}",
            "domain": "docker.local",
            "server": "192.168.1.254",
            "description": "Test record"
        }
    }
    
    # Create with curl
    print("\nCURL - Create Record:")
    curl_create, curl_create_time = curl_request("POST", "unbound/settings/addHostOverride", test_data)
    curl_uuid = curl_create.get("uuid") if isinstance(curl_create, dict) else None
    
    # Delete with curl if created
    if curl_uuid:
        print(f"\nCURL - Delete Record (UUID: {curl_uuid}):")
        curl_delete, curl_delete_time = curl_request("POST", f"unbound/settings/delHostOverride/{curl_uuid}")
    
    # Create with requests
    print("\nREQUESTS - Create Record:")
    requests_create, requests_create_time = requests_api_call("POST", "unbound/settings/addHostOverride", test_data)
    requests_uuid = requests_create.get("uuid") if isinstance(requests_create, dict) else None
    
    # Delete with requests if created
    if requests_uuid:
        print(f"\nREQUESTS - Delete Record (UUID: {requests_uuid}):")
        requests_delete, requests_delete_time = requests_api_call("POST", f"unbound/settings/delHostOverride/{requests_uuid}")
    
    # Test reconfiguration
    print("\nCURL - Reconfigure:")
    curl_reconfig, curl_reconfig_time = curl_request("POST", "unbound/service/reconfigure", None, timeout=60)
    
    print("\nREQUESTS - Reconfigure:")
    requests_reconfig, requests_reconfig_time = requests_api_call("POST", "unbound/service/reconfigure", None, timeout=(5, 60))

if __name__ == "__main__":
    test_side_by_side()
