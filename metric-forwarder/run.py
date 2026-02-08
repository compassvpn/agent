import os

from shared_lib.logger import log

METRIC_PUSH_METHOD = os.environ.get("METRIC_PUSH_METHOD", "pushgateway")

log.info("Starting metric forwarder", hypothesisId="METRIC", method=METRIC_PUSH_METHOD)

if METRIC_PUSH_METHOD == "pushgateway":
    from pushgateway import run_jobs

    run_jobs()
else:
    from grafana_agent import start

    start()
