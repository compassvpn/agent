FROM alpine:3.22.4

RUN apk add --no-cache wget && \
    ARCH=$(uname -m) && \
    if [ "$ARCH" = "x86_64" ]; then arch="amd64"; elif [ "$ARCH" = "aarch64" ]; then arch="arm64"; else echo "Unsupported architecture" && exit 1; fi && \
    wget -O /xray-exporter https://github.com/compassvpn/xray-exporter/releases/download/v0.4.0/xray-exporter-linux-${arch} && \
    chmod +x /xray-exporter && \
    apk del wget

COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

EXPOSE 9550

# entrypoint picks the --log-level from the DEBUG flag in env_file
CMD ["/entrypoint.sh"]
