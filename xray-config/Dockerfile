FROM python:3.11.9-alpine3.19
COPY requirements.txt requirements.txt

RUN pip3 install --break-system-packages -r requirements.txt

RUN wget https://github.com/XTLS/Xray-core/releases/download/v1.8.16/Xray-linux-64.zip && \
     unzip Xray-linux-64.zip && mv ./xray /usr/bin/ && rm README.md LICENSE

RUN wget https://github.com/lilendian0x00/xray-knife/releases/download/v2.12.17/Xray-knife-linux-64.zip && \
     unzip Xray-knife-linux-64.zip && mv ./xray-knife /usr/bin/

RUN apk add curl openssl wireguard-tools-wg-quick

WORKDIR /root

# install acme.sh for creating SSL certificate
RUN curl https://get.acme.sh | sh

COPY utils.py utils.py
COPY config.py config.py
COPY run.py run.py

CMD ["python3", "run.py"]
