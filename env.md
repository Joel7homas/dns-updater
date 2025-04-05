# DNS Updater Environment Variables
# This file documents all available environment variables for dns-updater

# Basic Configuration
LOG_LEVEL=INFO                             # Logging level: DEBUG, INFO, WARNING, ERROR
VERSION=2.0.17                             # Version number

# OPNsense API Configuration
OPNSENSE_URL=https://lavash.7homas.com/api  # OPNsense API URL
OPNSENSE_KEY=your_api_key                  # OPNsense API key
OPNSENSE_SECRET=your_api_secret            # OPNsense API secret
OPNSENSE_DIRECT_IP=192.168.4.1             # Use direct IP instead of hostname
VERIFY_SSL=false                           # Verify SSL certificates (set to false for self-signed)

# Connection Timeouts
SOCKET_TIMEOUT=3.0                         # Socket-level timeout in seconds
CONNECT_TIMEOUT=5                          # Connection timeout in seconds
READ_TIMEOUT=30                            # Read timeout in seconds
API_TIMEOUT=10                             # Overall API timeout in seconds

# Retry Configuration
API_RETRY_COUNT=3                          # Number of retries for API calls
API_BACKOFF_FACTOR=0.3                     # Backoff factor between retries
MAX_CONNECTION_ERRORS=3                    # Max errors before switching methods

# Rate Limiting
MIN_RECONFIGURE_INTERVAL=1800              # Minimum time between reconfigurations (30 min)
SKIP_RECONFIG_AFTER_DELETE=true            # Skip reconfiguration after deletions
EMERGENCY_BYPASS_RECONFIG=false            # Emergency bypass for rate limiting (use with caution)

# Sync and Cleanup Intervals
DNS_SYNC_INTERVAL=300                      # Sync interval in seconds (5 min)
DNS_CLEANUP_INTERVAL=3600                  # Cleanup interval in seconds (1 hour)
CLEANUP_ON_STARTUP=true                    # Run cleanup on startup

# Unbound Management
RESTART_THRESHOLD=50                       # Restart after this many reconfigurations
RESTART_INTERVAL=86400                     # Force restart every X seconds (24 hours)

# Cache Settings
DNS_CACHE_TTL=300                          # Cache TTL in seconds (5 min)

# API Implementation
USE_CURL=false                             # Use curl implementation instead of requests
USE_CURL_FIRST=auto                        # Use curl for first connection (auto/true/false)
STAY_WITH_CURL=false                       # Keep using curl if successful
FORCE_HTTP1=true                           # Force HTTP/1.1 protocol

# Multi-Instance Support 
API_JITTER=true                            # Use jitter to prevent thundering herd
JITTER_MAX_SECONDS=15                      # Maximum jitter in seconds
