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

