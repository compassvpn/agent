#!/usr/bin/bash

git stash

# Fetch the latest changes from the remote
git fetch

# Check if there are any new changes by comparing the local and remote HEADs
LOCAL=$(git rev-parse @)
REMOTE=$(git rev-parse @{u})

if [ "$LOCAL" != "$REMOTE" ]; then
    echo "There are new changes. Updating..."
    bash ./update.sh
    echo "Update done! - Restarting..."
    sleep 1
    ./restart.sh
    echo "Restart done! - Please wait at least 5 minutes for all services to run."
else
    echo "No new changes."
fi
