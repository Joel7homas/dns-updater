# DNS Updater

A robust DNS update service for Docker containers that integrates with OPNsense's Unbound DNS server.

## Overview

DNS Updater automatically creates and updates DNS records in OPNsense for all Docker containers running on the host. It provides:

- Automatic DNS registration for all running containers
- Set-based IP management for multi-network containers
- Multiple domain support (network-specific and default domains)
- Efficient API communication with OPNsense
- Intelligent state tracking to minimize Unbound reconfigurations

## Features

- **Set-Based Network Management**: Properly handles containers with multiple networks without IP flapping
- **Automatic Discovery**: Monitors Docker events and automatically creates/removes DNS entries
- **Batched DNS Updates**: All updates are processed in a single batch to minimize Unbound restarts
- **Network-Specific Domains**: Creates entries for both network-specific and default domains
- **Advanced Error Handling**: Robust recovery from API and connection failures
- **Optimized Caching**: Reduces redundant API calls with TTL-based caching
- **Resource Efficient**: Minimal CPU and memory usage

## Installation

### Prerequisites

- Docker installed and running
- Access to OPNsense API (URL, API key, and API secret)
- Network connectivity between the Docker host and OPNsense

### Using Docker

The recommended way to run DNS Updater is with Docker:

```bash
docker run -d --name dns-updater \
  -v /var/run/docker.sock:/var/run/docker.sock:rw \
  -v /etc/hostname:/etc/docker_host_name:ro \
  -e OPNSENSE_URL=https://your-opnsense-ip/api \
  -e OPNSENSE_KEY=your_api_key \
  -e OPNSENSE_SECRET=your_api_secret \
  -e LOG_LEVEL=INFO \
  -e DNS_SYNC_INTERVAL=60 \
  -e DNS_CACHE_TTL=300 \
  jthomas/dns-updater:latest
```

### Building from Source

To build the image yourself:

```bash
git clone https://github.com/username/dns-updater.git
cd dns-updater
docker build -t dns-updater:latest .

# Then run with the same parameters as above
docker run -d --name dns-updater \
  -v /var/run/docker.sock:/var/run/docker.sock:rw \
  -v /etc/hostname:/etc/docker_host_name:ro \
  -e OPNSENSE_URL=https://your-opnsense-ip/api \
  -e OPNSENSE_KEY=your_api_key \
  -e OPNSENSE_SECRET=your_api_secret \
  -e LOG_LEVEL=INFO \
  dns-updater:latest
```

## Configuration

DNS Updater is configured through environment variables. Here's a complete list of available options:

### Required Configuration

| Variable | Description | Default | Notes |
|----------|-------------|---------|-------|
| `OPNSENSE_URL` | OPNsense API URL | (required) | |
| `OPNSENSE_KEY` | OPNsense API key | (required) | |
| `OPNSENSE_SECRET` | OPNsense API secret | (required) | |

### Logging

| Variable | Description | Default | Notes |
|----------|-------------|---------|-------|
| `LOG_LEVEL` | Logging level (DEBUG, INFO, WARNING, ERROR) | INFO | |

### API Connection

| Variable | Description | Default | Notes |
|----------|-------------|---------|-------|
| `OPNSENSE_DIRECT_IP` | Use direct IP instead of hostname | | Use to bypass DNS issues |
| `API_TIMEOUT` | Overall API timeout in seconds | 10 | |
| `SOCKET_TIMEOUT` | Socket-level timeout in seconds | 3.0 | Critical for TrueNAS Scale |
| `CONNECT_TIMEOUT` | Connection timeout in seconds | 5 | |
| `READ_TIMEOUT` | Read timeout in seconds | 30 | |
| `API_RETRY_COUNT` | Number of retry attempts for API calls | 3 | |
| `API_BACKOFF_FACTOR` | Backoff factor for retries | 0.3 | |
| `VERIFY_SSL` | Verify SSL certificates | true | Set to false for self-signed certs |
| `MAX_CONNECTION_ERRORS` | Max errors before switching methods | 3 | |
| `RECONNECT_DELAY` | Time to wait after connection failures | 5.0 | In seconds |

