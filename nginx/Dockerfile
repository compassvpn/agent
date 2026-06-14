FROM nginx:1.31.1-alpine-slim

RUN apk add curl jq

COPY ./nginx.conf /etc/nginx/nginx.conf

COPY ./entrypoint.sh /docker-entrypoint.sh
