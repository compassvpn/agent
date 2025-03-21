#!/usr/bin/bash


# Check if the script is run as root
if [ "$EUID" -ne 0 ]; then
    echo "This script must be run as root."
    exit 1
fi


file_path="env_file"
if [ -f $file_path ]; then
    echo "'$file_path' exists."
else
    echo "'$file_path' file does not exist. use env_file.example as template"
    exit;
fi

docker compose up -d --build
docker compose restart
