#!/bin/bash
# This script sets up a firewall using nftables and generates a dynamic fail2ban configuration file.
# It checks for firewalld and ufw, removes/disables them if installed, then applies the nftables config.
# It dynamically detects the SSH port from /etc/ssh/sshd_config and uses it in both the nftables configuration and the fail2ban jail configuration.

# Paths & Variables
CONFIG_FILE="/etc/nftables.conf"
SSH_CONFIG="/etc/ssh/sshd_config"
SSH_PORT=""
FAIL2BAN_CONFIG="./fail2ban/jail.local"  # Local file that is mounted into the fail2ban container

# Function to check and remove firewalld if installed & disable ufw
remove_firewalld() {
    # Check and remove firewalld
    if dpkg -l | grep -qw firewalld; then
        echo "firewalld detected. Removing firewalld..."
        sudo apt purge firewalld -yq
    else
        echo "firewalld not found."
    fi

    # Check and disable ufw
    if dpkg -l | grep -qw ufw; then
        echo "ufw detected. Disabling ufw..."
        sudo ufw disable
    else
        echo "ufw not found."
    fi
}

# Function to detect SSH port from sshd_config
find_ssh_port() {
    echo "Detecting SSH port..."
    if [ -f "$SSH_CONFIG" ]; then
        SSH_PORT=$(grep -oP '^Port\s+\K\d+' "$SSH_CONFIG" 2>/dev/null)
        if [ -z "$SSH_PORT" ]; then
            echo "No SSH port found; defaulting to 22."
            SSH_PORT=22
        else
            echo "SSH port detected: $SSH_PORT"
        fi
    else
        echo "SSH configuration file not found; defaulting to 22."
        SSH_PORT=22
    fi
}

# Function to create the nftables configuration file using a heredoc
create_nftables_config() {
    cat << EOF | sudo tee "$CONFIG_FILE" > /dev/null
#!/usr/sbin/nft -f
flush ruleset
table inet filter {
    chain input {
        type filter hook input priority 0; policy drop;
        iif lo accept
        ct state established,related accept
        tcp dport $SSH_PORT accept
        tcp dport 80 accept
        tcp dport 443 accept
        udp dport 443 accept
        tcp dport 2053 accept
        udp dport 2053 accept
        tcp dport 8443 accept
        udp dport 8443 accept
    }
    chain forward {
        type filter hook forward priority 0; policy drop;
    }
    chain output {
        type filter hook output priority 0; policy accept;
    }
}
EOF
}

# Function to secure the nftables config file
secure_config_file() {
    sudo chown root:root "$CONFIG_FILE"
    sudo chmod 600 "$CONFIG_FILE"
}

# Function to apply the nftables rules from the config file with error checking
apply_nftables_rules() {
    sudo nft -f "$CONFIG_FILE"
    if [ $? -ne 0 ]; then
        echo "Failed to load firewall rules from $CONFIG_FILE. Check syntax."
        exit 1
    fi
    echo "Firewall rules applied successfully from $CONFIG_FILE."
}

# Function to generate dynamic fail2ban configuration file (jail.local) with SSH port detection
generate_fail2ban_config() {
    # Ensure the fail2ban directory exists
    if [ ! -d "./fail2ban" ]; then
        mkdir -p ./fail2ban
    fi

    cat << EOF > "$FAIL2BAN_CONFIG"
[DEFAULT]
# Ignore localhost to prevent self-bans
ignoreip = 127.0.0.1/8 ::1

[sshd]
enabled  = true
port     = $SSH_PORT
filter   = sshd
logpath  = /var/log/auth.log
maxretry = 3
findtime = 600    # 10 minutes
bantime  = 86400  # 24 hours

[nginx-http-auth]
enabled  = true
port     = 80,2053,8443
filter   = nginx-http-auth
logpath  = /var/log/nginx/error.log
maxretry = 3

[xray]
enabled  = true
port     = 443
filter   = xray
logpath  = /var/log/xray_access.log
maxretry = 3
EOF

    echo "Dynamic fail2ban configuration generated at $FAIL2BAN_CONFIG."
}

# Main execution flow
main() {
    remove_firewalld
    sleep 0.5
    find_ssh_port
    sleep 0.5
    create_nftables_config
    sleep 0.5
    secure_config_file
    sleep 0.5
    apply_nftables_rules
    sleep 0.5
    generate_fail2ban_config
    sleep 0.5
}

main
