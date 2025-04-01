#!/usr/bin/env python3

import sys
import re
import datetime
import time
import argparse
import ipaddress
from collections import defaultdict
from http.server import HTTPServer, BaseHTTPRequestHandler
import threading
import gzip
import os

# Default values
DEFAULT_LOG_PATH = '/var/log/compassvpn/xray_access.log'
DEFAULT_PORT = 9551
DEFAULT_INTERVAL = 300  # seconds
DEFAULT_MINUTES = 2
MAX_CACHE_SIZE = 5000  # Maximum number of IPs to keep in memory

# Global variables to store metrics
unique_ip_count = 0
total_connections = 0
blocked_requests = 0
collection_timestamp = 0
last_processed_position = 0
last_processed_inode = 0 # Added inode tracking
debug_mode = False

# Known system IPs and networks to filter out
SYSTEM_IPS = {
    '127.0.0.1',
    'localhost',
    '::1'
}

# Private IP networks to filter
PRIVATE_NETWORKS = [
    '10.0.0.0/8',
    '172.16.0.0/12',
    '192.168.0.0/16',
    'fc00::/7',  # IPv6 unique local addresses
    'fe80::/10'  # IPv6 link-local addresses
]

# Common DNS server IPs to filter out
COMMON_DNS = {
    # Cloudflare DNS
    '1.1.1.1',
    '1.0.0.1',
    '2606:4700:4700::1111',
    '2606:4700:4700::1001',
    '1.1.1.2',
    '1.0.0.2',
    '2606:4700:4700::1112',
    '2606:4700:4700::1002',
    '1.1.1.3',
    '1.0.0.3',
    '2606:4700:4700::1113',
    '2606:4700:4700::1003',

    # Google DNS
    '8.8.8.8',
    '8.8.4.4',
    '2001:4860:4860::8888',
    '2001:4860:4860::8844',
    
    # Quad9 DNS
    '9.9.9.9',
    '149.112.112.112',
    '2620:fe::fe',
    '2620:fe::9',
    '9.9.9.10',
    '149.112.112.10',
    '2620:fe::10',
    '2620:fe::fe:10',
    '9.9.9.11',
    '149.112.112.11',
    '2620:fe::11',
    '2620:fe::fe:11',

    # Level3 DNS
    '209.244.0.3',
    '209.244.0.4',
    '4.2.2.4',
    '4.2.2.2',
    
    # AdGuard DNS
    '94.140.14.14',
    '94.140.15.15',
    '2a10:50c0::ad1:ff',
    '2a10:50c0::ad2:ff',
    '94.140.14.140',
    '94.140.14.141',
    '2a10:50c0::1:ff',
    '2a10:50c0::2:ff',
    '94.140.14.15',
    '94.140.15.16',
    '2a10:50c0::bad1:ff',
    '2a10:50c0::bad2:ff',

    # DNS0.eu
    '193.110.81.0',
    '185.253.5.0',
    '2a0f:fc80::',
    '2a0f:fc81::',
    
    # ControlD
    '76.76.2.2',
    '76.76.10.10',
    '2606:1a40::2',
    '2606:1a40::10',
    '76.76.2.0',
    '76.76.10.0',
    '2606:1a40::',
    '2606:1a40:1::',
    '76.76.2.1',
    '76.76.10.1',
    '2606:1a40::1',
    '2606:1a40:1::1',
    '76.76.2.3',
    '76.76.10.3',
    '2606:1a40::3',
    '2606:1a40:1::3',
    '76.76.2.4',
    '76.76.10.4',
    '2606:1a40::4',
    '2606:1a40:1::4',
    '76.76.2.5',
    '76.76.10.5',
    '2606:1a40::5',
    '2606:1a40:1::5',
    
    #AliDNS
    '223.5.5.5',
    '223.6.6.6',
    '2400:3200::1',
    '2400:3200:baba::1',
    

    # GcoreDNS
    '95.85.95.85',
    '95.85.95.86',
    '2a03:90c0:999d::1',
    '2a03:90c0:999d::2',
    
    # CleanBrowsing
    '185.228.168.9',
    '185.228.169.9',
    '2a0d:2a00:1::2',
    '2a0d:2a00:2::2',
    
    # OpenDNS
    '208.67.222.222',
    '208.67.220.220',
    '208.67.222.123',
    '208.67.220.123',
    '2620:119:35::35',
    '2620:119:53::53',
    '2620:0:ccc::2',
    '2620:0:ccd::2',
    
    # Yandex DNS
    '77.88.8.8',
    '77.88.8.88',
    '77.88.8.7',
    '77.88.8.77',
    '2a02:6b8::feed:0ff',
    '2a02:6b8::feed:bad',
    '2a02:6b8::feed:0fe',
    '2a02:6b8::feed:bad',
    
    # UltraDNS
    '64.6.64.6',
    '156.154.70.2',
    '64.6.65.6',
    '156.154.71.2',
    '2620:74:1b::1:1',
    '2610:a1:1018::2',
    '2620:74:1b::1:2',
    '2610:a1:1018::3',
}

