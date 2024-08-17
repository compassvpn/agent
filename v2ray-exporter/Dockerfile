FROM alpine:3.19.1

RUN apk add --no-cache wget
RUN wget -O /v2ray-exporter https://github.com/wi1dcard/v2ray-exporter/releases/download/v0.6.0/v2ray-exporter_linux_$( ( [ $(uname -m) = 'x86_64' ] && echo "amd64") || ([ $(uname -m) = "aarch64" ] && echo "arm64" ) )
RUN chmod +x /v2ray-exporter
RUN apk del -r wget

CMD ["/v2ray-exporter", "--v2ray-endpoint", "xray:54321"]