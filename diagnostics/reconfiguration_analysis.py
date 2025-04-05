#!/usr/bin/env python3
# reconfiguration-analysis.py - Analyze DNS Updater reconfiguration patterns
# This script parses log files to identify reconfiguration patterns and rate limiting issues

import re
import sys
import os
import time
from datetime import datetime, timedelta
import collections
import statistics

# Configuration
LOG_FILE = "dns_updater.log"  # Default log file path
if len(sys.argv) > 1:
    LOG_FILE = sys.argv[1]

# Time patterns
TIMESTAMP_PATTERN = r"(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})"

# Event pattern matching
FORCE_RECONFIG_PATTERN = r"Forcing Unbound reconfiguration \(bypassing rate limiting\)"
RATE_LIMIT_PATTERN = r"Skipping reconfigure - last one was ([\d\.]+)s ago"
RECONFIG_PATTERN = r"Reconfiguring Unbound \(([\d\.]+)s since last reconfigure\)"
DNS_FETCH_PATTERN = r"Fetching all DNS entries"
FAILED_DELETE_PATTERN = r"Failed to remove DNS entry"
SUCCESSFUL_RECONFIG_PATTERN = r"Unbound reconfiguration successful"
FORCED_SUCCESS_PATTERN = r"Forced reconfiguration successful"

# Analysis state
reconfig_events = []  # List of (timestamp, elapsed_time, is_forced)
rate_limit_events = []  # List of (timestamp, skipped_time)
dns_fetch_events = []  # List of timestamp
failed_delete_events = []  # List of timestamp
successful_reconfig = []  # List of timestamp

# Success rates
reconfig_attempts = 0
reconfig_successes = 0

# Parse the log file
def parse_log_file():
    global reconfig_attempts, reconfig_successes
    
    print(f"Analyzing log file: {LOG_FILE}")
    with open(LOG_FILE, 'r') as f:
        for line in f:
            # Extract timestamp
            match = re.search(TIMESTAMP_PATTERN, line)
            if not match:
                continue
                
            timestamp = datetime.strptime(match.group(1), "%Y-%m-%d %H:%M:%S")
            
            # Check for forced reconfiguration
            if re.search(FORCE_RECONFIG_PATTERN, line):
                reconfig_events.append((timestamp, 0, True))
                reconfig_attempts += 1
            
            # Check for normal reconfiguration
            reconfig_match = re.search(RECONFIG_PATTERN, line)
            if reconfig_match:
                elapsed = float(reconfig_match.group(1))
                reconfig_events.append((timestamp, elapsed, False))
                reconfig_attempts += 1
            
            # Check for rate limiting
            rate_limit_match = re.search(RATE_LIMIT_PATTERN, line)
            if rate_limit_match:
                skipped_time = float(rate_limit_match.group(1))
                rate_limit_events.append((timestamp, skipped_time))
            
            # Check for DNS fetch
            if re.search(DNS_FETCH_PATTERN, line):
                dns_fetch_events.append(timestamp)
            
            # Check for failed delete
            if re.search(FAILED_DELETE_PATTERN, line):
                failed_delete_events.append(timestamp)
                
            # Check for successful reconfig
            if re.search(SUCCESSFUL_RECONFIG_PATTERN, line) or re.search(FORCED_SUCCESS_PATTERN, line):
                successful_reconfig.append(timestamp)
                reconfig_successes += 1

# Calculate intervals between events
def calculate_intervals(events):
    if len(events) < 2:
        return []
    
    if isinstance(events[0], tuple):
        # If events are tuples, use first element (timestamp)
        return [(events[i][0] - events[i-1][0]).total_seconds() for i in range(1, len(events))]
    else:
        # If events are just timestamps
        return [(events[i] - events[i-1]).total_seconds() for i in range(1, len(events))]

# Generate statistics for intervals
def interval_statistics(intervals):
    if not intervals:
        return {"count": 0, "min": 0, "max": 0, "avg": 0, "median": 0}
    
    return {
        "count": len(intervals),
        "min": min(intervals),
        "max": max(intervals),
        "avg": sum(intervals) / len(intervals),
        "median": statistics.median(intervals) if len(intervals) > 0 else 0
    }

# Count events by hour
def events_by_hour(events):
    if not events:
        return {}
    
    if isinstance(events[0], tuple):
        # If events are tuples, use first element (timestamp)
        timestamps = [e[0] for e in events]
    else:
        # If events are just timestamps
        timestamps = events
    
    hourly_counts = collections.defaultdict(int)
    for ts in timestamps:
        hour_key = ts.replace(minute=0, second=0, microsecond=0)
        hourly_counts[hour_key] += 1
    
    return dict(sorted(hourly_counts.items()))

