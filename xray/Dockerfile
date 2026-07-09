FROM teddysun/xray:26.3.27

RUN apk update && apk add curl wget wireguard-tools-wg-quick monit jq net-tools

RUN wget -O /usr/share/xray/geoip.dat https://github.com/Loyalsoldier/v2ray-rules-dat/releases/latest/download/geoip.dat
RUN wget -O /usr/share/xray/geosite.dat https://github.com/Loyalsoldier/v2ray-rules-dat/releases/latest/download/geosite.dat
RUN wget -O /usr/share/xray/geoip_IR.dat https://github.com/chocolate4u/Iran-v2ray-rules/releases/latest/download/geoip.dat
RUN wget -O /usr/share/xray/geosite_IR.dat https://github.com/chocolate4u/Iran-v2ray-rules/releases/latest/download/geosite.dat

COPY ./start_xray.sh /start_xray.sh
COPY ./stop_xray.sh /stop_xray.sh
COPY ./heal_inbound.sh /heal_inbound.sh

COPY wg_monit /wg_monit
# Template only: the entrypoint renders it to /etc/monit.d/xray with one port
# check per inbound taken from the generated config.
COPY ./xray_monit /xray_monit

COPY entrypoint.sh entrypoint.sh

CMD ["./entrypoint.sh"]
