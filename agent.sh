#!/usr/bin/bash
#
# Single entry point for the CompassVPN agent host. Run `./agent.sh help`.

usage() {
    cat <<'EOF'
CompassVPN agent

Usage: ./agent.sh <command>

Commands:
  start         set up / update / restart everything (safe to re-run)
  stop          stop and remove containers, networks, volumes and images
  update        pull the latest code and reconverge
  configs       print the VPN config links
  logs [svc]    tail the container logs (optionally for one service)
  help          show this help
EOF
}

command_not_exists() {
    ! command -v "$1" >/dev/null 2>&1
}

# Set up the host and (re)deploy the stack via Ansible. Idempotent.
start() {
    set -euo pipefail

    # Must run as root
    if [ "$EUID" -ne 0 ]; then
        echo "Error: run this as root"
        exit 1
    fi

    # env_file is required (the stack and the playbook both read it)
    if [ ! -f env_file ]; then
        echo "Error: env_file is missing. Copy env_file.example to env_file and fill it in"
        exit 1
    fi
    # Pull in the two operational knobs the playbook needs for cron (not secrets).
    source env_file

    # uv installs to ~/.local/bin; put that on PATH unconditionally so an already
    # installed uv is found even under cron's minimal PATH (rather than re-downloaded).
    export PATH="$HOME/.local/bin:$PATH"

    # Ansible's controller needs Python 3.12+, newer than these releases ship;
    # uv fetches a suitable one itself, so we only need uv on the box.
    if command_not_exists uv; then
        echo "Installing uv"
        curl -LsSf https://astral.sh/uv/install.sh | sh
    fi

    # Only show tasks that changed or failed, unless DEBUG is on.
    local debug="${DEBUG:-false}"
    if [ "${debug,,}" != "true" ]; then
        export ANSIBLE_DISPLAY_OK_HOSTS=false ANSIBLE_DISPLAY_SKIPPED_HOSTS=false
    fi
    # One line per task, and failures as one line with the error
    export ANSIBLE_STDOUT_CALLBACK=community.general.unixy

    # Run Ansible from the pinned toolchain in pyproject.toml / uv.lock, so every
    # server gets the exact same versions. --frozen uses the committed lock as-is.
    # -i localhost, skips the "no inventory" warnings.
    echo "Setting up the host"
    uv run --frozen ansible-playbook -i localhost, agent.yml \
        -e "auto_update=${AUTO_UPDATE:-}" \
        -e "redeploy_interval=${REDEPLOY_INTERVAL:-}"

    cat <<'EOF'

Done. Metrics should show up in Grafana within 5 to 10 minutes.

Useful commands:
  ./agent.sh configs   print the VPN config links
  ./agent.sh logs      tail the container logs
  ./agent.sh help      show all commands
EOF
}

# Stop the stack and remove its containers, networks, volumes and images.
stop() {
    set -euo pipefail
    echo "Stopping and removing the stack"
    docker compose down --rmi all --volumes --remove-orphans
    echo "Done"
}

# Pull the latest code and reconverge if the remote has moved (used by cron).
update() {
    set -euo pipefail

    git fetch || { echo "git fetch failed, skipping the update"; exit 0; }
    local head upstream
    head=$(git rev-parse @)
    # Bail out cleanly if this checkout has no upstream (e.g. a detached deploy).
    upstream=$(git rev-parse @{u} 2>/dev/null || true)
    if [ -z "$upstream" ]; then
        echo "No upstream branch, skipping the update"
        exit 0
    fi

    if [ "$head" != "$upstream" ]; then
        echo "New changes found, updating"
        git reset --hard "@{u}"
        chmod +x ./*.sh
        echo "Updated, setting up again"
        exec ./agent.sh start
    else
        echo "Already up to date"
    fi
}

# Tail the container logs (optionally for a single service).
logs() {
    docker compose logs --tail 100 "$@"
}

# Print the VPN config links served by xray-config.
configs() {
    raw_data=$(docker compose exec xray-config curl -s http://localhost:5000/metrics 2>/dev/null)
    if [ -z "$raw_data" ]; then
        echo "No configs yet, xray-config may still be starting"
        return 0
    fi

    echo
    echo "$raw_data" | grep "^vpn_config{" | while read -r line; do
        config_name=$(echo "$line" | grep -o 'config_name="[^"]*"' | sed 's/config_name="//;s/"//')
        config_link=$(echo "$line" | grep -o 'config_link="[^"]*"' | sed 's/config_link="//;s/"$//')
        latency=$(echo "$line" | awk '{print $NF}')

        if [ "$latency" = "-1" ]; then
            echo "${config_name:-unknown} (down)"
        else
            echo "${config_name:-unknown} (up, ${latency} ms)"
        fi
        echo "${config_link}"
        echo
    done
}

case "${1:-}" in
    start)             start ;;
    stop)              stop ;;
    update)            update ;;
    configs)           configs ;;
    logs)              shift; logs "$@" ;;
    help|-h|--help|"")  usage ;;
    *)
        echo "Unknown command: $1"
        echo
        usage
        exit 1
        ;;
esac
