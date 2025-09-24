# dns_replication_api.py
"""
Simple HTTP API for DNS record replication between hosts
"""

import json
import logging
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs
import os

logger = logging.getLogger('dns_updater.replication_api')

class DNSReplicationHandler(BaseHTTPRequestHandler):
    """HTTP handler for DNS replication API"""
    
    def __init__(self, *args, distributed_dns_manager=None, **kwargs):
        self.distributed_dns_manager = distributed_dns_manager
        super().__init__(*args, **kwargs)
    
    def do_GET(self):
        """Handle GET requests - health check and status"""
        if self.path == "/health":
            self._send_response(200, {"status": "healthy", "role": getattr(self.distributed_dns_manager, 'role', 'unknown')})
        elif self.path == "/status":
            self._send_response(200, self._get_status())
        else:
            self._send_response(404, {"error": "Not found"})
    
    def do_POST(self):
        """Handle POST requests - DNS operations"""
        try:
            # Parse URL
            parsed_url = urlparse(self.path)
            path_parts = parsed_url.path.strip('/').split('/')
            
            if len(path_parts) < 2 or path_parts[0] != 'dns':
                self._send_response(400, {"error": "Invalid path"})
                return
            
            action = path_parts[1]  # add, remove, etc.
            
            # Parse request body
            content_length = int(self.headers.get('Content-Length', 0))
            if content_length == 0:
                self._send_response(400, {"error": "Empty request body"})
                return
            
            body = self.rfile.read(content_length)
            data = json.loads(body.decode('utf-8'))
            
            # Process the action
            result = self._process_dns_action(action, data)
            
            if result:
                self._send_response(200, {"status": "success", "action": action})
            else:
                self._send_response(500, {"status": "error", "action": action})
                
        except json.JSONDecodeError:
            self._send_response(400, {"error": "Invalid JSON"})
        except Exception as e:
            logger.error(f"API request failed: {e}")
            self._send_response(500, {"error": str(e)})
    
    def _process_dns_action(self, action: str, data: dict) -> bool:
        """Process DNS action with provided data"""
        hostname = data.get('hostname')
        if not hostname:
            return False
        
        if not self.distributed_dns_manager:
            logger.error("No distributed DNS manager available")
            return False
        
        try:
            if action == "add":
                ip = data.get('ip')
                network_name = data.get('network_name')
                if not ip:
                    return False
                return self.distributed_dns_manager.add_container_record(hostname, ip, network_name)
            
            elif action == "remove":
                network_name = data.get('network_name')
                return self.distributed_dns_manager.remove_container_record(hostname, network_name)
            
            else:
                logger.error(f"Unknown action: {action}")
                return False
                
        except Exception as e:
            logger.error(f"DNS action {action} failed: {e}")
            return False
    
    def _get_status(self) -> dict:
        """Get current status information"""
        status = {
            "role": getattr(self.distributed_dns_manager, 'role', 'unknown'),
            "host_name": getattr(self.distributed_dns_manager, 'host_name', 'unknown'),
            "local_unbound_enabled": bool(getattr(self.distributed_dns_manager, 'local_unbound', None)),
            "replication_enabled": bool(getattr(self.distributed_dns_manager, 'replication_client', None)),
            "api_fallback_enabled": bool(getattr(self.distributed_dns_manager, 'api_client', None))
        }
        return status
    
    def _send_response(self, status_code: int, data: dict):
        """Send HTTP response"""
        self.send_response(status_code)
        self.send_header('Content-type', 'application/json')
        self.end_headers()
        self.wfile.write(json.dumps(data).encode('utf-8'))
    
    def log_message(self, format, *args):
        """Override to use our logger instead of stderr"""
        logger.info(f"API: {format % args}")

class DNSReplicationServer:
    """HTTP server for DNS replication API"""
    
    def __init__(self, distributed_dns_manager, port: int = 8080):
        self.distributed_dns_manager = distributed_dns_manager
        self.port = port
        self.server = None
        self.server_thread = None
    
    def start(self):
        """Start the replication server"""
        try:
            # Create handler class with distributed_dns_manager
            def handler_factory(*args, **kwargs):
                return DNSReplicationHandler(*args, distributed_dns_manager=self.distributed_dns_manager, **kwargs)
            
            self.server = HTTPServer(('0.0.0.0', self.port), handler_factory)
            self.server_thread = threading.Thread(target=self.server.serve_forever, daemon=True)
            self.server_thread.start()
            
            logger.info(f"DNS replication API server started on port {self.port}")
            
        except Exception as e:
            logger.error(f"Failed to start replication server: {e}")
    
    def stop(self):
        """Stop the replication server"""
        if self.server:
            self.server.shutdown()
            logger.info("DNS replication API server stopped")

# Integration with main dns-updater