# Precompile regular expressions for better performance
TIMESTAMP_REGEX = re.compile(r'^(\d{4}/\d{2}/\d{2} \d{2}:\d{2}:\d{2})')
NEW_FORMAT_IP_REGEX = re.compile(r'from (?:tcp:)?(\d+\.\d+\.\d+\.\d+|\S+):')
OLD_FORMAT_IP_REGEX = re.compile(r'from (?:\[([0-9a-fA-F:]+)\]|(\d+\.\d+\.\d+\.\d+)):')

# Create private_networks as IP network objects once
private_networks = [ipaddress.ip_network(net) for net in PRIVATE_NETWORKS]

# Pre-combine all filtered IPs for faster lookup
FILTERED_IPS = SYSTEM_IPS | COMMON_DNS

# Cache for IP address normalization and validation
IP_CACHE = {}
# Cache for is_filtered_ip results
FILTER_CACHE = {}

# Connection tracking with TTL
class ConnectionTracker:
    def __init__(self, ttl_minutes, max_entries=MAX_CACHE_SIZE):
        self.connections = {}  # IP -> (count, last_seen)
        self.ttl = ttl_minutes * 60  # Convert to seconds
        self.max_entries = max_entries
        self.last_cleanup = time.time()
        
    def add_connection(self, ip):
        # Enforce size limit
        if len(self.connections) >= self.max_entries and ip not in self.connections:
            # Remove oldest entry if at capacity
            oldest_ip = min(self.connections.items(), key=lambda x: x[1][1])[0]
            del self.connections[oldest_ip]
            
        current_time = time.time()
        if ip in self.connections:
            count, _ = self.connections[ip]
            self.connections[ip] = (count + 1, current_time)
        else:
            self.connections[ip] = (1, current_time)
    
    def cleanup(self):
        # Only clean if more than 1000 entries to avoid frequent cleanups
        # And only if it's been at least 30 seconds since last cleanup
        current_time = time.time()
        if len(self.connections) < 1000 or current_time - self.last_cleanup < 30:
            return
            
        # More efficient cleanup without building a list
        for ip in list(self.connections.keys()):
            _, last_seen = self.connections[ip]
            if current_time - last_seen > self.ttl:
                del self.connections[ip]
        
        self.last_cleanup = current_time
    
    def get_stats(self):
        self.cleanup()
        return len(self.connections), sum(count for count, _ in self.connections.values())