# Check for correlation between events
def check_correlations():
    # Check if DNS fetches often follow reconfigurations
    reconfig_to_fetch_correlation = 0
    
    if reconfig_events and dns_fetch_events:
        for reconfig_time, _, _ in reconfig_events:
            # Look for DNS fetches within 5 seconds after reconfig
            for fetch_time in dns_fetch_events:
                if 0 <= (fetch_time - reconfig_time).total_seconds() <= 5:
                    reconfig_to_fetch_correlation += 1
                    break
    
    # Check if deletions often lead to forced reconfigurations
    delete_to_force_correlation = 0
    
    if failed_delete_events and reconfig_events:
        for delete_time in failed_delete_events:
            # Look for forced reconfigs within 5 seconds after delete
            for reconfig_time, _, is_forced in reconfig_events:
                if is_forced and 0 <= (reconfig_time - delete_time).total_seconds() <= 5:
                    delete_to_force_correlation += 1
                    break
    
    return {
        "reconfig_to_fetch": reconfig_to_fetch_correlation,
        "reconfig_to_fetch_pct": (reconfig_to_fetch_correlation / len(reconfig_events)) * 100 if reconfig_events else 0,
        "delete_to_force": delete_to_force_correlation,
        "delete_to_force_pct": (delete_to_force_correlation / len(failed_delete_events)) * 100 if failed_delete_events else 0
    }

