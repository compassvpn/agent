#!/usr/bin/bash

raw_data=$(docker compose exec xray-config curl -s http://localhost:5000/metrics 2>/dev/null)

echo
echo "CompassVPN Configuration Links"
echo "=============================="
echo

if [ -z "$raw_data" ]; then
    echo "No data available. The xray-config service may not be ready yet."
    echo
    echo "=============================="
    echo
    exit 0
fi

echo "$raw_data" | grep "vpn_config" | grep -v "HELP" | grep -v "TYPE" | while read -r line; do
    config_name=$(echo "$line" | grep -o 'config_name="[^"]*"' | sed 's/config_name="//;s/"//')
    config_link=$(echo "$line" | grep -o 'config_link="[^"]*"' | sed 's/config_link="//;s/"$//')
    latency=$(echo "$line" | awk '{print $NF}')

    if [ "$latency" = "-1" ]; then
        echo "${config_name:-unknown} (FAIL: -1 ms)"
    else
        echo "${config_name:-unknown} (OK: ${latency} ms)"
    fi
    echo "${config_link}"
    echo
done

echo "=============================="
echo
