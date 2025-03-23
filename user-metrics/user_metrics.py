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
DEFAULT_PORT = 9551
DEFAULT_INTERVAL = 300  # seconds
DEFAULT_MINUTES = 10
MAX_CACHE_SIZE = 10000  # Maximum number of IPs to keep in memory

# Global variables to store metrics
unique_ip_count = 0
total_connections = 0
blocked_requests = 0
collection_timestamp = 0
last_processed_position = 0
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

private_networks = [ipaddress.ip_network(net) for net in PRIVATE_NETWORKS]

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

# Connection tracking with TTL
class ConnectionTracker:
    def __init__(self, ttl_minutes, max_entries=MAX_CACHE_SIZE):
        self.connections = {}  # IP -> (count, last_seen)
        self.ttl = ttl_minutes * 60  # Convert to seconds
        self.max_entries = max_entries
        
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
        if len(self.connections) < 1000:
            return
            
        current_time = time.time()
        # More efficient cleanup without building a list
        for ip in list(self.connections.keys()):
            _, last_seen = self.connections[ip]
            if current_time - last_seen > self.ttl:
                del self.connections[ip]
    
    def get_stats(self):
        self.cleanup()
        return len(self.connections), sum(count for count, _ in self.connections.values())

# Don't pre-compute all IPs in private networks
FILTERED_IPS = SYSTEM_IPS | COMMON_DNS

def parse_arguments():
    parser = argparse.ArgumentParser(description='Serve Prometheus metrics for xray_access.log')
    parser.add_argument('--port', '-p', type=int, default=DEFAULT_PORT,
                      help=f'Port to serve metrics on (default: {DEFAULT_PORT})')
    parser.add_argument('--interval', '-i', type=int, default=DEFAULT_INTERVAL,
                      help=f'Collection interval in seconds (default: {DEFAULT_INTERVAL})')
    parser.add_argument('--minutes', '-m', type=int, default=DEFAULT_MINUTES,
                      help=f'Number of minutes to look back (default: {DEFAULT_MINUTES})')
    parser.add_argument('--log-path', '-l', default='/var/log/xray_access.log',
                      help='Path to the xray_access.log file')
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
    """Normalize IP address to standard format."""
    try:
        # Handle IPv6 addresses
        if ':' in ip:
            # Remove brackets if present
            ip = ip.strip('[]')
            # Normalize IPv6 address
            return str(ipaddress.IPv6Address(ip))
        # Handle IPv4 addresses
        return str(ipaddress.IPv4Address(ip))
    except ValueError:
        return None

def is_valid_ip(ip):
    """Check if an IP address is valid (IPv4 or IPv6)."""
    try:
        # Remove brackets if present
        ip = ip.strip('[]')
        # Try IPv6 first
        ipaddress.IPv6Address(ip)
        return True
    except ValueError:
        try:
            # Try IPv4
            ipaddress.IPv4Address(ip)
            return True
        except ValueError:
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
        # Example: 2024/03/22 07:39:53 [Info] [1127] [proxy/xray/inbound01] [tcp] accepted connection from [112.48.152.206]:49228
        # or: 2024/03/22 02:41:18 Info proxy/vless: accepted a new connection from [2a09:dc43:5900:e70f:56ae:d21f:d5a:8bfa]:53518 (direct)
        # New format: 2025/03/23 08:09:56.214805 from 5.123.36.145:42103 accepted tcp:api.ad.intl.xiaomi.com:443 [vless-tcp-tls-direct -> blocked]
        
        # Extract timestamp
        timestamp_match = re.match(r'^(\d{4}/\d{2}/\d{2} \d{2}:\d{2}:\d{2})', line)
        if timestamp_match:
            timestamp_str = timestamp_match.group(1)
            try:
                timestamp = datetime.datetime.strptime(timestamp_str, '%Y/%m/%d %H:%M:%S')
            except ValueError:
                debug_print(f"Failed to parse timestamp: {timestamp_str}")
                return None, None, False
        
        # Check if request was blocked (new format)
        if "-> blocked]" in line:
            is_blocked = True
                
        # Extract IP address - handle both formats
        # First try new format: from 5.123.36.145:42103
        ip_match = re.search(r'from (?:tcp:)?(\d+\.\d+\.\d+\.\d+|\S+):', line)
        if ip_match:
            raw_ip = ip_match.group(1)
            if is_valid_ip(raw_ip):
                ip = normalize_ip(raw_ip)
            else:
                debug_print(f"Invalid IP address found: {raw_ip}")
        else:
            # Try old format: from [112.48.152.206]:49228
            ip_match = re.search(r'from (?:\[([0-9a-fA-F:]+)\]|(\d+\.\d+\.\d+\.\d+)):', line)
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
    """Check if an IP should be filtered out."""
    try:
        # First check direct matches which is faster
        if ip in FILTERED_IPS:
            return True
            
        # Then check network membership for private networks
        try:
            ip_obj = ipaddress.ip_address(ip)
            # Check if in private networks
            for network in private_networks:
                if ip_obj in network:
                    return True
        except ValueError:
            return True  # Invalid IP format
            
        return False
    except Exception as e:
        debug_print(f"Error filtering IP {ip}: {e}")
        return True  # Filter out on error to be safe

