#!/bin/sh
# Surgical heal for a single deaf inbound, called by monit when a port stops
# accepting connections: remove + re-add just that inbound through the xray
# API (the doko inbound on 54321), so every other inbound and its users are
# untouched. Falls back to a full restart when the API path fails or the same
# port goes deaf twice within 5 minutes.

port="$1"
case "$port" in
    ''|*[!0-9]*) echo "heal_inbound: bad port '$port'"; exit 1;;
esac

API="127.0.0.1:54321"
marker="/tmp/heal_inbound_${port}.last"
now=$(date +%s)

# Second failure in a short window means the surgical heal isn't holding -
# escalate to the sledgehammer.
if [ -f "$marker" ] && [ $(( now - $(cat "$marker") )) -lt 300 ]; then
    echo "heal_inbound: port $port deaf again within 5 minutes; full restart"
    rm -f "$marker"
    monit restart xray
    exit 0
fi
echo "$now" > "$marker"

tmp="/tmp/heal_inbound_${port}.json"
jq "{inbounds: [.inbounds[] | select(.port == ${port})]}" /etc/xray/config.json > "$tmp"
if [ "$(jq '.inbounds | length' "$tmp")" -eq 0 ]; then
    # Stale check on a port that left the config; the re-rendered monit
    # config drops the check on the next reload, nothing to heal here.
    echo "heal_inbound: port $port not in config.json; nothing to heal"
    exit 0
fi

if xray api rmi --server="$API" "$tmp" && xray api adi --server="$API" "$tmp"; then
    echo "heal_inbound: inbound on port $port removed and re-added"
    exit 0
fi

echo "heal_inbound: API heal failed for port $port; full restart"
monit restart xray