def parse_arguments():
    parser = argparse.ArgumentParser(description='Serve Prometheus metrics for xray_access.log')
    parser.add_argument('--port', '-p', type=int, default=DEFAULT_PORT,
                      help=f'Port to serve metrics on (default: {DEFAULT_PORT})')
    parser.add_argument('--interval', '-i', type=int, default=DEFAULT_INTERVAL,
                      help=f'Collection interval in seconds (default: {DEFAULT_INTERVAL})')
    parser.add_argument('--minutes', '-m', type=int, default=DEFAULT_MINUTES,
                      help=f'Number of minutes to look back (default: {DEFAULT_MINUTES})')
    parser.add_argument('--log-path', '-l', default=DEFAULT_LOG_PATH,
                      help=f'Path to the xray_access.log file (default: {DEFAULT_LOG_PATH})')
    parser.add_argument('--debug', '-d', action='store_true',
                      help='Enable debug mode for troubleshooting')
    parser.add_argument('--test', '-t', action='store_true',
                      help='Test log parsing and then exit')
    return parser.parse_args()

def debug_print(message):
    """Print debug messages if debug mode is enabled."""
    if debug_mode:
        print(f"[DEBUG] {message}")

def normalize_ip(ip):
    """Normalize IP address to standard format with caching."""
    if ip in IP_CACHE:
        return IP_CACHE[ip]
        
    try:
        # Handle IPv6 addresses
        if ':' in ip:
            # Remove brackets if present
            ip = ip.strip('[]')
            # Normalize IPv6 address
            normalized = str(ipaddress.IPv6Address(ip))
            IP_CACHE[ip] = normalized
            return normalized
        # Handle IPv4 addresses
        normalized = str(ipaddress.IPv4Address(ip))
        IP_CACHE[ip] = normalized
        return normalized
    except ValueError:
        IP_CACHE[ip] = None
        return None

def is_valid_ip(ip):
    """Check if an IP address is valid (IPv4 or IPv6) with caching."""
    if ip in IP_CACHE:
        return IP_CACHE[ip] is not None
        
    try:
        # Remove brackets if present
        ip = ip.strip('[]')
        # Try IPv6 first
        ipaddress.IPv6Address(ip)
        IP_CACHE[ip] = ip
        return True
    except ValueError:
        try:
            # Try IPv4
            ipaddress.IPv4Address(ip)
            IP_CACHE[ip] = ip
            return True
        except ValueError:
            IP_CACHE[ip] = None
            return False

def find_log_files(base_log_path):
    """Find all relevant log files, including rotated ones."""
    log_dir = os.path.dirname(base_log_path)
    log_basename = os.path.basename(base_log_path)
    result = []
    
    # If directory is empty, use current directory
    if not log_dir:
        log_dir = '.'
    
    # Check if the base log file exists
    if os.path.isfile(base_log_path):
        result.append((base_log_path, False))
    
    # Check for rotated and compressed files
    if os.path.isdir(log_dir):
        for filename in os.listdir(log_dir):
            file_path = os.path.join(log_dir, filename)
            # Look for files like xray_access.log.1, xray_access.log.2.gz, etc.
            if filename.startswith(log_basename) and os.path.isfile(file_path):
                is_compressed = filename.endswith(".gz")
                # Only add if not the base log file (which we've already added)
                if file_path != base_log_path:
                    result.append((file_path, is_compressed))
    
    # Sort by modification time, newest first
    result.sort(key=lambda x: os.path.getmtime(x[0]), reverse=True)
    return result

def open_log_file(file_path, is_compressed):
    """Open a log file, handling compressed files."""
    if is_compressed:
        return gzip.open(file_path, 'rt', encoding='utf-8', errors='ignore')
    else:
        return open(file_path, 'r', encoding='utf-8', errors='ignore')

