# DNS Updater v2.0.3

A robust DNS update service for Docker containers that integrates with OPNsense's Unbound DNS server.

## Major Improvements in v2.0.3

This version resolves the connection issues on TrueNAS Scale by:

1. **Split Architecture**: Using a modular multi-module design for better maintainability
2. **Socket-Level Timeouts**: Properly handling socket timeouts to prevent connection hanging
3. **Connection Resilience**: Improved error handling and recovery from dropped connections
4. **Fallback Mechanisms**: Alternative implementation using curl when needed
5. **Protocol Optimizations**: Force HTTP/1.1 to avoid HTTP/2 issues

## Overview

This service automatically creates and updates DNS records in OPNsense for all Docker containers running on the host. It provides:

- Automatic DNS registration for all containers
- Multiple domain support (network-specific and default domains)
- Efficient API communication with rate limiting
- Improved reliability with OPNsense/Unbound
- Caching to reduce unnecessary API calls

## Features

- **Batched DNS Updates**: All updates are processed in a single batch to minimize Unbound restarts
- **Rate Limiting**: Prevents Unbound service flapping with controlled API calls
- **Intelligent Caching**: Reduces redundant API calls with TTL-based caching
- **Network-Specific Domains**: Creates entries for both network-specific and default domains
- **Advanced Error Handling**: Robust recovery from API and connection failures

## Configuration

### Environment Variables

| Variable | Description | Default | Notes |
|----------|-------------|---------|-------|
| `OPNSENSE_URL` | OPNsense API URL | (required) | |
| `OPNSENSE_KEY` | OPNsense API key | (required) | |
| `OPNSENSE_SECRET` | OPNsense API secret | (required) | |
| `LOG_LEVEL` | Logging level (DEBUG, INFO, WARNING, ERROR) | INFO | |
| `SOCKET_TIMEOUT` | Low-level socket timeout in seconds | 5.0 | Critical for TrueNAS Scale |
| `CONNECT_TIMEOUT` | Connection timeout in seconds | 5 | |
| `READ_TIMEOUT` | Read timeout in seconds | 30 | |
| `API_RETRY_COUNT` | Number of retry attempts for API calls | 3 | |
| `API_BACKOFF_FACTOR` | Backoff factor for retries | 0.5 | |
| `RECONNECT_DELAY` | Delay between reconnection attempts in seconds | 10.0 | |
| `DNS_CACHE_TTL` | Cache TTL in seconds | 300 | |
| `VERIFY_SSL` | Verify SSL certificates | true | Set to false for self-signed certs |
| `FORCE_HTTP1` | Force HTTP/1.1 protocol | false | Helps with some servers |
| `USE_CURL` | Use curl implementation instead of requests | false | Fallback option |

### Platform-Specific Configurations

#### TrueNAS Scale

```yaml
environment:
  - SOCKET_TIMEOUT=5.0
  - CONNECT_TIMEOUT=5
  - READ_TIMEOUT=30
  - VERIFY_SSL=false
  - FORCE_HTTP1=true
  - RECONNECT_DELAY=10.0
  - MAX_CONNECTION_ERRORS=3
```

#### Ubuntu/Debian

```yaml
environment:
  - SOCKET_TIMEOUT=1.0
  - CONNECT_TIMEOUT=3
  - READ_TIMEOUT=20
  - RECONNECT_DELAY=3.0
```

### Docker Compose Example

```yaml
version: '3.8'

services:
  dns-updater:
    image: dns-updater:2.0.3
    container_name: dns-updater
    restart: unless-stopped
    volumes:
      - /var/run/docker.sock:/var/run/docker.sock:rw
      - /etc/hostname:/etc/docker_host_name:ro
    environment:
      - TZ=America/Denver
      - OPNSENSE_URL=${OPNSENSE_URL}
      - OPNSENSE_KEY=${OPNSENSE_KEY}
      - OPNSENSE_SECRET=${OPNSENSE_SECRET}
      - LOG_LEVEL=INFO
      - SOCKET_TIMEOUT=5.0
      - CONNECT_TIMEOUT=5
      - VERIFY_SSL=false
    logging:
      driver: "json-file"
      options:
        max-size: "1m"
        max-file: "1"
```

## Domain Structure

DNS Updater creates entries with the following patterns:

1. **Default domain**: `container.docker.local`
2. **Network-specific domain**: `container.network.docker.local`

For example, a container named "webapp" on the "frontend" network would get these entries:
- `webapp.docker.local`
- `webapp.frontend.docker.local`

## Troubleshooting

### Common Issues

1. **Connection Timeouts**:
   - Increase `SOCKET_TIMEOUT` and `CONNECT_TIMEOUT`
   - Set `FORCE_HTTP1=true` to avoid HTTP/2 issues
   - Consider `USE_CURL=true` for alternative implementation

2. **DNS Entries Not Updating**:
   - Set `LOG_LEVEL=DEBUG` for more detailed logs
   - Check if Unbound is running on OPNsense
   - Verify API user has sufficient permissions

3. **Slow Recovery After Dropped Connections**:
   - Adjust `RECONNECT_DELAY` to a lower value
   - Decrease `MAX_CONNECTION_ERRORS` for faster fallback

### Debugging

For more detailed logging, set `LOG_LEVEL=DEBUG`:

```bash
docker-compose down
LOG_LEVEL=DEBUG docker-compose up -d
docker-compose logs -f
```

## Architecture

DNS Updater follows a minimalist multi-module pattern with these components:

1. **API Client Core**: Base functionality and configuration
2. **API Client Requests**: Primary implementation using Python requests
3. **API Client Alternative**: Fallback implementation using curl
4. **DNS Manager**: Manages DNS record creation and updates
5. **Container Monitor**: Tracks Docker container events
6. **Cache Manager**: Provides efficient caching to reduce API calls

This modular design ensures reliability across different platforms and allows for easy maintenance and extension.
