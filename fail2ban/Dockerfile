FROM crazymax/fail2ban:1.1.0

# Create nginx log directory
RUN mkdir -p /var/log/nginx

# Default environment variables
ENV TZ=UTC \
    F2B_LOG_TARGET=STDOUT \
    F2B_LOG_LEVEL=NOTICE \
    F2B_DB_PURGE_AGE=1d 