def parse_log_line(line):
    """Parse a log line and extract timestamp, IP, protocol, and routing information."""
    timestamp = None
    ip = None
    is_blocked = False

    try:
        # Check if request was blocked (new format) - this is a fast check
        if "-> blocked]" in line:
            is_blocked = True
        
        # Extract timestamp
        timestamp_match = TIMESTAMP_REGEX.match(line)
        if timestamp_match:
            timestamp_str = timestamp_match.group(1)
            try:
                timestamp = datetime.datetime.strptime(timestamp_str, '%Y/%m/%d %H:%M:%S')
            except ValueError:
                debug_print(f"Failed to parse timestamp: {timestamp_str}")
                return None, None, False
                
        # Extract IP address - handle both formats
        # First try new format: from 5.123.36.145:42103
        ip_match = NEW_FORMAT_IP_REGEX.search(line)
        if ip_match:
            raw_ip = ip_match.group(1)
            if is_valid_ip(raw_ip):
                ip = normalize_ip(raw_ip)
            else:
                debug_print(f"Invalid IP address found: {raw_ip}")
        else:
            # Try old format: from [112.48.152.206]:49228
            ip_match = OLD_FORMAT_IP_REGEX.search(line)
            if ip_match:
                # Group 1 is IPv6, Group 2 is IPv4
                raw_ip = ip_match.group(1) if ip_match.group(1) else ip_match.group(2)
                if is_valid_ip(raw_ip):
                    ip = normalize_ip(raw_ip)
                else:
                    debug_print(f"Invalid IP address found: {raw_ip}")
        
        return timestamp, ip, is_blocked
    except Exception as e:
        debug_print(f"Error parsing log line: {e}\nLine: {line}")
        return None, None, False

def is_filtered_ip(ip):
    """Check if an IP should be filtered out with caching."""
    if ip in FILTER_CACHE:
        return FILTER_CACHE[ip]
        
    try:
        # First check direct matches which is faster
        if ip in FILTERED_IPS:
            FILTER_CACHE[ip] = True
            return True
            
        # Then check network membership for private networks
        try:
            ip_obj = ipaddress.ip_address(ip)
            # Check if in private networks
            for network in private_networks:
                if ip_obj in network:
                    FILTER_CACHE[ip] = True
                    return True
        except ValueError:
            FILTER_CACHE[ip] = True
            return True  # Invalid IP format
            
        FILTER_CACHE[ip] = False
        return False
    except Exception as e:
        debug_print(f"Error filtering IP {ip}: {e}")
        FILTER_CACHE[ip] = True
        return True  # Filter out on error to be safe

def count_unique_ips(log_file_path, minutes_ago):
    """Count unique IP addresses in log file within the specified time window using incremental processing."""
    global last_processed_position, last_processed_inode

    cutoff_time = datetime.datetime.now() - datetime.timedelta(minutes=minutes_ago)
    debug_print(f"Cutoff time: {cutoff_time}")

    tracker = ConnectionTracker(minutes_ago)
    parsed_lines = 0
    filtered_ips = 0
    blocked_count = 0
    current_position = 0

    log_files = find_log_files(log_file_path)
    if not log_files:
        print(f"Error: No log files found matching {log_file_path}")
        return 0, 0, 0

    current_file_path, is_compressed = log_files[0]
    debug_print(f"Processing log file: {current_file_path} (compressed: {is_compressed})")

    try:
        # Check for log rotation using inode
        current_inode = os.stat(current_file_path).st_ino
        if current_inode != last_processed_inode:
            debug_print(f"Log file rotated (inode changed from {last_processed_inode} to {current_inode}). Resetting position.")
            last_processed_position = 0
            last_processed_inode = current_inode
        
        file_size = os.path.getsize(current_file_path)
        # Handle case where file shrunk (e.g., log cleared)
        if last_processed_position > file_size:
             debug_print(f"Log file shrunk (size {file_size} < last position {last_processed_position}). Resetting position.")
             last_processed_position = 0

        # Open the log file (handles compressed or plain text)
        with open_log_file(current_file_path, is_compressed) as f:
            # Seek to the last known position
            if last_processed_position > 0:
                f.seek(last_processed_position)
                debug_print(f"Seeking to position: {last_processed_position}")

            # Read and process new lines
            for line in f:
                timestamp, ip, is_blocked = parse_log_line(line)
                if timestamp and ip and timestamp >= cutoff_time:
                    parsed_lines += 1
                    if is_blocked:
                        blocked_count += 1
                    if not is_filtered_ip(ip):
                        tracker.add_connection(ip)
                    else:
                        filtered_ips += 1
            
            # Update position to the end of the file
            current_position = f.tell()

    except FileNotFoundError:
        print(f"Error: Log file {current_file_path} not found during processing.")
        last_processed_position = 0
        last_processed_inode = 0
        return 0, 0, 0
    except Exception as e:
        print(f"Error processing log file {current_file_path}: {e}")
        # Attempt to reset position on error, might recover on next run
        last_processed_position = 0
        last_processed_inode = 0 # Reset inode as well
        return 0, 0, 0 # Return zero counts for this run

    # Update global position only after successful processing of the current file chunk
    last_processed_position = current_position

    unique_count, total_count = tracker.get_stats()

    print(f"Processing summary: {unique_count} unique IPs, {total_count} total connections, {blocked_count} blocked requests")
    print(f"  Successfully parsed {parsed_lines} new entries since last check.")
    print(f"  Filtered IPs in new entries: {filtered_ips}")
    print(f"  Current log file: {current_file_path}")
    print(f"  Last processed position: {last_processed_position}")
    print(f"  Last processed inode: {last_processed_inode}")

    # Clear caches periodically to avoid memory growth
    if len(IP_CACHE) > 10000:
        IP_CACHE.clear()
        debug_print("Cleared IP_CACHE")
    if len(FILTER_CACHE) > 10000:
        FILTER_CACHE.clear()
        debug_print("Cleared FILTER_CACHE")

    # Return counts for this interval only
    return unique_count, total_count, blocked_count

