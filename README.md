## ⚠️ Caution: This project is under active development! ⚠️

# Compass VPN Agent

### Read the complete guide [here](https://www.compassvpn.org/installation/).

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
21. Easy-to-use web panel for configuring.


## Requirements

- **VPS Architecture**: **AMD64** or **ARM64** _(recommended: 2 vCPUs and 2GB RAM)_.
- **Supported OS**: **Ubuntu (20+)**, **Debian (10+)**.
- `git` package installed on the server:

```bash
sudo apt update -qq && sudo apt install -yqq git
```

# How to run

## Getting Started

Follow these steps to get the Compass VPN Agent running:

1.  **Clone the Repository and Start the Panel:**
    Connect to your VPS via SSH and run the following commands:

    ```bash
    git clone https://github.com/compassvpn/agent.git && cd agent && ./start_panel.sh
    ```

2.  **Access the Web Panel:**
    Open your web browser and navigate to `http://<your_vps_ip>:5050`. Remember to replace `<your_vps_ip>` with the actual public IP address of your VPS.

3.  **Configure the Agent via the Panel:**
    Use the web panel interface to configure the agent settings, which will be saved to the `env_file`. This involves setting up your domain, Cloudflare details, metric endpoints, and other preferences. For detailed guidance on each configuration option, please refer to the [complete guide](https://www.compassvpn.org/installation/).

4.  **Apply Configuration and Start Agent:**
    After saving your settings in the panel, follow the instructions provided within the panel to apply the configuration and start the main agent services.

## Setup Manager
Please follow [this tutorial](https://github.com/compassvpn/manager) to create a manager. You can choose between the following options:
- Grafana Cloud
- Hosted Grafana + Prometheus

Ensure you obtain the authentication values from the manager setup. These values will be required to be included in the `env_file` of the agent.

## Commands

### Bootstrap: _(first time)_
```bash
./bootstrap.sh
```

### Rebuild and restart all services:
```bash
./restart.sh
```

### Start the Panel
```bash
./start_panel.sh
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
