#!/bin/sh

rm -f /run/*.pid

# monit configs (xray + wg watchdogs) are rendered into this directory at
# runtime; nothing creates it at build time anymore.
mkdir -p /etc/monit.d

# Normalize DEBUG (accept True/TRUE/"true") to match the Python services.
DEBUG=$(printf '%s' "${DEBUG:-false}" | tr -d "\"'" | tr '[:upper:]' '[:lower:]')
if [ "$DEBUG" = "true" ]; then
    echo "Debug mode enabled"
fi

# Mock resolvconf to prevent wg-quick from breaking Docker DNS
# This keeps the container's /etc/resolv.conf (Docker DNS) intact.
cat <<EOF > /usr/sbin/resolvconf
#!/bin/sh
# No-op mock to prevent wg-quick DNS changes
exit 0
EOF
chmod +x /usr/sbin/resolvconf

if [ "$XRAY_OUTBOUND" = "warp" ] || [ "$XRAY_OUTBOUND" = "warp-selective" ]; then
  # xray-config upstream URL for WireGuard configs
  WG_CONFIGS_URL="http://xray-config:5000/wg-configs"

  # Wait for xray-config to be ready
  MAX_RETRIES=30
  RETRY_COUNT=0
  while [ $RETRY_COUNT -lt $MAX_RETRIES ]; do
      RESPONSE=$(curl -s -o /dev/null -w "%{http_code}" "$WG_CONFIGS_URL")
      if [ "$RESPONSE" -eq 200 ]; then
          echo "xray-config is ready: $WG_CONFIGS_URL"
          break
      fi
      echo "Waiting for xray-config to generate WG configs... (HTTP status: $RESPONSE)"
      sleep 2
      RETRY_COUNT=$((RETRY_COUNT + 1))
  done

  if [ $RETRY_COUNT -eq $MAX_RETRIES ]; then
      echo "Error: xray-config timed out"
      exit 1
  fi

  # Fetch WireGuard configs and save them locally
  mkdir -p /etc/wireguard
  if ! WG_CONFIGS=$(curl -sf "$WG_CONFIGS_URL"); then
      echo "Error: Failed to fetch WireGuard configs"
      exit 1
  fi

  if [ "$DEBUG" = "true" ]; then
      echo "$WG_CONFIGS"
  fi

  # Extract and save each WireGuard config
  for iface in $(echo "$WG_CONFIGS" | jq -r 'keys[]'); do
      CONFIG_CONTENT=$(echo "$WG_CONFIGS" | jq -r ".\"$iface\"")
      echo "$CONFIG_CONTENT" > "/etc/wireguard/${iface}.conf"
      if [ "$DEBUG" = "true" ]; then
          echo "Saved /etc/wireguard/${iface}.conf:"
          echo "$CONFIG_CONTENT"
      else
          echo "Saved /etc/wireguard/${iface}.conf"
      fi
  done

  # Bring up wg interfaces
  for iface in $(echo "$WG_CONFIGS" | jq -r 'keys[]'); do
      echo "Bringing up $iface..."
      # Only install the monit watchdog if the interface actually came up -
      # otherwise monit loops forever trying to restart a dead interface.
      if /usr/bin/wg-quick up "$iface"; then
          MONIT_CONF_PATH="/etc/monit.d/$iface"
          cp /wg_monit "$MONIT_CONF_PATH"
          sed -i "s|\${INTERFACE}|$iface|g" "$MONIT_CONF_PATH"
      else
          echo "Warning: Failed to bring up $iface; skipping its monit watchdog"
      fi
  done
fi

sed -i 's/^#  include \/etc\/monit\.d\/\*$/  include \/etc\/monit.d\/*/' /etc/monitrc

XRAY_CONFIG_URL="http://xray-config:5000/config"

# Wait for Xray config
MAX_RETRIES=30
RETRY_COUNT=0
while [ $RETRY_COUNT -lt $MAX_RETRIES ]; do
    RESPONSE=$(curl -s -o /dev/null -w "%{http_code}" "$XRAY_CONFIG_URL")
    if [ "$RESPONSE" -eq 200 ]; then
        echo "xray-config is ready: $XRAY_CONFIG_URL"
        break
    fi
    echo "Waiting for xray-config... (HTTP status: $RESPONSE)"
    sleep 2
    RETRY_COUNT=$((RETRY_COUNT + 1))
done

if [ $RETRY_COUNT -eq $MAX_RETRIES ]; then
    echo "Error: xray-config timed out"
    exit 1
fi

# Fetch the final config and verify it
if ! curl -sf "$XRAY_CONFIG_URL" > /etc/xray/config.json; then
    echo "Error: Failed to fetch xray config from $XRAY_CONFIG_URL"
    exit 1
fi

# Verify the config is valid JSON and functional
if ! xray -test -config /etc/xray/config.json; then
    echo "Error: Fetched xray config is invalid"
    cat /etc/xray/config.json
    exit 1
fi

# A process check alone misses a wedged listener: an inbound can stop
# accepting connections while the xray process stays alive (seen in the wild
# with httpupgrade under junk traffic - the port's accept queue fills up and
# every new connection times out). Render the monit config from the template
# plus one TCP connect check per inbound port. A deaf port gets healed
# surgically (/heal_inbound.sh re-adds just that inbound via the xray API, no
# impact on other inbounds); only the API inbound itself (doko) falls back to
# a full restart since a dead API can't heal anything. "for 3 cycles" (~90s)
# tolerates brief load spikes; "repeat" re-fires the heal so it can escalate.
generate_monit_config() {
    {
        cat /xray_monit
        jq -r '
            [ .inbounds[]
              | select((.listen // "0.0.0.0") == "0.0.0.0" or .listen == "127.0.0.1")
              | select((.port | type) == "number") ]
            | unique_by(.port) | .[]
            | if .tag == "doko" then
                "  if failed host 127.0.0.1 port \(.port) type tcp with timeout 10 seconds for 3 cycles then restart"
              else
                "  if failed host 127.0.0.1 port \(.port) type tcp with timeout 10 seconds for 3 cycles then exec \"/heal_inbound.sh \(.port)\" repeat every 3 cycles"
              end
        ' /etc/xray/config.json
    } > /etc/monit.d/xray
}
generate_monit_config

# Start Xray immediately so xray-config can test it
/start_xray.sh

monit --version

# Poll xray-config hourly; if the served config changes (e.g. renewed TLS cert),
# write the new config.json and SIGHUP xray so it reloads without a full restart.
config_watcher() {
    while true; do
        sleep 3600
        new=$(curl -sf "$XRAY_CONFIG_URL") || continue
        if [ "$new" != "$(cat /etc/xray/config.json)" ]; then
            printf '%s' "$new" > /etc/xray/config.json
            # The inbound ports may have changed (e.g. a TLS inbound dropped
            # after a cert problem); re-render the port checks and make monit
            # re-read them, otherwise a check on a removed port would restart
            # xray forever.
            generate_monit_config
            kill -HUP "$(pidof monit)" 2>/dev/null
            if [ -f /run/xray.pid ]; then
                kill -HUP "$(cat /run/xray.pid)" && echo "xray config updated and reloaded"
            fi
        fi
    done
}
config_watcher &

monit -I
