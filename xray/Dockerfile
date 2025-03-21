FROM teddysun/xray:25.3.6

RUN apk update && apk add curl wget wireguard-tools-wg-quick monit jq net-tools

RUN wget -O /usr/share/xray/geoip.dat https://github.com/Loyalsoldier/v2ray-rules-dat/releases/latest/download/geoip.dat
RUN wget -O /usr/share/xray/geosite.dat https://github.com/Loyalsoldier/v2ray-rules-dat/releases/latest/download/geosite.dat
RUN wget -O /usr/share/xray/geoip_IR.dat https://github.com/chocolate4u/Iran-v2ray-rules/releases/latest/download/geoip.dat
RUN wget -O /usr/share/xray/geosite_IR.dat https://github.com/chocolate4u/Iran-v2ray-rules/releases/latest/download/geosite.dat

#RUN curl -L https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64 -o /usr/bin/cloudflared && chmod +x /usr/bin/cloudflared

COPY ./start_xray.sh /start_xray.sh
COPY ./stop_xray.sh /stop_xray.sh
COPY ./start_wg.sh /start_wg.sh
COPY ./stop_wg.sh /stop_wg.sh
COPY ./start_cloudflared.sh /start_cloudflared.sh
COPY ./stop_cloudflared.sh /stop_cloudflared.sh

COPY ./wg_template.conf /wg_template.conf
COPY wg_monit /wg_monit
COPY ./xray_monit /etc/monit.d/xray
#COPY ./cloudflared_monit /etc/monit.d/cloudflared

COPY entrypoint.sh entrypoint.sh

CMD ["./entrypoint.sh"]
