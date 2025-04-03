#!/bin/bash

# --- Configuration ---
BOOTSTRAP_SCRIPT="./bootstrap.sh"
CHECK_UPDATE_SCRIPT="./check_update.sh"
LOG_FILES_TO_CLEAN=(
    "/var/log/compassvpn/xray_access.log"
    "/var/log/compassvpn/xray_error.log"
    "/var/log/compassvpn/nginx_access.log"
    "/var/log/compassvpn/nginx_error.log"
    "/var/log/compassvpn/xray.log"
)
RENEW_INTERVAL="$1" # Read renewal interval from the first argument
# AUTO_UPDATE environment variable is checked directly later

SCRIPT_MARKER_BEGIN="# BEGIN MANAGED CRON JOBS BY setup_cron.sh"
SCRIPT_MARKER_END="# END MANAGED CRON JOBS BY setup_cron.sh"
# Use fixed string for log cleaning command fragment for safety with grep -F
LOG_CLEAN_COMMAND_FRAGMENT="truncate -s 0 /var/log/xray_access.log"
# Use extended regex for bootstrap command fragment
BOOTSTRAP_COMMAND_FRAGMENT="&& ./bootstrap.sh"

# --- Helper Functions ---

# Function to validate renewal interval (e.g., 10d, 1m)
validate_interval() {
    local interval="$1"
    if ! [[ "$interval" =~ ^[0-9]+[md]$ ]]; then
        echo "Error: Invalid RENEW_INTERVAL format '$interval'. Use formats like 1m (1 month), 10d (10 days)." >&2
        return 1
    fi
    local unit="${interval: -1}"
    local value="${interval%?}"
    case "$unit" in
        m)
            if (( value < 1 || value > 12 )); then
                echo "Error: Invalid month value '$value'. It should be between 1 and 12." >&2
                return 1
            fi
            ;;
        d)
            if (( value < 1 || value > 31 )); then
                echo "Error: Invalid day value '$value'. It should be between 1 and 31." >&2
                return 1
            fi
            ;;
        *) # Should not happen due to regex, but good practice
            echo "Error: Unsupported time unit '$unit'." >&2
            return 1
            ;;
    esac
    return 0
}

# Function to convert a validated interval to a cron schedule string
get_renewal_cron_schedule() {
    local interval="$1"
    local unit="${interval: -1}"
    local value="${interval%?}"
    case "$unit" in
        m) echo "0 0 1 */$value *" ;; # Monthly schedule
        d) echo "0 0 */$value * *" ;; # Daily schedule
    esac
}

