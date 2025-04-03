# DNS Updater v2.0.0

A robust DNS update service for Docker containers that integrates with OPNsense's Unbound DNS server.

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

| Variable | Description | Default |
|----------|-------------|---------|
| `OPNSENSE_URL` | OPNsense API URL | (required) |
| `OPNSENSE_KEY` | OPNsense API key | (required) |
| `OPNSENSE_SECRET` | OPNsense API secret | (required) |
| `LOG_LEVEL` | Logging level (DEBUG, INFO, WARNING, ERROR) | INFO |
| `API_TIMEOUT` | API request timeout in seconds | 10 |
| `API_RETRY_COUNT` | Number of retry attempts for API calls | 3 |
| `API_BACKOFF_FACTOR` | Backoff factor for retries | 0.3 |
| `DNS_CACHE_TTL` | Cache TTL in seconds | 60 |
| `HEALTH_CHECK_INTERVAL` | Health check interval in seconds | 300 |
| `VERSION` | Version number to display in logs | 2.0.0 |

### Docker Compose Example

```yaml
version: '3.8'

services:
  dns-updater:
    image: dns-updater:2.0.0
    container_name: dns-updater
    restart: unless-stopped
    volumes:
      - /var/run/docker.sock:/var/run/docker.sock
      - /etc/hostname:/etc/docker_host_name:ro
    environment:
      - TZ=America/Denver
      - OPNSENSE_KEY=${OPNSENSE_KEY}
      - OPNSENSE_SECRET=${OPNSENSE_SECRET}
      - OPNSENSE_URL=${OPNSENSE_URL}
      - VERSION=2.0.0
      - LOG_LEVEL=INFO
      - API_TIMEOUT=10
      - API_RETRY_COUNT=3
      - API_BACKOFF_FACTOR=0.3
      - DNS_CACHE_TTL=60
      - HEALTH_CHECK_INTERVAL=300
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

1. **API Connection Failures**:
   - Verify OPNsense API credentials
   - Check network connectivity to OPNsense
   - Increase `API_TIMEOUT` for slower networks

2. **DNS Entries Not Updating**:
   - Set `LOG_LEVEL=DEBUG` for more detailed logs
   - Check if Unbound is running on OPNsense
   - Verify API user has sufficient permissions

3. **Container Stuck on API Test**:
   - This may indicate network connectivity issues
   - Check firewalls between host and OPNsense
   - Increase timeout with `API_TIMEOUT=30`

### Debugging

For more detailed logging, set `LOG_LEVEL=DEBUG`:

```bash
docker-compose down
LOG_LEVEL=DEBUG docker-compose up -d
docker-compose logs -f
```

## Architecture

DNS Updater follows a minimalist multi-module pattern with these components:

1. **API Client**: Handles OPNsense API communication with rate limiting and retries
2. **DNS Manager**: Manages DNS record creation, deletion, and updates
3. **Container Monitor**: Listens for container events and tracks network changes
4. **Cache Manager**: Provides efficient caching to reduce API calls
5. **Logger**: Configurable logging system

## License

BSD 2-Clause License
