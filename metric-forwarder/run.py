import os
from time import sleep


METRIC_PUSH_METHOD = os.environ.get('METRIC_PUSH_METHOD')

if METRIC_PUSH_METHOD == "pushgateway":
    from pushgateway import run_jobs
    run_jobs()

elif METRIC_PUSH_METHOD == "grafana_agent":
    # grafana_agent method
    from grafana_agent import start
    start()

else:
    sleep(3)

while True:
    print("entering endless loop.", flush=True)
    sleep(1000)
