import threading
from time import sleep
from urllib.parse import urlparse

import requests

from common import generate_config, instance_ip, remote_write_url

from shared_lib.system import exec_command
from shared_lib.logger import log


def _check_push():
    # Scrapes run every 5m, so give the first push time to land, then say
    # once whether it did. Alloy itself only logs warnings and errors.
    sleep(420)
    try:
        text = requests.get("http://127.0.0.1:12345/metrics", timeout=10).text
    except requests.RequestException as e:
        log.warning("Couldn't read alloy's metrics", cat="metrics", error=str(e))
        return

    def total(name):
        return int(sum(float(line.rsplit(" ", 1)[1]) for line in text.splitlines() if line.startswith(name + "{")))

    sent = total("prometheus_remote_storage_samples_total")
    failed = total("prometheus_remote_storage_samples_failed_total")
    if sent and not failed:
        log.info("Metrics pushed", cat="metrics", samples=sent)
    elif sent:
        log.warning("Some metrics failed to push", cat="metrics", samples=sent, failed=failed)
    else:
        log.warning("No metrics pushed yet", cat="metrics", failed=failed, hint="check the remote write URL and login")


def start():
    generate_config()
    log.info("Starting alloy", cat="metrics", remote=urlparse(remote_write_url).hostname, instance=instance_ip)
    threading.Thread(target=_check_push, daemon=True).start()
    exec_command(["alloy", "run", "config.alloy", "--storage.path=/var/lib/alloy/data"])
