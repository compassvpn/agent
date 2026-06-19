from pathlib import Path

# Project root directory
ROOT_DIR = Path(__file__).parent.parent.absolute()

# Common file paths
ENV_FILE = ROOT_DIR / "env_file"
INBOUNDS_JSON = ROOT_DIR / "xray-config" / "inbounds.json"
CONFIGS_CSV = ROOT_DIR / "configs.csv"
VALID_CSV = ROOT_DIR / "valid.csv"
ACME_DIR = ROOT_DIR / "acme"

# Service-specific paths
LOG_DIR = Path("/var/log/compassvpn")
DEBUG_LOG = LOG_DIR / "debug.log"
XRAY_ACCESS_LOG = LOG_DIR / "xray_access.log"
XRAY_ERROR_LOG = LOG_DIR / "xray_error.log"

ACME_SH_PATH = Path("/root/.acme.sh")
CERT_DIR = ACME_SH_PATH

# Container-specific overrides (when running inside Docker)
if Path("/root/inbounds.json").exists():
    INBOUNDS_JSON = Path("/root/inbounds.json")
    CONFIGS_CSV = Path("/root/configs.csv")
    VALID_CSV = Path("/root/valid.csv")
    ENV_FILE = Path("/root/env_file")
