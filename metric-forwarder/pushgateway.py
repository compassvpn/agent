import os
import requests
import threading
from time import sleep
from prometheus_client.parser import text_string_to_metric_families
from requests.auth import HTTPBasicAuth
from utils import get_public_ip, convert_to_ascii

instance_location_info = get_public_ip(extra=True)

last_values = {}

pushgateway_url = os.environ['PUSHGATEWAY_URL']
donor = os.environ.get('DONOR', os.environ['PUSHGATEWAY_AUTH_USER'])


def process_metrics(metrics_text):
    new_lines = []
    for line in metrics_text.split("\n"):
        if line.startswith("#"):
            new_lines.append(line)
        else:
            for family in text_string_to_metric_families(line):
                for metric in family.samples:
                    labels = metric[1]
                    labels.update({"donor": donor})  # Adding additional labels
                    new_lines.append(
                        f"""{metric[0]}{{{','.join(f'{k}="{v}"' for k, v in labels.items())}}} {metric[2]}"""
                    )

    return "\n".join(new_lines) + "\n"


def forward_metrics(job_name, metric_urls):

    instance_ip = instance_location_info['ip']

    # Endpoint to push metrics to a specific job in Pushgateway
    endpoint = f'{pushgateway_url}/metrics/job/{job_name}/instance/{instance_ip}'

    metrics = ""
    for url in metric_urls:
        try:
            print(f"getting metrics from {url}...", flush=True)
            r = requests.get(url)
        except requests.exceptions.RequestException as e:
            print(f"error: {e}")
            return False
        print(r, flush=True)
        metrics += r.content.decode("utf-8")

    # convert non-ascii chars to closest ascii (prom does not support non-ascii)
    metrics = convert_to_ascii(metrics)

    new_metrics = process_metrics(metrics)

    if last_values.get('job_name', '') == new_metrics:
        # same as the last value - skip
        return True

    try:
        # Send the metric to the Pushgateway
        try:
            print("sending metrics...", flush=True)
            # print(new_metrics, flush=True)
            response = requests.post(endpoint,
                                     data=new_metrics,
                                     auth=HTTPBasicAuth(os.environ['PUSHGATEWAY_AUTH_USER'],
                                                        os.environ['PUSHGATEWAY_AUTH_PASSWORD']))
        except requests.exceptions.RequestException as e:
            print(f"error: {e}")
            return False

        if response.status_code == 200:
            last_values[job_name] = new_metrics  # store the last value

            print(f'Metric sent successfully to Pushgateway.', flush=True)
            return True
        else:
            print(response.content, flush=True)
            print(f'Failed to send metric to Pushgateway. Status code: {response.status_code}', flush=True)
            return False

    except requests.RequestException as e:
        print(f'Error sending metric to Pushgateway: {e}')
        return False


def node_exporter_job():
    while True:
        success = forward_metrics("node-exporter", ["http://host.docker.internal:9100/metrics"])
        if not success:
            sleep(10)  # retry after 10 seconds
        else:
            # push metrics every minute (if there is a change)
            sleep(600)


def xray_job():
    while True:
        success = forward_metrics("xray", ["http://xray-config:5000/metrics", "http://v2ray-exporter:9550/scrape"])
        if not success:
            sleep(10)  # retry after 10 seconds
        else:
            # push metrics every minute (if there is a change)
            sleep(60)


def run_jobs():
    print("run node metrics thead", flush=True)
    node_exporter_job_thread = threading.Thread(target=node_exporter_job)
    node_exporter_job_thread.daemon = True
    node_exporter_job_thread.start()

    print("run xray push metrics thead", flush=True)
    xray_job_thread = threading.Thread(target=xray_job)
    xray_job_thread.daemon = True
    xray_job_thread.start()