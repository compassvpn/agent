#!/bin/sh

rm /run/*.pid

sleep 10

if [ $XRAY_OUTBOUND = "warp" ]; then
  # xray-config upstream URL
  UPSTREAM_URL="http://xray-config:5000/warps"

  # Perform a GET request to the upstream
  RESPONSE=$(curl -s -o /dev/null -w "%{http_code}" "$UPSTREAM_URL")

  # Check the HTTP status code of xray-config upstream
  if [ "$RESPONSE" -eq 200 ]; then
      echo "xray-config is ready: $UPSTREAM_URL"
  else
      echo "xray-config is not ready yet: $UPSTREAM_URL (HTTP status: $RESPONSE)"
      sleep 5
      exit 1
  fi

  WARP_CONFIGS=$(curl -s "$UPSTREAM_URL")

  mkdir -p /etc/wireguard/

  echo $WARP_CONFIGS

  counter=0
  # Parse and iterate over each dictionary in the list
  echo "$WARP_CONFIGS" | jq -c '.[]' | while read -r item; do
      addresses=$(echo "$item" | jq -r '.addresses')
      addr_v4=$(echo "$addresses" | jq -r '.[0]')
      addr_v6=$(echo "$addresses" | jq -r '.[1]')
      private_key=$(echo "$item" | jq -r '.privatekey')
      pubkey=$(echo "$item" | jq -r '.pubkey')

      WG_CONF_PATH=/etc/wireguard/wg${counter}.conf
      cp /wg_template.conf $WG_CONF_PATH
      sed -i "s|\${PRIVATE_KEY}|$private_key|g" "$WG_CONF_PATH"
      sed -i "s|\${ADDR_V4}|172.16.${counter}.2|g" "$WG_CONF_PATH"
      sed -i "s|\${ADDR_V6}|$addr_v6|g" "$WG_CONF_PATH"
      sed -i "s|\${PUBKEY}|$pubkey|g" "$WG_CONF_PATH"

      MONIT_CONF_PATH=/etc/monit.d/wg${counter}
      cp /wg_monit /etc/monit.d/wg${counter}
      sed -i "s|\${INTERFACE}|wg${counter}|g" "$MONIT_CONF_PATH"

      counter=$((counter + 1))
  done

fi

sed -i 's/^#  include \/etc\/monit\.d\/\*$/  include \/etc\/monit.d\/*/' /etc/monitrc

XRAY_CONFIG_URL="http://xray-config:5000/config"

# Perform a GET request to the upstream
RESPONSE=$(curl -s -o /dev/null -w "%{http_code}" "$XRAY_CONFIG_URL")

# Check the HTTP status code of xray-config upstream
if [ "$RESPONSE" -eq 200 ]; then
    echo "xray-config is ready: $XRAY_CONFIG_URL"
else
    echo "xray-config is not ready yet: $XRAY_CONFIG_URL (HTTP status: $RESPONSE)"
    sleep 5
    exit 1
fi

curl $XRAY_CONFIG_URL > /etc/xray/config.json

echo "#bin/sh" > /usr/sbin/resolvconf

#echo -e "nameserver 127.0.0.1\nnameserver 127.0.0.11" > /etc/resolv.conf

monit --version

monit -I
