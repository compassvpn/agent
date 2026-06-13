#!/bin/sh

NGINX_CONF_PATH=/etc/nginx/nginx.conf

sed -i "s|\${NGINX_FAKE_WEBSITE}|$NGINX_FAKE_WEBSITE|g" "$NGINX_CONF_PATH"
sed -i "s|\${NGINX_PATH}|$NGINX_PATH|g" "$NGINX_CONF_PATH"

UPSTREAM_URL="http://xray-config:5000/subdomain"

MAX_RETRIES=30
RETRY_COUNT=0
DIRECT_SUBDOMAIN=""

while [ $RETRY_COUNT -lt $MAX_RETRIES ]; do
    TMPFILE=$(mktemp)
    HTTP_CODE=$(curl -s -o "$TMPFILE" -w "%{http_code}" "$UPSTREAM_URL")
    BODY_TEXT=$(cat "$TMPFILE")
    rm -f "$TMPFILE"

    if [ "$HTTP_CODE" -eq 200 ] && [ -n "$BODY_TEXT" ]; then
        DIRECT_SUBDOMAIN="$BODY_TEXT"
        echo "xray-config is ready: $UPSTREAM_URL ($DIRECT_SUBDOMAIN)"
        break
    fi

    echo "Waiting for xray-config subdomain... (HTTP status: $HTTP_CODE)"
    sleep 2
    RETRY_COUNT=$((RETRY_COUNT + 1))
done

if [ -z "$DIRECT_SUBDOMAIN" ]; then
    echo "Error: xray-config subdomain not available after $MAX_RETRIES retries"
    exit 1
fi

# Set Nginx log level based on DEBUG env
NGINX_LOG_LEVEL="warn"
if [ "$DEBUG" = "true" ]; then
    NGINX_LOG_LEVEL="debug"
fi

# Robust replacement for the global error_log directive
if grep -q "^error_log /var/log/compassvpn/nginx_error.log" "$NGINX_CONF_PATH"; then
    sed -i "s|^error_log /var/log/compassvpn/nginx_error.log.*|error_log /var/log/compassvpn/nginx_error.log $NGINX_LOG_LEVEL;|" "$NGINX_CONF_PATH"
else
    echo "Warning: error_log directive for nginx_error.log not found in $NGINX_CONF_PATH"
fi

sed -i "s|\${DIRECT_SUBDOMAIN}|$DIRECT_SUBDOMAIN|g" "$NGINX_CONF_PATH"

# Fetch replica location blocks and write include files (empty = no replicas configured)
LOCATIONS=$(curl -sf "http://xray-config:5000/nginx-locations" 2>/dev/null || echo "{}")
for port in 2053 8880 8443; do
    mkdir -p "/etc/nginx/locations.d/$port"
    printf '%s\n' "$(echo "$LOCATIONS" | jq -r ".\"$port\" // empty")" \
        > "/etc/nginx/locations.d/$port/replicas.conf"
done

CERT_FLAG="/var/log/compassvpn/.cert_renewed"
LAST_FLAG_TIME=""

# Watch for cert renewal flag and reload nginx when it appears
(
    while true; do
        if [ -f "$CERT_FLAG" ]; then
            CURRENT_TIME=$(cat "$CERT_FLAG" 2>/dev/null)
            if [ "$CURRENT_TIME" != "$LAST_FLAG_TIME" ]; then
                LAST_FLAG_TIME="$CURRENT_TIME"
                echo "Cert renewal detected; reloading nginx"
                nginx -s reload
            fi
        fi
        sleep 60
    done
) &

nginx -g "daemon off;"
