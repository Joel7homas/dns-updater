# Set-Based DNS Updater Implementation

This document describes the set-based implementation for DNS Updater that prevents IP address "flapping" and excessive Unbound reconfigurations.

## Overview

The set-based implementation keeps track of container network states between cycles, only making DNS changes when true network changes occur. This significantly reduces unnecessary DNS updates and Unbound reconfigurations, especially for containers with multiple networks.

## Key Components

1. **ContainerNetworkState** (`container_network_state.py`): 
   - Core class for tracking container network states and detecting real changes
   - Uses deep copies to prevent state corruption
   - Implements container cleanup to prevent memory growth

2. **ContainerMonitor Updates**:
   - Modified to use the new state tracking system
   - Improved change detection logic
   - Better handling of multi-network containers

3. **DNSManager Updates**:
   - New `process_dns_changes` method for efficient batch processing
   - Better caching to reduce API calls
   - Improved reconfiguration decision logic

4. **Diagnostic Tools**:
   - `dns_tracker_diagnostic.py` for testing the implementation
   - Helps validate change detection and update processing

## Implementation Benefits

1. **Reduced Reconfiguration**: Only reconfigures Unbound when real changes are detected
2. **Multi-Network Support**: Properly handles containers with multiple networks
3. **Improved Stability**: Eliminates the "flapping" behavior where IPs constantly change
4. **Lower API Load**: Reduced API calls to Unbound improves performance
5. **Memory Efficient**: Cleanup mechanism prevents memory growth over time

## Deployment Guide

### Prerequisites
- Same prerequisites as the original DNS Updater
- Python 3.6 or higher
- Access to Docker socket
- OPNsense API access

### Installation Steps

1. **Backup existing configuration**:
   ```
   cp -r /path/to/current/dns-updater /path/to/backup/dns-updater
   ```

2. **Copy new files**:
   ```
   # Copy the new implementation files to the appropriate locations
   cp container_network_state.py /path/to/dns-updater/
   cp dns_tracker_diagnostic.py /path/to/dns-updater/
   ```

3. **Update existing files**:
   - Update `container_monitor.py` with the modified functions
   - Add the new `process_dns_changes` method to `dns_manager.py`

4. **Rebuild the container**:
   ```
   cd /path/to/dns-updater
   docker build -t dns-updater:set-based .
   ```

5. **Deploy the updated version**:
   ```
   docker stop dns-updater
   docker rm dns-updater
   docker run -d --name dns-updater \
     -v /var/run/docker.sock:/var/run/docker.sock:rw \
     -v /etc/hostname:/etc/docker_host_name:ro \
     -e OPNSENSE_URL=https://your-opnsense-ip/api \
     -e OPNSENSE_KEY=your_api_key \
     -e OPNSENSE_SECRET=your_api_secret \
     -e STATE_CLEANUP_CYCLES=3 \
     dns-updater:set-based
   ```

### Configuration Options

The set-based implementation adds one new environment variable:

- `STATE_CLEANUP_CYCLES`: Number of cycles before removing containers that no longer exist (default: 3)

All existing environment variables continue to work as before.

## Testing and Validation

### Running the Diagnostic Tool

For testing without affecting your production DNS, run the diagnostic tool:

```bash
cd /path/to/dns-updater
python3 dns_tracker_diagnostic.py --cycles 5 --interval 30 --verbose
```

This will:
1. Connect to your Docker daemon
2. Track container networks for 5 cycles, 30 seconds apart
3. Simulate DNS updates (without making actual changes)
4. Log detailed information about what changes would be made

### Monitoring Production Deployment

After deploying the updated version, monitor the logs:

```bash
docker logs -f dns-updater
```

Look for:
- `"No container network changes detected"` - Indicates stability
- `"State statistics: X containers, Y with multiple networks"` - Shows tracking is working
- Reduction in reconfiguration frequency

## Troubleshooting

### Issue: DNS records not being updated

**Possible causes**:
- Changes not being detected due to false equivalence
- API connection issues

**Solution**:
- Check logs for network state changes
- Ensure OPNsense API is accessible

### Issue: Memory usage increases over time

**Possible causes**:
- Container cleanup not working properly
- Docker API or volume leaks

**Solution**:
- Increase log verbosity
- Check if STATE_CLEANUP_CYCLES is set appropriately

### Issue: Excessive DNS changes still occurring

**Possible causes**:
- Implementation not correctly comparing states
- Edge case in IP detection

**Solution**:
- Enable verbose logging to identify precise change triggers
- Review state snapshots to diagnose issues

## Future Improvements

Potential enhancements for future versions:

1. **Performance Metrics**: Add detailed metrics on API calls saved
2. **Multi-Host Consistency**: Improved coordination between DNS updaters on different hosts
3. **Selective Updates**: Allow configuring which containers get DNS entries
4. **Health Checks**: Add API health checks to reduce unnecessary API calls when OPNsense is unavailable

## Support and Feedback

If you encounter issues or have suggestions for improvements, please submit an issue on the project repository.
