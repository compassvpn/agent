#!/bin/sh
# Follow the stack's DEBUG flag (read from the mounted env_file): debug when it's
# on, warn otherwise. Normalized the same way as the nginx/xray entrypoints so a
# stray capital or quotes still work.
DEBUG=$(printf '%s' "${DEBUG:-false}" | tr -d "\"'" | tr '[:upper:]' '[:lower:]')
if [ "$DEBUG" = "true" ]; then
    LOG_LEVEL=debug
else
    LOG_LEVEL=warn
fi

exec /xray-exporter \
    --xray-endpoint xray:54321 \
    --log-path /var/log/compassvpn/xray_access.log \
    --log-level "$LOG_LEVEL"
