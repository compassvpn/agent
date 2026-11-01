#!/bin/sh

. /shared_lib/common.sh

# Go hoards ~2x the live heap without a limit. /proc/meminfo shows host RAM here.
mem_total_kb=$(awk '/^MemTotal:/ {print $2}' /proc/meminfo)
case "$mem_total_kb" in
    ''|*[!0-9]*|0)
        log error xray "Couldn't read MemTotal from /proc/meminfo" "value=$mem_total_kb"
        exit 1
        ;;
esac
export GOMEMLIMIT="$(( mem_total_kb * 65 / 100 / 1024 ))MiB"

/usr/bin/xray -c /etc/xray/config.json > /var/log/compassvpn/xray.log 2>&1 &

echo $! > /run/xray.pid

sleep 1
if kill -0 "$(cat /run/xray.pid)" 2>/dev/null; then
    log info xray "Xray started" "gomemlimit=$GOMEMLIMIT"
else
    log error xray "Xray exited right after starting" log=/var/log/compassvpn/xray.log
fi
