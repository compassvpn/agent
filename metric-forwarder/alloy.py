from common import generate_config

from shared_lib.system import exec_command
from shared_lib.logger import log


def start():
    generate_config()
    log.info("running alloy", hypothesisId="METRIC")
    exec_command(["alloy", "run", "config.alloy", "--storage.path=/var/lib/alloy/data"])