### State Management

| Variable | Description | Default | Notes |
|----------|-------------|---------|-------|
| `STATE_CLEANUP_CYCLES` | Cycles before removing gone containers | 3 | |

### Rate Limiting

| Variable | Description | Default | Notes |
|----------|-------------|---------|-------|
| `MIN_RECONFIGURE_INTERVAL` | Minimum time between reconfigurations | 1800 | In seconds (30 min) |
| `MIN_CALL_INTERVAL` | Minimum interval between API calls | 1.0 | In seconds |
| `SKIP_RECONFIG_AFTER_DELETE` | Skip reconfiguration after deletions | true | |
| `EMERGENCY_BYPASS_RECONFIG` | Emergency bypass for rate limiting | false | Use with caution |

### Sync and Cleanup Intervals

| Variable | Description | Default | Notes |
|----------|-------------|---------|-------|
| `DNS_SYNC_INTERVAL` | Sync interval in seconds | 60 | How often to update DNS |
| `DNS_CLEANUP_INTERVAL` | Cleanup interval in seconds | 3600 | How often to clean up stale entries |
| `DNS_CLEANUP_BATCH_SIZE` | Number of entries to process per batch | 50 | Larger values may be faster |
| `DNS_CLEANUP_MAX_HOSTNAMES` | Maximum hostnames to process per cleanup | 25 | |
| `CLEANUP_ON_STARTUP` | Run cleanup on startup | true | |

### Unbound Management

| Variable | Description | Default | Notes |
|----------|-------------|---------|-------|
| `RESTART_THRESHOLD` | Restart after this many reconfigurations | 50 | |
| `RESTART_INTERVAL` | Force restart every X seconds | 86400 | 24 hours |
| `VERIFICATION_DELAY` | Delay after deletion operations | 0 | Set to 0 for faster operation |

### Cache Settings

| Variable | Description | Default | Notes |
|----------|-------------|---------|-------|
| `DNS_CACHE_TTL` | Cache TTL in seconds | 300 | 5 minutes |

### API Implementation

| Variable | Description | Default | Notes |
|----------|-------------|---------|-------|
| `USE_CURL` | Use curl implementation instead of requests | false | Fallback option |
| `USE_CURL_FIRST` | Use curl for first connection | auto | auto/true/false |
| `STAY_WITH_CURL` | Keep using curl if successful | false | |
| `FORCE_HTTP1` | Force HTTP/1.1 protocol | false | Helps with some servers |

## Set-Based Network Management

Starting with version 2.1.0, DNS Updater uses a set-based approach to manage container IP addresses. This solves the problem of "IP flapping" for containers that are connected to multiple networks.

### The Problem

Before v2.1.0, containers with multiple networks would cause issues:
- Each update cycle would consider only one IP for the default domain (e.g., container.docker.local)
- Different network IPs would alternate between cycles
- This led to constant adding/removing of DNS entries and unnecessary reconfigurations

### The Solution

The set-based approach:
1. Tracks all valid IPs for each container across all networks
2. Maintains state between cycles to detect real changes
3. Adds entries for each network plus the default domain
4. Only updates DNS when actual network changes occur

This eliminates the IP flapping issue, drastically reduces Unbound reconfigurations, and improves overall service stability.

## Platform-Specific Configurations

### TrueNAS Scale

TrueNAS Scale may have connectivity issues with the default settings. Use these environment variables for better reliability:

```yaml
environment:
  - SOCKET_TIMEOUT=5.0
  - CONNECT_TIMEOUT=5
  - READ_TIMEOUT=30
  - VERIFY_SSL=false
  - FORCE_HTTP1=true
  - RECONNECT_DELAY=10.0
  - MAX_CONNECTION_ERRORS=3
  - USE_CURL=true
  - STAY_WITH_CURL=true
```

### Ubuntu/Debian

For Ubuntu/Debian hosts, these settings work well:

```yaml
environment:
  - SOCKET_TIMEOUT=1.0
  - CONNECT_TIMEOUT=3
  - READ_TIMEOUT=20
  - RECONNECT_DELAY=3.0
```

