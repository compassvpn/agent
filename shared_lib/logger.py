import structlog
import logging
import os
from typing import List
from shared_lib.paths import DEBUG_LOG, ENV_FILE


def _is_debug_enabled():
    """Check if debug is enabled in environment or env_file without circular imports."""
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

    # We always attempt to add the file handler if we're in debug mode
    # or if the file already exists.
    if _is_debug_enabled() or os.path.isfile(str(DEBUG_LOG)):
        handlers.append(logging.FileHandler(str(DEBUG_LOG)))
except Exception:
    # Fail gracefully if we can't write to the log directory (e.g. permission issues)
    pass


log_level = logging.DEBUG if _is_debug_enabled() else logging.INFO

# Configure standard logging for both file and stdout
logging.basicConfig(
    level=log_level,
    format="%(message)s",
    handlers=handlers,
)

structlog.configure(
    processors=[
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.add_log_level,
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
        structlog.processors.UnicodeDecoder(),
        structlog.processors.JSONRenderer(),
    ],
    logger_factory=structlog.stdlib.LoggerFactory(),
)

log = structlog.get_logger()
