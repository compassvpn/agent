#!/bin/sh
set -eu

NGINX_CONF_PATH=/etc/nginx/nginx.conf
TLS_TEMPLATE=/etc/nginx/tls_servers.conf.template
TLS_CONF=/etc/nginx/conf.d/tls_servers.conf
XRAY_CONFIG_BASE="http://xray-config:5000"

mkdir -p /etc/nginx/conf.d

. /shared_lib/common.sh
debug "Debug logging on"

NGINX_LOG_LEVEL="warn"
if [ "$DEBUG" = "true" ]; then
    NGINX_LOG_LEVEL="debug"
fi

# /nginx-locations returns 503 until xray-config has finished initializing.
wait_for "$XRAY_CONFIG_BASE/nginx-locations" || exit 1
LOCATIONS=$(curl -sf "$XRAY_CONFIG_BASE/nginx-locations")

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
    TLS=on
else
    TLS=off
    : > "$TLS_CONF"
fi

# Write per-port replica location blocks and their xhttp upstreams.
for port in 2053 8880 8443 8080; do
    mkdir -p "/etc/nginx/locations.d/$port"
    printf '%s\n' "$(printf '%s' "$LOCATIONS" | jq -r ".\"$port\" // empty")" \
        > "/etc/nginx/locations.d/$port/replicas.conf"
done
mkdir -p /etc/nginx/upstreams.d
printf '%s\n' "$(printf '%s' "$LOCATIONS" | jq -r '.upstreams // empty')" \
    > /etc/nginx/upstreams.d/replicas.conf

# Watch for cert renewal flag and reload nginx when it changes. Start from the
# current value, since nginx is about to load the current cert anyway.
CERT_FLAG="/var/log/compassvpn/.cert_renewed"
LAST_FLAG_TIME=$(cat "$CERT_FLAG" 2>/dev/null || true)
(
    while true; do
        if [ -f "$CERT_FLAG" ]; then
            CURRENT_TIME=$(cat "$CERT_FLAG" 2>/dev/null || true)
            if [ "$CURRENT_TIME" != "$LAST_FLAG_TIME" ]; then
                LAST_FLAG_TIME="$CURRENT_TIME"
                if out=$(nginx -s reload 2>&1); then
                    log info "TLS cert renewed, nginx reloaded"
                else
                    log error "Couldn't reload nginx"
                    echo "$out"
                fi
            fi
        fi
        sleep 60
    done
) &

log info "Starting nginx" "tls=$TLS"
nginx -g "daemon off;"
