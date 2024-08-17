# Compass VPN Agent

## Features
1. One command VPN setup and remote monitoring
2. Send metrics and created configs' link to a central dashboard
3. Collect vital VM metrics such as CPU, Memory usage and Traffic 
4. Auto Cloudflare DNS management
5. Direct configs or configs behind Cloudflare proxy
6. Auto certificate generation for TLS configs (zerossl or letsencrypt)
7. Support Warp and Direct outbound
8. Auto discovery of the best Warp endpoint and auto rotation
9. Create variety of VPN configs
10. Auto update
11. Auto configs rotation
12. Auto block torrent or internal websites (download geosite files automatically)
13. Support Free Grafana Cloud or Pushgateway for metric collection and dashboard
14. Configs self testing using xray-knife
15. and more...

## Requirements

* AMD64/ARM64 VPS (2 vCPUs and 2GB RAM recommended)
* Including but not limited to Ubuntu (20.04, 22.04 or 24.04), Debian 10-12 and Fedora

## Services

### xray-config
Creates config.json, monitor configs and export xray configs via /metrics path.

### xray
This service reads config.json from xray-config service and runs the xray-core.

### v2ray-exporter
Export v2ray configs metrics

### node-exporter
Prometheus node exporter that collects all important metrics of the agent machine.

### metric-forwarder
Reads xray-config, node-exporter and v2ray-exporter metrics and push them to the remote manager pushgateway service or Grafana Cloud promotheus endpoint.

## Setup Manager
Please follow [this tutorial](https://github.com/compassvpn/manager) to create a manager (Options: Grafana Cloud or hosted Grafana+Prometheus). 

We need authentication values from the manager to include in the "env_file" of the agent.

# How to run

The following must run on a VPS that you want to use as a VPN server.

## Clone
1. git clone https://github.com/compassvpn/agent.git
2. cd agent

## Configure env_file
1. cp env_file.example env_file
2. set METRIC_PUSH_METHOD to either "pushgateway" or "grafana_cloud" (depending on your selected option for the Manager)
3. if METRIC_PUSH_METHOD=grafana_agent (comes from the manager setup [[Option 1](https://github.com/compassvpn/manager?tab=readme-ov-file#option-1-use-garafana-cloud)])
      * set GRAFANA_AGENT_REMOTE_WRITE_URL
      * set GRAFANA_AGENT_REMOTE_WRITE_USER
      * set GRAFANA_AGENT_REMOTE_WRITE_PASSWORD
4. if METRIC_PUSH_METHOD=pushgateway (comes from the manager setup [[Option 2](https://github.com/compassvpn/manager?tab=readme-ov-file#option-2-deploy-your-own-server)])
      * set PUSHGATEWAY_URL (pushgateway URL)
      * set PUSHGATEWAY_AUTH_USER (pushgateway basic auth user)
      * set PUSHGATEWAY_AUTH_PASSWORD (pushgateway basic auth password)
5. DONOR=noname (will be used as a label in the promtheus metrics)
6. REDEPLOY_INTERVAL (reset IDENTIFIER and create new configs on each interval. e.g: 1d=1 day, 14d=every two weeks)
7. IPINFO_API_TOKEN (https://ipinfo.io/signup - not mandatory)
8. CF_ENABLE (true or false)
9. CF_ONLY (true or false) - if the ip of the server is not clean (already filtered), set this to "true"
10. CF_API_TOKEN (https://developers.cloudflare.com/fundamentals/api/get-started/create-token/ - for one zone)
11. CF_ZONE_ID (zone id that is selected when creating CF API token)
12. SSL_PROVIDER=letsencrypt (or zerossl)
13. XRAY_OUTBOUND=direct # or warp
14. set XRAY_INBOUNDS to your desired inbounds, listed in inbounds.json
15. AUTO_UPDATE=on or off ("off" if it's not provided or commented)

## Commands

### Bootstrap - first time
```
./bootstrap.sh
```

### Rebuild and restart all services
```
./restart.sh
```

### Update
```
./update.sh
./restart.sh
```

