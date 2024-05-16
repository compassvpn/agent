#!/usr/bin/bash

git stash

# Fetch the latest changes from the remote
git fetch

# Check if there are any new changes by comparing the local and remote HEADs
LOCAL=$(git rev-parse @)
REMOTE=$(git rev-parse @{u})

if [ "$LOCAL" != "$REMOTE" ]; then
    echo "There are new changes. run update.sh"
    bash ./update.sh
    echo "update done! - build nad restart services..."
    ./restart.sh
else
    echo "No new changes."
fi