## Usage

### DNS Entry Structure

DNS Updater creates entries with the following patterns:

1. **Default domain**: `container.docker.local`
2. **Network-specific domain**: `container.network.docker.local`

For example, a container named "webapp" on the "frontend" network would get these entries:
- `webapp.docker.local`
- `webapp.frontend.docker.local`

If the container is on a Flannel network and the Flannel network is detected, it will also create:
- `webapp.flannel.docker.local`

### Monitoring

You can monitor DNS Updater's operation using:

```bash
# View logs
docker logs dns-updater

# Check specific log sections
docker logs dns-updater 2>&1 | grep -e synchronization
docker logs dns-updater 2>&1 | grep -e reconfiguring
```

### Verifying DNS Records

To verify that DNS records are being created correctly, you can:

1. Access the OPNsense UI
2. Navigate to Services → Unbound DNS → Overrides
3. Look for entries with the format `container.docker.local`

You can also check DNS resolution from another host:

```bash
# Test DNS resolution
dig webapp.docker.local @opnsense-ip
```

## Troubleshooting

### Common Issues

#### Containers with Multiple Networks

**Symptoms**:
- Container has multiple IPs across different networks
- DNS records are inconsistent or changing frequently

**Solution**:
- This is handled automatically in v2.1.0+ with the set-based approach
- Each network will have its own DNS record
- The default domain will use one of the IPs consistently

#### Connection Timeouts

**Symptoms**:
- Log messages showing `Request timed out`
- API connection failures

**Solutions**:
- Increase `SOCKET_TIMEOUT` and `CONNECT_TIMEOUT`
- Set `FORCE_HTTP1=true` to avoid HTTP/2 issues
- Consider `USE_CURL=true` for alternative implementation
- Use `OPNSENSE_DIRECT_IP` to bypass DNS resolution

#### DNS Entries Not Updating

**Symptoms**:
- Container starts but DNS record doesn't appear
- Log shows successful operations but DNS doesn't resolve

**Solutions**:
- Set `LOG_LEVEL=DEBUG` for more detailed logs
- Check if Unbound is running on OPNsense
- Verify API user has sufficient permissions
- Check for "Endpoint not found" errors that may indicate API changes

#### Slow Performance

**Symptoms**:
- Updates taking multiple minutes to complete
- Excessive API calls or logs

**Solutions**:
- Set `VERIFICATION_DELAY=0` to skip post-deletion verification
- Increase `DNS_CACHE_TTL` to reduce API calls
- Verify `DNS_SYNC_INTERVAL` is not too short (60s is recommended)
- Use `DNS_CLEANUP_BATCH_SIZE=100` for faster cleanup operations

### Running Diagnostics

Use the provided diagnostic script to identify issues:

```bash
# Inside the container or from the source directory
python3 api_diagnostics.py
```

### Repair Script

A repair script is included that can fix common issues:

```bash
# Run from the source directory
./dns-updater-repair.sh
```

This script will:
1. Check for missing imports
2. Fix import-related issues
3. Update error handling
4. Offer to rebuild and restart the container

## Architecture

DNS Updater follows a modular architecture:

1. **Container Network State**: Tracks container networks and detects changes
   - Monitors changes to container network configurations
   - Uses a set-based approach to handle multi-network containers
   - Determines which DNS entries need to be added or removed

2. **API Client**: Handles communication with OPNsense API
   - Supports both requests and curl implementations
   - Includes fallback mechanisms and automatic recovery

3. **DNS Manager**: Manages DNS record operations
   - Handles creation, updates, and deletions
   - Manages caching and batch operations
   - Controls Unbound reconfiguration

4. **Container Monitor**: Tracks Docker container events
   - Listens for container start/stop events
   - Syncs DNS entries on a regular cycle
   - Manages cleanup of stale entries

## Contributing

Contributions are welcome! Please feel free to submit a Pull Request.

## License

This project is licensed under the BSD 2-Clause License - see the LICENSE file for details.

## Acknowledgments

- OPNsense for providing a robust DNS service with API capabilities
- Docker for the container monitoring capabilities

