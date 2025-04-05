#!/bin/bash

ENV_FILE="env_file"
PANEL_PORT="5050"

# Function to check if a command exists
command_exists() {
    command -v "$1" >/dev/null 2>&1
}

# Function to setup firewall rule
setup_firewall() {
    if ! command_exists ufw || ! command_exists sudo; then
        echo "Warning: 'ufw' or 'sudo' not found. Skipping firewall setup." >&2
        return
    fi

    echo "Checking UFW status and attempting to allow port $PANEL_PORT/tcp..."
    sudo ufw allow "$PANEL_PORT"/tcp comment "Allow Web Panel"
    if [ $? -ne 0 ]; then
        echo "Warning: Failed to add UFW rule for port $PANEL_PORT/tcp." >&2
    else
        echo "UFW rule added or already exists for port $PANEL_PORT/tcp."
    fi
}

# Function to cleanup firewall rule
cleanup_firewall() {
    if ! command_exists ufw || ! command_exists sudo; then
        return
    fi
    echo "Attempting to remove UFW rule for port $PANEL_PORT/tcp..."
    # We run delete twice because UFW often creates separate v4 and v6 rules with the same comment
    sudo ufw delete allow "$PANEL_PORT"/tcp comment "Allow Web Panel" >/dev/null 2>&1
    sudo ufw delete allow "$PANEL_PORT"/tcp comment "Allow Web Panel" >/dev/null 2>&1
    echo "Firewall cleanup attempted."
}

# --- Setup Trap for Cleanup --- 
# Ensure cleanup_firewall is called when script exits (normally or via interrupt)
trap cleanup_firewall EXIT SIGINT SIGTERM

# --- Check/Create env_file --- 
if [ ! -f "$ENV_FILE" ]; then
  echo "$ENV_FILE not found. Creating empty file."
  touch "$ENV_FILE"
  if [ $? -ne 0 ]; then
    echo "Error: Failed to create $ENV_FILE. Please check permissions." >&2
    exit 1
  fi
fi

# --- Set Permissions --- 
chmod 600 "$ENV_FILE"
if [ $? -ne 0 ]; then
  echo "Warning: Failed to set permissions (600) on $ENV_FILE." >&2
fi

# --- Setup Firewall --- 
setup_firewall

# Check if Flask is installed, install if not
echo "Checking if python3-flask is installed..."
dpkg -s python3-flask > /dev/null 2>&1
if [ $? -ne 0 ]; then
    echo "python3-flask not found. Installing..."
    sudo apt-get update
    sudo apt-get install -y python3-flask
    if [ $? -ne 0 ]; then
        echo "Failed to install python3-flask. Please install it manually and retry." >&2
        exit 1
    fi
    echo "python3-flask installed successfully."
else
    echo "python3-flask is already installed."
fi

# Navigate to the script directory (where start_panel.sh is)
cd "$(dirname "$0")"

# --- Run the Flask app --- 
echo "Starting the web panel on port $PANEL_PORT... Press Ctrl+C to stop."
# Check if web_panel directory exists
if [ -d "web_panel" ]; then
    # Run Flask app from within its directory
    cd web_panel || exit 1 # Exit if cd fails
    python3 app.py
    FLASK_EXIT_CODE=$?
    cd .. # Go back to the original directory
else
    echo "Error: Directory 'web_panel' not found." >&2
    exit 1
fi

# --- Exit --- 
# The cleanup_firewall function is automatically called by the trap on EXIT
echo "Flask app exited with code: $FLASK_EXIT_CODE"
exit $FLASK_EXIT_CODE 
