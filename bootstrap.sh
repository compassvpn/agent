#!/usr/bin/bash

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

# Check if lsb_release command exists
if ! command -v lsb_release &>/dev/null; then
    echo "lsb_release command not found. Please make sure you are running this script on Ubuntu."
    exit 1
fi

# Get Ubuntu release information
ubuntu_release=$(lsb_release -rs)

# Check if the release is Ubuntu 20.04 or 22.04
if [[ $ubuntu_release == "20.04" ]]; then
    echo "Ubuntu 20.04"
elif [[ $ubuntu_release == "22.04" ]]; then
    echo "Ubuntu 22.04"
elif [[ $ubuntu_release == "24.04" ]]; then
    echo "Ubuntu 24.04"
else
    echo "This script is intended to run on Ubuntu 20.04, 22.04 or 24.04."
    exit 1
fi

if command_not_exists docker-compose; then
  echo "install docker and docker-compose"
  sudo apt update && sudo apt install -y docker.io
  if [[ $ubuntu_release == "24.04" ]]; then
      curl -L "https://github.com/docker/compose/releases/download/v2.28.1/docker-compose-linux-x86_64" -o /usr/local/bin/docker-compose
      chmod +x /usr/local/bin/docker-compose
  else
      sudo apt install -y docker-compose
  fi
fi

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

docker-compose up -d --build