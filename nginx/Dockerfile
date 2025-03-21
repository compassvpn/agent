FROM nginx:1.26.3-alpine

RUN apk add curl

COPY ./nginx.conf /etc/nginx/nginx.conf

COPY ./entrypoint.sh /docker-entrypoint.sh
