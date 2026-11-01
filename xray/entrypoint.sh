#!/bin/sh

rm -f /run/*.pid

. /shared_lib/common.sh
debug "Debug logging on"

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

  wait_for "$WG_CONFIGS_URL" || exit 1

  # Fetch WireGuard configs and save them locally
  mkdir -p /etc/wireguard
  if ! WG_CONFIGS=$(curl -sf "$WG_CONFIGS_URL"); then
      log error "Couldn't fetch the WireGuard configs"
      exit 1
  fi

  # Extract and save each WireGuard config
  for iface in $(echo "$WG_CONFIGS" | jq -r 'keys[]'); do
      CONFIG_CONTENT=$(echo "$WG_CONFIGS" | jq -r ".\"$iface\"")
      echo "$CONFIG_CONTENT" > "/etc/wireguard/${iface}.conf"
      debug "Saved the WireGuard config" "path=/etc/wireguard/${iface}.conf"
      if [ "$DEBUG" = "true" ]; then echo "$CONFIG_CONTENT"; fi
  done

  # Bring up wg interfaces
  for iface in $(echo "$WG_CONFIGS" | jq -r 'keys[]'); do
      # Only install the monit watchdog if the interface actually came up -
      # otherwise monit loops forever trying to restart a dead interface.
      if out=$(/usr/bin/wg-quick up "$iface" 2>&1); then
          if [ "$DEBUG" = "true" ]; then echo "$out"; fi
          log info "WARP tunnel up" "iface=$iface"
          MONIT_CONF_PATH="/etc/monit.d/$iface"
          cp /wg_monit "$MONIT_CONF_PATH"
          sed -i "s|\${INTERFACE}|$iface|g" "$MONIT_CONF_PATH"
      else
          log warning "WARP tunnel failed, skipping its watchdog" "iface=$iface"
          echo "$out"
      fi
  done
fi

sed -i 's/^#  include \/etc\/monit\.d\/\*$/  include \/etc\/monit.d\/*/' /etc/monitrc

XRAY_CONFIG_URL="http://xray-config:5000/config"

wait_for "$XRAY_CONFIG_URL" || exit 1

# Fetch the final config and verify it
if ! curl -sf "$XRAY_CONFIG_URL" > /etc/xray/config.json; then
    log error "Couldn't fetch the xray config" "url=$XRAY_CONFIG_URL"
    exit 1
fi

# Verify the config is valid JSON and functional
if ! out=$(xray -test -config /etc/xray/config.json 2>&1); then
    log error "Xray config is invalid"
    echo "$out"
    cat /etc/xray/config.json
    exit 1
fi
if [ "$DEBUG" = "true" ]; then echo "$out"; fi

# Start Xray immediately so xray-config can test it
/start_xray.sh

# Poll xray-config hourly; if the served config changes (e.g. renewed TLS cert),
# write the new config.json and SIGHUP xray so it reloads without a full restart.
config_watcher() {
    while true; do
        sleep 3600
        new=$(curl -sf "$XRAY_CONFIG_URL") || continue
        if [ "$new" != "$(cat /etc/xray/config.json)" ]; then
            printf '%s' "$new" > /etc/xray/config.json
            if [ -f /run/xray.pid ]; then
                kill -HUP "$(cat /run/xray.pid)" && log info "Xray config changed, reloaded"
            fi
        fi
    done
}
config_watcher &

# monit prints plain lines; reword the restart ones to match ours and keep its
# startup chatter for debug.
monit -I 2>&1 | while IFS= read -r line; do
    name=$(printf '%s' "$line" | sed -n "s/^'\([^']*\)'.*/\1/p")
    case "$line" in
        *"process is not running") log warning "Process stopped, restarting it" "name=$name" ;;
        *"process is running with pid"*) log info "Process is back up" "name=$name" ;;
        *failed*|*unmonitor*) log warning "$line" ;;
        *"trying to restart"|*" start: "*|*"Monit id"*|*"Stored in"*|*"Starting Monit"*|*" started") debug "$line" ;;
        *) log info "$line" ;;
    esac
done
