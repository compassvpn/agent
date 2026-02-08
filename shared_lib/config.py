import os
from typing import Dict, Any, List, Optional
from .paths import ENV_FILE

from shared_lib.logger import log


def load_env(
    file_path: str = str(ENV_FILE), include_os_environ: bool = True
) -> Dict[str, str]:
    """Reads key-value pairs from an env file, optionally including os.environ."""
    env_vars: Dict[str, str] = {}

    # 1. Start with os.environ if requested
    if include_os_environ:
        for key, value in os.environ.items():
            env_vars[key] = value

    # 2. Override with values from the env_file if it exists
    if os.path.exists(file_path):
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                for line in f:
                    stripped_line = line.strip()
                    if not stripped_line or stripped_line.startswith("#"):
                        continue
                    if "=" in stripped_line:
                        try:
                            key, value = stripped_line.split("=", 1)
                            key = key.strip()
                            value = value.strip()
                            if key:
                                env_vars[key] = value
                        except ValueError:
                            continue
            log.debug(
                "Env loaded from file",
                hypothesisId="CFG",
                path=file_path,
                count=len(env_vars),
            )
        except Exception as e:
            log.debug(
                "Error loading env file",
                hypothesisId="CFG",
                path=file_path,
                error=str(e),
            )

    return env_vars


def write_env(
    env_data: Dict[str, Any],
    schema: Optional[List[Dict[str, Any]]] = None,
    file_path: str = str(ENV_FILE),
) -> None:
    """Writes configuration data to an env file, preserving schema order if provided."""
    log.debug("Writing env file", hypothesisId="CFG", path=file_path)
    # Only load from file, do NOT include os.environ to avoid polluting env_file
    original_config = load_env(file_path, include_os_environ=False)
    lines_to_write: List[str] = []

    schema_keys = set()
    if schema:
        schema_keys = {item["name"] for item in schema}
        for item in schema:
            key = item["name"]
            value = env_data.get(key, item.get("default", ""))
            if isinstance(value, list):
                value = ",".join(value)
            value_str = str(value).strip().replace("\n", " ").replace("\r", "")
            lines_to_write.append(f"{key}={value_str}\n\n")

    # Append non-schema variables
    header_added = False
    for key, value in original_config.items():
        if key not in schema_keys:
            if not header_added and schema:
                lines_to_write.append("\n")
                header_added = True
            lines_to_write.append(f"{key}={value}\n\n")

    try:
        with open(file_path, "w", newline="", encoding="utf-8") as f:
            f.writelines(lines_to_write)
    except Exception as e:
        log.error(f"Error writing {file_path}: {e}", hypothesisId="CFG")
        raise e


def get_identifier() -> str:
    """
    Retrieves the system identifier from environment variables or config file.
    Note: Stays in config.py to prevent circular imports with logger and system modules.
    """
    identifier = os.environ.get("IDENTIFIER")
    if not identifier:
        # Check if we can load it from env_file if not in environment
        env_config = load_env()
        identifier = env_config.get("IDENTIFIER")

    if not identifier:
        raise RuntimeError(
            "Critical system error: 'IDENTIFIER' not found in environment or configuration file."
        )
    return identifier.lower()
