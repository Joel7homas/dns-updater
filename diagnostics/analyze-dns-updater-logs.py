#!/usr/bin/env python3
# analyze-dns-updater-logs.py - Count reconfiguration and timeout events
import re
import sys
from datetime import datetime, timedelta
import collections

# Configuration
LOG_FILE = "dns_updater.log"  # Change to your log file path
if len(sys.argv) > 1:
    LOG_FILE = sys.argv[1]

# Patterns to look for
RECONFIG_PATTERN = r"Reconfiguring Unbound"
RESTART_PATTERN = r"Restarting Unbound service"
TIMEOUT_PATTERN = r"curl failed with code 28"
ERROR_PATTERN = r"ERROR"
REMOVE_PATTERN = r"Failed to remove DNS entry"
GET_ENTRIES_PATTERN = r"Failed to get DNS entries"

# Counters
reconfig_times = []
restart_times = []
timeout_times = []
error_times = []
remove_times = []
get_times = []

# Parse log file
with open(LOG_FILE, 'r') as f:
    for line in f:
        # Extract timestamp
        match = re.search(r"(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})", line)
        if not match:
            continue
            
        timestamp = datetime.strptime(match.group(1), "%Y-%m-%d %H:%M:%S")
        
        # Check for events
        if re.search(RECONFIG_PATTERN, line):
            reconfig_times.append(timestamp)
        if re.search(RESTART_PATTERN, line):
            restart_times.append(timestamp)
        if re.search(TIMEOUT_PATTERN, line):
            timeout_times.append(timestamp)
        if re.search(ERROR_PATTERN, line):
            error_times.append(timestamp)
        if re.search(REMOVE_PATTERN, line):
            remove_times.append(timestamp)
        if re.search(GET_ENTRIES_PATTERN, line):
            get_times.append(timestamp)

# Calculate events per hour
def events_per_hour(event_times):
    if not event_times:
        return []
        
    start_time = min(event_times)
    end_time = max(event_times)
    
    # If less than an hour of data, return empty list
    if end_time - start_time < timedelta(hours=1):
        return []
        
    # Create hourly buckets
    hourly_counts = collections.defaultdict(int)
    for t in event_times:
        hour_key = t.replace(minute=0, second=0, microsecond=0)
        hourly_counts[hour_key] += 1
        
    return sorted(hourly_counts.items())

# Calculate events per minute
def events_per_minute(event_times):
    if not event_times:
        return []
        
    # Create minute buckets
    minute_counts = collections.defaultdict(int)
    for t in event_times:
        minute_key = t.replace(second=0, microsecond=0)
        minute_counts[minute_key] += 1
        
    return sorted(minute_counts.items())

# Calculate intervals between events
def calculate_intervals(event_times):
    if len(event_times) < 2:
        return []
        
    intervals = []
    for i in range(1, len(event_times)):
        interval = (event_times[i] - event_times[i-1]).total_seconds()
        intervals.append(interval)
        
    return intervals

# Print summary
print(f"Log Analysis Summary for {LOG_FILE}")
print(f"Total events found:")
print(f"  Reconfigurations: {len(reconfig_times)}")
print(f"  Restarts: {len(restart_times)}")
print(f"  Timeouts: {len(timeout_times)}")
print(f"  Remove DNS failures: {len(remove_times)}")
print(f"  Get DNS entries failures: {len(get_times)}")
print(f"  All Errors: {len(error_times)}")

if timeout_times:
    print(f"\nFirst event: {min(error_times)}")
    print(f"Last event: {max(error_times)}")
    
    # Calculate averages
    time_range = max(error_times) - min(error_times)
    minutes = time_range.total_seconds() / 60
    
    if minutes > 0:
        print(f"\nAverage events per minute:")
        print(f"  Timeouts: {len(timeout_times) / minutes:.2f}")
        print(f"  Remove failures: {len(remove_times) / minutes:.2f}")
        print(f"  Get entries failures: {len(get_times) / minutes:.2f}")

    # Check intervals between timeouts
    timeout_intervals = calculate_intervals(timeout_times)
    if timeout_intervals:
        avg_interval = sum(timeout_intervals) / len(timeout_intervals)
        min_interval = min(timeout_intervals)
        max_interval = max(timeout_intervals)
        
        print(f"\nTimeout intervals:")
        print(f"  Average: {avg_interval:.2f} seconds")
        print(f"  Minimum: {min_interval:.2f} seconds")
        print(f"  Maximum: {max_interval:.2f} seconds")
        
        # Distribution of intervals
        brackets = [0, 30, 60, 120, 300, 600]
        counts = [0] * (len(brackets))
        
        for interval in timeout_intervals:
            for i, threshold in enumerate(brackets):
                if interval >= threshold:
                    counts[i] += 1
                else:
                    break
        
        print("\nInterval distribution:")
        for i in range(len(brackets)-1):
            print(f"  {brackets[i]}-{brackets[i+1]}s: {counts[i] - counts[i+1]}")
        print(f"  600+s: {counts[-1]}")
    
    # Show minute-by-minute events
    timeout_by_minute = events_per_minute(timeout_times)
    print("\nMinutes with highest timeout count:")
    high_minutes = sorted(timeout_by_minute, key=lambda x: x[1], reverse=True)[:5]
    for minute, count in high_minutes:
        print(f"  {minute.strftime('%H:%M')}: {count} timeouts")

