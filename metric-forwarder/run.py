import os
import sys

# Add root to sys.path to allow importing shared_lib
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
from shared_lib.logger import log

METRIC_PUSH_METHOD = os.environ.get("METRIC_PUSH_METHOD", "pushgateway")

log.info("Starting metric forwarder", hypothesisId="METRIC", method=METRIC_PUSH_METHOD)

if METRIC_PUSH_METHOD == "pushgateway":
    from pushgateway import run_jobs

    run_jobs()
else:
    from grafana_agent import start

    start()
