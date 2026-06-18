#!/bin/bash
# Executed by the GitHub Actions runner for each server in the matrix.

set -e

# --- Check required environment variables ---
if [[ -z "$SERVER_INDEX" ]]; then echo "::error::SERVER_INDEX env var not set."; exit 1; fi
if [[ -z "$SERVERS_SECRET" ]]; then echo "::error::SERVERS_SECRET env var not set."; exit 1; fi
if [[ -z "$ENV_FILE_CONTENT" ]]; then echo "::warning::ENV_FILE_CONTENT env var not set or is empty. Remote env_file will be empty."; fi
if [[ -z "$GITHUB_REPOSITORY" ]]; then echo "::error::GITHUB_REPOSITORY env var not set."; exit 1; fi
if [[ -z "$GITHUB_REF_NAME" ]]; then echo "::error::GITHUB_REF_NAME env var not set."; exit 1; fi
if [[ -z "$LOCAL_SCRIPT_PATH" ]]; then echo "::error::LOCAL_SCRIPT_PATH env var not set."; exit 1; fi
# SSH_KEY_SECRET and DEBUG_LOGS may be empty

# --- Determine authentication mode ---
AUTH_MODE="password"
if [[ -n "$SSH_KEY_SECRET" ]]; then
  AUTH_MODE="key"
  echo "Using SSH Key authentication via ssh-agent."
else
  echo "Using Password authentication via sshpass."
fi

# --- Get the specific server line for this job instance ---
echo "Processing Server Index: $SERVER_INDEX"
line=$(printf "%s" "$SERVERS_SECRET" | awk "NR==${SERVER_INDEX}")
if [[ -z "$line" ]]; then
  echo "::error::Could not extract server line for index $SERVER_INDEX from SERVERS secret."
  exit 1
fi
echo "Processing Server Line (from index $SERVER_INDEX): [$line]"

# Trim leading/trailing whitespace and trailing comma
line=$(echo "$line" | sed 's/^[[:space:]]*//;s/[[:space:]]*$//;s/,$//')
if [[ -z "$line" ]]; then
    echo "::error::Extracted server line for index $SERVER_INDEX is empty after trimming."
    exit 1
fi

# Validate format: user:password@ip or user@ip
if ! echo "$line" | grep -q '@'; then
  echo "::error::Invalid server line format (missing @) for index $SERVER_INDEX: [$line]"
  exit 1
fi

# --- Parse server details ---
ip=$(echo "$line" | sed 's/.*@//')
user_pass=$(echo "$line" | sed 's/@.*//')
user=""
password=""

ssh_base_options="-o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null -o ConnectTimeout=10"
ssh_connect_cmd=""

if [[ "$AUTH_MODE" == "key" ]]; then
  user="$user_pass"
  echo "Attempting key auth for $user@$ip"
  ssh_verbose_flag=""
  if [[ "$DEBUG_LOGS" == "true" ]]; then ssh_verbose_flag="-v"; fi
  # -T disables pty allocation; script runs non-interactively
  ssh_connect_cmd="ssh $ssh_base_options $ssh_verbose_flag -T ${user}@${ip}"
else
  # Password auth: user:password@ip format expected
  if ! echo "$user_pass" | grep -q ':'; then
    echo "::error::Invalid server line format for password auth (missing : in user:password part) for index $SERVER_INDEX: [$line]"
    exit 1
  fi
  { set +x; } 2>/dev/null
  user=$(echo "$user_pass" | cut -d':' -f1)
  password=$(echo "$user_pass" | cut -d':' -f2-)
  if [[ -z "$password" ]]; then
     { set -x; } 2>/dev/null
     echo "::error::Empty password found for user $user@$ip (Index: $SERVER_INDEX)"
     exit 1
  fi
  export SSHPASS="$password"
  { set -x; } 2>/dev/null
  ssh_verbose_flag=""
  if [[ "$DEBUG_LOGS" == "true" ]]; then ssh_verbose_flag="-v"; fi
  # sshpass reads password from SSHPASS env var (-e); -t required for auth handshake
  ssh_connect_cmd="sshpass -e ssh $ssh_base_options $ssh_verbose_flag -t -o PreferredAuthentications=password ${user}@${ip}"
fi

if [[ -z "$user" ]] || [[ -z "$ip" ]]; then
  echo "::error::Could not extract user or ip from server line for index $SERVER_INDEX: [$line]"
  exit 1
fi

if [ ! -f "$LOCAL_SCRIPT_PATH" ]; then
  echo "::error::Local script to execute ($LOCAL_SCRIPT_PATH) not found. Make sure it exists in the repository and the Checkout step ran."
  exit 1
fi

# --- Prepare remote execution arguments ---
{ set +x; } 2>/dev/null
ENCODED_ENV_FILE=$(echo "$ENV_FILE_CONTENT" | base64 -w0)
{ set -x; } 2>/dev/null

repo_arg_quoted=$(printf %q "$GITHUB_REPOSITORY")
ref_arg_quoted=$(printf %q "$GITHUB_REF_NAME")
debug_flag_quoted=$(printf %q "$DEBUG_LOGS")

# --- Execute the remote script ---
# '; exit \$?' - escaped so $? is evaluated on the REMOTE shell (the bootstrap's
# real status). Unescaped, it would expand locally on the runner (always 0) and
# mask every remote failure.
remote_script_execution_command="bash -s -- $repo_arg_quoted $ref_arg_quoted $debug_flag_quoted; exit \$?"

echo "Executing remote script ($LOCAL_SCRIPT_PATH) via stdin pipe..."

# ENV_FILE_B64 prepended to stdin so secrets never appear in /proc/cmdline
if { printf 'ENV_FILE_B64=%s\n' "$ENCODED_ENV_FILE"; cat "$LOCAL_SCRIPT_PATH"; } | $ssh_connect_cmd "$remote_script_execution_command"; then
    echo "Successfully executed remote script via stdin on ${user}@${ip}"
else
    echo "::error::Failed executing remote script via stdin on ${user}@${ip}" >&2
    if [[ "$AUTH_MODE" == "password" ]]; then unset SSHPASS; fi
    exit 1
fi

if [[ "$AUTH_MODE" == "password" ]]; then unset SSHPASS; fi

echo "Deployment logic script finished successfully for server index $SERVER_INDEX."
