#!/usr/bin/env python3
# module_check.py - Check if required modules are installed and accessible

import os
import sys
import importlib.util

def check_module(module_name):
    """Check if a module is available and print information about it."""
    spec = importlib.util.find_spec(module_name)
    
    if spec is None:
        print(f"✗ Module {module_name} is NOT available")
        return False
    
    print(f"✓ Module {module_name} is available at: {spec.origin}")
    
    # If it's a local module, check the content
    if spec.origin and os.path.isfile(spec.origin) and not spec.origin.startswith("/usr"):
        try:
            with open(spec.origin, 'r') as f:
                content = f.read()
                lines = content.split('\n')
                print(f"  - File size: {len(content)} bytes")
                print(f"  - Line count: {len(lines)}")
                
                # Check for required functions
                if module_name == 'api_client_core':
                    for func in ['__init__', '_rate_limit', 'get', 'post']:
                        if f"def {func}" in content:
                            print(f"  - Function {func}: ✓")
                        else:
                            print(f"  - Function {func}: ✗ (NOT FOUND)")
                
                elif module_name == 'api_client':
                    if "def create_api_client" in content:
                        print(f"  - Function create_api_client: ✓")
                    else:
                        print(f"  - Function create_api_client: ✗ (NOT FOUND)")
                
        except Exception as e:
            print(f"  - Error reading file: {e}")
    
    return True

def check_imports():
    """Check imports between modules."""
    try:
        import api_client
        print("\nChecking imports in api_client:")
        
        # Check if OPNsenseAPICore is imported
        has_core = hasattr(api_client, 'OPNsenseAPICore')
        print(f"  - Imports OPNsenseAPICore: {'✓' if has_core else '✗'}")
        
        # Check for create_api_client function
        has_factory = hasattr(api_client, 'create_api_client')
        print(f"  - Has create_api_client function: {'✓' if has_factory else '✗'}")
        
        # Try to check imports for requests module
        try:
            import api_client_requests
            print("\nChecking api_client_requests:")
            has_api_class = hasattr(api_client_requests, 'OPNsenseAPI')
            print(f"  - Has OPNsenseAPI class: {'✓' if has_api_class else '✗'}")
        except ImportError:
            print("\n✗ Cannot import api_client_requests")
        
    except ImportError:
        print("\n✗ Cannot import api_client")

def main():
    """Main function to check modules."""
    print(f"Python version: {sys.version}")
    print(f"Working directory: {os.getcwd()}")
    print(f"Files in current directory: {os.listdir('.')}")
    print("\nChecking required modules:")
    
    modules_to_check = [
        'requests',  # External dependency
        'docker',    # External dependency
        'api_client',
        'api_client_core',
        'api_client_requests',
        'api_client_alt',
        'dns_manager',
        'container_monitor',
        'cache_manager'
    ]
    
    for module in modules_to_check:
        check_module(module)
        print("")
    
    check_imports()

if __name__ == "__main__":
    main()
