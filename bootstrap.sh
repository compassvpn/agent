#!/usr/bin/bash

clear

# Exit on error, unset vars, and failed pipes
set -euo pipefail

# Function to check if a command exists
command_not_exists() {
    ! command -v "$1" >/dev/null 2>&1
}

# Check if running as root
check_root() {
    if [ "$EUID" -ne 0 ]; then
        echo "Error: This script must be run as root."
        exit 1
    fi
}

# Check environment file
check_env_file() {
    local file_path="env_file"
    if [ -f $file_path ]; then
        source $file_path
    else
        echo "Error: '$file_path' file does not exist."
        exit 1
    fi
}

# Prepare the VM
prepare_vm() {
    ./prepare_vm.sh
}

# Install Docker if needed
install_docker() {
    echo "Checking Docker installation..."
    if command_not_exists docker; then
        echo "Docker is not installed"
        curl -fsSL https://get.docker.com | sh
    else
        echo "Docker is installed"
    fi
}

# Generate and add unique identifier
add_identifier() {
    if [ -n "${IDENTIFIER:-}" ]; then
        echo "Identifier already exists: $IDENTIFIER"
        return 0
    fi

    echo "Generating unique identifier..."
    # Declare first, then assign: `local x=$(...)` would hide the pipeline's
    # exit status behind the (always-0) `local` builtin. `|| true` swallows the
    # harmless SIGPIPE from `head` closing the pipe early - we validate the
    # result by checking it's non-empty, which is what actually matters.
    local identifier
    identifier=$(head -c 4096 /dev/urandom | tr -dc 'a-zA-Z0-9' | head -c 10) || true
    if [ -z "$identifier" ]; then
        echo "Error: Failed to generate unique identifier."
        exit 1
    fi

    echo "" >> ./env_file
    echo "IDENTIFIER=$identifier" >> ./env_file
    echo "Added identifier: $identifier"
}

# Setup cron jobs
setup_cron() {
    echo "Setting up cron jobs..."
    ./setup_cron.sh "${REDEPLOY_INTERVAL:-}"
    echo "Cron setup completed."
}

# Deploy with Docker Compose
deploy() {
    echo "Starting deployment with Docker Compose..."
    docker compose up -d --build
    echo "Deployment completed."
}

# Main function to execute all steps
main() {
    echo "Starting bootstrap process..."
    echo

    declare -A STEP_NAMES
    STEP_NAMES=(
        [check_root]="Checking root privileges"
        [check_env_file]="Checking environment file"
        [prepare_vm]="Preparing the VM"
        [install_docker]="Installing Docker"
        [add_identifier]="Generating unique identifier"
        [setup_cron]="Setting up cron jobs"
        [deploy]="Deploying with Docker Compose"
    )

    local steps=(
        check_root
        check_env_file
        prepare_vm
        install_docker
        add_identifier
        setup_cron
        deploy
    )

    for step in "${steps[@]}"; do
        echo "Step: ${STEP_NAMES[$step]}"
        if ! $step; then
            echo "Error: ${STEP_NAMES[$step]} failed."
            echo
            exit 1
        fi
        echo
        sleep 0.5
    done
    
    echo "Bootstrap completed successfully."
    echo
    echo "Please allow 5~10 minutes for the metrics to appear in your Grafana dashboard."
    echo
}

# Execute main function
main
