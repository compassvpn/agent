from common import generate_config

from shared_lib.system import exec_command
from shared_lib.logger import log


def start():
    generate_config()
    exec_command(["cat", "config.yaml"], capture_output=True)
    log.info("running grafana-agent", hypothesisId="METRIC")
    exec_command(["grafana-agent", "--config.file=config.yaml"])
