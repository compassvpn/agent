#!/bin/bash

# Configuration variables
DNS_SERVERS=("1.1.1.2" "127.0.0.53")
REQUIRED_PORTS=("80" "8080" "443" "2053" "8443")
SYSCTL_CONF_PATH="/etc/sysctl.d/99-compassvpn.conf"

# Paths
HOST_PATH="/etc/hosts"
DNS_PATH="/etc/resolv.conf"
PROF_PATH="/etc/profile"
SSH_PATH="/etc/ssh/sshd_config"
COMPASSVPN_LOG_PATH="/var/log/compassvpn/"

# Check if a command exists
command_exists() {
    command -v "$1" >/dev/null 2>&1
}

# Variable to track OpenVZ detection
IS_OPENVZ=0

# Check Root Function
check_root() {
    if [[ "$EUID" -ne 0 ]]; then
        echo "Error: You must run this script as root!"
        exit 1
    fi
}

# Check if running on a supported system
check_system() {
    if [ ! -f /etc/os-release ]; then
        echo "Error: Could not detect system type."
        exit 1
    fi

    if ! grep -qi "ubuntu\|debian" /etc/os-release; then
        echo "Error: This script is only supported on Debian/Ubuntu systems."
        exit 1
    fi
}

# Check for OpenVZ virtualization
check_openvz() {
    if [ -f /proc/user_beancounters ]; then
        IS_OPENVZ=1
        echo "Warning: OpenVZ detected. This virtualization has known limitations."
        sleep 3
    fi
}

# Fix Hosts file
fix_etc_hosts() { 
    if [ ! -f "$HOST_PATH" ]; then
        echo "Error: Hosts file not found at $HOST_PATH."
        return 1
    fi

    cp "$HOST_PATH" /etc/hosts.bak
    chmod 644 /etc/hosts.bak
    if [ $? -ne 0 ]; then
        echo "Error: Failed to backup hosts file."
        return 1
    fi

    if ! grep -q "$(hostname)" "$HOST_PATH"; then
        echo "127.0.1.1 $(hostname)" | sudo tee -a "$HOST_PATH" > /dev/null
        echo "Hosts file updated."
    fi
}

# Fix DNS Temporarily
fix_dns() {
    if [ ! -f "$DNS_PATH" ]; then
        echo "Error: resolv.conf file not found at $DNS_PATH."
        return 1
    fi

    cp "$DNS_PATH" /etc/resolv.conf.bak
    chmod 644 /etc/resolv.conf.bak
    if [ $? -ne 0 ]; then
        echo "Error: Failed to backup resolv.conf file."
        return 1
    fi

    # Test DNS servers before applying
    for dns in "${DNS_SERVERS[@]}"; do
        if ! ping -c 1 -W 1 "$dns" >/dev/null 2>&1; then
            echo "Warning: DNS server $dns is not responding."
        fi
    done

    sed -i '/nameserver/d' "$DNS_PATH"
    for dns in "${DNS_SERVERS[@]}"; do
        echo "nameserver $dns" >> "$DNS_PATH"
    done

    echo "DNS settings updated."
}

# Set the server TimeZone to UTC
set_timezone() {
    if ! command_exists timedatectl; then
        echo "Error: timedatectl command not found."
        return 1
    fi

    sudo timedatectl set-timezone "UTC"
    if [ $? -ne 0 ]; then
        echo "Error: Failed to set timezone to UTC."
        return 1
    fi
    echo "Timezone set to UTC."
}

# Update & Install necessary packages
install_base_packages() {
    echo "Installing base packages..."
    apt-get update -qq
    apt-get install -yqq curl wget sudo coreutils iproute2 lsof
    echo "Base packages installed."
}

