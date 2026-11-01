# Sourced by the shell entrypoints so their lines match the Python services:
# logfmt with time= level= cat= msg=, and debug lines only when DEBUG=true.

# Accept True/TRUE/"true", same as the Python side.
DEBUG=$(printf '%s' "${DEBUG:-false}" | tr -d "\"'" | tr '[:upper:]' '[:lower:]')

# log <level> <cat> <msg> [key=value ...]
log() {
    # Escape quotes so text from other tools can't break the msg field
    _level=$1 _cat=$2 _msg=$(printf '%s' "$3" | sed 's/"/\\"/g')
    shift 3
    printf 'time=%s level=%s cat=%s msg="%s"%s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$_level" "$_cat" "$_msg" "${*:+ $*}"
}

debug() {
    if [ "$DEBUG" = "true" ]; then log debug "$@"; fi
}

# wait_for <url>: block until xray-config answers 200 there, or give up after 2m
wait_for() {
    _tries=0
    until [ "$(curl -s -o /dev/null -w '%{http_code}' "$1")" = 200 ]; do
        if [ "$_tries" -eq 0 ]; then log info config "Waiting for xray-config"; fi
        _tries=$((_tries + 1))
        if [ "$_tries" -ge 60 ]; then
            log error config "Gave up waiting for xray-config" after=2m "url=$1"
            return 1
        fi
        debug config "xray-config isn't ready yet" "url=$1" "attempt=$_tries/60"
        sleep 2
    done
    if [ "$_tries" -gt 0 ]; then debug config "Connected to xray-config" "after=$((_tries * 2))s"; fi
}