# Store command line args globally to avoid repeated parsing
global_args = None

def update_metrics(minutes_ago):
    """Update global metrics from log file."""
    global unique_ip_count, total_connections, blocked_requests
    global collection_timestamp, last_processed_position # Keep last_processed_position for context, but it's not returned by count_unique_ips anymore
    global global_args
    
    # Only parse arguments once
    if global_args is None:
        global_args = parse_arguments()
    
    log_file_path = global_args.log_path
    
    # Check if log file exists
    print(f"Checking log file: {log_file_path}")
    if not os.path.exists(log_file_path):
        print(f"ERROR: Log file {log_file_path} does not exist!")
        # List available files in /var/log to help troubleshoot
        log_dir = os.path.dirname(log_file_path)
        print(f"Files in {log_dir}:")
        try:
            for f in os.listdir(log_dir):
                if "xray" in f:
                    print(f"  - {f}")
        except Exception as e:
            print(f"  Error listing directory: {e}")
    else:
        print(f"Log file exists: {log_file_path}, size: {os.path.getsize(log_file_path)} bytes")
    
    # Update metrics
    try:
        # last_processed_position is now updated globally inside count_unique_ips
        unique_count, total_count, blocked_req = count_unique_ips(
            log_file_path, minutes_ago # Remove last_processed_position from args
        )
        # NOTE: The ConnectionTracker now manages the time window.
        # The global counts should reflect the state within the tracker's window.
        unique_ip_count = unique_count
        total_connections = total_count
        blocked_requests = blocked_req # Assuming count_unique_ips now correctly tracks blocked requests within the window
        
        collection_timestamp = time.time()
        
        # Print explicit values for debugging
        print(f"Updated metrics: unique_ip_count={unique_ip_count}, total_connections={total_connections}, blocked_requests={blocked_requests}")
        # The 'last_processed_position' printed here reflects the end of the *last read*, not directly related to the counts returned
        print(f"Log processing state: last_processed_position={last_processed_position}, last_processed_inode={last_processed_inode}")
    except Exception as e:
        print(f"Error updating metrics: {e}")
        import traceback
        traceback.print_exc()

