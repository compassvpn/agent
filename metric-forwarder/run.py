from shared_lib.logger import log

from alloy import start

log.info("Starting metric forwarder", hypothesisId="METRIC")

start()
