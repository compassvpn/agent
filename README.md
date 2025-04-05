## ⚠️ Caution: This project is under active development! ⚠️

# Compass VPN Agent

### Read the complete guide [on our website](https://www.compassvpn.org/installation/).

## Features
### [Read Here.](https://www.compassvpn.org/features/)

## Requirements

### [Read Here.](https://www.compassvpn.org/installation/#requirements)

# How to run

## 1. Setup Agent

### Follow [this tutorial](https://www.compassvpn.org/installation/) to get the Compass VPN Agent running.

## 2. Setup Manager
### Follow [this tutorial](https://www.compassvpn.org/installation/manager-setup/) to create a manager.

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
