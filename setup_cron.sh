#!/bin/bash

# --- Configuration ---
BOOTSTRAP_SCRIPT="./bootstrap.sh"
CHECK_UPDATE_SCRIPT="./check_update.sh"
LOG_FILES_TO_CLEAN=()
RENEW_INTERVAL="$1" # Read renewal interval from the first argument
# AUTO_UPDATE environment variable is checked directly later

SCRIPT_MARKER_BEGIN="# BEGIN MANAGED CRON JOBS BY setup_cron.sh"
SCRIPT_MARKER_END="# END MANAGED CRON JOBS BY setup_cron.sh"
# Fixed string to remove any legacy truncate jobs
LOG_CLEAN_COMMAND_FRAGMENT="truncate -s 0 /var/log/compassvpn/"
# Use extended regex for bootstrap command fragment
BOOTSTRAP_COMMAND_FRAGMENT="&& ./bootstrap.sh"

# --- Helper Functions ---

# Function to log info messages consistently
log_info() {
    echo "Info: $1"
}

# Function to log error messages consistently
log_error() {
    echo "Error: $1"
}

# Function to validate renewal interval (e.g., 10d, 1m)
validate_interval() {
    local interval="$1"
    if ! [[ "$interval" =~ ^[0-9]+[md]$ ]]; then
        log_error "Invalid RENEW_INTERVAL format '$interval'. Use formats like 1m (1 month), 10d (10 days)."
        return 1
    fi
    local unit="${interval: -1}"
    local value="${interval%?}"
    case "$unit" in
        m)
            if (( value < 1 || value > 12 )); then
                log_error "Invalid month value '$value'. It should be between 1 and 12."
                return 1
            fi
            ;;
        d)
            if (( value < 1 || value > 31 )); then
                log_error "Invalid day value '$value'. It should be between 1 and 31."
                return 1
            fi
            ;;
        *) # Should not happen due to regex, but good practice
            log_error "Unsupported time unit '$unit'."
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

    # 1) Renewal Cron Job (optional)
    if [ -n "$RENEW_INTERVAL" ]; then # Only add if interval is provided
      if validate_interval "$RENEW_INTERVAL"; then
          local schedule
          schedule=$(get_renewal_cron_schedule "$RENEW_INTERVAL")
          # Ensure script_dir path is quoted if it contains spaces
          jobs+=("$schedule cd \"$script_dir\" && $BOOTSTRAP_SCRIPT # Renewal Job")
          log_info "Renewal cron job will be scheduled: $schedule" >&2
      else
          # Validation failed, error message already printed by validate_interval
          echo "Warning: Renewal cron job NOT scheduled due to invalid interval '$RENEW_INTERVAL'." >&2
      fi
    else
        log_info "No RENEW_INTERVAL provided. Skipping renewal cron job setup." >&2
    fi

    # 2) Auto Update Cron Job (optional)
    if [ "$AUTO_UPDATE" == "on" ]; then
        # Ensure script_dir path is quoted if it contains spaces
        jobs+=("0 * * * * cd \"$script_dir\" && $CHECK_UPDATE_SCRIPT # Auto Update Check")
        log_info "Auto-update check cron job will be scheduled hourly." >&2
    elif [ -z "$AUTO_UPDATE" ]; then
        log_info "AUTO_UPDATE is not set or empty. Auto-update check disabled." >&2
    else
        log_info "AUTO_UPDATE is set to '$AUTO_UPDATE' (not 'on'). Auto-update check disabled." >&2
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

ensure_cron_installed() {
    if ! command -v crontab >/dev/null 2>&1; then
        log_info "crontab not found. Installing cron..."
        apt-get update -qq && apt-get install -yqq cron
        if ! command -v crontab >/dev/null 2>&1; then
            log_error "Failed to install cron."
            return 1
        fi
        systemctl enable cron >/dev/null 2>&1 || true
        systemctl start cron >/dev/null 2>&1 || true
    fi
}

main() {
    echo "Setting up cron jobs..."
    echo

    declare -A STEP_NAMES
    STEP_NAMES=(
        [ensure_cron_installed]="Ensuring cron is installed"
        [fetch_crontab]="Fetching current crontab"
        [remove_managed_blocks]="Removing old managed blocks"
        [remove_stray_jobs]="Removing stray bootstrap and log jobs"
        [generate_new_jobs]="Generating new cron jobs"
        [install_crontab]="Installing updated crontab"
    )

    local steps=(
        ensure_cron_installed
        fetch_crontab
        remove_managed_blocks
        remove_stray_jobs
        generate_new_jobs
        install_crontab
    )

    for step in "${steps[@]}"; do
        echo "Step: ${STEP_NAMES[$step]}"
        if ! $step; then
            echo "Error: ${STEP_NAMES[$step]} failed."
            echo
            exit 1
        fi
        echo
        sleep 0.5
    done

    echo "Cron setup script finished."
}

fetch_crontab() {
    crontab_content=$(crontab -l 2>/dev/null)
    log_info "Initial crontab content fetched." >&2
}

remove_managed_blocks() {
    while true; do
        # Check if markers exist in the current content
        start_line=$(echo "$crontab_content" | grep -F -n -m 1 "$SCRIPT_MARKER_BEGIN" | cut -d: -f1 || echo 0)
        end_line=$(echo "$crontab_content" | grep -F -n -m 1 "$SCRIPT_MARKER_END" | cut -d: -f1 || echo 0)

        if (( start_line > 0 && end_line >= start_line )); then
            log_info "Found managed block from line $start_line to $end_line. Removing it." >&2
            # Remove the block and update the content for the next iteration
            crontab_content=$(printf '%s\n' "$crontab_content" | sed "${start_line},${end_line}d")
        elif (( start_line > 0 && end_line == 0 )) || (( end_line > 0 && start_line == 0 )) || (( end_line > 0 && start_line > end_line )); then
             echo "Warning: Found mismatched markers (start: $start_line, end: $end_line). Stopping block removal loop." >&2
             break
        else
            log_info "No more managed blocks found." >&2
            break
        fi
    done
    crontab_without_any_managed_blocks="$crontab_content"
}

remove_stray_jobs() {
    log_info "Removing stray bootstrap jobs..." >&2
    crontab_without_stray_bootstrap=$(printf '%s\n' "$crontab_without_any_managed_blocks" | grep -E -v "$BOOTSTRAP_COMMAND_FRAGMENT")
    
    log_info "Removing stray log cleaning jobs..." >&2
    final_existing_crontab=$(printf '%s\n' "$crontab_without_stray_bootstrap" | grep -F -v "$LOG_CLEAN_COMMAND_FRAGMENT")
}

generate_new_jobs() {
    new_cron_jobs_section=$(generate_cron_jobs)
}

install_crontab() {
    updated_crontab=$(printf "%s\\n%s\\n" "$final_existing_crontab" "$new_cron_jobs_section" | grep -v '^\\s*$')
    trimmed_crontab=$(echo "$updated_crontab" | tr -d '[:space:]')
    
    if [[ -z "$trimmed_crontab" ]]; then
        log_info "No cron jobs to install. Crontab will be empty." >&2
        crontab -r >/dev/null 2>&1
    else
        printf "%s\\n" "$updated_crontab" | crontab -
        if [ $? -ne 0 ]; then
            log_error "Failed to update crontab." >&2
            return 1
        fi
    fi
}

main
