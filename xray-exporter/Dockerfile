FROM alpine:3.22.4

# keep ca-certificates around after dropping wget - the exporter needs it to
# fetch the GeoIP dbs over https on startup
RUN apk add --no-cache ca-certificates wget && \
    ARCH=$(uname -m) && \
    if [ "$ARCH" = "x86_64" ]; then arch="amd64"; elif [ "$ARCH" = "aarch64" ]; then arch="arm64"; else echo "Unsupported architecture" && exit 1; fi && \
    wget -O /xray-exporter https://github.com/compassvpn/xray-exporter/releases/download/v0.6.0/xray-exporter-linux-${arch} && \
    chmod +x /xray-exporter && \
    apk del wget

# where the exporter caches the GeoIP dbs it downloads (volume-backed in compose)
RUN mkdir -p /geoip

COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

EXPOSE 9550

# entrypoint picks the --log-level from the DEBUG flag in env_file
CMD ["/entrypoint.sh"]
