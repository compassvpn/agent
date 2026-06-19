#!/usr/bin/bash
set -euo pipefail

# Fetch the latest changes from the remote
git fetch

# Compare local vs upstream HEAD. Bail out cleanly if this checkout has no
# upstream (e.g. a hand-copied or detached deploy) instead of aborting under set -e.
LOCAL=$(git rev-parse @)
REMOTE=$(git rev-parse @{u} 2>/dev/null || true)
if [ -z "$REMOTE" ]; then
    echo "No upstream tracking branch; skipping auto-update."
    exit 0
fi

if [ "$LOCAL" != "$REMOTE" ]; then
    echo "There are new changes. Updating..."
    # Match the remote exactly, then keep scripts executable
    git reset --hard "@{u}"
    chmod +x ./*.sh
    echo "Update done - re-running bootstrap to reconverge..."
    ./agent.sh
else
    echo "No new changes."
fi
