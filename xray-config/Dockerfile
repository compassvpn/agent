FROM teddysun/xray:1.8.16 AS xray-image

FROM python:3.11.9-alpine3.19

COPY requirements.txt requirements.txt

RUN pip3 install --break-system-packages -r requirements.txt

COPY --from=xray-image /usr/bin/xray /usr/bin/xray

RUN arch=$(uname -m) && arch_name=$( [ "$arch" = "x86_64" ] && echo "64" ) || ( [ "$arch" = "aarch64" ] && echo "arm64-v8a" ) && \
    wget -O knife.zip https://github.com/lilendian0x00/xray-knife/releases/download/v2.13.18/Xray-knife-linux-$arch_name.zip && \
    unzip knife.zip && mv ./xray-knife /usr/bin/

RUN apk add curl openssl wireguard-tools-wg-quick

WORKDIR /root

# install acme.sh for creating SSL certificate
RUN curl https://get.acme.sh | sh

COPY utils.py utils.py
COPY config.py config.py
COPY run.py run.py
COPY inbounds.json inbounds.json

CMD ["python3", "run.py"]
