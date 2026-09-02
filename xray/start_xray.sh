#!/bin/sh

# Go hoards ~2x the live heap without a limit. /proc/meminfo shows host RAM here.
mem_total_kb=$(awk '/^MemTotal:/ {print $2}' /proc/meminfo)
case "$mem_total_kb" in
    ''|*[!0-9]*|0)
        echo "start_xray: could not read MemTotal from /proc/meminfo (got '$mem_total_kb')" >&2
        exit 1
        ;;
esac
export GOMEMLIMIT="$(( mem_total_kb * 65 / 100 / 1024 ))MiB"
echo "start_xray: GOMEMLIMIT=$GOMEMLIMIT (65% of ${mem_total_kb} kB)"

/usr/bin/xray -c /etc/xray/config.json > /var/log/compassvpn/xray.log 2>&1 &

echo $! > /run/xray.pid

sleep 1
