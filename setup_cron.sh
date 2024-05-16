#!/bin/bash


# Path to the script that updates env vars and redeploys containers
BOOTSTRAP_SCRIPT=./bootstrap.sh

# Variable for renewal interval (e.g., 10d - 10 days, 2m - 2 months)
RENEW_INTERVAL=$1

# Validate the RENEW_INTERVAL format
if ! [[ $RENEW_INTERVAL =~ ^[0-9]+[md]$ ]]; then
    echo "Invalid RENEW_INTERVAL format. Use formats like 1m (1 month), 10d (10 days)"
    exit 1
fi

# Convert the RENEW_INTERVAL to a cron schedule
case ${RENEW_INTERVAL: -1} in
    m)
        MONTHS=${RENEW_INTERVAL%?}
        if (( MONTHS < 1 || MONTHS > 12 )); then
            echo "Invalid moth value. It should be between 1 and 12."
            exit 1
        fi
        CRON_SCHEDULE="0 0 1 */$MONTHS *"
        ;;
    d)
        DAYS=${RENEW_INTERVAL%?}
        if (( DAYS < 1 || DAYS > 31 )); then
            echo "Invalid day value. It should be between 1 and 31."
            exit 1
        fi
        CRON_SCHEDULE="0 0 */$DAYS * *"
        ;;
    *)
        echo "Unsupported time unit. Use 'm' for month, 'd' for day"
        exit 1
        ;;
esac

# Write the cron job to a temporary file
CRON_JOB="$CRON_SCHEDULE cd $(pwd) && $BOOTSTRAP_SCRIPT"

# Remove the old cron job if it exists
(crontab -l | grep -v "$UPDATE_SCRIPT") | crontab -

# Install the cron job
(crontab -l 2>/dev/null; echo "$CRON_JOB") | crontab -

if [ -z "${AUTO_UPDATE}" ]; then
    echo "AUTO_UPDATE is not set. disable AUTO_UPDATE"
else
  if [ "$AUTO_UPDATE" == "on" ]; then
      echo "AUTO_UPDATE enable"
      # run check_update.sh every hour
      (crontab -l 2>/dev/null; echo "0 * * * * cd $(pwd) && ./check_update.sh") | crontab -
  fi
fi

crontab -l