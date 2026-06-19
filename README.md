## ⚠️ Caution: This project is under active development! ⚠️

# Compass VPN Agent

A self-contained, Dockerized [Xray](https://github.com/XTLS/Xray-core) VPN node. You
provision the whole host with one command, and it ships its metrics back to your
manager's Grafana.

- [Full guide](https://www.compassvpn.org/installation/)
- [Features](https://www.compassvpn.org/features/)

## Requirements

- A fresh **Debian 11+** or **Ubuntu 22.04+** server, with **root** access.
- The auth values from your [manager setup](https://www.compassvpn.org/installation/manager-setup/); they go in `env_file`.

Full requirements are [on the website](https://www.compassvpn.org/installation/#requirements).

## Quick start

```bash
# 1. Get the code
git clone https://github.com/compassvpn/agent.git
cd agent

# 2. Configure it
cp env_file.example env_file
nano env_file          # paste the values from your manager setup

# 3. Bring it up
./agent.sh start
```

The first run installs Docker and builds the images, so give it a few minutes. Metrics
should appear in your Grafana within 5 to 10 minutes.

## Commands

Everything goes through `./agent.sh` (run `./agent.sh help` to list them):

| Command | What it does |
| --- | --- |
| `./agent.sh start` | Set up, update, or restart everything. Run this first and any time after; it's safe to re-run. |
| `./agent.sh stop` | Stop and remove the containers, networks, volumes and images. |
| `./agent.sh update` | Pull the latest code and reconverge. |
| `./agent.sh configs` | Print the VPN config links. |
| `./agent.sh logs [service]` | Tail the container logs. |
| `./agent.sh help` | Show the command list. |

## How it works

Two files drive everything:

- **`agent.sh`** is the launcher you run. It makes sure [`uv`](https://docs.astral.sh/uv/)
  is installed (Ansible's control side needs Python 3.12+, newer than these releases ship,
  and `uv` fetches one on its own, so there's nothing system-wide to manage), then runs the
  playbook from a pinned toolchain (`pyproject.toml` plus `uv.lock`) so every server gets
  the exact same Ansible and dependency versions.
- **`agent.yml`** is a single Ansible playbook that provisions the host and deploys the
  stack, in stages.

`./agent.sh start` runs the playbook top to bottom:

1. **prepare**: base packages, DNS and UTC timezone, kernel/network tuning (BBR,
   conntrack, file limits), the UFW firewall (SSH plus the service ports), and the log
   files and rotation.
2. **docker**: installs Docker if it's missing.
3. **identifier**: generates a stable per-node ID once (stored in `env_file`), used as a
   metrics label.
4. **cron**: schedules the optional hourly auto-update and the periodic re-deploy and
   cert renewal.
5. **deploy**: `docker compose up -d --build` to (re)start the stack.

It's **idempotent**, so re-running `./agent.sh start` only changes what has drifted
(usually just a container rebuild). Each stage is also a tag, so you can run one on its
own, for example `uv run --frozen ansible-playbook agent.yml --tags deploy`.

The Ansible version is pinned in `pyproject.toml` and locked in `uv.lock`. To move to a
newer Ansible, bump it there and run `uv lock`; to refresh the pinned dependencies without
changing Ansible, run `uv lock --upgrade`. Commit both files either way.

## The stack

Six containers, wired up in `docker-compose.yml`:

| Service | Role |
| --- | --- |
| `xray-config` | Builds the Xray config, fetches and renews TLS certs (acme.sh and Cloudflare), runs the config self-tests. Internal only. |
| `xray` | The proxy that handles all the public VPN traffic. Brings up a WireGuard tunnel for egress in warp mode. |
| `nginx` | Public TLS front plus a decoy site for anything that isn't real proxy traffic. |
| `xray-exporter` | Turns Xray's access log and stats API into Prometheus metrics on `:9550`, with GeoIP enrichment. |
| `node-exporter` | Host metrics (CPU, memory, disk, network). Internal only. |
| `metric-forwarder` | Runs Grafana Alloy, which scrapes the metrics above and ships them to your manager's Grafana. |
