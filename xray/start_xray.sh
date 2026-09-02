#!/bin/sh

# Go keeps ~2x the live heap and hands freed pages back slowly, so xray sat on
# 5.6 GB while using 1.6 GB and left the box 1 GB from OOM. GOMEMLIMIT makes
# the GC work harder as it nears the limit and return memory. 65% of the box
# leaves room for the kernel socket buffers and the other containers, which
# grow with connections too. /proc/meminfo shows the host total inside the
# container since xray has no memory cap.
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
