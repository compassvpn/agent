#!/usr/bin/bash
set -e

source env_file

# Function to check if a command exists
command_not_exists() {
    ! command -v "$1" >/dev/null 2>&1
}

# Check if the script is run as root
if [ "$EUID" -ne 0 ]; then
    echo "This script must be run as root."
    exit 1
fi

curl -fsSL https://get.docker.com | sh

file_path="env_file"
if [ -f $file_path ]; then
    echo "'$file_path' exists."
else
    echo "'$file_path' file does not exist. use env_file.example as template"
    exit;
fi

identifier=$(head /dev/urandom | tr -dc 'a-zA-Z0-9' | head -c 10)

echo "creating a new identifier and append to the env_file"
echo "IDENTIFIER=$identifier" >> ./env_file

# setup redeploy cron
./setup_cron.sh $REDEPLOY_INTERVAL

docker compose up -d --build