# Print a summary of patterns
def print_summary():
    # Calculate time ranges
    if not (reconfig_events or dns_fetch_events):
        print("No relevant events found in log file.")
        return
    
    all_timestamps = []
    if reconfig_events:
        all_timestamps.extend([t for t, _, _ in reconfig_events])
    if dns_fetch_events:
        all_timestamps.extend(dns_fetch_events)
    
    if not all_timestamps:
        print("No timestamps found for analysis.")
        return
    
    # Calculate time range
    start_time = min(all_timestamps)
    end_time = max(all_timestamps)
    duration = (end_time - start_time).total_seconds()
    
    # Calculate statistics
    reconfig_intervals = calculate_intervals(reconfig_events)
    dns_fetch_intervals = calculate_intervals(dns_fetch_events)
    
    reconfig_stats = interval_statistics(reconfig_intervals)
    dns_fetch_stats = interval_statistics(dns_fetch_intervals)
    
    # Count forced reconfigurations
    forced_reconfigs = sum(1 for _, _, is_forced in reconfig_events if is_forced)
    normal_reconfigs = len(reconfig_events) - forced_reconfigs
    
    # Check rate limiting effectiveness
    rate_limited_count = len(rate_limit_events)
    rate_limiting_effectiveness = (rate_limited_count / (rate_limited_count + len(reconfig_events))) * 100 if (rate_limited_count + len(reconfig_events)) > 0 else 0
    
    # Calculate success rate
    success_rate = (reconfig_successes / reconfig_attempts) * 100 if reconfig_attempts > 0 else 0
    
    # Check correlations
    correlations = check_correlations()
    
    # Print the summary
    print("\n" + "="*80)
    print(f"DNS UPDATER CONFIGURATION ANALYSIS SUMMARY")
    print("="*80)
    
    print(f"\nLog timespan: {start_time} to {end_time} ({duration/3600:.2f} hours)")
    
    print("\nRECONFIGURATION PATTERNS:")
    print(f"Total reconfigurations: {len(reconfig_events)}")
    print(f"  - Forced reconfigs: {forced_reconfigs} ({forced_reconfigs/len(reconfig_events)*100:.1f}% of total)")
    print(f"  - Normal reconfigs: {normal_reconfigs} ({normal_reconfigs/len(reconfig_events)*100:.1f}% of total)")
    print(f"Reconfiguration success rate: {success_rate:.1f}%")
    print(f"Average time between reconfigs: {reconfig_stats['avg']:.1f} seconds")
    print(f"Reconfiguration frequency: {len(reconfig_events)/(duration/3600):.1f} per hour")
    
    print("\nRATE LIMITING EFFECTIVENESS:")
    print(f"Rate limiting applied: {rate_limited_count} times")
    print(f"Rate limiting effectiveness: {rate_limiting_effectiveness:.1f}%")
    if rate_limit_events:
        skipped_times = [t for _, t in rate_limit_events]
        print(f"Average skipped time: {sum(skipped_times)/len(skipped_times):.1f} seconds")
    
    print("\nDNS FETCH PATTERNS:")
    print(f"Total DNS fetches: {len(dns_fetch_events)}")
    print(f"DNS fetch frequency: {len(dns_fetch_events)/(duration/3600):.1f} per hour")
    print(f"Average time between fetches: {dns_fetch_stats['avg']:.1f} seconds")
    
    print("\nCORRELATIONS:")
    print(f"DNS fetches after reconfigs: {correlations['reconfig_to_fetch']} ({correlations['reconfig_to_fetch_pct']:.1f}% of reconfigs)")
    print(f"Forced reconfigs after failed deletes: {correlations['delete_to_force']} ({correlations['delete_to_force_pct']:.1f}% of failed deletes)")
    
    print("\nHOURLY PATTERNS:")
    reconfig_by_hour = events_by_hour(reconfig_events)
    dns_fetch_by_hour = events_by_hour(dns_fetch_events)
    
    if reconfig_by_hour:
        max_hour = max(reconfig_by_hour.items(), key=lambda x: x[1])[0]
        max_count = reconfig_by_hour[max_hour]
        print(f"Hour with most reconfigurations: {max_hour.strftime('%Y-%m-%d %H:00')} ({max_count} reconfigs)")
    
    # Find the interval distribution for reconfigurations
    if reconfig_intervals:
        print("\nRECONFIGURATION INTERVAL DISTRIBUTION:")
        intervals = [0, 10, 30, 60, 300, 900, 1800]
        counts = [0] * (len(intervals) + 1)
        
        for interval in reconfig_intervals:
            placed = False
            for i, threshold in enumerate(intervals):
                if interval < threshold:
                    counts[i] += 1
                    placed = True
                    break
            if not placed:
                counts[-1] += 1
        
        for i in range(len(intervals)):
            if i < len(intervals) - 1:
                print(f"  {intervals[i]}-{intervals[i+1]}s: {counts[i]} ({counts[i]/len(reconfig_intervals)*100:.1f}%)")
            else:
                print(f"  {intervals[i]}+s: {counts[-1]} ({counts[-1]/len(reconfig_intervals)*100:.1f}%)")
    
    # Find the interval distribution for DNS fetches
    if dns_fetch_intervals:
        print("\nDNS FETCH INTERVAL DISTRIBUTION:")
        intervals = [0, 10, 30, 60, 300, 900, 1800]
        counts = [0] * (len(intervals) + 1)
        
        for interval in dns_fetch_intervals:
            placed = False
            for i, threshold in enumerate(intervals):
                if interval < threshold:
                    counts[i] += 1
                    placed = True
                    break
            if not placed:
                counts[-1] += 1
        
        for i in range(len(intervals)):
            if i < len(intervals) - 1:
                print(f"  {intervals[i]}-{intervals[i+1]}s: {counts[i]} ({counts[i]/len(dns_fetch_intervals)*100:.1f}%)")
            else:
                print(f"  {intervals[i]}+s: {counts[-1]} ({counts[-1]/len(dns_fetch_intervals)*100:.1f}%)")
    
    print("\nCONCLUSIONS:")
    # Rate limiting effectiveness
    if rate_limiting_effectiveness < 25:
        print("⚠️  CRITICAL: Rate limiting is mostly being bypassed")
    elif rate_limiting_effectiveness < 50:
        print("⚠️  WARNING: Rate limiting is partially effective")
    else:
        print("✓  Rate limiting is working effectively")
    
    # Forced reconfigurations
    if forced_reconfigs > normal_reconfigs:
        print("⚠️  CRITICAL: Most reconfigurations are forced (bypassing rate limiting)")
    elif forced_reconfigs > normal_reconfigs * 0.5:
        print("⚠️  WARNING: Many reconfigurations are forced (partially bypassing rate limiting)")
    
    # DNS fetch frequency
    if dns_fetch_stats['avg'] < 60:
        print("⚠️  CRITICAL: DNS entries are fetched too frequently (less than 60s intervals)")
    elif dns_fetch_stats['avg'] < 300:
        print("⚠️  WARNING: DNS entries are fetched somewhat frequently (less than 5m intervals)")
    
    # Reconfiguration frequency
    reconfigs_per_hour = len(reconfig_events)/(duration/3600)
    if reconfigs_per_hour > 30:
        print("⚠️  CRITICAL: Very high reconfiguration frequency (>30/hour)")
    elif reconfigs_per_hour > 10:
        print("⚠️  WARNING: High reconfiguration frequency (>10/hour)")
    
    # DNS fetch after reconfig correlation
    if correlations['reconfig_to_fetch_pct'] > 75:
        print("⚠️  NOTE: DNS fetches frequently occur immediately after reconfigurations")
    
    # Failed delete correlation
    if correlations['delete_to_force_pct'] > 75:
        print("⚠️  NOTE: Failed deletes frequently lead to forced reconfigurations")

# Main execution
if __name__ == "__main__":
    parse_log_file()
    print_summary()
