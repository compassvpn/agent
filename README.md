## ⚠️ Caution: This project is under active development! ⚠️

# Compass VPN Agent

## Features

1. One-command VPN setup and remote monitoring.
2. Send metrics and generated configuration links to a central dashboard.
3. Collect vital VM metrics, such as CPU, memory, and traffic.
4. Automatic Cloudflare DNS management.
5. Support for direct configurations or configurations behind the Cloudflare CDN proxy.
6. Automatic certificate generation for TLS configurations _(using ZeroSSL or Let's Encrypt)_.
7. Support for WARP and Direct outbound connections.
8. Create a variety of VPN configurations.
9. Automatic updates.
10. Automatic configuration rotation.
11. Automatic blocking of: torrents, Iranian websites, Ads, Malware, and Phishing _(with automatic files download)_.
12. Support for free Grafana Cloud or Pushgateway for metric collection and dashboard integration.
13. Configuration self-testing using Xray-Knife.
14. Utilize the NGINX web server to enhance resource efficiency and strengthen security.
15. Ability to configure Custom DNS to block junk traffic at egress, effectively reducing bandwidth consumption.
16. Enhanced security with fail2ban to protect against brute force attacks.
17. Automatic firewall configuration through UFW to secure the server.
18. User metrics for tracking approximate active unique users across all inbounds and monitoring blocked requests due to junk traffic (DNS and Custom CompassVPN routing rules), effectively optimizing bandwidth usage.
19. WireGuard integration for WARP outbound connections with automatic fallback.
20. Intelligent process monitoring for all services using Monit.


## Requirements

- **VPS Architecture**: **AMD64** or **ARM64** _(recommended: 2 vCPUs and 2GB RAM)_.
- **Supported OS**: **Ubuntu (20+)**, **Debian (10+)**.
- `git` and `curl` packages installed on the server:
```bash
sudo apt update -q && sudo apt install -yq git curl
```


## Services

### `xray-config`
Creates `config.json`, monitors configurations, and export Xray configurations via `/metrics` path.

### `xray`
Reads `config.json` from the **xray-config** service and runs the Xray-core.

### `v2ray-exporter`
Exports V2Ray/Xray configuration metrics.

### `node-exporter`
Prometheus Node Exporter that collects all critical metrics of the agent machine.

### `nginx`
NGINX webserver to manage Xray inbounds and fallbacks, enhancing both performance and security.

### `metric-forwarder`
Reads metrics from `xray-config`, `node-exporter`, and `v2ray-exporter` services and pushes them to a remote manager `Pushgateway` service or `Grafana Cloud Prometheus` endpoint.

### `fail2ban`
Protects the server against brute force attacks by monitoring logs and automatically blocking suspicious IPs.

### `user-metrics`
Tracks approximate active unique users across all configured inbounds and monitors blocked requests due to junk traffic, providing insights into bandwidth optimization.

## Setup Manager
Please follow [this tutorial](https://github.com/compassvpn/manager) to create a manager. You can choose between the following options:
- Grafana Cloud
- Hosted Grafana + Prometheus

Ensure you obtain the authentication values from the manager setup. These values will be required to be included in the `env_file` of the agent.


# How to run

The following services must be run on a VPS you intend to use as a VPN server.

## Clone

1. ```bash
      git clone https://github.com/compassvpn/agent.git
      ```
2. ```bash
      cd agent
      ```

## Configure `env_file`

1. Copy the example file to `env_file`, the program's required configuration file:
      ```bash
      cp env_file.example env_file
      ```

2. Set `METRIC_PUSH_METHOD` to either `pushgateway` or `grafana_cloud`, based on your chosen Manager option. (recommended: `grafana_cloud` for simplicity.)

3. if `METRIC_PUSH_METHOD=grafana_agent` _(set during the manager setup: [Option 1](https://github.com/compassvpn/manager?tab=readme-ov-file#option-1-use-garafana-cloud))_
      - set `GRAFANA_AGENT_REMOTE_WRITE_URL` _(Grafana remote URL)_
      - set `GRAFANA_AGENT_REMOTE_WRITE_USER` _(Grafana user)_
      - set `GRAFANA_AGENT_REMOTE_WRITE_PASSWORD` _(Grafana token password)_

4. if `METRIC_PUSH_METHOD=pushgateway` _(set during the manager setup: [Option 2](https://github.com/compassvpn/manager?tab=readme-ov-file#option-2-deploy-your-own-server))_
      - set `PUSHGATEWAY_URL` _(pushgateway URL)_
      - set `PUSHGATEWAY_AUTH_USER` _(pushgateway basic auth user)_
      - set `PUSHGATEWAY_AUTH_PASSWORD` _(pushgateway basic auth password)_

5. Set `DONOR=noname` _(used as a label in Prometheus metrics)_.

6. Set `REDEPLOY_INTERVAL` _(resets `IDENTIFIER` and generates new configurations at each interval, e.g., `1d` for 1 day, `14d` for every two weeks)_.

7. Set `IPINFO_API_TOKEN` _(Optional, signup at [ipinfo](https://ipinfo.io/signup))_

8. Set `CF_ENABLE` to:
      - `true` to include Cloudflare CDN configuration links alongside other configs.
      - `false` to skip generating Cloudflare CDN configs.

9. Set `CF_ONLY` to:
      - `true` if the server's IP is filtered or not clean.
      - `false` to allow direct configurations without Cloudflare.

10. Configure Cloudflare `CF_API_TOKEN` and `CF_ZONE_ID`:
      - `CF_API_TOKEN`: Create this token for one zone at [Cloudflare API Token Setup](https://developers.cloudflare.com/fundamentals/api/get-started/create-token/).
      - `CF_ZONE_ID`: Use the Zone ID selected when creating the API token.

11. Set `SSL_PROVIDER` to `letsencrypt` or `zerossl` (depending on your preferred SSL certificate provider):

12. Set `XRAY_OUTBOUND` to:
      - `direct` for direct outbound connections.
      - `warp` for [WARP](https://one.one.one.one) outbound connections.

13. Set `XRAY_INBOUNDS` to your desired inbound configurations, as defined in inbounds.json.
      
      Supported Inbounds:
      - `vless-tcp-tls-direct`
      - `vless-hu-tls-direct`
      - `vless-hu-tls-cdn`
      - `vless-xhttp-quic-direct`
      - `vless-xhttp-quic-cdn`
      - _(Default when not set: all inbounds)_

14. Set `AUTO_UPDATE` to:
      - `on` to enable automatic updates.
      - `off` to disable automatic updates _(default if not provided or commented out)_.

15. Configure `NGINX`:
      - Set `NGINX_PATH`: Any value is fine; it just needs to be present as firewalls won't see it.
      - Set `NGINX_FAKE_WEBSITE`. Use a site relevant to your VPS region, avoiding Cloudflare CDN websites.

16. Set `CUSTOM_DNS` to:
      - `default`: Use the VPS default DNS servers.
      - `cf`: Use the [CloudFlare Security DoH](https://security.cloudflare-dns.com/dns-query): Will block Malware services.
      - `controld`: Use the [ControlD free DoH](https://freedns.controld.com/no-ads-dating-drugs-gambling-malware-typo/): Will block Ads, Dating, Drugs, Gambling, Malware services. _(default)_
      - `custom`: Use any DNS server you wish to provide, with support for DoU, DoT, DoH, and DoQ. For each, input as follows:

      DoU: `CUSTOM_DNS=76.76.2.2`

      DoT: `CUSTOM_DNS=tls+local://p2.freedns.controld.com`

      DoH: `CUSTOM_DNS=https+local://freedns.controld.com/p2`

      DoQ: `CUSTOM_DNS=quic+local://p2.freedns.controld.com`

17. Set `DEBUG` to:
      - `disable`. _(default)_
      - `enable`: Show Xray debug & DNS logs.


## Commands

### Bootstrap: _(first time)_
```bash
./bootstrap.sh
```

### Rebuild and restart all services:
```bash
./restart.sh
```

### View Configuration Links:
```bash
./show_configs.sh
```

### Check & Update:
```bash
./check_update.sh
```

### Show Logs:
```bash
./logs.sh
```

