#!/bin/sh
set -eu

NGINX_CONF_PATH=/etc/nginx/nginx.conf
TLS_TEMPLATE=/etc/nginx/tls_servers.conf.template
TLS_CONF=/etc/nginx/conf.d/tls_servers.conf
XRAY_CONFIG_BASE="http://xray-config:5000"
MAX_RETRIES=60

mkdir -p /etc/nginx/conf.d

# Normalize DEBUG (accept True/TRUE/"true") to match the Python services.
DEBUG=$(printf '%s' "${DEBUG:-false}" | tr -d "\"'" | tr '[:upper:]' '[:lower:]')

NGINX_LOG_LEVEL="warn"
if [ "$DEBUG" = "true" ]; then
    echo "Debug mode enabled"
    NGINX_LOG_LEVEL="debug"
fi

# Wait for xray-config to fully initialize and capture nginx locations in one
# request. /nginx-locations returns 503 while config.initialized is False.
echo "Waiting for xray-config to initialize..."
RETRY_COUNT=0
LOCATIONS="{}"
while [ "$RETRY_COUNT" -lt "$MAX_RETRIES" ]; do
    TMPFILE=$(mktemp)
    HTTP_CODE=$(curl -s -o "$TMPFILE" -w "%{http_code}" \
        "$XRAY_CONFIG_BASE/nginx-locations" 2>/dev/null || printf "000")
    if [ "$HTTP_CODE" -eq 200 ]; then
        LOCATIONS=$(cat "$TMPFILE")
        rm -f "$TMPFILE"
        echo "xray-config is ready"
        break
    fi
    rm -f "$TMPFILE"
    echo "Waiting for xray-config... (HTTP $HTTP_CODE, attempt $((RETRY_COUNT + 1))/$MAX_RETRIES)"
    sleep 2
    RETRY_COUNT=$((RETRY_COUNT + 1))
done

if [ "$RETRY_COUNT" -eq "$MAX_RETRIES" ]; then
    echo "Error: xray-config not ready after $MAX_RETRIES retries"
    exit 1
fi

# Render static placeholders in the main config.
# The explicit variable list leaves nginx's own $variables untouched.
NGINX_LOG_LEVEL="$NGINX_LOG_LEVEL" \
    envsubst '${FAKE_WEBSITE}${NGINX_PATH}${NGINX_LOG_LEVEL}' \
    < "$NGINX_CONF_PATH" > /tmp/nginx.conf && mv /tmp/nginx.conf "$NGINX_CONF_PATH"

# TLS server blocks require a Cloudflare subdomain and certificate.
# When CF credentials are present the subdomain is always available at this
# point because xray-config finished initializing above.
if [ -n "${CF_API_TOKEN:-}" ] && [ -n "${CF_ZONE_ID:-}" ]; then
    DIRECT_SUBDOMAIN=$(curl -sf "$XRAY_CONFIG_BASE/subdomain")
    DIRECT_SUBDOMAIN="$DIRECT_SUBDOMAIN" \
        envsubst '${FAKE_WEBSITE}${NGINX_PATH}${DIRECT_SUBDOMAIN}' \
        < "$TLS_TEMPLATE" > "$TLS_CONF"
    echo "TLS config generated for $DIRECT_SUBDOMAIN"
else
    echo "Cloudflare not configured: TLS server blocks disabled"
    : > "$TLS_CONF"
fi

# Write per-port replica location blocks.
for port in 2053 8880 8443 8080; do
    mkdir -p "/etc/nginx/locations.d/$port"
    printf '%s\n' "$(printf '%s' "$LOCATIONS" | jq -r ".\"$port\" // empty")" \
        > "/etc/nginx/locations.d/$port/replicas.conf"
done

# Watch for cert renewal flag and reload nginx when it changes.
CERT_FLAG="/var/log/compassvpn/.cert_renewed"
LAST_FLAG_TIME=""
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