def count_unique_ips(log_file_path, minutes_ago, start_position=0):
    """Count unique IP addresses in log file within the specified time window."""
    global last_processed_position
    
    # Calculate the cutoff time
    cutoff_time = datetime.datetime.now() - datetime.timedelta(minutes=minutes_ago)
    debug_print(f"Cutoff time: {cutoff_time}")
    
    # Use connection tracker with TTL
    tracker = ConnectionTracker(minutes_ago)
    
    log_files = find_log_files(log_file_path)
    if not log_files:
        print(f"Error: No log files found matching {log_file_path}")
        return 0, 0, 0, 0
    
    debug_print(f"Found log files: {log_files}")
    
    current_position = start_position
    total_lines = 0
    parsed_lines = 0
    filtered_ips = 0
    blocked_count = 0
    
    # Process only the most recent log file
    current_file = log_files[0][0]
    try:
        print(f"Processing current log file from position {current_position}: {current_file}")
        with open(current_file, 'r', encoding='utf-8', errors='ignore') as f:
            if current_position > 0:
                f.seek(current_position)
                debug_print(f"Seeking to position {current_position}")
            
            # Get current file size
            f.seek(0, 2)
            current_file_size = f.tell()
            f.seek(current_position)
            
            # Process lines directly without buffering all 1000 in memory
            line_buffer = []
            line_count = 0
            for line in f:
                line_count += 1
                
                # Process every 100 lines to avoid memory buildup
                if line_count % 100 == 0:
                    timestamp, ip, is_blocked = parse_log_line(line)
                    if timestamp and ip and timestamp >= cutoff_time:
                        parsed_lines += 1
                        if is_blocked:
                            blocked_count += 1
                        if not is_filtered_ip(ip):
                            tracker.add_connection(ip)
                        else:
                            filtered_ips += 1
                else:
                    line_buffer.append(line)
                    
                # Process buffer periodically
                if len(line_buffer) >= 100:
                    for buffered_line in line_buffer:
                        timestamp, ip, is_blocked = parse_log_line(buffered_line)
                        if timestamp and ip and timestamp >= cutoff_time:
                            parsed_lines += 1
                            if is_blocked:
                                blocked_count += 1
                            if not is_filtered_ip(ip):
                                tracker.add_connection(ip)
                            else:
                                filtered_ips += 1
                    line_buffer = []
                    
                # Update total processed
                total_lines += 1
                
                # Periodic cleanup to keep memory usage in check
                if total_lines % 10000 == 0:
                    tracker.cleanup()
            
            # Process any remaining lines in buffer
            for buffered_line in line_buffer:
                timestamp, ip, is_blocked = parse_log_line(buffered_line)
                if timestamp and ip and timestamp >= cutoff_time:
                    parsed_lines += 1
                    if is_blocked:
                        blocked_count += 1
                    if not is_filtered_ip(ip):
                        tracker.add_connection(ip)
                    else:
                        filtered_ips += 1
            
            last_processed_position = current_file_size
            print(f"Updated last_processed_position to {last_processed_position}")
            
    except Exception as e:
        print(f"Error reading current log file: {e}")
        last_processed_position = 0
    
    unique_count, total_count = tracker.get_stats()
    
    print(f"Processing summary: {unique_count} unique IPs, {total_count} total connections, {blocked_count} blocked requests")
    print(f"  Total lines read: {total_lines}")
    print(f"  Successfully parsed entries: {parsed_lines}")
    print(f"  Filtered IPs: {filtered_ips}")
    print(f"  Last processed position: {last_processed_position}")
    
    return unique_count, total_count, blocked_count, last_processed_position

# Store command line args globally to avoid repeated parsing
global_args = None

def update_metrics(minutes_ago):
    """Update global metrics from log file."""
    global unique_ip_count, total_connections, blocked_requests
    global collection_timestamp, last_processed_position
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
        unique_ip_count, total_connections, blocked_requests, last_processed_position = count_unique_ips(
            log_file_path, minutes_ago, last_processed_position
        )
        collection_timestamp = time.time()
        
        # Print explicit values for debugging
        print(f"Updated raw metrics values: unique_ip_count={unique_ip_count}, total_connections={total_connections}, blocked_requests={blocked_requests}")
        print(f"Updated metrics: {unique_ip_count} unique IPs, {total_connections} total connections, {blocked_requests} blocked requests")
        print(f"Last processed position: {last_processed_position}")
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
            unique_count, total_count, blocked_count, _ = count_unique_ips(global_args.log_path, global_args.minutes)
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