# Function to generate all cron job lines managed by this script
# IMPORTANT: This function *outputs* only the cron lines and markers to stdout.
#            Informational messages are printed to stderr.
generate_cron_jobs() {
    local jobs=()
    local script_dir
    script_dir="$(cd "$(dirname "$0")" && pwd)" # Get absolute directory of the script

    # 1. Renewal Cron Job
    if [ -n "$RENEW_INTERVAL" ]; then # Only add if interval is provided
      if validate_interval "$RENEW_INTERVAL"; then
          local schedule
          schedule=$(get_renewal_cron_schedule "$RENEW_INTERVAL")
          # Ensure script_dir path is quoted if it contains spaces
          jobs+=("$schedule cd \"$script_dir\" && $BOOTSTRAP_SCRIPT # Renewal Job")
          echo "Info: Renewal cron job will be scheduled: $schedule" >&2
      else
          # Validation failed, error message already printed by validate_interval
          echo "Warning: Renewal cron job NOT scheduled due to invalid interval '$RENEW_INTERVAL'." >&2
      fi
    else
        echo "Info: No RENEW_INTERVAL provided. Skipping renewal cron job setup." >&2
    fi

    # 2. Auto Update Cron Job
    if [ "$AUTO_UPDATE" == "on" ]; then
        # Ensure script_dir path is quoted if it contains spaces
        jobs+=("0 * * * * cd \"$script_dir\" && $CHECK_UPDATE_SCRIPT # Auto Update Check")
        echo "Info: Auto-update check cron job will be scheduled hourly." >&2
    elif [ -z "$AUTO_UPDATE" ]; then
        echo "Info: AUTO_UPDATE is not set or empty. Auto-update check disabled." >&2
    else
        echo "Info: AUTO_UPDATE is set to '$AUTO_UPDATE' (not 'on'). Auto-update check disabled." >&2
    fi

    # 3. Log Cleaning Cron Job
    if [ ${#LOG_FILES_TO_CLEAN[@]} -gt 0 ]; then
        local log_clean_cmd="truncate -s 0 ${LOG_FILES_TO_CLEAN[*]}"
        jobs+=("0 0 */2 * * $log_clean_cmd # Log Cleaning Job")
        echo "Info: Log cleaning cron job will be scheduled every 2 days for specified files." >&2
    else
        echo "Info: No log files specified for cleaning. Skipping log cleaning cron job." >&2
    fi


    # Output the jobs section ONLY if any jobs were defined
    # This output goes to stdout and is captured by the caller.
    if [ ${#jobs[@]} -gt 0 ]; then
        echo "$SCRIPT_MARKER_BEGIN"
        # Use printf for safer handling of potential special characters & ensure one job per line
        printf "%s\\n" "${jobs[@]}"
        echo "$SCRIPT_MARKER_END"
    fi
}

# --- Main Execution ---

echo "Setting up cron jobs managed by setup_cron.sh..."

# Get current full crontab content
crontab_content=$(crontab -l 2>/dev/null)
echo "Info: Initial crontab content fetched." >&2

# Loop to remove *all* managed blocks
while true; do
    # Check if markers exist in the current content
    start_line=$(echo "$crontab_content" | grep -F -n -m 1 "$SCRIPT_MARKER_BEGIN" | cut -d: -f1 || echo 0)
    end_line=$(echo "$crontab_content" | grep -F -n -m 1 "$SCRIPT_MARKER_END" | cut -d: -f1 || echo 0)

    if (( start_line > 0 && end_line >= start_line )); then
        echo "Info: Found managed block from line $start_line to $end_line. Removing it." >&2
        # Remove the block and update the content for the next iteration
        crontab_content=$(echo -e "$crontab_content" | sed "${start_line},${end_line}d")
    elif (( start_line > 0 && end_line == 0 )) || (( end_line > 0 && start_line == 0 )) || (( end_line > 0 && start_line > end_line )); then
         echo "Warning: Found mismatched markers (start: $start_line, end: $end_line). Stopping block removal loop to prevent errors." >&2
         # Break the loop on mismatched markers to avoid infinite loops or incorrect removals
         break
    else
        # No more valid blocks found, exit the loop
        echo "Info: No more managed blocks found." >&2
        break
    fi
done

# Now crontab_content contains lines outside any managed block
crontab_without_any_managed_blocks="$crontab_content"

# Filter out any remaining ./bootstrap.sh lines from the non-managed content
echo "Info: Removing stray bootstrap jobs (matching '$BOOTSTRAP_COMMAND_FRAGMENT', if any)..." >&2
crontab_without_stray_bootstrap=$(echo -e "$crontab_without_any_managed_blocks" | grep -E -v "$BOOTSTRAP_COMMAND_FRAGMENT")

# Filter out any remaining log cleaning lines from the result
echo "Info: Removing stray log cleaning jobs (matching '$LOG_CLEAN_COMMAND_FRAGMENT', if any)..." >&2
final_existing_crontab=$(echo -e "$crontab_without_stray_bootstrap" | grep -F -v "$LOG_CLEAN_COMMAND_FRAGMENT")

# Generate the new cron job lines (including markers)
# This captures ONLY the stdout from generate_cron_jobs (the actual cron lines)
new_cron_jobs_section=$(generate_cron_jobs)

# Combine the fully cleaned existing crontab and the new block
# Use printf to avoid issues with empty variables and ensure a newline
# Also filter out empty lines that might result from empty sections
updated_crontab=$(printf "%s\\n%s\\n" "$final_existing_crontab" "$new_cron_jobs_section" | grep -v '^\\s*$')

# Check if updated_crontab is empty or just whitespace before installing
# Trim whitespace for check
trimmed_crontab=$(echo "$updated_crontab" | tr -d '[:space:]')
if [[ -z "$trimmed_crontab" ]]; then
    echo "Info: No cron jobs to install or update. Crontab will be empty." >&2
    # Remove the crontab completely if it should be empty
    crontab -r
    if [ $? -eq 0 ]; then
        echo "Crontab cleared successfully."
    else
        # crontab -r can fail if crontab doesn't exist, which is fine
        echo "Info: No existing crontab to clear or crontab -r failed (may be normal)." >&2
    fi
else
    # Install the new crontab
    # Use printf to pipe to crontab to handle special characters safely
    printf "%s\\n" "$updated_crontab" | crontab -
    if [ $? -eq 0 ]; then
        echo "Crontab updated successfully."
    else
        echo "Error: Failed to update crontab." >&2
        echo "--- Crontab Content Attempted ---" >&2
        # Use cat -vet to show hidden characters in attempted crontab
        printf "%s\\n" "$updated_crontab" | cat -vet >&2
        echo "------------------------------" >&2
        exit 1
    fi
fi

echo "--- Current Crontab ---"
crontab -l
echo "-----------------------"

echo "Cron setup script finished."
exit 0