# SYSCTL Optimization
sysctl_optimizations() {
    if [ "$IS_OPENVZ" -eq 1 ]; then
        echo "Skipping sysctl optimizations due to OpenVZ detection."
        return 0
    fi

    echo "Optimizing network settings..."

    # Create sysctl.d directory if it doesn't exist
    mkdir -p /etc/sysctl.d

    # Add new settings to a dedicated file
    cat <<EOF > "$SYSCTL_CONF_PATH"
fs.file-max = 67108864
net.core.default_qdisc = fq
net.core.optmem_max = 262144
net.core.rmem_max = 33554432
net.core.wmem_max = 33554432
net.ipv4.tcp_congestion_control = bbr
net.ipv4.tcp_max_syn_backlog = 10240
net.ipv4.tcp_fin_timeout = 25
net.core.netdev_max_backlog = 32768
net.netfilter.nf_conntrack_max = 1048576
net.netfilter.nf_conntrack_buckets = 262144
EOF

    # Apply settings
    sudo sysctl --system >/dev/null 2>&1
    echo "Network settings optimized."
}

# Handle firewalld if installed
handle_firewalld() {
    if command_exists firewall-cmd; then
        echo "Removing firewalld..."
        systemctl stop firewalld
        systemctl disable firewalld
        apt-get purge -y firewalld
    fi
}

# Install UFW if not already installed
install_ufw() {
    if ! command_exists ufw; then
        echo "Installing UFW..."
        apt-get update -qq
        apt-get install -qqy ufw
        
        if ! command_exists ufw; then
            echo "Error: Failed to install UFW."
            exit 1
        fi
    fi
}

# Find SSH port and store it in SSH_PORT variable
find_ssh_port() {
    # 1. Try active detection first (what is actually listening)
    SSH_PORT=$(ss -tlnp | grep -oP '(?<=:)\d+(?=.*sshd)' | head -n1 || echo "")
    
    if [ -n "$SSH_PORT" ]; then
        echo "Active SSH port: $SSH_PORT"
    else
        # 2. Fallback to config parsing if active detection fails
        echo "Active detection failed. Parsing $SSH_PATH..."
        if [ -e "$SSH_PATH" ]; then
            SSH_PORT=$(grep -oP '^Port\s+\K\d+' "$SSH_PATH" | head -n1 || echo "")
        fi
        
        # 3. Final default to 22
        if [ -z "$SSH_PORT" ]; then
            SSH_PORT=22
            echo "SSH port not detected. Defaulting to: $SSH_PORT"
        else
            echo "SSH port from config: $SSH_PORT"
        fi
    fi
}

# Optimize UFW configuration
optimize_ufw() {
    if [ -f /etc/default/ufw ]; then
        sed -i 's+/etc/ufw/sysctl.conf+/etc/sysctl.conf+gI' /etc/default/ufw 2>/dev/null
    fi
}

# Configure UFW rules
configure_ufw() {
    # Reset any existing rules
    ufw --force reset >/dev/null 2>&1

    # Set default policies
    ufw default deny incoming >/dev/null 2>&1
    ufw default allow outgoing >/dev/null 2>&1

    # Allow SSH port
    ufw allow "$SSH_PORT/tcp" >/dev/null 2>&1

    # Allow required ports from array (both TCP and UDP)
    for port in "${REQUIRED_PORTS[@]}"; do
        ufw allow "$port/tcp" >/dev/null 2>&1
        ufw allow "$port/udp" >/dev/null 2>&1
    done

    # Enable UFW
    echo "y" | ufw enable >/dev/null 2>&1
}

# Setup CompassVPN log directory
setup_compassvpn_logs() {
    echo "Setting up log directory..."

    # Create the log directory if it doesn't exist
    if [ ! -d "$COMPASSVPN_LOG_PATH" ]; then
        echo "Creating log directory at $COMPASSVPN_LOG_PATH."
        mkdir -p "$COMPASSVPN_LOG_PATH"
    fi

    # Set appropriate permissions (Prevent world-read/write)
    chmod 750 "$COMPASSVPN_LOG_PATH"

    # Set ownership to root:root (standard for system logs)
    chown root:root "$COMPASSVPN_LOG_PATH"

    # Create log files and set permissions to 640 (Read only for owner/group)
    echo "Creating log files..."
    local logs=("nginx_access.log" "nginx_error.log" "xray_access.log" "xray_error.log" "xray.log" "debug.log")
    for log in "${logs[@]}"; do
        touch "$COMPASSVPN_LOG_PATH/$log"
        chmod 640 "$COMPASSVPN_LOG_PATH/$log"
    done

    # Setup standard Nginx error log path
    echo "Setting up Nginx error log..."
    mkdir -p /var/log/nginx
    touch /var/log/nginx/error.log
    chmod 640 /var/log/nginx/error.log

    echo "Log setup completed."
}

