#!/bin/sh

. /shared_lib/common.sh

/usr/bin/xray -c /etc/xray/config.json > /var/log/compassvpn/xray.log 2>&1 &

echo $! > /run/xray.pid

sleep 1
if kill -0 "$(cat /run/xray.pid)" 2>/dev/null; then
    log info "Xray started"
else
    log error "Xray exited right after starting" log=/var/log/compassvpn/xray.log
fi
