#!/usr/bin/bash

clear

# Exit on error
set -e

# Function to check if a command exists
command_not_exists() {
    ! command -v "$1" >/dev/null 2>&1
}

# Check if running as root
check_root() {
    if [ "$EUID" -ne 0 ]; then
        echo "This script must be run as root."
        exit 1
    fi
    echo "Running as root: OK"
}

# Check environment file
check_env_file() {
    local file_path="env_file"
    if [ -f $file_path ]; then
        echo "'$file_path' exists."
        source $file_path
    else
        echo "'$file_path' file does not exist. use env_file.example as template"
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
    echo "Generating unique identifier..."
    local identifier=$(head /dev/urandom | tr -dc 'a-zA-Z0-9' | head -c 10)
    if [ $? -ne 0 ]; then
        echo "Error: Failed to generate unique identifier."
        exit 1
    fi
    
    echo "Creating a new identifier and appending to the env_file..."
    echo "" >> ./env_file
    echo "IDENTIFIER=$identifier" >> ./env_file
    echo "Added identifier: $identifier"
}

# Setup cron jobs
setup_cron() {
    echo "Setting up cron jobs..."
    ./setup_cron.sh $REDEPLOY_INTERVAL
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
    echo
    echo "Starting bootstrap process..."
    echo

    check_root
    sleep 0.5

    check_env_file
    sleep 0.5

    prepare_vm
    sleep 0.5

    install_docker
    sleep 0.5

    add_identifier
    sleep 0.5

    setup_cron
    sleep 0.5

    deploy
    sleep 0.5
    
    echo
    echo "Bootstrap completed successfully."
    echo
}

# Execute main function
main
