#!/usr/bin/bash

# Get raw metrics data
raw_data=$(docker compose exec xray-config curl -s http://localhost:5000/metrics)

# Print header
echo 
echo "CompassVPN Configuration Links"
echo "=============================="
echo

# Filter out the HELP and TYPE lines, then process each vpn_config line
echo "$raw_data" | grep "vpn_config" | grep -v "HELP" | grep -v "TYPE" | while read -r line; do
    # Extract the config name (from the end of the config_link, after the #)
    config_name=$(echo "$line" | grep -o '#[^"]*' | sed 's/#//')
    
    # Extract the config link
    config_link=$(echo "$line" | grep -o 'config_link="[^"]*' | sed 's/config_link="//g')
    
    # Extract latency value (number at the end of the line)
    latency=$(echo "$line" | awk '{print $NF}')
    
    # Simple status based on latency
    status="Working"
    if [ "$latency" = "-1" ]; then
        status="Not Working"
    fi
    
    # Print formatted output
    echo "$config_name"
    echo "Status: $status (Latency: $latency ms)"
    echo "$config_link"
    echo
done

echo "=============================="
echo
