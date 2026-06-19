#!/usr/bin/bash

clear

# Exit on error, unset vars, and failed pipes
set -euo pipefail

command_not_exists() {
    ! command -v "$1" >/dev/null 2>&1
}

# Must run as root
if [ "$EUID" -ne 0 ]; then
    echo "Error: This script must be run as root."
    exit 1
fi

# env_file is required (the stack and the playbook both read it)
if [ ! -f env_file ]; then
    echo "Error: 'env_file' does not exist. Use env_file.example as a template."
    exit 1
fi
# Pull in the two operational knobs the playbook needs for cron (not secrets).
source env_file

# Ansible's controller needs a newer Python than Debian 12 / Ubuntu 22.04 ship;
# uv fetches a suitable one itself, so we only need uv on the box - install it if
# it's missing, then hand off to the playbook for everything else.
if command_not_exists uvx; then
    echo "Installing uv..."
    curl -LsSf https://astral.sh/uv/install.sh | sh
    export PATH="$HOME/.local/bin:$PATH"
fi

echo "Converging the host with Ansible..."
uvx --from ansible@14.0.0 ansible-playbook agent.yml \
    -e "auto_update=${AUTO_UPDATE:-}" \
    -e "redeploy_interval=${REDEPLOY_INTERVAL:-}"

echo
echo "Please allow 5~10 minutes for the metrics to appear in your Grafana dashboard."
echo
