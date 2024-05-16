import os
import platform
import threading
from time import sleep
import requests
from prometheus_client.parser import text_string_to_metric_families
from requests.auth import HTTPBasicAuth
import unicodedata


# initial wait
print("initial 30 seconds wait...", flush=True)
# sleep(30)

METRIC_PUSH_METHOD = os.environ.get('METRIC_PUSH_METHOD', 'pushgateway')

if METRIC_PUSH_METHOD == "pushgateway":
    from pushgateway import run_jobs
    run_jobs()

else:
    # grafana_agent method
    from grafana_agent import start
    start()

while True:
    print("entering endless loop.", flush=True)
    sleep(1000)