def start_replication_api_if_needed(distributed_dns_manager):
    """Start replication API server if this host should provide it"""
    
    # Only start API server on hosts that have local Unbound
    if not getattr(distributed_dns_manager, 'local_unbound', None):
        logger.info("No local Unbound, skipping replication API server")
        return None
    
    # Get port from environment
    api_port = int(os.environ.get('DNS_REPLICATION_PORT', '8080'))
    
    try:
        server = DNSReplicationServer(distributed_dns_manager, api_port)
        server.start()
        return server
    except Exception as e:
        logger.error(f"Failed to start replication API server: {e}")
        return None

# Example usage in main.py integration:

def integrate_with_main():
    """Integration code to add to main.py"""
    
    # Replace the existing dns_manager initialization with:
    from dns_updater_integration import HybridDNSManager
    from dns_replication_api import start_replication_api_if_needed
    
    # Initialize hybrid DNS manager
    dns_manager = HybridDNSManager(api_client, "docker.local", hostname)
    
    # Start replication API if needed
    replication_server = None
    if hasattr(dns_manager, 'distributed_dns') and dns_manager.distributed_dns:
        replication_server = start_replication_api_if_needed(dns_manager.distributed_dns)
    
    # Continue with existing container_monitor initialization...
    container_monitor = ContainerMonitor(dns_manager)

# Client code for sending updates to master (culvert use case)

class DNSMasterClient:
    """Client for sending DNS updates to master server"""
    
    def __init__(self, master_url: str):
        self.master_url = master_url.rstrip('/')
        self.session = requests.Session()
        self.session.timeout = (5, 15)
        logger.info(f"Initialized DNS master client: {master_url}")
    
    def add_record(self, hostname: str, ip: str, network_name: str = None) -> bool:
        """Add DNS record via master server"""
        try:
            data = {
                "hostname": hostname,
                "ip": ip,
                "network_name": network_name
            }
            
            response = self.session.post(f"{self.master_url}/dns/add", json=data)
            success = response.status_code == 200
            
            if success:
                logger.info(f"Added record via master: {hostname} -> {ip}")
            else:
                logger.error(f"Failed to add record via master: {response.status_code}")
            
            return success
            
        except Exception as e:
            logger.error(f"Master client add failed: {e}")
            return False
    
    def remove_record(self, hostname: str, network_name: str = None) -> bool:
        """Remove DNS record via master server"""
        try:
            data = {
                "hostname": hostname,
                "network_name": network_name
            }
            
            response = self.session.post(f"{self.master_url}/dns/remove", json=data)
            success = response.status_code == 200
            
            if success:
                logger.info(f"Removed record via master: {hostname}")
            else:
                logger.error(f"Failed to remove record via master: {response.status_code}")
            
            return success
            
        except Exception as e:
            logger.error(f"Master client remove failed: {e}")
            return False

# Modified HybridDNSManager to support master client mode

class HybridDNSManagerWithClient(HybridDNSManager):
    """Extended HybridDNSManager with master client support"""
    
    def __init__(self, api_client=None, base_domain="docker.local", host_name="unknown"):
        super().__init__(api_client, base_domain, host_name)
        
        # Initialize master client if configured
        self.master_client = None
        master_url = os.environ.get('DNS_MASTER_URL')
        if master_url:
            import requests
            self.master_client = DNSMasterClient(master_url)
            logger.info("Initialized DNS master client mode")
    
    def process_dns_changes(self, entries_to_add, entries_to_remove) -> bool:
        """Process changes via master client when available"""
        
        # Use master client if available
        if self.master_client:
            return self._process_changes_via_master(entries_to_add, entries_to_remove)
        
        # Fall back to parent implementation
        return super().process_dns_changes(entries_to_add, entries_to_remove)
    
    def _process_changes_via_master(self, entries_to_add, entries_to_remove) -> bool:
        """Process changes by sending to master server"""
        changes_made = False
        
        try:
            # Process removals
            for entry in entries_to_remove:
                hostname = entry.get('hostname')
                if not hostname:
                    continue
                
                network_name = entry.get('network_name') if 'network_name' in entry else None
                if self.master_client.remove_record(hostname, network_name):
                    changes_made = True
            
            # Process additions
            for entry in entries_to_add:
                hostname = entry.get('hostname')
                ip = entry.get('ip')
                network_name = entry.get('network_name')
                
                if not hostname or not ip:
                    continue
                
                if self.master_client.add_record(hostname, ip, network_name):
                    changes_made = True
            
            logger.info(f"Processed {len(entries_to_add)} additions and {len(entries_to_remove)} removals via master client")
            
        except Exception as e:
            logger.error(f"Master client processing failed: {e}")
            # Fall back to local processing
            return super().process_dns_changes(entries_to_add, entries_to_remove)
        
        return changes_made
