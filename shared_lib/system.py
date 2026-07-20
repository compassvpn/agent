import csv
import os
import subprocess
from typing import List, Optional, Dict, Mapping

from shared_lib.logger import log


def get_machine_id() -> str:
    """Retrieves the machine ID from the host system."""
    paths = ["/host/etc/machine-id", "/etc/machine-id"]
    for path in paths:
        if os.path.exists(path):
            with open(path, "r", encoding="utf-8") as f:
                machine_id = f.read().strip()
                log.debug(
                    "Machine ID retrieved",
                    hypothesisId="SYS",
                    path=path,
                    id=machine_id,
                )
                return machine_id
    log.debug("Failed to retrieve machine ID", hypothesisId="SYS", checked_paths=paths)
    raise RuntimeError("Failed to retrieve machine ID: No valid machine-id file found.")


def exec_command(
    cmd: List[str],
    cwd: Optional[str] = None,
    capture_output: bool = False,
    env: Optional[Mapping[str, str]] = None,
) -> subprocess.CompletedProcess:
    """Standardized subprocess execution wrapper."""
    log.debug("Executing command", hypothesisId="SYS", cmd=" ".join(cmd), cwd=cwd)
    try:
        # Merge current env with provided env if exists
        full_env = os.environ.copy()
        if env:
            full_env.update(env)

        result = subprocess.run(
            cmd,
            cwd=cwd,
            capture_output=capture_output,
            text=True,
            check=False,
            env=full_env,
        )
        if result.returncode != 0:
            log.debug(
                "Command failed",
                hypothesisId="SYS",
                cmd=" ".join(cmd),
                exit_code=result.returncode,
                stderr=result.stderr if capture_output else "Check container logs",
            )
        return result
    except Exception as e:
        log.debug(
            "Command execution error",
            hypothesisId="SYS",
            cmd=" ".join(cmd),
            error=str(e),
        )
        raise e


def csv_to_dict(filename: str) -> Dict[str, Dict[str, str]]:
    """Parses xray-knife's CSV output, keyed by config link.

    Uses csv.DictReader so quoted fields (e.g. a `reason` that contains a
    comma) are parsed by column name instead of by position, which a naive
    split(",") would get wrong.
    """
    data: Dict[str, Dict[str, str]] = {}
    if os.path.exists(filename):
        try:
            with open(filename, "r", encoding="utf-8", newline="") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    link = row.get("link", "")
                    if not link.startswith(("vmess://", "vless://")):
                        continue
                    data[link] = row
        except Exception as e:
            log.error(f"Error reading CSV {filename}: {e}", hypothesisId="SYS")
    return data