def generate_metrics():
    """Generate Prometheus metrics from collected data."""
    # Get donor value from environment variable, with fallback
    donor_value = os.environ.get('DONOR', 'vmvm')
    
    metrics = []
    
    # Add metric headers with HELP and TYPE
    metrics.append("# HELP xray_unique_users Number of unique users in the specified time window")
    metrics.append("# TYPE xray_unique_users gauge")
    metrics.append(f"xray_unique_users{{donor=\"{donor_value}\"}} {unique_ip_count}")
    
    metrics.append("# HELP xray_total_connections Total number of connections in the specified time window")
    metrics.append("# TYPE xray_total_connections gauge")
    metrics.append(f"xray_total_connections{{donor=\"{donor_value}\"}} {total_connections}")
    
    # Add new metrics for blocked requests
    metrics.append("# HELP xray_blocked_requests Number of blocked requests in the specified time window")
    metrics.append("# TYPE xray_blocked_requests gauge")
    metrics.append(f"xray_blocked_requests{{donor=\"{donor_value}\"}} {blocked_requests}")
    
    # Add percentage of blocked requests
    blocked_percentage = 0
    if total_connections > 0:
        blocked_percentage = (blocked_requests / total_connections) * 100
    
    metrics.append("# HELP xray_blocked_percentage Percentage of blocked requests relative to total connections")
    metrics.append("# TYPE xray_blocked_percentage gauge")
    metrics.append(f"xray_blocked_percentage{{donor=\"{donor_value}\"}} {blocked_percentage:.2f}")
    
    result = "\n".join(metrics)
    print(f"Generated metrics: {result}")  # Debug print to see what's being generated
    return result

class MetricsHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        # Always return metrics for any path
        print(f"Received GET request from {self.client_address[0]} for path: {self.path}")
        
        self.send_response(200)
        self.send_header('Content-Type', 'text/plain')
        self.end_headers()
        metrics_output = generate_metrics()
        self.wfile.write(metrics_output.encode('utf-8'))
        print(f"Sent metrics response to {self.client_address[0]}")
    
    def log_message(self, format, *args):
        # Log all requests during troubleshooting
        print(f"{self.address_string()} - {format % args}")

def metrics_collector(interval, minutes_ago):
    """Background thread that updates metrics at regular intervals."""
    last_activity = time.time()
    while True:
        try:
            current_time = time.time()
            # Adaptive interval based on activity
            if current_time - last_activity > 300:  # 5 minutes of inactivity
                time.sleep(interval * 2)  # Double the interval
            else:
                time.sleep(interval)
            
            update_metrics(minutes_ago)
            last_activity = current_time
            
        except Exception as e:
            print(f"Error updating metrics: {e}")
            time.sleep(interval)  # Wait before retrying

def main():
    global debug_mode, global_args
    
    global_args = parse_arguments()
    debug_mode = global_args.debug
    
    if debug_mode:
        print("Debug mode enabled")
        print(f"Log path: {global_args.log_path}")
        print(f"Looking back: {global_args.minutes} minutes")
        print(f"Update interval: {global_args.interval} seconds")
    
    # Test mode - parse log file and exit
    if global_args.test:
        print(f"Testing log parsing from {global_args.log_path}...")
        try:
            # Need to initialize inode/position for test mode
            global last_processed_inode, last_processed_position
            last_processed_inode = 0
            last_processed_position = 0
            unique_count, total_count, blocked_count = count_unique_ips(global_args.log_path, global_args.minutes)
            print(f"\nTest results:")
            print(f"  Unique users: {unique_count}")
            print(f"  Total connections: {total_count}")
            print(f"  Blocked requests: {blocked_count}")
            sys.exit(0)
        except Exception as e:
            print(f"Error during test: {e}")
            sys.exit(1)
    
    # Initial metrics update
    try:
        update_metrics(global_args.minutes)
    except Exception as e:
        print(f"Initial metrics update failed: {e}")
    
    # Start background metrics collector
    collector_thread = threading.Thread(
        target=metrics_collector, 
        args=(global_args.interval, global_args.minutes),
        daemon=True
    )
    collector_thread.start()
    
    # Start HTTP server
    server_address = ('', global_args.port)
    httpd = HTTPServer(server_address, MetricsHandler)
    print(f"Starting metrics server on port {global_args.port}")
    print(f"Collecting metrics every {global_args.interval} seconds, looking back {global_args.minutes} minutes")
    httpd.serve_forever()

if __name__ == "__main__":
    main() 
