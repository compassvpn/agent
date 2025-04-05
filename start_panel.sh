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
    # Try adding the rule
    sudo ufw allow "$PANEL_PORT"/tcp comment "Allow Web Panel"
    if [ $? -ne 0 ]; then
        echo "Warning: Failed to add UFW rule for port $PANEL_PORT/tcp." >&2
        echo "Please ensure UFW is active and you have sudo permissions." >&2
    else
        echo "UFW rule added or already exists for port $PANEL_PORT/tcp."
    fi
}

# Function to cleanup firewall rule
cleanup_firewall() {
    if ! command_exists ufw || ! command_exists sudo; then
        return
    fi

    echo "Attempting to remove UFW rule: allow $PANEL_PORT/tcp comment 'Allow Web Panel'"
    sudo ufw delete allow "$PANEL_PORT"/tcp comment "Allow Web Panel" >/dev/null 2>&1
    # We run delete twice because UFW often creates separate v4 and v6 rules
    sudo ufw delete allow "$PANEL_PORT"/tcp comment "Allow Web Panel" >/dev/null 2>&1
    # Check status *after* attempting deletion (less reliable but provides feedback)
    if sudo ufw status | grep -q "$PANEL_PORT/tcp.*ALLOW.*Anywhere.*Allow Web Panel"; then 
        echo "Warning: Failed to delete UFW rule for $PANEL_PORT/tcp (or it was already gone). Manual check recommended." >&2
    else
        echo "UFW rule for $PANEL_PORT/tcp likely removed."
    fi
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
# Ensure owner has read/write permissions
chmod 600 "$ENV_FILE"
if [ $? -ne 0 ]; then
  echo "Warning: Failed to set permissions (600) on $ENV_FILE. The panel might not be able to save changes." >&2
  # Continue execution, but warn the user
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

# Navigate to the script directory
cd "$(dirname "$0")"

# Define the port and PID file
PORT=5001

# --- Run the Flask app --- 
echo "Starting the web panel on port $PANEL_PORT... Press Ctrl+C to stop."
python3 web_panel/app.py
FLASK_EXIT_CODE=$?

# --- Exit --- 
# The cleanup_firewall function is automatically called by the trap on EXIT
echo "Flask app exited with code: $FLASK_EXIT_CODE"
exit $FLASK_EXIT_CODE 