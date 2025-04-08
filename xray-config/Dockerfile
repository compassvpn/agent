FROM teddysun/xray:25.3.6 AS xray-image

FROM python:3.13.2-alpine3.21

COPY requirements.txt requirements.txt

RUN pip3 install --break-system-packages -r requirements.txt

COPY --from=xray-image /usr/bin/xray /usr/bin/xray

RUN apk add --no-cache --virtual .build-deps wget unzip && \
    apk add --no-cache curl openssl wireguard-tools-wg-quick && \
    \
    # Detect architecture and download/install xray-knife
    ARCH=$(uname -m) && \
    if [ "$ARCH" = "x86_64" ]; then \
        arch_name="64"; \
    elif [ "$ARCH" = "aarch64" ]; then \
        arch_name="arm64-v8a"; \
    else \
        echo "Unsupported architecture: $ARCH" >&2; \
        exit 1; \
    fi && \
    wget -L -O knife.zip "https://github.com/lilendian0x00/xray-knife/releases/download/v3.20.45/Xray-knife-linux-${arch_name}.zip" && \
    unzip knife.zip && \
    mv ./xray-knife /usr/bin/ && \
    rm knife.zip && \
    \
    # Install acme.sh
    curl https://get.acme.sh | sh && \
    \
    # Clean up build dependencies
    apk del .build-deps

WORKDIR /root

COPY utils.py utils.py
COPY config.py config.py
COPY run.py run.py
COPY inbounds.json inbounds.json

CMD ["python3", "run.py"]
