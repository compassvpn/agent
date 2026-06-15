FROM nginx:1.31.1-alpine-slim

RUN apk add --no-cache curl jq gettext

COPY ./nginx.conf /etc/nginx/nginx.conf
COPY ./tls_servers.conf.template /etc/nginx/tls_servers.conf.template

COPY ./entrypoint.sh /docker-entrypoint.sh
