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

Everything is driven by `./agent.sh` — run `./agent.sh help` to list the commands:

| Command | What it does |
| --- | --- |
| `./agent.sh start` | Set up / update / restart everything — run this first and any time after (safe to re-run). |
| `./agent.sh stop` | Stop and remove the containers, networks, volumes and images. |
| `./agent.sh update` | Pull the latest code and reconverge. |
| `./agent.sh configs` | Print the VPN config links. |
| `./agent.sh logs [service]` | Tail the container logs. |
| `./agent.sh help` | Show the command list. |

## Services

### `xray-config`
Creates `config.json`, monitors configurations, and export Xray configurations via `/metrics` path.

### `xray`
Reads `config.json` from the **xray-config** service and runs the Xray-core.

### `xray-exporter`
Reads Xray's access log and gRPC stats API and exposes them as Prometheus metrics on `:9550`. Also downloads the GeoIP databases on startup to geo-enrich destination metrics.

### `node-exporter`
Prometheus Node Exporter that collects all critical metrics of the agent machine.

### `nginx`
NGINX webserver to manage Xray inbounds and fallbacks, enhancing both performance and security.

### `metric-forwarder`
Reads metrics from `xray-config`, `node-exporter`, and `xray-exporter` services and pushes them to a remote manager `Pushgateway` service or `Grafana Cloud Prometheus` endpoint.

### `user-metrics`
Tracks approximate active unique users across all configured inbounds and monitors blocked requests due to junk traffic, providing insights into bandwidth optimization.
