#!/bin/sh

curl http://xray-config:5000/config > /etc/xray/config.json

cat /etc/xray/config.json

/usr/bin/xray -config /etc/xray/config.json