# Configure logrotate for CompassVPN logs
setup_logrotate_for_compassvpn() {
    echo "Configuring logrotate..."

    # Ensure logrotate is installed
    if ! command_exists logrotate; then
        apt-get update -qq
        apt-get install -yqq logrotate
    fi

    local lr_file="/etc/logrotate.d/compassvpn"
    cat > "$lr_file" <<'EOF'
/var/log/compassvpn/*.log {
    size 500M
    rotate 2
    compress
    delaycompress
    missingok
    notifempty
    copytruncate
    dateext
    dateformat -%Y%m%d-%s
}
EOF

    # Enable systemd timer if available; otherwise rely on cron.daily
    if command_exists systemctl && systemctl list-unit-files | grep -q '^logrotate.timer'; then
        systemctl enable --now logrotate.timer >/dev/null 2>&1 || true
    fi

    # Run once to validate config
    logrotate -f /etc/logrotate.conf >/dev/null 2>&1 || true
    echo "Logrotate configured."
}

# Check if required ports are in use
check_required_ports() {
    local conflict_found=0

    for port in "${REQUIRED_PORTS[@]}"; do
        # Use ss to check for listening sockets on the current TCP port
        local listening_process
        listening_process=$(ss -tlpn "sport = :$port" | grep LISTEN || true)

        if [ -n "$listening_process" ]; then
            conflict_found=1
            echo "Error: Port $port is already in use."
            # Attempt to extract process information more reliably
            local pid
            pid=$(echo "$listening_process" | grep -oP 'pid=\K\d+')
            if [ -n "$pid" ]; then
                local process_name
                process_name=$(ps -p "$pid" -o comm=)
                echo "Process: $process_name (PID: $pid)"
            fi
            exit 1
        fi
    done

    if [ "$conflict_found" -eq 0 ]; then
        echo "All required ports are free."
    fi
}

# Main execution
echo
echo "Preparing the VM..."
echo

# Define the sequence of operations
declare -A STEP_NAMES
STEP_NAMES=(
    [check_root]="Checking root privileges"
    [check_system]="Checking system compatibility"
    [install_base_packages]="Installing base packages"
    [check_openvz]="Checking virtualization type"
    [check_required_ports]="Checking required ports"
    [fix_etc_hosts]="Configuring hosts file"
    [fix_dns]="Configuring DNS servers"
    [set_timezone]="Setting system timezone"
    [sysctl_optimizations]="Applying network optimizations"
    [handle_firewalld]="Removing conflicting firewalls"
    [install_ufw]="Installing UFW"
    [find_ssh_port]="Detecting SSH port"
    [optimize_ufw]="Optimizing UFW configuration"
    [configure_ufw]="Configuring firewall rules"
    [setup_compassvpn_logs]="Setting up log directories"
    [setup_logrotate_for_compassvpn]="Configuring log rotation"
)

STEPS=(
    check_root
    check_system
    install_base_packages
    check_openvz
    check_required_ports
    fix_etc_hosts
    fix_dns
    set_timezone
    sysctl_optimizations
    handle_firewalld
    install_ufw
    find_ssh_port
    optimize_ufw
    configure_ufw
    setup_compassvpn_logs
    setup_logrotate_for_compassvpn
)

# Execute the sequence with defined intervals
for step in "${STEPS[@]}"; do
    echo "Step: ${STEP_NAMES[$step]}"
    if ! $step; then
        echo "Error: ${STEP_NAMES[$step]} failed."
        echo
        exit 1
    fi
    echo
    sleep 0.5
done

echo
echo "VM is ready for bootstrapping."
echo
exit 0
