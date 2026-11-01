import structlog
import logging
import os
from typing import List
from shared_lib.paths import DEBUG_LOG, ENV_FILE


def is_debug() -> bool:
    """Single source of truth for the DEBUG flag.

    Checked here, the lowest-level module, so every other module can share one
    definition (env var first, then env_file) without circular imports. Accepts
    True/TRUE and optionally-quoted values so a stray capital doesn't half-enable
    debug across the stack.
    """
    # 1. Check environment
    if os.environ.get("DEBUG", "").lower() == "true":
        return True

    # 2. Check env_file manually
    if os.path.exists(str(ENV_FILE)):
        try:
            with open(str(ENV_FILE), "r", encoding="utf-8") as f:
                for line in f:
                    # Robust check for DEBUG=true (handles spaces, optional quotes, etc.)
                    line = line.strip()
                    if not line or line.startswith("#"):
                        continue
                    if "DEBUG" in line and "=" in line:
                        key, val = [p.strip() for p in line.split("=", 1)]
                        if key == "DEBUG":
                            return val.strip("'\"").lower() == "true"
        except Exception:
            # If the env file cannot be read for any reason, fail closed and
            # leave DEBUG disabled by returning False below.
            pass
    return False


# Setup handlers
handlers: List[logging.Handler] = [logging.StreamHandler()]
# Ensure the log directory exists and handle debug file creation
try:
    log_dir = os.path.dirname(str(DEBUG_LOG))
    if log_dir and not os.path.exists(log_dir):
        os.makedirs(log_dir, exist_ok=True)

    # Write debug.log only while DEBUG is on. (Previously this also fired when
    # the file merely existed, so the log kept growing after DEBUG was turned
    # back off until someone deleted it.)
    if is_debug():
        handlers.append(logging.FileHandler(str(DEBUG_LOG)))
except Exception:
    # Fail gracefully if we can't write to the log directory (e.g. permission issues)
    pass


# info and up by default, so keep info for milestones; DEBUG=true shows everything.
log_level = logging.DEBUG if is_debug() else logging.INFO

# Configure standard logging for both file and stdout
logging.basicConfig(
    level=log_level,
    format="%(message)s",
    handlers=handlers,
)
# Flask's per-request lines are only worth seeing while debugging.
logging.getLogger("werkzeug").setLevel(log_level if is_debug() else logging.WARNING)

# logfmt, the same shape xray-exporter and alloy print: time= level= cat= msg=
structlog.configure(
    processors=[
        structlog.processors.TimeStamper(fmt="%Y-%m-%dT%H:%M:%SZ", key="time"),
        structlog.processors.add_log_level,
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
        structlog.processors.UnicodeDecoder(),
        structlog.processors.EventRenamer("msg"),
        structlog.processors.LogfmtRenderer(
            key_order=["time", "level", "cat", "msg"],
            drop_missing=True,
            bool_as_flag=False,
        ),
    ],
    logger_factory=structlog.stdlib.LoggerFactory(),
)

log = structlog.get_logger()

# One line at startup so the operator can confirm the flag actually took effect.
log.debug("Debug logging on", cat="log")
