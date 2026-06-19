#!/bin/bash
# Runs on the remote server via SSH: fresh-clone the repo, write env_file, deploy with agent.sh.

set -e

if ! command -v git &> /dev/null; then echo "::error::git command not found. Install git."; exit 1; fi
if ! command -v base64 &> /dev/null; then echo "::error::base64 command not found. Install base64."; exit 1; fi

# Non-interactive SSH may have a minimal PATH
export PATH=$PATH:/usr/local/bin:/usr/bin:/bin

GITHUB_REPOSITORY_ARG="$1"
GITHUB_REF_NAME_ARG="$2"

if [[ -z "$GITHUB_REPOSITORY_ARG" ]] || [[ -z "$GITHUB_REF_NAME_ARG" ]]; then
  echo "::error::Repository name (arg 1) or branch name (arg 2) argument missing."
  exit 1
fi

REPO_URL="https://github.com/${GITHUB_REPOSITORY_ARG}.git"
REPO_NAME=$(basename "${GITHUB_REPOSITORY_ARG}")
REPO_DIR="./$REPO_NAME"
BRANCH_NAME="${GITHUB_REF_NAME_ARG}"

echo "Working with branch: $BRANCH_NAME in dir $REPO_DIR for repo $REPO_URL"

# Always fresh-clone to avoid stale state
echo "Removing existing repository directory $REPO_DIR if it exists..."
rm -rf "$REPO_DIR"

echo "Cloning repository..."
git clone --branch "$BRANCH_NAME" "$REPO_URL" "$REPO_DIR" || { echo "::error::Git clone failed"; exit 1; }
cd "$REPO_DIR" || { echo "::error::Could not cd into $REPO_DIR"; exit 1; }

# ENV_FILE_B64 injected via stdin prefix, not argv, to keep secrets out of /proc/cmdline
echo "Writing env_file..."
if [[ -n "$ENV_FILE_B64" ]]; then
    printf "%s" "$ENV_FILE_B64" | base64 -d > ./env_file || { echo "::error::Failed to base64 decode or write env_file"; exit 1; }
    echo "env_file written."
else
    echo "::warning::ENV_FILE_B64 not set or empty. Creating empty env_file."
    :> ./env_file
fi
chmod 600 ./env_file

if [ -f ./agent.sh ]; then
  echo "Making agent.sh executable..."
  chmod +x ./agent.sh || { echo "::error::Failed to chmod agent.sh"; exit 1; }
  echo "Running ./agent.sh start..."
  ./agent.sh start || { echo "::error::agent.sh start failed"; exit 1; }
  echo "agent.sh finished successfully."
else
  echo "::error::agent.sh not found in $REPO_DIR"; exit 1;
fi

echo "Remote script completed."
